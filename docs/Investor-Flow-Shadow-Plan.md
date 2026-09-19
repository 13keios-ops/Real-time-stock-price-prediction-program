# Investor Flow Shadow Plan

## Purpose

This document defines a separate EOD research lane for foreign and institutional flow. It is not a serving feature, an order rule, or an E7 input.

The first implementation is intentionally source-neutral and accepts only an operator-exported record from an official source. It does not automate browser scraping or call KRX, KIS, or any social platform.

## Current Status

- The EOD report entrypoint is scripts/summarize_investor_flow_shadow.py.
- The input path is runtime-data/investor-flow/observations/investor_flow_eod.jsonl.
- The report paths are runtime-data/reports/research/latest-investor-flow-shadow-h15.json and .md.
- With no input file, the report ends safely as no_observations_file.
- The database is opened read-only only after a valid observation input exists.

## EOD Observation Contract

Each JSONL record represents one finalized investor group for one symbol and trade date. Required fields are observation_id, source, source_url, market, symbol, trade_date, investor_group, net_value_krw, available_at, observed_at, and completeness.

- investor_group is foreign or institution.
- completeness must be final.
- available_at and observed_at must be timezone-aware ISO-8601 timestamps.
- available_at is the information boundary. No observation may be evaluated against a label at or before this timestamp.
- Two records with the same source, market, symbol, and trade_date form one two-sided flow group.
- A group must contain exactly one foreign row and one institution row. Missing or duplicate group rows are excluded fail-closed and recorded as report group issues.
- The effective group available_at is the later of the two source timestamps.

The initial source is an operator export from KRX Data Marketplace investor trading results. KRX states that same-day final investor trading details are available after 20:00 KST. The actual available_at from each export, not a guessed fixed time, is the canonical boundary.

No input file ends as `no_observations_file`; malformed rows end as `no_valid_observations`; and a file without any exact two-sided group ends as `no_complete_two_sided_groups`. None of these states is a trading instruction or a reason to create a trade.

## Evaluation Contract

The report joins each complete two-sided group to the first closed h15 or h60 feature label strictly after available_at. It records both-net-buy, both-net-sell, and disagreement regimes.

- Both net buy is evaluated as a positive-direction observation.
- Both net sell is evaluated as a negative-direction observation.
- Disagreement and zero-flow regimes are retained but are not assigned a direction.
- Missing labels remain unmatched. The report never substitutes an earlier label.
- Results are retrospective research diagnostics, not returns to mix with E7.

E7 evaluator version, manifest, threshold, active model, feature selection, signal, gate, allocator, paper order policy, and live flags remain unchanged.

## Free Public Source Portfolio

### Start Now

1. KRX finalized EOD investor flow: manual official export into the EOD input contract.
2. Existing social event shadow: official API, public feed, or manual export only. No private access, login bypass, or anti-bot bypass.

### Requires a User Credential but No Planned Fee

Open DART is a next candidate for disclosure-event shadow. Its official terms state that the service is generally free, but its API needs a user-issued authentication key. The key must stay outside git in the local secret store. Until the user provides it, no DART network collection is attempted.

### Not Started Without Explicit Entitlement

- X, Instagram, Facebook, Threads, and similar sources are not automatically collected merely because an account is public. Official API access, OAuth, quota, and possible pricing must be confirmed per platform.
- Real-time KRX investor-flow feeds require separate entitlement and may incur information-use fees.
- No unauthorised web scraping is a substitute for an official API or permitted export.

## Research Promotion Boundary

A source remains shadow-only until it has complete provenance, a recorded availability boundary, broad enough independent future observations, and a separately preregistered evaluation. No source is promoted because of a few profitable examples or a famous author.

The immediate next evidence is a valid KRX EOD export containing both foreign and institutional rows for the watchlist. After the first import, the report can begin accumulating no-look-ahead shadow observations.
