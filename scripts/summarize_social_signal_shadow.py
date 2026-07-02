from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


KST = timezone(timedelta(hours=9))


def _now_kst() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_iso_kst(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                events.append({"event_id": f"invalid-line-{line_no}", "invalid": True, "line_no": line_no})
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row[1]) for row in rows}


def _match_label(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    published_at: str,
    max_lag_minutes: int,
    horizon_min: int,
) -> dict[str, Any] | None:
    start_dt = _parse_dt(published_at)
    if start_dt is None:
        return None
    start_iso = _to_iso_kst(start_dt)
    end_iso = _to_iso_kst(start_dt + timedelta(minutes=max_lag_minutes))
    row = connection.execute(
        """
        SELECT event_time, label, future_return_pct
        FROM feature_labels
        WHERE symbol = ?
          AND horizon_min = ?
          AND event_time >= ?
          AND event_time <= ?
        ORDER BY event_time ASC
        LIMIT 1
        """,
        (symbol, horizon_min, start_iso, end_iso),
    ).fetchone()
    if row is None:
        return None
    return {
        "label_event_time": row[0],
        "label": row[1],
        "future_return_pct": float(row[2]),
    }


def _normalize_symbols(event: dict[str, Any]) -> list[str]:
    symbols = event.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [symbols]
    return [str(symbol).strip() for symbol in symbols if str(symbol).strip()]


def _direction_hit(impact_direction: str | None, future_return_pct: float | None) -> bool | None:
    if future_return_pct is None:
        return None
    direction = (impact_direction or "").lower()
    if direction in {"positive", "up", "bullish"}:
        return future_return_pct > 0
    if direction in {"negative", "down", "bearish"}:
        return future_return_pct < 0
    if direction in {"neutral", "flat"}:
        return abs(future_return_pct) < 0.35
    return None


