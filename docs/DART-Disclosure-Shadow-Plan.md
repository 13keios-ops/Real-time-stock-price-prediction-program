# DART Disclosure Shadow Plan

## Purpose

This document defines a disclosure-event research lane separate from E7, serving, and all order decisions. Its first version accepts only an operator-exported official disclosure record and never calls OpenDART itself.

## Current Status

- Entrypoint: `scripts/summarize_dart_disclosure_shadow.py`.
- Input: `runtime-data/disclosures/events/dart_disclosure_events.jsonl`.
- Output: `runtime-data/reports/research/latest-dart-disclosure-shadow-h15.{json,md}`.
- No input file ends safely as `no_events_file`.
- The feature-label database is opened read-only only after a valid input event exists.

## Event Contract

Each JSONL line represents one published disclosure that has already been classified before its outcome is examined. Required fields are:

```json
{
  "event_id": "dart-unique-filing-or-revision-id",
  "source": "opendart_manual_export",
  "source_url": "https://dart.fss.or.kr/...",
  "symbol": "005930",
  "disclosure_type": "contract_or_order",
  "impact_direction": "positive",
  "available_at": "2026-09-21T18:02:00+09:00",
  "observed_at": "2026-09-21T18:04:00+09:00",
  "publication_state": "published"
}
```

- `symbol` is a six-digit listed symbol.
- `disclosure_type` is one of `financial_results`, `contract_or_order`, `capital_allocation`, `capital_structure`, `governance`, or `other`.
- `impact_direction` is `positive`, `negative`, or `unknown`; it is an evaluation hypothesis, never an order direction.
- `available_at` and `observed_at` must be timezone-aware. The latter cannot precede the former.
- `event_id` must be unique. A duplicate is excluded fail-closed so amended filings require a distinct revision event ID and an explicit pre-outcome classification.
- Unpublished, malformed, or duplicate records are reported but never join to a label.

An OpenDART key may be used later in a separately approved collector. It must remain in the local secret store and is not required for this manual-export path.

## Evaluation Contract

The report matches each valid event to the first same-symbol closed h15 or h60 feature label strictly after `available_at`, within the default 72-hour bound. A label at or before `available_at` is never used.

Directional hit rate is calculated only for explicitly positive or negative hypotheses. `unknown` records retain outcome data but do not contribute to directional accuracy. Small samples are evidence collection only and cannot alter E7, model selection, signal, gate, allocator, paper orders, or live orders.

## Research Boundary

The source remains shadow-only until it has full provenance, enough independent future observations, and a separately preregistered evaluation. This report is not mixed with the E7 evaluator or E7 manifest.
