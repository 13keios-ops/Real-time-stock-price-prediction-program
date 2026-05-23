# Production Architecture / Implementation Blueprint - Codex Work Ver 3-2

## 맥락

- 기준 작업본: `work_ver_3`
- 직전 하위 작업: `work_ver_3-1`
- 새 cowork 리뷰: 아직 없음
- 이번 파일은 `review_ver_3` 전의 두 번째 하위 작업 기록이다.

## 이번 구현

Slice 2a `live storage 원장`을 구현했다. 실전 주문 전송 경로는 만들지 않았다.

- 추가/수정: `app/storage/contracts.py`
- 추가/수정: `app/storage/sqlite_store.py`
- 추가/수정: `app/storage/runtime_writer.py`
- 추가: `tests/test_live_storage.py`
- 문서 갱신: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`, `docs/cowork-reports/README.md`

구현된 초기 원장:

- `market_status_snapshots`
- `live_orders`
- `live_order_events`

핵심 잠금:

- `live_orders.idempotency_key`는 `UNIQUE`이고 duplicate insert가 실패한다.
- `MarketStatusSnapshot.status_json`은 `symbols`, `market_session`, `source_generated_at` 키를 요구한다.
- `LiveOrder.detail_json`은 `order_policy`, `blocking_reasons`, `raw_broker_response` 키를 요구한다.
- `LiveOrderEvent.detail_json`은 `reason`, `source`, `raw_broker_response` 키를 요구한다.
- `LiveOrderEvent.actor`는 `system`, `account_owner`, `recovery`, `kill_switch`, `codex`만 허용한다.

## 검증 결과

- `python -m unittest tests.test_live_storage`
  - 결과: 통과, 5개
- `python -m unittest tests.test_live_storage tests.test_sqlite_store tests.test_broker_paper_sync tests.test_paper_reconciliation`
  - 결과: 통과, 21개
- `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: 통과, 124개

## 안전 확인

- 실전 주문 API 호출 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- `app/risk/` 변경 없음
- gate 기준값 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- live 체결/포지션/감사 원장은 아직 구현하지 않음

## 다음 작업 권장

🟢 다음 단계 권장: Slice 3 market status 순수 로직을 fixture 기반으로 먼저 구현한다. 외부 API 연결은 market status 원천 결정 뒤 별도 slice로 분리한다.

🟢 다음 단계 권장: Slice 2b를 바로 진행하려면 운영 DB migration/backup dry-run 절차를 테스트로 먼저 고정한다.

## 남은 결정

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요: market status 자동 데이터 원천을 KIS REST, 한국거래소 OpenAPI, 수동 snapshot 중 어디까지 Phase 1/2 필수로 둘지 결정해야 한다.

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요: audit hash chain anchor 방식, 보관 기간, NAS recovery self-test 미통과 시 Phase 2 금지 여부를 결정해야 한다.
