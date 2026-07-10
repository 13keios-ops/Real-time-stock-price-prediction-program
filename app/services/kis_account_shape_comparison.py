"""Compare sanitized KIS paper/live account snapshot shapes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_PRESENCE_FIELDS = (
    "cash_balance_present",
    "stock_evaluation_present",
    "total_asset_present",
)


def compare_kis_account_snapshot_checks(
    paper_check: dict[str, Any],
    live_check: dict[str, Any],
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare only whitelisted shape metadata from two sanitized checks."""

    observed_at = checked_at or datetime.now(timezone.utc)
    paper = _summarize_check(paper_check)
    live = _summarize_check(live_check)

    blocking_reasons = _validation_reasons("paper", paper, expected_mode="paper")
    blocking_reasons.extend(_validation_reasons("live", live, expected_mode="live"))

    shape_differences: list[dict[str, Any]] = []
    for field in (
        "required_attributes",
        "missing_attributes",
        "invalid_type_attributes",
        *_PRESENCE_FIELDS,
    ):
        if paper[field] != live[field]:
            shape_differences.append(
                {
                    "field": field,
                    "paper": paper[field],
                    "live": live[field],
                }
            )

    if shape_differences:
        blocking_reasons.append("paper_live_account_shape_differs")

    passed = not blocking_reasons
    return {
        "schema_version": 1,
        "status": "ok" if passed else "blocked",
        "passed": passed,
        "checked_at": observed_at.isoformat(),
        "comparison": "kis_account_snapshot_shape_paper_vs_live",
        "paper": paper,
        "live": live,
        "shape_differences": shape_differences,
        "row_count_observation": {
            "paper_position_row_count": paper["position_row_count"],
            "paper_summary_row_count": paper["summary_row_count"],
            "live_position_row_count": live["position_row_count"],
            "live_summary_row_count": live["summary_row_count"],
            "counts_are_shape_observations_not_equality_requirements": True,
        },
        "blocking_reasons": _dedupe(blocking_reasons),
        "sanitization": {
            "raw_response_included": False,
            "account_identifier_included": False,
            "balance_values_included": False,
        },
    }


def _summarize_check(check: dict[str, Any]) -> dict[str, Any]:
    details = check.get("details") if isinstance(check.get("details"), dict) else {}
    return {
        "key": _safe_text(check.get("key")),
        "status": _safe_text(check.get("status")),
        "passed": bool(check.get("passed", False)),
        "mode": _safe_text(details.get("mode")),
        "shape_status": _safe_text(details.get("shape_status")),
        "required_attributes": _safe_string_list(details.get("required_attributes")),
        "missing_attributes": _safe_string_list(details.get("missing_attributes")),
        "invalid_type_attributes": _safe_invalid_type_attributes(details.get("invalid_type_attributes")),
        "position_row_count": _safe_non_negative_int(details.get("position_row_count")),
        "summary_row_count": _safe_non_negative_int(details.get("summary_row_count")),
        **{field: bool(details.get(field, False)) for field in _PRESENCE_FIELDS},
    }


def _validation_reasons(label: str, summary: dict[str, Any], *, expected_mode: str) -> list[str]:
    reasons: list[str] = []
    if summary["key"] != "account_snapshot":
        reasons.append(f"{label}_account_snapshot_check_invalid_key")
    if summary["mode"] != expected_mode:
        reasons.append(f"{label}_account_snapshot_check_mode_mismatch")
    if not summary["passed"] or summary["status"] != "ok":
        reasons.append(f"{label}_account_snapshot_check_not_passed")
    if summary["shape_status"] != "ok":
        reasons.append(f"{label}_account_snapshot_shape_not_ok")
    return reasons


def _safe_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(item for item in value if isinstance(item, str))


def _safe_invalid_type_attributes(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    sanitized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        sanitized.append(
            {
                "attribute": _safe_text(item.get("attribute")),
                "expected": _safe_text(item.get("expected")),
                "actual_type": _safe_text(item.get("actual_type")),
            }
        )
    return sorted(sanitized, key=lambda item: (item["attribute"], item["expected"], item["actual_type"]))


def _safe_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
