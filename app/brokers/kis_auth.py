"""KIS authentication helpers for paper/live separation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config.settings import AppSettings, KisCredentialSet
from app.utils.time import get_timezone, now_local


TOKEN_ENDPOINT = "/oauth2/tokenP"
TOKEN_REVOKE_ENDPOINT = "/oauth2/revokeP"
APPROVAL_ENDPOINT = "/oauth2/Approval"
HASHKEY_ENDPOINT = "/uapi/hashkey"
KST = get_timezone("Asia/Seoul")


class KisApiError(RuntimeError):
    """Raised when the KIS API returns an error or invalid payload."""


@dataclass(slots=True)
class KisAccessToken:
    access_token: str
    token_type: str
    expires_at: datetime

    @property
    def authorization_header(self) -> str:
        return f"{self.token_type} {self.access_token}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= now_local("Asia/Seoul") + timedelta(minutes=5)


@dataclass(slots=True)
class KisAuthProfile:
    mode: str
    app_key: str
    app_secret: str
    account_no: str
    product_code: str
    hts_id: str
    customer_type: str
    rest_url: str
    ws_url: str
    token_cache_path: Path

    @property
    def is_configured(self) -> bool:
        return all([self.app_key, self.app_secret, self.account_no, self.product_code])

    @property
    def is_ready_for_quotes(self) -> bool:
        return all([self.app_key, self.app_secret])

    @property
    def websocket_tryitout_url(self) -> str:
        return f"{self.ws_url.rstrip('/')}/tryitout"


def _request_json(url: str, payload: dict[str, object], timeout_seconds: int = 15) -> dict:
    encoded = json.dumps(payload).encode("utf-8")
    request = Request(
        url=url,
        data=encoded,
        headers={"content-type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise KisApiError(f"KIS HTTP error {exc.code}: {body}") from exc
    except URLError as exc:
        raise KisApiError(f"KIS network error: {exc}") from exc


def _parse_expiration(payload: dict) -> datetime:
    expired_at = payload.get("access_token_token_expired")
    if isinstance(expired_at, str) and expired_at.strip():
        return datetime.strptime(expired_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    expires_in = int(payload.get("expires_in", 0))
    return now_local("Asia/Seoul") + timedelta(seconds=expires_in)


def get_kis_profile(settings: AppSettings, mode: str | None = None) -> KisAuthProfile:
    resolved_mode = (mode or settings.trading_mode).strip().lower()
    if resolved_mode not in {"paper", "live"}:
        raise ValueError("KIS mode must be either 'paper' or 'live'.")
    credential: KisCredentialSet = settings.kis_live if resolved_mode == "live" else settings.kis_paper
    environment = settings.kis_environment
    runtime_mode_dir = settings.runtime_data_dir / "cache" / "kis" / resolved_mode
    runtime_mode_dir.mkdir(parents=True, exist_ok=True)
    return KisAuthProfile(
        mode=resolved_mode,
        app_key=credential.app_key,
        app_secret=credential.app_secret,
        account_no=credential.account_no,
        product_code=credential.product_code,
        hts_id=environment.hts_id,
        customer_type=environment.customer_type,
        rest_url=environment.rest_url_live if resolved_mode == "live" else environment.rest_url_paper,
        ws_url=environment.ws_url_live if resolved_mode == "live" else environment.ws_url_paper,
        token_cache_path=runtime_mode_dir / "access_token.json",
    )


def get_active_kis_profile(settings: AppSettings) -> KisAuthProfile:
    return get_kis_profile(settings, settings.trading_mode)


class KisTokenManager:
    def __init__(self, profile: KisAuthProfile) -> None:
        self.profile = profile

    def load_cached_token(self) -> KisAccessToken | None:
        if not self.profile.token_cache_path.exists():
            return None
        payload = json.loads(self.profile.token_cache_path.read_text(encoding="utf-8"))
        token = KisAccessToken(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "Bearer"),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
        )
        return None if token.is_expired else token

    def save_token(self, token: KisAccessToken) -> None:
        self.profile.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": token.access_token,
            "token_type": token.token_type,
            "expires_at": token.expires_at.isoformat(),
        }
        self.profile.token_cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def issue_access_token(self) -> KisAccessToken:
        if not self.profile.is_ready_for_quotes:
            raise KisApiError("KIS app key and secret are required before requesting a token.")

        payload = _request_json(
            url=f"{self.profile.rest_url}{TOKEN_ENDPOINT}",
            payload={
                "grant_type": "client_credentials",
                "appkey": self.profile.app_key,
                "appsecret": self.profile.app_secret,
            },
        )
        token = KisAccessToken(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "Bearer"),
            expires_at=_parse_expiration(payload),
        )
        self.save_token(token)
        return token

    def get_access_token(self, force_refresh: bool = False) -> KisAccessToken:
        if not force_refresh:
            cached = self.load_cached_token()
            if cached is not None:
                return cached
        return self.issue_access_token()

    def revoke_access_token(self, token: KisAccessToken | None = None) -> dict:
        active = token or self.load_cached_token()
        if active is None:
            raise KisApiError("No cached access token is available to revoke.")
        payload = _request_json(
            url=f"{self.profile.rest_url}{TOKEN_REVOKE_ENDPOINT}",
            payload={
                "appkey": self.profile.app_key,
                "appsecret": self.profile.app_secret,
                "token": active.access_token,
            },
        )
        return payload

    def issue_approval_key(self) -> str:
        if not self.profile.is_ready_for_quotes:
            raise KisApiError("KIS app key and secret are required before requesting an approval key.")
        payload = _request_json(
            url=f"{self.profile.rest_url}{APPROVAL_ENDPOINT}",
            payload={
                "grant_type": "client_credentials",
                "appkey": self.profile.app_key,
                "secretkey": self.profile.app_secret,
            },
        )
        approval_key = payload.get("approval_key")
        if not approval_key:
            raise KisApiError(f"KIS approval key response is missing approval_key: {payload}")
        return approval_key

    def issue_hashkey(self, payload: dict[str, object]) -> str:
        if not self.profile.is_ready_for_quotes:
            raise KisApiError("KIS app key and secret are required before requesting a hashkey.")
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url=f"{self.profile.rest_url}{HASHKEY_ENDPOINT}",
            data=encoded,
            headers={
                "content-type": "application/json; charset=utf-8",
                "appkey": self.profile.app_key,
                "appsecret": self.profile.app_secret,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise KisApiError(f"KIS HTTP error {exc.code}: {body}") from exc
        except URLError as exc:
            raise KisApiError(f"KIS network error: {exc}") from exc

        hashkey = str(response_payload.get("HASH", "")).strip()
        if not hashkey:
            raise KisApiError(f"KIS hashkey response is missing HASH: {response_payload}")
        return hashkey
