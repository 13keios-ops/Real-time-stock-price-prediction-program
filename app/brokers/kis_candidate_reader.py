"""Paper-only, cached-token GET reader for separately approved candidate capture."""

import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from app.brokers.kis_readonly import get_kis_paper_candidate_client
from app.utils.time import now_local, get_timezone

KST = get_timezone("Asia/Seoul")

def _fresh(value, now, seconds=20):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Aware provider time required")
    stamp = stamp.astimezone(KST)
    if stamp.date() != now.date() or not timedelta(0) <= now-stamp <= timedelta(seconds=seconds):
        raise ValueError("Provider time stale or future")
    return stamp


PATHS = {
    "/uapi/domestic-stock/v1/quotations/inquire-index-price": "FHPUP02100000",
    "/uapi/domestic-stock/v1/quotations/volume-rank": "FHPST01710000",
    "/uapi/domestic-stock/v1/quotations/inquire-price": "FHKST01010100",
    "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn": "FHKST01010200",
}
RANK_QUERY = dict(FID_COND_MRKT_DIV_CODE="J", FID_COND_SCR_DIV_CODE="20171", FID_INPUT_ISCD="0000",
                  FID_DIV_CLS_CODE="1", FID_BLNG_CLS_CODE="3", FID_TRGT_CLS_CODE="111111111",
                  FID_TRGT_EXLS_CLS_CODE="1111111111", FID_INPUT_PRICE_1="20000", FID_INPUT_PRICE_2="30000",
                  FID_VOL_CNT="", FID_INPUT_DATE_1="")
RANK_FIELDS = ("mksc_shrn_iscd", "stck_prpr", "prdy_ctrt", "acml_vol", "prdy_vol", "acml_tr_pbmn")
PRICE_FIELDS = ("stck_shrn_iscd", "stck_prpr", "prdy_ctrt", "acml_tr_pbmn", "temp_stop_yn",
                "sltr_yn", "mang_issu_cls_code", "invt_caful_yn", "mrkt_warn_cls_code", "short_over_yn")
QUOTE_FIELDS = ("askp1", "bidp1", "aspr_acpt_hour")


class CandidateRestReader:
    """No order/auth/account methods. A live provider-date verifier is mandatory.

    Verification callbacks are trusted input ports, NOT implemented exchange evidence
    acquisition. Constructing this reader does not activate or approve any polling.
    """
    def __init__(self, profile, token_manager, *, verifier=None, clock=None):
        url = urlsplit(profile.rest_url)
        if (profile.mode != "paper" or url.scheme != "https"
                or url.hostname != "openapivts.koreainvestment.com" or url.port != 29443
                or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("Explicit official paper endpoint required")
        if getattr(token_manager, "profile", profile) != profile:
            raise ValueError("Token profile mismatch")
        self._client = get_kis_paper_candidate_client(profile, token_manager)
        self._verifier = verifier
        self._clock = clock or (lambda: now_local("Asia/Seoul"))

    def get(self, path, tr_id, params, *, timeout_seconds, allow_retry):
        if allow_retry is not False or timeout_seconds != 3 or PATHS.get(path) != tr_id:
            raise ValueError("Unsupported read contract")
        if not callable(self._verifier):
            raise ValueError("Exchange date verification is not connected")
        if not isinstance(params, dict):
            raise ValueError("Invalid read query")
        if path.endswith("volume-rank"):
            if params != RANK_QUERY:
                raise ValueError("Ranking query outside approved capture scope")
        elif (set(params) != {"FID_COND_MRKT_DIV_CODE", "FID_INPUT_ISCD"}
              or params["FID_COND_MRKT_DIV_CODE"] != ("U" if path.endswith("inquire-index-price") else "J")
              or not isinstance(params["FID_INPUT_ISCD"], str)
              or not re.fullmatch(r"[0-9]{4}" if path.endswith("inquire-index-price") else r"[0-9]{6}", params["FID_INPUT_ISCD"])):
            raise ValueError("Only explicit KRX stock quote queries allowed")
        preflight = getattr(self._verifier, 'preflight', None)
        if callable(preflight):
            preflight(path, params)
        try:
            payload, _ = self._client.get_candidate_response(path=path, tr_id=tr_id, query_params=params)
        except Exception:
            raise ValueError("Candidate read failed; no retry or token refresh") from None
        if not isinstance(payload, dict):
            raise ValueError("Invalid read response")
        code = str(payload.get("msg_cd", ""))
        code = code if re.fullmatch(r"[A-Za-z0-9_-]{0,24}", code) else "redacted"
        result = dict(rt_cd=str(payload.get("rt_cd", ""))[:4], msg_cd=code)
        if result["rt_cd"] != "0":
            return result
        key, fields = (("output", ("bstp_nmix_prdy_ctrt",)) if path.endswith("inquire-index-price") else
                       ("output", RANK_FIELDS) if path.endswith("volume-rank") else
                       ("output", PRICE_FIELDS) if path.endswith("inquire-price") else ("output1", QUOTE_FIELDS))
        output = payload.get(key)
        def filtered(row):
            if not isinstance(row, dict):
                raise ValueError("Invalid quote record")
            return {k: row[k] for k in fields if k in row and isinstance(row[k], (str, int, float)) and not isinstance(row[k], bool)}
        if path.endswith("volume-rank"):
            if not isinstance(output, list) or len(output) > 1000:
                raise ValueError("Invalid ranking output")
            result[key] = [filtered(row) for row in output]
        else:
            result[key] = filtered(output)
        try:
            proof = self._verifier(path, dict(params), result)
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Aware read clock required")
            now = now.astimezone(KST)
            if proof.get("verification_version") != "kis-exchange-day-anchor-v1" or not re.fullmatch(r"[0-9a-f]{64}", proof.get("source_hash", "")):
                raise ValueError("Unverified exchange context")
            if proof.get("trade_date") != now.date().isoformat():
                raise ValueError("Provider trade date mismatch")
            _fresh(proof["verified_at"], now, 20)
            result["trade_date"] = proof["trade_date"]
            if key == "output1":
                provider = _fresh(proof["provider_at"], now, 20)
                if result[key].get("aspr_acpt_hour") != provider.strftime("%H%M%S"):
                    raise ValueError("Provider HHMMSS does not match dated evidence")
                result["provider_at"] = provider.isoformat()
            result["provider_source_hash"] = proof["source_hash"]
            result["received_at"] = now.isoformat()
            scope = proof.get("verification_scope")
            if scope in ("market_trading_day_context_only", "same_symbol_dated_minute", "index_market_day_context_only"):
                result["verification_scope"] = scope
            if path.endswith("inquire-index-price"):
                result["index_code"] = params["FID_INPUT_ISCD"]
        except Exception:
            raise ValueError("Provider date/time evidence unverified") from None
        return result
