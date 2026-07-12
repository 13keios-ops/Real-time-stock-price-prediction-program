#!/usr/bin/env python3
"""Run a read-only paper hold-rescue replay.

This report is a research diagnostic. It reconstructs closed paper lots from
local fills, treats the actual paper sell fill as the baseline exit, and checks
whether a LightGBM up-probability threshold would have improved or worsened the
lot if the position had been held a little longer.

It does not submit orders, alter paper/live runtime behavior, update risk gates,
or change active model state.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.paper_trading.costs import (
    build_domestic_stock_cost_model_metadata,
)

from scripts.summarize_hold_rescue_paper_replay_feasibility import (
    DEFAULT_DATABASE,
    DEFAULT_MODEL_VERSION,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SINCE_DATE,
    BarPoint,
    ClosedLot,
    PredictionPoint,
    _connect_readonly,
    _float,
    _load_bars,
    _load_fills,
    _load_predictions,
    _minute_key,
    _now_iso,
    _parse_date,
    _parse_time,
    reconstruct_closed_lots,
)


DEFAULT_TRADE_COST_PCT = float(build_domestic_stock_cost_model_metadata()["round_trip_cost_pct"])
DEFAULT_THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65)
MIN_ELIGIBLE_LOTS = 30
MIN_APPLIED_LOTS = 10
MIN_NONNEGATIVE_DAY_SHARE = 2.0 / 3.0
MIN_IMPROVED_APPLIED_SHARE = 0.50


@dataclass(frozen=True)
class EligibleLot:
    lot: ClosedLot
    exit_prediction: PredictionPoint
    future_bars: list[BarPoint]


@dataclass(frozen=True)
class RescueLotResult:
    symbol: str
    qty: float
    entry_time: datetime
    baseline_exit_time: datetime
    rescue_exit_time: datetime
    entry_price: float
    baseline_exit_price: float
    rescue_exit_price: float
    baseline_probability_up: float
    threshold: float
    rescue_applied: bool
    rescue_exit_reason: str
    extension_minutes: float
    baseline_cash_delta: float
    rescue_cash_delta: float
    delta_cash: float
    baseline_net_return_pct: float
    rescue_net_return_pct: float
    delta_return_pct: float
    max_drawdown_pct: float


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _same_day_limit(exit_time: datetime, forced_flat_time: time) -> datetime:
    limit = datetime.combine(exit_time.date(), forced_flat_time)
    if exit_time.tzinfo is not None:
        limit = limit.replace(tzinfo=exit_time.tzinfo)
    return limit


def _prediction_up(prediction: PredictionPoint | None) -> float | None:
    if prediction is None:
        return None
    value = _float(prediction.probability_up)
    return value if value is not None else None


def _future_bars_for_lot(
    bars_by_symbol: dict[str, list[BarPoint]],
    lot: ClosedLot,
    *,
    max_extension_minutes: int,
    forced_flat_time: time,
) -> list[BarPoint]:
    symbol_bars = bars_by_symbol.get(lot.symbol, [])
    if not symbol_bars:
        return []
    exit_minute = lot.exit_time.replace(second=0, microsecond=0)
    target_time = min(
        exit_minute + timedelta(minutes=max_extension_minutes),
        _same_day_limit(lot.exit_time, forced_flat_time),
    )
    times = [bar.event_time for bar in symbol_bars]
    start = bisect.bisect_right(times, exit_minute)
    future: list[BarPoint] = []
    for bar in symbol_bars[start:]:
        if bar.event_time.date() != lot.exit_time.date():
            break
        if bar.event_time > target_time:
            break
        future.append(bar)
    return future


def _eligibility(
    lots: list[ClosedLot],
    predictions: dict[tuple[str, str], PredictionPoint],
    bars_by_symbol: dict[str, list[BarPoint]],
    *,
    max_extension_minutes: int,
    forced_flat_time: time,
) -> tuple[list[EligibleLot], dict[str, Any]]:
    eligible: list[EligibleLot] = []
    excluded: Counter[str] = Counter()
    for lot in lots:
        if lot.entry_time.date() != lot.exit_time.date():
            excluded["cross_day_lot"] += 1
            continue
        if lot.exit_time.weekday() >= 5:
            excluded["non_weekday_exit"] += 1
            continue
        if lot.exit_time.timetz().replace(tzinfo=None) >= forced_flat_time:
            excluded["exit_at_or_after_forced_flat"] += 1
            continue
        exit_prediction = predictions.get((lot.symbol, _minute_key(lot.exit_time)))
        if _prediction_up(exit_prediction) is None:
            excluded["missing_exit_prediction"] += 1
            continue
        future_bars = _future_bars_for_lot(
            bars_by_symbol,
            lot,
            max_extension_minutes=max_extension_minutes,
            forced_flat_time=forced_flat_time,
        )
        if not future_bars:
            excluded["missing_future_bars"] += 1
            continue
        eligible.append(EligibleLot(lot=lot, exit_prediction=exit_prediction, future_bars=future_bars))
    return eligible, {
        "closed_lots": len(lots),
        "eligible_lots": len(eligible),
        "excluded_lots": sum(excluded.values()),
        "excluded_reasons": dict(sorted(excluded.items())),
    }


def simulate_rescue_for_lot(
    eligible_lot: EligibleLot,
    *,
    threshold: float,
    predictions: dict[tuple[str, str], PredictionPoint],
    max_loss_pct: float | None,
    trade_cost_pct: float,
) -> RescueLotResult:
    lot = eligible_lot.lot
    baseline_probability_up = _prediction_up(eligible_lot.exit_prediction)
    if baseline_probability_up is None:
        raise ValueError("eligible_lot must include an exit prediction with probability_up.")

    rescue_applied = baseline_probability_up >= threshold
    rescue_exit_time = lot.exit_time
    rescue_exit_price = lot.exit_price
    rescue_exit_reason = "threshold_not_met"
    max_drawdown_pct = ((lot.exit_price / lot.entry_price) - 1.0) * 100.0
    max_loss_limit = abs(max_loss_pct) if max_loss_pct is not None else None

    if rescue_applied:
        rescue_exit_reason = "end_of_available_path"
        for index, bar in enumerate(eligible_lot.future_bars):
            rescue_exit_time = bar.event_time
            rescue_exit_price = bar.close
            current_return_pct = ((bar.close / lot.entry_price) - 1.0) * 100.0
            max_drawdown_pct = min(max_drawdown_pct, current_return_pct)
            if max_loss_limit is not None and current_return_pct <= -max_loss_limit:
                rescue_exit_reason = "max_loss"
                break
            prediction_up = _prediction_up(predictions.get((lot.symbol, _minute_key(bar.event_time))))
            if prediction_up is None:
                rescue_exit_reason = "missing_prediction"
                break
            if prediction_up < threshold:
                rescue_exit_reason = "probability_dropped"
                break
            if index == len(eligible_lot.future_bars) - 1:
                rescue_exit_reason = "max_extension_or_forced_flat"

    baseline_cash_delta = (lot.exit_price - lot.entry_price) * lot.qty
    rescue_cash_delta = (rescue_exit_price - lot.entry_price) * lot.qty
    baseline_net_return_pct = ((lot.exit_price / lot.entry_price) - 1.0) * 100.0 - trade_cost_pct
    rescue_net_return_pct = ((rescue_exit_price / lot.entry_price) - 1.0) * 100.0 - trade_cost_pct
    return RescueLotResult(
        symbol=lot.symbol,
        qty=lot.qty,
        entry_time=lot.entry_time,
        baseline_exit_time=lot.exit_time,
        rescue_exit_time=rescue_exit_time,
        entry_price=lot.entry_price,
        baseline_exit_price=lot.exit_price,
        rescue_exit_price=rescue_exit_price,
        baseline_probability_up=baseline_probability_up,
        threshold=threshold,
        rescue_applied=rescue_applied,
        rescue_exit_reason=rescue_exit_reason,
        extension_minutes=max(0.0, (rescue_exit_time - lot.exit_time).total_seconds() / 60.0),
        baseline_cash_delta=baseline_cash_delta,
        rescue_cash_delta=rescue_cash_delta,
        delta_cash=rescue_cash_delta - baseline_cash_delta,
        baseline_net_return_pct=baseline_net_return_pct,
        rescue_net_return_pct=rescue_net_return_pct,
        delta_return_pct=rescue_net_return_pct - baseline_net_return_pct,
        max_drawdown_pct=max_drawdown_pct,
    )


def _share(count: int, denominator: int) -> float:
    return count / denominator if denominator else 0.0


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def percentile(pct: float) -> float:
        index = int(round((len(ordered) - 1) * pct))
        return ordered[max(0, min(index, len(ordered) - 1))]

    return {
        "count": len(ordered),
        "min": _round(ordered[0]),
        "p10": _round(percentile(0.10)),
        "p25": _round(percentile(0.25)),
        "p50": _round(percentile(0.50)),
        "p75": _round(percentile(0.75)),
        "p90": _round(percentile(0.90)),
        "p95": _round(percentile(0.95)),
        "max": _round(ordered[-1]),
        "avg": _round(sum(ordered) / len(ordered)),
    }


def _summarize_threshold(results: list[RescueLotResult], threshold: float) -> dict[str, Any]:
    applied = [result for result in results if result.rescue_applied]
    improved = [result for result in applied if result.delta_cash > 0]
    worsened = [result for result in applied if result.delta_cash < 0]
    unchanged = [result for result in applied if abs(result.delta_cash) <= 1e-9]
    exit_reasons = Counter(result.rescue_exit_reason for result in results)
    applied_days: dict[str, float] = {}
    for result in applied:
        day = result.baseline_exit_time.date().isoformat()
        applied_days[day] = applied_days.get(day, 0.0) + result.delta_cash
    nonnegative_days = sum(1 for value in applied_days.values() if value >= 0)
    baseline_cash_delta_sum = sum(result.baseline_cash_delta for result in results)
    rescue_cash_delta_sum = sum(result.rescue_cash_delta for result in results)
    delta_cash_sum = rescue_cash_delta_sum - baseline_cash_delta_sum
    applied_delta_cash_sum = sum(result.delta_cash for result in applied)
    applied_delta_returns = [result.delta_return_pct for result in applied]
    return {
        "threshold": float(threshold),
        "eligible_lots": len(results),
        "applied_lots": len(applied),
        "applied_rate": _share(len(applied), len(results)),
        "baseline_cash_delta_sum": _round(baseline_cash_delta_sum),
        "strategy_cash_delta_sum": _round(rescue_cash_delta_sum),
        "delta_cash_sum": _round(delta_cash_sum),
        "applied_delta_cash_sum": _round(applied_delta_cash_sum),
        "improved_lots": len(improved),
        "worsened_lots": len(worsened),
        "unchanged_applied_lots": len(unchanged),
        "improved_applied_share": _share(len(improved), len(applied)),
        "worsened_applied_share": _share(len(worsened), len(applied)),
        "nonnegative_day_share": _share(nonnegative_days, len(applied_days)),
        "applied_days": len(applied_days),
        "avg_applied_delta_return_pct": _round(sum(applied_delta_returns) / len(applied_delta_returns))
        if applied_delta_returns
        else 0.0,
        "max_single_lot_delta_cash": _round(max((result.delta_cash for result in applied), default=0.0)),
        "min_single_lot_delta_cash": _round(min((result.delta_cash for result in applied), default=0.0)),
        "min_rescue_max_drawdown_pct": _round(min((result.max_drawdown_pct for result in applied), default=0.0)),
        "exit_reasons": dict(sorted(exit_reasons.items())),
    }


def replay_hold_rescue(
    eligible_lots: list[EligibleLot],
    predictions: dict[tuple[str, str], PredictionPoint],
    *,
    thresholds: tuple[float, ...],
    max_loss_pct: float | None,
    trade_cost_pct: float,
) -> dict[str, Any]:
    threshold_results: list[dict[str, Any]] = []
    exit_probabilities = [
        _prediction_up(eligible_lot.exit_prediction)
        for eligible_lot in eligible_lots
        if _prediction_up(eligible_lot.exit_prediction) is not None
    ]
    for threshold in thresholds:
        lot_results = [
            simulate_rescue_for_lot(
                eligible_lot,
                threshold=threshold,
                predictions=predictions,
                max_loss_pct=max_loss_pct,
                trade_cost_pct=trade_cost_pct,
            )
            for eligible_lot in eligible_lots
        ]
        threshold_results.append(_summarize_threshold(lot_results, threshold))
    return {
        "thresholds": [float(value) for value in thresholds],
        "exit_probability_up_distribution": _distribution([float(value) for value in exit_probabilities]),
        "threshold_results": threshold_results,
    }


def _decision(eligibility: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if int(eligibility.get("eligible_lots", 0)) < MIN_ELIGIBLE_LOTS:
        blockers.append("eligible_lot_sample_too_small")

    candidates: list[dict[str, Any]] = []
    for result in replay.get("threshold_results", []):
        if int(result.get("applied_lots", 0)) < MIN_APPLIED_LOTS:
            continue
        if float(result.get("delta_cash_sum", 0.0)) <= 0:
            continue
        if float(result.get("improved_applied_share", 0.0)) < MIN_IMPROVED_APPLIED_SHARE:
            continue
        if float(result.get("nonnegative_day_share", 0.0)) < MIN_NONNEGATIVE_DAY_SHARE:
            continue
        candidates.append(result)

    if blockers:
        status = "sample_insufficient"
        recommended_action = "paper lot 과 LightGBM shadow 표본을 더 쌓은 뒤 재검토"
    elif candidates:
        candidates = sorted(candidates, key=lambda item: float(item.get("delta_cash_sum", 0.0)), reverse=True)
        status = "diagnostic_candidate_paper_only"
        recommended_action = "KIS live 적용 없이 paper-only 추가 관측과 cowork 검토 대상으로 유지"
    else:
        status = "diagnostic_only_no_hold_rescue_candidate"
        recommended_action = "hold-rescue 우선순위를 낮추고 buy-avoid shadow 관측을 계속"

    return {
        "status": status,
        "blockers": blockers,
        "candidate_thresholds": [
            {
                "threshold": result["threshold"],
                "applied_lots": result["applied_lots"],
                "delta_cash_sum": result["delta_cash_sum"],
                "improved_applied_share": result["improved_applied_share"],
                "nonnegative_day_share": result["nonnegative_day_share"],
            }
            for result in candidates
        ],
        "minimums": {
            "eligible_lots": MIN_ELIGIBLE_LOTS,
            "applied_lots": MIN_APPLIED_LOTS,
            "improved_applied_share": MIN_IMPROVED_APPLIED_SHARE,
            "nonnegative_day_share": MIN_NONNEGATIVE_DAY_SHARE,
        },
        "recommended_action": recommended_action,
        "scope_guardrail": "paper-only offline replay; no paper/live order, gate, config, active model, or shadow expansion change",
    }


def analyze_database(
    connection: Any,
    *,
    database_path: str,
    since_date: str,
    horizon_min: int,
    model_version: str,
    thresholds: tuple[float, ...],
    max_extension_minutes: int,
    max_loss_pct: float | None,
    trade_cost_pct: float,
    forced_flat_time: str,
) -> dict[str, Any]:
    cost_model = build_domestic_stock_cost_model_metadata(
        round_trip_cost_pct=trade_cost_pct,
    )
    parsed_forced_flat_time = _parse_time(forced_flat_time)
    fills, fill_summary = _load_fills(connection, since_date)
    closed_lots, reconstruction_summary = reconstruct_closed_lots(fills)
    predictions, prediction_summary = _load_predictions(
        connection,
        since_date=since_date,
        horizon_min=horizon_min,
        model_version=model_version,
    )
    bars_by_symbol, bar_summary = _load_bars(connection, since_date)
    eligible_lots, eligibility_summary = _eligibility(
        closed_lots,
        predictions,
        bars_by_symbol,
        max_extension_minutes=max_extension_minutes,
        forced_flat_time=parsed_forced_flat_time,
    )
    replay = replay_hold_rescue(
        eligible_lots,
        predictions,
        thresholds=thresholds,
        max_loss_pct=max_loss_pct,
        trade_cost_pct=trade_cost_pct,
    )
    decision = _decision(eligibility_summary, replay)
    return {
        "generated_at": _now_iso(),
        "report": "hold_rescue_paper_replay",
        "database_path": database_path,
        "since_date": since_date,
        "horizon_min": horizon_min,
        "model_version": model_version,
        "cost_model_version": cost_model["version"],
        "cost_model": cost_model,
        "forced_flat_time": forced_flat_time,
        "max_extension_minutes": max_extension_minutes,
        "max_loss_pct": max_loss_pct,
        "trade_cost_pct": trade_cost_pct,
        "fill_source": fill_summary,
        "position_reconstruction": reconstruction_summary,
        "lightgbm_shadow_source": prediction_summary,
        "future_bar_source": bar_summary,
        "eligibility": eligibility_summary,
        "replay": replay,
        "decision": decision,
        "interpretation": {
            "what_this_is": "actual paper exit 대비 LightGBM hold-rescue 를 paper-only 로 재생한 진단 리포트",
            "what_this_is_not": "실전/모의 주문 정책 변경, 모델 승격, gate 변경, KIS live shadow 추가 근거가 아님",
            "baseline_definition": "actual paper sell fill reconstructed from paper_orders and paper_fills",
            "rescue_definition": "hold at baseline exit only when LightGBM probability_up is above the fixed threshold, then exit within the configured extension window",
        },
    }


def _fmt_pct(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "확인 불가"
    return f"{number * 100.0:.2f}%" if abs(number) <= 1.0 else f"{number:.4f}%"


def render_markdown(report: dict[str, Any]) -> str:
    decision = report["decision"]
    eligibility = report["eligibility"]
    lines = [
        "# Hold-Rescue Paper Replay",
        "",
        "## 요약",
        "",
        f"- 판정: `{decision['status']}`",
        f"- cost_model_version: `{report.get('cost_model_version', 'unknown')}`",
        f"- 권장 조치: {decision['recommended_action']}",
        f"- 범위: {decision['scope_guardrail']}",
        f"- 분석 기간: `{report['since_date']}` 이후, h{report['horizon_min']}, `{report['model_version']}`",
        f"- 연장 한도: `{report['max_extension_minutes']}`분, 최대 손실 제한: `{report['max_loss_pct']}`%, 비용 proxy: `{report['trade_cost_pct']}`%p",
        f"- threshold grid: `{report['replay']['thresholds']}`",
        "",
        "이 리포트는 실제 paper 청산을 기준선으로 두고, 그 청산 시점에 LightGBM 이 상승 지속을 말했을 때 조금 더 보유했으면 나아졌는지 보는 paper-only 진단입니다.",
        "3분류 모델에서 0.40 이상은 상승 쪽 기울기 후보, 0.55 이상은 더 강한 상승 확신 후보로 봅니다.",
        "이 결과만으로 주문 정책, gate, active model, KIS live shadow 를 바꾸지 않습니다.",
        "",
        "관련 문서/코드 경로: "
        "`scripts/summarize_hold_rescue_paper_replay.py`, "
        "`runtime-data/dev.db`, "
        "`runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.json`",
        "",
        "## 표본",
        "",
        f"- 재구성된 닫힌 lot: `{eligibility.get('closed_lots', 0)}`건",
        f"- replay 가능 lot: `{eligibility.get('eligible_lots', 0)}`건",
        f"- 제외 lot: `{eligibility.get('excluded_lots', 0)}`건",
        f"- 제외 사유: `{eligibility.get('excluded_reasons', {})}`",
        f"- exit 시점 `probability_up` 분포: `{report['replay'].get('exit_probability_up_distribution', {})}`",
        "",
        "관련 문서/코드 경로: `paper_orders`, `paper_fills`, `serving_predictions`, `curated_minute_bars`",
        "",
        "## Threshold별 결과",
        "",
        "| threshold | 적용 lot | 적용률 | 기준선 손익 | 전략 손익 | 차이 | 개선 비중 | 비음수 일자 비중 | 주요 종료 사유 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in report["replay"]["threshold_results"]:
        lines.append(
            "| "
            f"{result['threshold']:.2f} | "
            f"{result['applied_lots']} | "
            f"{_fmt_pct(result['applied_rate'])} | "
            f"{float(result['baseline_cash_delta_sum']):,.0f}원 | "
            f"{float(result['strategy_cash_delta_sum']):,.0f}원 | "
            f"{float(result['delta_cash_sum']):,.0f}원 | "
            f"{_fmt_pct(result['improved_applied_share'])} | "
            f"{_fmt_pct(result['nonnegative_day_share'])} | "
            f"`{result['exit_reasons']}` |"
        )
    lines.extend(
        [
            "",
            "관련 문서/코드 경로: `scripts/summarize_hold_rescue_paper_replay.py`",
            "",
            "## 해석",
            "",
        ]
    )
    if decision["candidate_thresholds"]:
        lines.append(
            "- 후보 threshold 가 있더라도 `paper-only` 진단 후보입니다. KIS live 적용 전에는 buy-avoid 공식 관측, cowork 검토, 별도 shadow 설계가 필요합니다."
        )
    else:
        lines.append(
            "- 현재 고정 threshold grid 에서는 hold-rescue 를 바로 후속 shadow 로 올릴 근거가 없습니다."
        )
    lines.extend(
        [
            "- `delta_cash_sum`은 실제 paper 청산 기준선 대비 hypothetical hold-rescue 의 현금 손익 차이입니다.",
            "- 표본 제외에는 장외/주말 sync lot, forced flat 이후 청산, exit 예측 또는 미래 분봉 누락이 포함됩니다.",
            "- 이 리포트는 실제 체결가가 아니라 미래 분봉 close 를 쓰는 연구용 proxy 이므로 과대해석하지 않습니다.",
            "",
            "관련 문서/코드 경로: `docs/Execution-Plan.md`, `docs/Production-Transition-Progress.md`, `docs/Current-Implementation.md`",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_thresholds(value: str) -> tuple[float, ...]:
    thresholds = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not thresholds:
        raise argparse.ArgumentTypeError("at least one threshold is required")
    for threshold in thresholds:
        if threshold < 0.0 or threshold > 1.0:
            raise argparse.ArgumentTypeError("thresholds must be between 0 and 1")
    return thresholds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--since-date", default=DEFAULT_SINCE_DATE)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    parser.add_argument("--thresholds", type=_parse_thresholds, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--max-extension-minutes", type=int, default=15)
    parser.add_argument("--max-loss-pct", type=float, default=2.0)
    parser.add_argument("--trade-cost-pct", type=float, default=DEFAULT_TRADE_COST_PCT)
    parser.add_argument("--forced-flat-time", default="15:20")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _parse_date(args.since_date)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"latest-hold-rescue-paper-replay-h{args.horizon_min}.json"
    md_path = args.output_dir / f"latest-hold-rescue-paper-replay-h{args.horizon_min}.md"
    with _connect_readonly(args.database_path) as connection:
        report = analyze_database(
            connection,
            database_path=str(args.database_path),
            since_date=args.since_date,
            horizon_min=args.horizon_min,
            model_version=args.model_version,
            thresholds=args.thresholds,
            max_extension_minutes=args.max_extension_minutes,
            max_loss_pct=args.max_loss_pct,
            trade_cost_pct=args.trade_cost_pct,
            forced_flat_time=args.forced_flat_time,
        )
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {"json_path": str(json_path), "md_path": str(md_path), "status": report["decision"]["status"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
