"""Sanitized KIS probe error classification helpers."""

from __future__ import annotations

import re
from typing import Any


_KIS_CODE_PATTERN = re.compile(r"\b(?:EGW|APBK|APIGW|MCA|OPS)\d{3,}\b", re.IGNORECASE)
_HTTP_STATUS_PATTERN = re.compile(r"KIS HTTP error\s+(\d{3})", re.IGNORECASE)


def build_sanitized_kis_probe_error(exc: Exception) -> dict[str, Any]:
    """Classify a KIS probe exception without returning the raw error body."""

    message = str(exc)
    lower = message.lower()
    codes = sorted({match.upper() for match in _KIS_CODE_PATTERN.findall(message)})
    http_status = _extract_http_status(message)

    category = "client_error"
    if "app key and secret are required" in lower:
        category = "missing_quote_credentials"
    elif "account number and product code are required" in lower:
        category = "missing_account_credentials"
    elif "egw00201" in lower or "초당 거래건수" in message:
        category = "rate_limited"
    elif "egw00121" in lower or "egw00123" in lower:
        category = "token_invalid_or_expired"
    elif lower.startswith("kis network error"):
        category = "network_error"
    elif lower.startswith("kis http error"):
        category = "http_error"
    elif lower.startswith("kis rest quote error"):
        category = "kis_business_error"

    result: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error_category": category,
    }
    if http_status is not None:
        result["http_status"] = http_status
    if codes:
        result["kis_error_codes"] = codes
    return result


def _extract_http_status(message: str) -> int | None:
    match = _HTTP_STATUS_PATTERN.search(message)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
