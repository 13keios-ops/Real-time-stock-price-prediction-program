# Codex 중간 작업 리포트 work_ver_9-1: Slice 5-2 live execution sync mapper + status apply

## 1. 작업 맥락

- 기준 리뷰: 아직 `review_ver_9` 없음
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_9.md`
- 작업 이유: cowork 회복 전까지 Slice 5에서 독립적으로 진행 가능한 live execution sync의 순수 parser/mapper를 먼저 구현
- 작업 시각: 2026-05-16 22시대, `weekend`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| live execution sync | 설계상 후보만 있고 상태 해석 코드 없음 | KIS daily order/fill record를 live 상태와 delta fill로 해석하고, `live_orders` 상태/수량과 event를 반영하는 좁은 applicator 추가 | `app/services/live_execution_sync.py`, `app/storage/sqlite_store.py`, tests | 실제 KIS 응답 field variation은 fixture가 더 필요 |
| 상태 해석 | paper sync의 상태 해석을 live에서 직접 재사용할지 미정 | live는 unmatched를 `unknown`으로 두고, `accepted/open/partial/filled/cancelled/cancelled_partial/expired/rejected`를 명시적으로 계산 | live order lifecycle | 브로커의 "접수" 표현이 field별로 다르면 accepted/open 구분 보강 필요 |
| delta fill | live 체결 delta 계산 없음 | 이전 적용 수량 이후 증가분만 delta로 계산하고 음수 delta는 0으로 고정 | 향후 `live_fills` 적용 | 수수료/세금/정산일 계산은 아직 포함하지 않음 |
| DB 상태 반영 | live execution sync가 DB에 닿지 않음 | `LiveExecutionSync.apply_order_snapshot()`이 `live_orders` status/filled/remaining/avg_fill과 `live_order_events`를 반영 | `SQLiteRuntimeStore`, live order lifecycle | 아직 `live_fills`/position에는 반영하지 않으므로 회계 원장과 주문 상태가 분리됨 |

## 3. 구현 세부

갱신 파일:

- `app/services/live_execution_sync.py`
- `app/storage/sqlite_store.py`
- `tests/test_live_execution_sync.py`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`
- `docs/cowork-reports/README.md`

주요 정책:

- 실제 KIS REST 호출은 만들지 않았다.
- `snapshot_from_kis_daily_order_fill(record)`는 `KisDailyOrderFillRecord` 또는 같은 attribute/key를 가진 입력을 live broker snapshot으로 정규화한다.
- `derive_live_order_status(snapshot)`는 unmatched를 `unknown`으로 둔다. paper sync의 `pending_lookup`보다 보수적인 live 기본값이다.
- `build_live_order_sync_decision(snapshot, previous_applied_fill_qty)`는 delta fill을 계산한다.
- `LiveExecutionSync.apply_order_snapshot()`은 `live_orders` 상태/수량과 `live_order_events`만 반영한다.
- `live_fills` 생성, 포지션 반영, 수수료/세금/정산일 계산은 후속 slice다.

## 4. 검증

- `python -m unittest tests.test_live_execution_sync`
  - 통과, 4개
- `python -m unittest tests.test_live_execution_sync tests.test_broker_paper_sync tests.test_live_order_manager tests.test_live_storage`
  - 통과, 20개
- `python -m unittest tests.test_live_execution_sync tests.test_live_order_manager tests.test_live_storage`
  - 통과, 18개
- `python -m unittest tests.test_live_execution_sync tests.test_broker_paper_sync tests.test_live_order_manager tests.test_live_storage tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script`
  - 통과, 30개
- `bash -n scripts/script_dispatch.sh scripts/set_live_kill_switch.sh scripts/run_codex_ops_job.sh scripts/run_live_readiness_dry_run.sh`
  - 통과
- `python -m unittest discover -s tests -p "test_*.py"`
  - 통과, 205개
- `python -m app --build-dashboard`
  - 통과
  - 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`
- `git diff --check`
  - 통과
  - 참고: `docs/logbook.md`의 CRLF/LF 정규화 경고만 표시됨
- `git diff -- app/risk VERSION config`
  - 출력 없음

## 5. 안전 확인

- 실제 KIS live 주문 API 호출 없음
- 실제 KIS REST 조회 호출 없음
- 운영 DB write 실행 없음. DB 반영 검증은 `.tmp-tests/` 아래 SQLite에서만 수행
- 운영 DB schema apply 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 6. 다음 권장

🟢 다음 단계 권장: 다음 slice는 `LiveFill` 생성과 포지션/포트폴리오 반영이다. Codex 권장안은 수수료/세금/정산일 정책을 확정하기 전까지 주문 상태와 회계 반영을 분리하고, 먼저 `live_fills` fixture와 delta fill idempotency를 테스트로 잠그는 것이다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 없음. 단, 실제 KIS live 응답 fixture 확보는 Phase 1 read-only 이후 필요하다.

## 7. cowork 확인 질문

1. live unmatched 상태를 `pending_lookup` 대신 `unknown`으로 두는 보수 정책이 맞는지.
2. 주문 상태 업데이트와 `live_fills`/position 반영을 분리한 경계에 이견이 없는지.
