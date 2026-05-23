# Codex followup: Production Implementation Blueprint cowork 리뷰 반영

## 반영 요약

`docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-cowork-review.md`의 운영 안전 관련 지적을 `docs/Production-Implementation-Blueprint.md`에 반영했다.

## 반영한 항목

- Slice 2를 `2a`(market status, live orders, live order events)와 `2b`(fills, positions, portfolio snapshots, audit, approval, readiness)로 분할했다.
- Phase 1 read-only factory를 `live` 전용으로 좁히고, 주문/취소 메서드는 hard fail이 아니라 미노출을 Codex 권장안으로 고정했다.
- live profile로 `KisRestQuoteClient(`를 직접 인스턴스화하는 우회 경로를 static isolation 테스트로 잠그도록 추가했다.
- 상태머신에 `expired`를 추가하고, Phase 2에서는 KIS 주문 정정(modify)을 금지하며 cancel + new submit만 허용하도록 명시했다.
- `live_orders`, `live_fills`, `ops_live_audit_events`, `market_status_snapshots`의 누락 필드를 schema 초안에 추가했다.
- `live_readiness_runs` 테이블 초안을 추가했다.
- kill switch 파일 후보 `runtime-data/reports/live-risk/kill-switch.json`의 schema, atomic write, stale/broken 기본 동작을 명시했다.
- storage anchor에 `RecordMixin`, `SQLiteRuntimeStore._initialize_schema()`, migration dry-run 규약을 추가했다.
- 신규 report 경로에 최초 생성 Slice를 매핑했다.
- `docs/cowork-reports/README.md`에 report/review/followup/decision 명명 규칙을 추가했다.

## 반영하지 않은 항목

- 코드 구현은 아직 시작하지 않았다.
- `app/risk/`, gate 기준값, `ALLOW_LIVE_ORDERS`, `VERSION`은 변경하지 않았다.
- 일일 손실 한도와 슬리피지 budget 수치는 계좌 소유자 또는 실전 운용 승인권자 결정 전까지 비워 둔다.

## 다음 코드 작업 권장

1. Slice 1: `app/brokers/kis_readonly.py`, `tests/test_live_readonly_guard.py`, `tests/test_live_client_isolation.py`
2. Slice 2a: storage core schema와 writer
3. Slice 3: market status 순수 로직
4. Slice 4: live order guard와 kill switch reader
