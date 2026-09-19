from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


KST = timezone(timedelta(hours=9))


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


def _finite_nonnegative(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _empty_summary() -> dict[str, Any]:
    return {
        "observations": 0,
        "matched": 0,
        "net_position_observations": 0,
        "net_position_delta_observations": 0,
        "avg_future_return_pct": None,
        "by_short_volume_band": {},
    }


def _read_observations(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        return [], []

    required = {
        "observation_id",
        "source",
        "source_url",
        "market",
        "symbol",
        "trade_date",
        "short_sale_volume",
        "total_volume",
        "short_sale_value_krw",
        "total_value_krw",
        "available_at",
        "observed_at",
        "completeness",
    }
    candidates: list[tuple[int, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                observation = json.loads(line)
            except json.JSONDecodeError:
                invalid.append({"line_no": line_no, "reason": "invalid_json"})
                continue
            if not isinstance(observation, dict):
                invalid.append({"line_no": line_no, "reason": "not_an_object"})
                continue

            missing = sorted(field for field in required if _is_missing(observation.get(field)))
            if missing:
                invalid.append({"line_no": line_no, "reason": "missing_required_fields", "fields": missing})
                continue
            symbol = str(observation.get("symbol") or "").strip()
            try:
                date.fromisoformat(str(observation.get("trade_date")))
            except ValueError:
                invalid.append({"line_no": line_no, "reason": "invalid_trade_date"})
                continue
            if not symbol.isdigit() or len(symbol) != 6:
                invalid.append({"line_no": line_no, "reason": "invalid_symbol"})
                continue
            if observation.get("completeness") != "final":
                invalid.append({"line_no": line_no, "reason": "not_finalized_eod_observation"})
                continue

            available_at = _parse_dt(observation.get("available_at"))
            observed_at = _parse_dt(observation.get("observed_at"))
            if available_at is None or observed_at is None:
                invalid.append({"line_no": line_no, "reason": "timezone_aware_timestamps_required"})
                continue
            if observed_at < available_at:
                invalid.append({"line_no": line_no, "reason": "observed_before_available_at"})
                continue

            numeric_fields = {
                field: _finite_nonnegative(observation.get(field))
                for field in (
                    "short_sale_volume",
                    "total_volume",
                    "short_sale_value_krw",
                    "total_value_krw",
                )
            }
            invalid_field = next((field for field, value in numeric_fields.items() if value is None), None)
            if invalid_field:
                invalid.append({"line_no": line_no, "reason": f"invalid_{invalid_field}"})
                continue
            if not numeric_fields["total_volume"]:
                invalid.append({"line_no": line_no, "reason": "invalid_total_volume"})
                continue
            if numeric_fields["short_sale_volume"] > numeric_fields["total_volume"]:
                invalid.append({"line_no": line_no, "reason": "short_sale_volume_exceeds_total_volume"})
                continue
            if numeric_fields["short_sale_value_krw"] > numeric_fields["total_value_krw"]:
                invalid.append({"line_no": line_no, "reason": "short_sale_value_exceeds_total_value"})
                continue

            position_fields = ("net_short_position_qty", "net_short_position_value_krw")
            present_position_fields = [field for field in position_fields if not _is_missing(observation.get(field))]
            if present_position_fields and len(present_position_fields) != len(position_fields):
                invalid.append({"line_no": line_no, "reason": "incomplete_net_short_position_fields"})
                continue
            position_values: dict[str, float | None] = {field: None for field in position_fields}
            if present_position_fields:
                for field in position_fields:
                    position_values[field] = _finite_nonnegative(observation.get(field))
                invalid_position_field = next(
                    (field for field, value in position_values.items() if value is None),
                    None,
                )
                if invalid_position_field:
                    invalid.append({"line_no": line_no, "reason": f"invalid_{invalid_position_field}"})
                    continue

            normalized = dict(observation)
            normalized["symbol"] = symbol
            normalized.update(numeric_fields)
            normalized.update(position_values)
            normalized["available_at"] = _to_iso_kst(available_at)
            normalized["observed_at"] = _to_iso_kst(observed_at)
            candidates.append((line_no, normalized))

    duplicate_ids = {
        observation_id
        for observation_id, count in Counter(str(row["observation_id"]) for _, row in candidates).items()
        if count > 1
    }
    valid: list[dict[str, Any]] = []
    for line_no, observation in candidates:
        if str(observation["observation_id"]) in duplicate_ids:
            invalid.append({"line_no": line_no, "reason": "duplicate_observation_id"})
        else:
            valid.append(observation)
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
    max_lag_days: int,
) -> dict[str, Any] | None:
    available_dt = _parse_dt(available_at)
    if available_dt is None:
        return None
    end_at = _to_iso_kst(available_dt + timedelta(days=max_lag_days))
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


def _short_volume_band(short_volume_ratio_pct: float) -> str:
    if short_volume_ratio_pct < 1:
        return "under_1pct"
    if short_volume_ratio_pct < 5:
        return "1_to_5pct"
    if short_volume_ratio_pct < 10:
        return "5_to_10pct"
    return "10pct_or_more"


def _summarize(matches: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _empty_summary()
    summary["observations"] = len(matches)
    evaluated = [match for match in matches if match.get("matched")]
    net_position = [match for match in matches if match.get("net_short_position_qty") is not None]
    net_deltas = [match for match in net_position if match.get("net_short_position_qty_delta") is not None]
    summary["matched"] = len(evaluated)
    summary["net_position_observations"] = len(net_position)
    summary["net_position_delta_observations"] = len(net_deltas)
    if evaluated:
        summary["avg_future_return_pct"] = round(
            sum(float(match["future_return_pct"]) for match in evaluated) / len(evaluated),
            6,
        )

    by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in evaluated:
        by_band[str(match["short_volume_band"])].append(match)
    summary["by_short_volume_band"] = {
        band: {
            "matched": len(rows),
            "avg_future_return_pct": round(
                sum(float(row["future_return_pct"]) for row in rows) / len(rows),
                6,
            ),
        }
        for band, rows in sorted(by_band.items())
    }
    return summary


def build_report(
    *,
    database_path: Path,
    observations_path: Path,
    horizon_min: int,
    max_lag_days: int = 7,
    generated_at: str | None = None,
) -> dict[str, Any]:
    observations, invalid_observations = _read_observations(observations_path)
    report: dict[str, Any] = {
        "generated_at": generated_at or _now_kst(),
        "report": "krx_short_sale_shadow",
        "scope": "finalized_eod_shadow_only_no_serving_or_order_policy_change",
        "database_path": str(database_path),
        "observations_path": str(observations_path),
        "horizon_min": horizon_min,
        "max_lag_days": max_lag_days,
        "raw_observation_count": len(observations) + len(invalid_observations),
        "invalid_observation_count": len(invalid_observations),
        "invalid_observations": invalid_observations,
        "matches": [],
        "summary": _empty_summary(),
        "guardrails": [
            "Use finalized EOD KRX observations only.",
            "Use available_at as the information-availability boundary.",
            "Use the first feature label strictly after available_at for retrospective evaluation.",
            "Do not infer a trade direction from short-sale data in this initial report.",
            "Do not change E7, paper/live orders, signal, gate, allocator, active model, config, or app/risk.",
        ],
    }
    if not observations_path.exists():
        report["status"] = "no_observations_file"
        return report
    if not observations:
        report["status"] = "no_valid_observations"
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
        previous_position: dict[tuple[str, str, str], float] = {}
        matches: list[dict[str, Any]] = []
        for observation in sorted(
            observations,
            key=lambda row: (
                str(row["source"]),
                str(row["market"]),
                str(row["symbol"]),
                str(row["trade_date"]),
                str(row["observation_id"]),
            ),
        ):
            match = dict(observation)
            ratio = 100 * float(match["short_sale_volume"]) / float(match["total_volume"])
            match["short_volume_ratio_pct"] = round(ratio, 6)
            match["short_volume_band"] = _short_volume_band(ratio)
            key = (str(match["source"]), str(match["market"]), str(match["symbol"]))
            quantity = match.get("net_short_position_qty")
            match["net_short_position_qty_delta"] = None
            if quantity is not None:
                prior = previous_position.get(key)
                if prior is not None:
                    match["net_short_position_qty_delta"] = float(quantity) - prior
                previous_position[key] = float(quantity)

            label = _match_first_label(
                connection,
                symbol=str(match["symbol"]),
                available_at=str(match["available_at"]),
                horizon_min=horizon_min,
                max_lag_days=max_lag_days,
            )
            match["matched"] = label is not None
            if label is None:
                match["unmatched_reason"] = "no_label_after_available_at_within_lag"
            else:
                match.update(label)
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
        "# KRX Short-Sale Shadow",
        "",
        "- generated_at: " + str(report.get("generated_at")),
        "- status: " + str(report.get("status")),
        "- scope: " + str(report.get("scope")),
        "- observations: " + str(summary.get("observations")),
        "- matched: " + str(summary.get("matched")),
        "- net-position observations: " + str(summary.get("net_position_observations")),
        "- net-position deltas: " + str(summary.get("net_position_delta_observations")),
        "- average future return: " + str(summary.get("avg_future_return_pct")),
        "",
        "## Interpretation",
        "",
        "- This is finalized EOD short-sale research, not an intraday, serving, or order signal.",
        "- A matched label is selected only after the recorded available_at boundary.",
        "- Short-sale ratios and net-position deltas are descriptive observations, not assumed buy or sell directions.",
        "- E7 is unchanged and this report must not be combined with E7 evaluator results.",
        "",
        "## Observations",
        "",
    ]
    matches = report.get("matches") or []
    if not matches:
        lines.append("- no short-sale observations")
    else:
        for match in matches:
            lines.append(
                "- {} {} ratio={} band={} matched={}".format(
                    match.get("symbol"),
                    match.get("trade_date"),
                    match.get("short_volume_ratio_pct"),
                    match.get("short_volume_band"),
                    match.get("matched"),
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
    parser = argparse.ArgumentParser(description="Summarize finalized KRX short-sale EOD observations.")
    parser.add_argument("--database-path", type=Path, default=Path("runtime-data/dev.db"))
    parser.add_argument(
        "--observations-path",
        type=Path,
        default=Path("runtime-data/short-sale/observations/short_sale_eod.jsonl"),
    )
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--max-lag-days", type=int, default=7)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime-data/reports/research"))
    args = parser.parse_args()

    report = build_report(
        database_path=args.database_path.resolve(),
        observations_path=args.observations_path.resolve(),
        horizon_min=args.horizon_min,
        max_lag_days=args.max_lag_days,
    )
    output_dir = args.output_dir.resolve()
    json_path = output_dir / f"latest-krx-short-sale-shadow-h{args.horizon_min}.json"
    markdown_path = output_dir / f"latest-krx-short-sale-shadow-h{args.horizon_min}.md"
    _write_json(json_path, report)
    _write_text(markdown_path, render_markdown(report))
    print(json_path)
    print(markdown_path)


if __name__ == "__main__":
    main()
