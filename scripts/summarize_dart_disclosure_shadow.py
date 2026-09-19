from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


KST = timezone(timedelta(hours=9))
_ALLOWED_DISCLOSURE_TYPES = {
    "capital_allocation",
    "capital_structure",
    "contract_or_order",
    "financial_results",
    "governance",
    "other",
}
_ALLOWED_DIRECTIONS = {"positive", "negative", "unknown"}


def _now_kst() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(KST)


def _to_iso_kst(value: datetime) -> str:
    return value.astimezone(KST).replace(microsecond=0).isoformat()


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _empty_summary() -> dict[str, Any]:
    return {
        "events": 0,
        "matched": 0,
        "directional_evaluated": 0,
        "directional_hit_rate": None,
        "avg_future_return_pct": None,
    }


def _read_events(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        return [], []

    required = {
        "event_id",
        "source",
        "source_url",
        "symbol",
        "disclosure_type",
        "impact_direction",
        "available_at",
        "observed_at",
        "publication_state",
    }
    candidates: list[tuple[int, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                invalid.append({"line_no": line_no, "reason": "invalid_json"})
                continue
            if not isinstance(event, dict):
                invalid.append({"line_no": line_no, "reason": "not_an_object"})
                continue

            missing = sorted(field for field in required if _is_missing(event.get(field)))
            disclosure_type = str(event.get("disclosure_type") or "").strip().lower()
            direction = str(event.get("impact_direction") or "").strip().lower()
            available_at = _parse_dt(event.get("available_at"))
            observed_at = _parse_dt(event.get("observed_at"))
            symbol = str(event.get("symbol") or "").strip()

            if missing:
                invalid.append({"line_no": line_no, "reason": "missing_required_fields", "fields": missing})
                continue
            if not symbol.isdigit() or len(symbol) != 6:
                invalid.append({"line_no": line_no, "reason": "invalid_symbol"})
                continue
            if disclosure_type not in _ALLOWED_DISCLOSURE_TYPES:
                invalid.append({"line_no": line_no, "reason": "unsupported_disclosure_type"})
                continue
            if direction not in _ALLOWED_DIRECTIONS:
                invalid.append({"line_no": line_no, "reason": "unsupported_impact_direction"})
                continue
            if event.get("publication_state") != "published":
                invalid.append({"line_no": line_no, "reason": "not_published_disclosure"})
                continue
            if available_at is None or observed_at is None:
                invalid.append({"line_no": line_no, "reason": "timezone_aware_timestamps_required"})
                continue
            if observed_at < available_at:
                invalid.append({"line_no": line_no, "reason": "observed_before_available_at"})
                continue

            normalized = dict(event)
            normalized["symbol"] = symbol
            normalized["disclosure_type"] = disclosure_type
            normalized["impact_direction"] = direction
            normalized["available_at"] = _to_iso_kst(available_at)
            normalized["observed_at"] = _to_iso_kst(observed_at)
            candidates.append((line_no, normalized))

    duplicate_ids = {
        event_id
        for event_id, count in Counter(str(event["event_id"]) for _, event in candidates).items()
        if count > 1
    }
    valid: list[dict[str, Any]] = []
    for line_no, event in candidates:
        if str(event["event_id"]) in duplicate_ids:
            invalid.append({"line_no": line_no, "reason": "duplicate_event_id"})
        else:
            valid.append(event)
    return valid, invalid


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _feature_labels_ready(connection: sqlite3.Connection) -> bool:
    rows = connection.execute("PRAGMA table_info(feature_labels)").fetchall()
    columns = {str(row[1]) for row in rows}
    return {"symbol", "event_time", "horizon_min", "label", "future_return_pct"}.issubset(columns)


def _match_first_label(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    available_at: str,
    horizon_min: int,
    max_lag_hours: int,
) -> dict[str, Any] | None:
    available_dt = _parse_dt(available_at)
    if available_dt is None:
        return None
    end_at = _to_iso_kst(available_dt + timedelta(hours=max_lag_hours))
    row = connection.execute(
        """
        SELECT event_time, label, future_return_pct
        FROM feature_labels
        WHERE symbol = ?
          AND horizon_min = ?
          AND event_time > ?
          AND event_time <= ?
        ORDER BY event_time ASC
        LIMIT 1
        """,
        (symbol, horizon_min, available_at, end_at),
    ).fetchone()
    if row is None:
        return None
    return {
        "label_event_time": str(row[0]),
        "label": str(row[1]),
        "future_return_pct": float(row[2]),
    }


def _direction_hit(direction: str, future_return_pct: float) -> bool | None:
    if direction == "positive":
        return future_return_pct > 0
    if direction == "negative":
        return future_return_pct < 0
    return None


def _summarize(matches: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _empty_summary()
    summary["events"] = len(matches)
    evaluated = [match for match in matches if match.get("matched")]
    directional = [match for match in evaluated if match.get("direction_hit") is not None]
    summary["matched"] = len(evaluated)
    summary["directional_evaluated"] = len(directional)
    if directional:
        summary["directional_hit_rate"] = round(
            sum(1 for match in directional if match["direction_hit"]) / len(directional),
            6,
        )
    if evaluated:
        summary["avg_future_return_pct"] = round(
            sum(float(match["future_return_pct"]) for match in evaluated) / len(evaluated),
            6,
        )
    return summary


def build_report(
    *,
    database_path: Path,
    events_path: Path,
    horizon_min: int,
    max_lag_hours: int = 72,
    generated_at: str | None = None,
) -> dict[str, Any]:
    events, invalid_events = _read_events(events_path)
    report: dict[str, Any] = {
        "generated_at": generated_at or _now_kst(),
        "report": "dart_disclosure_shadow",
        "scope": "disclosure_shadow_only_no_serving_or_order_policy_change",
        "database_path": str(database_path),
        "events_path": str(events_path),
        "horizon_min": horizon_min,
        "max_lag_hours": max_lag_hours,
        "raw_event_count": len(events) + len(invalid_events),
        "invalid_event_count": len(invalid_events),
        "invalid_events": invalid_events,
        "matches": [],
        "summary": _empty_summary(),
        "guardrails": [
            "Use a published official disclosure record only.",
            "Use available_at as the information-availability boundary.",
            "Use the first feature label strictly after available_at for retrospective evaluation.",
            "Do not change E7, paper/live orders, signal, gate, allocator, active model, config, or app/risk.",
        ],
    }
    if not events_path.exists():
        report["status"] = "no_events_file"
        return report
    if not events:
        report["status"] = "no_valid_events"
        return report
    if not database_path.exists():
        report["status"] = "missing_database"
        return report

    try:
        connection = _connect_readonly(database_path)
    except sqlite3.Error as exc:
        report["status"] = "database_open_failed"
        report["error"] = str(exc)
        return report

    try:
        if not _feature_labels_ready(connection):
            report["status"] = "missing_feature_labels_schema"
            return report
        matches: list[dict[str, Any]] = []
        for event in sorted(events, key=lambda row: (str(row["available_at"]), str(row["event_id"]))):
            match = dict(event)
            label = _match_first_label(
                connection,
                symbol=str(event["symbol"]),
                available_at=str(event["available_at"]),
                horizon_min=horizon_min,
                max_lag_hours=max_lag_hours,
            )
            match["matched"] = label is not None
            if label is None:
                match["unmatched_reason"] = "no_label_after_available_at_within_lag"
            else:
                match.update(label)
                match["direction_hit"] = _direction_hit(
                    str(event["impact_direction"]),
                    float(match["future_return_pct"]),
                )
            matches.append(match)
    finally:
        connection.close()

    report["matches"] = matches
    report["summary"] = _summarize(matches)
    report["status"] = "ok"
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or _empty_summary()
    lines = [
        "# DART Disclosure Shadow",
        "",
        "- generated_at: " + str(report.get("generated_at")),
        "- status: " + str(report.get("status")),
        "- scope: " + str(report.get("scope")),
        "- events: " + str(summary.get("events")),
        "- matched: " + str(summary.get("matched")),
        "- directional hit rate: " + str(summary.get("directional_hit_rate")),
        "- average future return: " + str(summary.get("avg_future_return_pct")),
        "",
        "## Interpretation",
        "",
        "- This report is a disclosure-event shadow, not a serving or order signal.",
        "- A matched label is selected only after the recorded available_at boundary.",
        "- E7 is unchanged and this report must not be combined with E7 evaluator results.",
        "- Small samples are observation only, not a strategy promotion result.",
        "",
        "## Events",
        "",
    ]
    matches = report.get("matches") or []
    if not matches:
        lines.append("- no disclosure events")
    else:
        for match in matches:
            lines.append(
                "- {} {} {} available_at={} matched={} hit={}".format(
                    match.get("symbol"),
                    match.get("event_id"),
                    match.get("disclosure_type"),
                    match.get("available_at"),
                    match.get("matched"),
                    match.get("direction_hit"),
                )
            )
    lines.extend(["", "## Guardrails", ""])
    for guardrail in report.get("guardrails") or []:
        lines.append("- " + str(guardrail))
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize official DART disclosure shadow events.")
    parser.add_argument("--database-path", type=Path, default=Path("runtime-data/dev.db"))
    parser.add_argument(
        "--events-path",
        type=Path,
        default=Path("runtime-data/disclosures/events/dart_disclosure_events.jsonl"),
    )
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--max-lag-hours", type=int, default=72)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime-data/reports/research"))
    args = parser.parse_args()

    report = build_report(
        database_path=args.database_path.resolve(),
        events_path=args.events_path.resolve(),
        horizon_min=args.horizon_min,
        max_lag_hours=args.max_lag_hours,
    )
    output_dir = args.output_dir.resolve()
    json_path = output_dir / f"latest-dart-disclosure-shadow-h{args.horizon_min}.json"
    markdown_path = output_dir / f"latest-dart-disclosure-shadow-h{args.horizon_min}.md"
    _write_json(json_path, report)
    _write_text(markdown_path, render_markdown(report))
    print(json_path)
    print(markdown_path)


if __name__ == "__main__":
    main()