def _summarize_group(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    matched = [row for row in materialized if row.get("matched")]
    directional = [row for row in matched if row.get("direction_hit") is not None]
    avg_return = None
    if matched:
        avg_return = round(sum(float(row["future_return_pct"]) for row in matched) / len(matched), 6)
    hit_rate = None
    if directional:
        hit_rate = round(sum(1 for row in directional if row.get("direction_hit")) / len(directional), 6)
    return {
        "events": len(materialized),
        "matched": len(matched),
        "directional_evaluated": len(directional),
        "directional_hit_rate": hit_rate,
        "avg_future_return_pct": avg_return,
    }


def build_report(
    *,
    database_path: Path,
    events_path: Path,
    horizon_min: int,
    max_lag_minutes: int = 180,
    generated_at: str | None = None,
) -> dict[str, Any]:
    events = _read_jsonl(events_path)
    invalid_events = [event for event in events if event.get("invalid")]
    valid_events = [event for event in events if not event.get("invalid")]
    report: dict[str, Any] = {
        "generated_at": generated_at or _now_kst(),
        "report": "social_signal_shadow",
        "scope": "phase1_shadow_only_no_order_policy_change",
        "database_path": str(database_path),
        "events_path": str(events_path),
        "horizon_min": horizon_min,
        "max_lag_minutes": max_lag_minutes,
        "event_count": len(valid_events),
        "invalid_event_count": len(invalid_events),
        "matches": [],
        "summary": {},
        "groups": {},
        "guardrails": [
            "Official API, public feed, or manual export only.",
            "No private scraping, account takeover, paywall bypass, or secret persistence.",
            "No paper/live order, gate, active model, config, VERSION, or app/risk change.",
            "Phase 1 uses social events as research features and alerts only, not execution signals.",
        ],
    }
    if not events_path.exists():
        report["status"] = "no_events_file"
        report["summary"] = _summarize_group([])
        return report
    if not valid_events:
        report["status"] = "no_events"
        report["summary"] = _summarize_group([])
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

    with connection:
        columns = _table_columns(connection, "feature_labels")
        required = {"symbol", "event_time", "horizon_min", "label", "future_return_pct"}
        if not required.issubset(columns):
            report["status"] = "missing_feature_labels_schema"
            report["missing_columns"] = sorted(required - columns)
            return report

        matches: list[dict[str, Any]] = []
        for event in valid_events:
            symbols = _normalize_symbols(event)
            if not symbols:
                matches.append(
                    {
                        "event_id": event.get("event_id") or event.get("source_event_id"),
                        "matched": False,
                        "unmatched_reason": "missing_symbols",
                    }
                )
                continue
            for symbol in symbols:
                label = _match_label(
                    connection,
                    symbol=symbol,
                    published_at=str(event.get("published_at") or ""),
                    max_lag_minutes=max_lag_minutes,
                    horizon_min=horizon_min,
                )
                row = {
                    "event_id": event.get("event_id") or event.get("source_event_id"),
                    "source": event.get("source"),
                    "author_id": event.get("author_id"),
                    "event_type": event.get("event_type"),
                    "impact_direction": event.get("impact_direction"),
                    "confidence": event.get("confidence"),
                    "symbol": symbol,
                    "published_at": event.get("published_at"),
                    "matched": label is not None,
                }
                if label is None:
                    row["unmatched_reason"] = "no_closed_label_within_lag"
                else:
                    row.update(label)
                    row["direction_hit"] = _direction_hit(
                        str(event.get("impact_direction") or ""),
                        float(label["future_return_pct"]),
                    )
                matches.append(row)
        report["matches"] = matches
        report["summary"] = _summarize_group(matches)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in matches:
            for key in ("source", "author_id", "event_type", "impact_direction"):
                grouped[f"{key}:{row.get(key) or 'unknown'}"].append(row)
        report["groups"] = {key: _summarize_group(rows) for key, rows in sorted(grouped.items())}
        report["status"] = "ok"
        return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {}) or {}
    lines = [
        "# Social Signal Shadow",
        "",
        f"- 생성 시각: `{report.get('generated_at')}`",
        f"- 상태: `{report.get('status')}`",
        f"- 범위: `{report.get('scope')}`",
        f"- 이벤트 파일: `{report.get('events_path')}`",
        f"- horizon: `{report.get('horizon_min')}분`",
        "",
        "## 요약",
        "",
        f"- 이벤트 수: `{report.get('event_count')}`",
        f"- label 매칭: `{summary.get('matched')}` / `{summary.get('events')}`",
        f"- 방향 적중률: `{summary.get('directional_hit_rate')}`",
        f"- 평균 미래 수익률: `{summary.get('avg_future_return_pct')}`",
        "",
        "## 해석",
        "",
        "- 이 리포트는 SNS/공개 이벤트가 이후 15분 또는 60분 가격 변화와 연결되는지 보는 진단입니다.",
        "- Phase 1에서는 알림과 연구 피처로만 보며, 주문 판단에는 쓰지 않습니다.",
        "- 표본이 작으면 수익률보다 `표본 부족`을 먼저 해석합니다.",
        "",
        "## 그룹 요약",
        "",
    ]
    groups = report.get("groups", {}) or {}
    if not groups:
        lines.append("- 그룹 결과가 없습니다.")
    else:
        for key, value in groups.items():
            lines.append(
                f"- `{key}`: events={value.get('events')}, matched={value.get('matched')}, "
                f"hit_rate={value.get('directional_hit_rate')}, avg_return={value.get('avg_future_return_pct')}"
            )
    lines.extend(["", "## 안전 가드레일", ""])
    for guardrail in report.get("guardrails", []):
        lines.append(f"- {guardrail}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize social/public influence signal shadow events.")
    parser.add_argument("--database-path", type=Path, default=Path("runtime-data/dev.db"))
    parser.add_argument("--events-path", type=Path, default=Path("runtime-data/social/signals/social_events.jsonl"))
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--max-lag-minutes", type=int, default=180)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime-data/reports/research"))
    args = parser.parse_args()

    database_path = args.database_path.resolve()
    events_path = args.events_path.resolve()
    report = build_report(
        database_path=database_path,
        events_path=events_path,
        horizon_min=args.horizon_min,
        max_lag_minutes=args.max_lag_minutes,
    )
    output_dir = args.output_dir.resolve()
    json_path = output_dir / f"latest-social-signal-shadow-h{args.horizon_min}.json"
    md_path = output_dir / f"latest-social-signal-shadow-h{args.horizon_min}.md"
    _write_json(json_path, report)
    _write_text(md_path, render_markdown(report))
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
