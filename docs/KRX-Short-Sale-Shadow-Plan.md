# KRX Short-Sale Shadow Plan

## Purpose

This document defines a finalized EOD KRX short-sale research lane. It is a descriptive observation of short-sale trading and, where supplied, net short-position changes. It is not a same-day intraday signal, serving feature, or order rule.

## Current Status

- Entrypoint: `scripts/summarize_short_sale_shadow.py`.
- Input: `runtime-data/short-sale/observations/short_sale_eod.jsonl`.
- Output: `runtime-data/reports/research/latest-krx-short-sale-shadow-h15.{json,md}`.
- No input file ends safely as `no_observations_file`.
- The feature-label database is opened read-only only after a valid finalized observation exists.

## EOD Observation Contract

Each JSONL line represents one finalized source row for one symbol and trade date:

```json
{
  "observation_id": "krx-short-005930-20260921",
  "source": "krx_manual_export",
  "source_url": "https://data.krx.co.kr/...",
  "market": "KOSPI",
  "symbol": "005930",
  "trade_date": "2026-09-21",
  "short_sale_volume": 100,
  "total_volume": 1000,
  "short_sale_value_krw": 7000000,
  "total_value_krw": 70000000,
  "net_short_position_qty": 1050,
  "net_short_position_value_krw": 73500000,
  "available_at": "2026-09-21T20:10:00+09:00",
  "observed_at": "2026-09-21T20:14:00+09:00",
  "completeness": "final"
}
```

- Required trade fields are `short_sale_volume`, `total_volume`, `short_sale_value_krw`, and `total_value_krw`.
- All quantities and values must be finite and non-negative. Total volume must be positive; short-sale volume/value cannot exceed total volume/value.
- Net-position quantity and value are optional, but if either is present both are required. The report computes a quantity delta only against the prior valid observation for the same source, market, and symbol.
- `available_at` is the canonical information boundary. `observed_at` cannot precede it.
- Each `observation_id` is unique. Invalid or duplicate rows are excluded before database access.

The initial source is an operator export from KRX Data Marketplace. No browser scraping, real-time entitlement, KIS call, or automatic network collection is used.

## Evaluation Contract

The report computes a descriptive short-volume ratio and fixed presentation bands: under 1%, 1-5%, 5-10%, and at least 10%. It joins the first same-symbol h15 or h60 feature label strictly after `available_at`, within the default seven-day bound.

The initial report deliberately assumes no positive or negative direction from a short-sale ratio or net-position change. It only reports grouped future outcomes after enough data accumulates. It cannot change E7, model selection, signal, gate, allocator, paper orders, or live orders.

## Research Boundary

This EOD lane is separate from the E7 evaluator and must not be combined with E7 evidence. Any predictive hypothesis, threshold, or promotion test requires a new preregistered study after independent sample accumulation.
