"""Redact sensitive fields from KIS response fixtures.

This helper is intentionally offline-only. It does not call KIS and does not
infer trading decisions; it just prepares raw response samples for tests or
cowork review without leaking credentials or account identifiers.
"""

from __future__ import annotations

import json
from typing import Any


REDACTED = "<REDACTED>"
SENSITIVE_KEY_PARTS = (
    "account",
    "acct",
    "acnt",
    "app_key",
    "appkey",
    "app_secret",
    "appsecret",
    "approval_key",
    "authorization",
    "cano",
    "cust",
    "email",
    "empno",
    "hts_id",
    "ip_addr",
    "phone",
    "prd_cd",
    "prdt_cd",
    "secret",
    "tlno",
    "token",
)
SAFE_EXACT_KEYS = {
    "odno",
    "ord_no",
    "ordno",
    "pdno",
    "prdt_name",
    "shtn_pdno",
    "stck_shrn_iscd",
}


def redact_kis_payload(value: Any, *, replacement: str = REDACTED) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                redacted[key] = replacement
            else:
                redacted[key] = redact_kis_payload(item, replacement=replacement)
        return redacted
    if isinstance(value, list):
        return [redact_kis_payload(item, replacement=replacement) for item in value]
    return value


def redact_kis_json_text(text: str, *, replacement: str = REDACTED) -> str:
    payload = json.loads(text)
    redacted = redact_kis_payload(payload, replacement=replacement)
    return json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def find_unredacted_sensitive_paths(value: Any, *, replacement: str = REDACTED) -> list[str]:
    findings: list[str] = []
    _collect_unredacted_sensitive_paths(value, "$", replacement, findings)
    return findings


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in SAFE_EXACT_KEYS:
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _collect_unredacted_sensitive_paths(value: Any, path: str, replacement: str, findings: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if _is_sensitive_key(str(key)):
                if item != replacement:
                    findings.append(child_path)
                continue
            _collect_unredacted_sensitive_paths(item, child_path, replacement, findings)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_unredacted_sensitive_paths(item, f"{path}[{index}]", replacement, findings)
