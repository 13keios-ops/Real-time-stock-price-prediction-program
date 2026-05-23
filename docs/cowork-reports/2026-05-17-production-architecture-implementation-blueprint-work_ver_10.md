# Codex 작업 리포트 work_ver_10: review_ver_9 반영, Slice 5-3 live_fills delta 멱등성 + Phase 2 pre-submit 정책 + 정합성 report

## 1. 맥락

- 기준 리뷰: `docs/cowork-reports/2026-05-16-production-architecture-implementation-blueprint-review_ver_9.md`
- 기준 작업본: `docs/cowork-reports/2026-05-16-production-architecture-implementation-blueprint-work_ver_9-2.md`
- 이번 작업: cowork 권장 1순위 `live_fills` delta idempotency 구현, 병행 권장 Phase 2 pre-submit 정책 구현, live fill 정합성 dashboard/runtime report read-only 노출과 mismatch 신규 intent 차단 추가, `unknown`/`stuck` 미해결 주문 dashboard/runtime report read-only 노출, `live_fills` 기반 순수 position accounting helper 추가, 기준 문서 갱신.
- 작업 시작 전 상태: `get_live_runtime_status`는 `status=stopped`, `session_status=weekend`, `trading_mode=paper`; watchdog은 `market_session_status=weekend`, `live_runtime_should_run=false`.

금지 범위 준수:

- 실제 KIS live 주문 호출 없음.
- 실제 KIS REST 조회 호출 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.

## 2. 코드 변경 요약

### 2.1 `LiveExecutionSync` 보강

파일: `app/services/live_execution_sync.py`

추가:

- `LiveFillApplyResult`
- `LiveFillConsistency`
- `LiveExecutionSync.apply_order_snapshot_and_fill_delta()`
- `LiveExecutionSync.validate_live_order_fill_qty()`

정책:

- broker snapshot의 `filled_qty`는 누적값으로 본다.
- 내부 `live_fills`의 기존 합계와 broker 누적 체결수량을 비교해 미기록 delta만 기록한다.
- `fill_id`는 `order_id`, broker branch/order no, 적용 후 누적수량, delta 수량으로 deterministic 생성한다.
- 같은 snapshot을 반복 적용하면 `live_fills`가 중복 insert되지 않는다.
- delta 체결가는 `broker cumulative avg fill price * broker cumulative filled qty - 기존 live_fills notional`을 delta 수량으로 나누어 계산한다.
- 포지션, 포트폴리오, 세금/수수료 정산, 계좌 reconciliation은 이번 slice에서 제외했다.
- unmatched snapshot은 `unknown`으로만 전이하고 수량/체결 원장에는 반영하지 않는다.
- 거래일 단위 `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)` mismatch scan/summary helper를 추가했다.

경계 명시:

- module docstring에 “order status와 fill delta까지만 반영하며 position/portfolio/tax/settlement accounting은 후속 slice”라고 명시했다.
- `apply_order_snapshot()`은 이미 같은 status/수량/broker id로 동기화된 snapshot이면 이벤트를 다시 쓰지 않고 반환한다.

### 2.2 SQLite/RuntimeWriter 보강

파일:

- `app/storage/sqlite_store.py`
- `app/storage/runtime_writer.py`

추가:

- `SQLiteRuntimeStore.insert_live_fill_if_absent()`
- `SQLiteRuntimeStore.fetch_live_fill()`
- `SQLiteRuntimeStore.fetch_live_fill_totals()`
- `SQLiteRuntimeStore.sum_live_fill_qty()`
- `SQLiteRuntimeStore.fetch_live_orders_for_trading_day()`
- `RuntimeWriter.write_live_fill_if_absent()`

의도:

- `live_fills.fill_id` primary key를 활용해 delta fill 중복 insert를 차단한다.
- `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)` 비교를 서비스에서 직접 검증할 수 있게 했다.
- Phase 2 1일 부모 주문 수 카운트에 필요한 거래일별 live order 조회를 추가했다.

### 2.3 `LiveOrderManager` Phase 2 pre-submit 정책

파일: `app/services/live_order_manager.py`

추가/변경:

- `LivePreSubmitPolicy`
- Phase 2 기본 정책:
  - 1거래일 1개 부모 주문서.
  - 같은 종목 pending/open/partial/unknown/stuck 주문이 있으면 새 부모 주문 차단.
  - 같은 거래일의 `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)`가 다르면 새 intent 차단.
- 위반 시 broker 호출 없이 `intent_created -> blocked`.
- event type은 `pre_submit_policy_blocked`.
- blocking reasons:
  - `phase2_parent_order_limit_exceeded`
  - `same_symbol_order_pending`
  - `live_fill_mismatch_detected`

docstring 보강:

- `blocked`는 terminal이다.
- 같은 idempotency key로는 retry하지 않는다.
- 차단 사유 해제 뒤 retry하려면 새 `prediction_id` 또는 `signal_id`가 필요하다.

### 2.4 Dashboard/runtime report read-only 정합성 노출

파일:

- `app/services/dashboard.py`
- `app/services/reporting.py`
- `tests/test_dashboard.py`
- `tests/test_reporting.py`

추가:

- `collect_dashboard_payload()`가 선택 거래일 기준 `live_fill_consistency`를 read-only로 계산한다.
- `실 운용계좌 -> 매수/매도 및 체결현황`에 `실전 fill 정합성`, `실전 fill 불일치 상세` 카드를 추가했다.
- mismatch가 있으면 dashboard 상단 status alert의 첫 항목으로 `실전 fill 정합성 불일치`를 표시한다.
- `build_runtime_report()`가 최신 live order 거래일 기준 `live_fill_consistency`를 JSON/Markdown report에 기록한다.
- 이 카드는 `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)` 차이를 보여주는 진단 카드다.
- SQLite 조회 실패나 아직 schema가 없는 상태에서는 dashboard 자체가 죽지 않도록 `status=unknown`으로 표시한다.
- 포지션, 회계, 세금, 정산, 주문 전송에는 연결하지 않았다.

### 2.5 `unknown`/`stuck` 미해결 주문 read-only 모니터링

파일:

- `app/services/live_order_monitoring.py`
- `app/services/dashboard.py`
- `app/services/reporting.py`
- `tests/test_dashboard.py`
- `tests/test_reporting.py`

추가:

- 거래일 단위 live order를 read-only로 조회해 `unknown`/`stuck` 주문 수, 열린 주문 수, 최장 미확인 경과 시간을 계산한다.
- dashboard `실 운용계좌 -> 매수/매도 및 체결현황`에 `실전 미해결 주문`, `실전 미해결 주문 상세` 카드를 추가했다.
- `unknown`/`stuck`이 있으면 dashboard 상단 status alert에 `실전 주문 상태 확인 필요`를 표시한다.
- runtime report JSON/Markdown에 `live_order_attention`, `live_open_orders` 요약과 상세 주문 ID를 기록한다.
- 이 helper는 주문 전이, 자동 취소, 브로커 조회를 수행하지 않는다. 운영자가 broker reconcile을 수행해야 하는 상태를 드러내기만 한다.

### 2.6 `live_fills` 기반 순수 position accounting helper

파일:

- `app/services/live_position_accounting.py`
- `app/storage/sqlite_store.py`
- `tests/test_live_position_accounting.py`

추가:

- 기록된 `live_fills`만 입력으로 받아 long-only 평균단가 position을 계산한다.
- 매수 수수료/비용은 cost basis에 포함하고, 매도 세금/비용은 realized PnL에서 차감한다.
- 내부 보유 수량보다 매도 fill 수량이 크면 계산 position은 0으로 평탄화하고 `over_sell_qty`를 detail에 남긴다.
- `broker_qty`가 내부 계산 수량과 다르면 `broker_qty_mismatch=true`를 detail에 남긴다.
- `SQLiteRuntimeStore.fetch_live_fills_for_trading_day()`를 추가해 거래일별 fill을 read-only로 가져올 수 있게 했다.
- 자동 position 저장, portfolio snapshot, 세금/결제일 확정, 브로커 잔고 reconciliation에는 아직 연결하지 않았다.

## 3. 테스트 추가/보강

파일: `tests/test_live_execution_sync.py`

추가 검증:

- 같은 broker snapshot 반복 적용 시 `live_fills` 중복 insert 없음.
- 누적 체결수량 증가 시 delta만 새 fill로 기록.
- 누적 평균가에서 delta 체결가를 계산.
- `live_orders.filled_qty`와 `live_fills` 합계 불일치 검출.
- unmatched snapshot은 fill을 만들지 않고 order 수량도 갱신하지 않음.
- 거래일 단위 mismatch scan이 일치 건은 숨기고 불일치 건만 반환함.
- 거래일 단위 summary가 checked order 수, mismatch 수, ok 여부를 반환함.

파일: `tests/test_kis_http_clients.py`

추가 검증:

- KIS 일별 주문/체결 조회 응답에서 `ord_orgno`, `ccld_qty`, `ord_remn_qty`, `avg_ccld_unpr`, `ord_dvsn_cd_name`, `excg_dvsn_cd` 같은 대체 필드명을 정상 매핑.
- KIS 연속 조회 header(`tr_cont=M`)와 `ctx_area_*` cursor가 있을 때 다음 페이지를 이어 조회해 주문/체결 record를 누적한다.

파일: `tests/test_live_order_manager.py`

추가 검증:

- Phase 2에서 같은 거래일 두 번째 부모 주문 차단.
- Phase 2에서 parent limit을 완화해도 같은 종목 pending 주문이 있으면 차단.
- Phase 2에서 live fill mismatch가 있으면 새 intent가 broker 호출 전 `blocked` 된다.

파일: `tests/test_dashboard.py`

추가 검증:

- live order의 `filled_qty`와 `live_fills` 합계가 다를 때 dashboard payload가 `status=mismatch`, `mismatch_count=1`을 반환한다.
- mismatch가 있으면 status alert 첫 항목이 `실전 fill 정합성 불일치`가 된다.
- HTML에 `실전 fill 정합성`, `실전 fill 불일치 상세`, 불일치 주문 ID가 표시된다.
- `unknown` live order가 있을 때 dashboard payload가 `status=attention`, `attention_count=1`을 반환한다.
- status alert에 `실전 주문 상태 확인 필요`가 표시되고 HTML에 `실전 미해결 주문`, 주문 ID가 표시된다.

파일: `tests/test_reporting.py`

추가 검증:

- runtime report summary에 `live_fill_mismatches`가 들어간다.
- `latest-runtime-report.json`과 `latest-runtime-report.md`에 live fill mismatch가 표시된다.
- runtime report summary에 `live_order_attention`, `live_open_orders`가 들어간다.
- `latest-runtime-report.json`과 `latest-runtime-report.md`에 `unknown` 미해결 주문이 표시된다.

파일: `tests/test_live_position_accounting.py`

추가 검증:

- long-only weighted average로 매수/매도 후 잔여 position, realized PnL, unrealized PnL을 계산한다.
- 매수 수수료와 매도 세금/비용을 position 계산에 반영한다.
- over-sell fill은 position을 음수로 만들지 않고 `over_sell_qty`로 기록한다.
- SQLite `live_fills`를 거래일별/종목별로 묶어 position 계산 결과를 만든다.

## 4. 문서 갱신

갱신:

- `docs/Production-Architecture.md`
  - 현재 구조 진단에 live order manager, live execution sync, live_fills delta 구현 상태 반영.
  - Phase 2 1일 1부모주문/같은 종목 pending 차단을 기본 정책으로 반영.
  - dashboard 카드 목록에 live fill 정합성 read-only 카드를 반영.
  - dashboard 카드 목록에 `unknown`/`stuck` 미해결 주문 read-only 카드를 반영.
  - runtime report와 dashboard 간 live fill mismatch 및 미해결 주문 확인 절차를 장후 운영 절차에 반영.
  - 포지션/포트폴리오/세금 정산은 후속임을 명시.
- `docs/Production-Implementation-Blueprint.md`
  - P1-B live execution sync 상태 갱신.
  - service interface에 `apply_order_snapshot_and_fill_delta()`와 `validate_live_order_fill_qty()` 추가.
  - `live_fills` SQL schema 초안을 현재 구현 schema와 맞춤.
  - P1-D dashboard/alert 상태에 live fill 정합성 카드 완료를 반영.
  - P1-D dashboard/alert 상태에 `unknown`/`stuck` 미해결 주문 카드 완료를 반영.
  - runtime report JSON/Markdown read-only 노출을 구현 상태에 반영.
  - Slice 5/6 구현 상태와 테스트 항목 갱신.
- `docs/logbook.md`
  - 2026-05-17 작업 entry 추가.
- `docs/cowork-reports/README.md`
  - `review_ver_9`, `work_ver_10` 등록.

## 5. 검증 결과

통과:

- `python -m unittest tests.test_live_execution_sync` -> 9개 통과.
- `python -m unittest tests.test_live_execution_sync tests.test_kis_http_clients` -> 16개 통과.
- `python -m unittest tests.test_sqlite_store` -> 9개 통과.
- `python -m unittest tests.test_live_order_manager` -> 8개 통과.
- `python -m unittest tests.test_live_execution_sync tests.test_dashboard` -> 25개 통과.
- `python -m unittest tests.test_reporting tests.test_dashboard tests.test_live_execution_sync` -> 26개 통과.
- `python -m unittest tests.test_live_order_manager tests.test_live_execution_sync tests.test_reporting tests.test_dashboard` -> 35개 통과.
- `python -m unittest tests.test_dashboard tests.test_live_order_manager tests.test_reporting` -> 25개 통과.
- `python -m py_compile app/services/live_order_monitoring.py app/services/dashboard.py app/services/reporting.py` -> 통과.
- `python -m unittest tests.test_dashboard tests.test_reporting` -> 17개 통과.
- `python -m unittest tests.test_live_order_manager tests.test_live_execution_sync tests.test_kis_http_clients tests.test_dashboard tests.test_reporting` -> 42개 통과.
- `python -m unittest tests.test_kis_http_clients` -> 7개 통과.
- `python -m py_compile app/services/live_position_accounting.py app/storage/sqlite_store.py` -> 통과.
- `python -m unittest tests.test_live_position_accounting tests.test_live_storage tests.test_live_execution_sync` -> 20개 통과.
- `python -m unittest tests.test_live_storage tests.test_live_order_guard tests.test_live_phase_readiness` -> 21개 통과.
- `python -m unittest discover -s tests -p "test_*.py"` -> 220개 통과.
- `python -m app --build-runtime-report` 통과. 최신 runtime report `live_fill_mismatches=0`.
- `python -m app --build-dashboard` 통과. 최신 dashboard snapshot `generated_at=2026-05-17T01:39:36.806128+09:00`.
- `git diff --check` 통과. 단, 기존처럼 `docs/logbook.md` CRLF/LF 정규화 경고가 표시됨.
- `git diff -- app/risk VERSION config` 출력 없음.

## 6. 남은 위험과 Codex 권장안

1. 실제 KIS live adapter 연결 전 응답 fixture가 아직 충분하지 않다.
   - 반영: 대체 필드명 fixture와 연속 조회(`tr_cont=M`) fixture는 추가했다.
   - 권장안: 다음에는 비밀값을 제거한 실제 KIS daily order/fill 응답 샘플을 fixture로 추가한 뒤 `snapshot_from_kis_daily_order_fill()` 매핑까지 연결 검증한다.

2. delta fill은 포지션/포트폴리오에 아직 적용하지 않는다.
   - 적용된 보수책: 현재 dashboard/runtime report에 노출한 fill/order mismatch는 Phase 2 신규 intent를 차단한다.
   - 추가 보수책: `unknown`/`stuck` 미해결 주문은 dashboard/runtime report와 status alert에 read-only로 노출한다.
   - 추가 구현: `live_fills` 기반 순수 position accounting helper는 만들었지만 자동 저장/portfolio에는 연결하지 않았다.
   - 권장안: 다음 slice는 차단 사유와 미해결 주문을 장중 외부 알림/장후 review checklist에 연결하고, 이후 계산된 position을 `live_positions`에 명시 저장하는 경로를 별도 review 후 연결한다.

3. Phase 2 부분 체결 잔량 자동 취소 여부가 아직 미정이다.
   - 권장안: Phase 2 기본은 “잔량 유지 + 같은 종목 신규 차단 + 장후/정해진 시각에 사람 승인 취소”로 두고, 자동 취소는 KIS cancel 응답 fixture가 충분해진 뒤 허용한다.

4. `blocked` terminal 정책은 보수적이지만 운영자가 retry 흐름을 이해해야 한다.
   - 권장안: dashboard 또는 runbook에 “차단 해제 후 같은 signal 재시도 불가, 새 signal 필요”를 표시한다.

5. `write_live_fill_if_absent()`는 SQLite insert 성공 후 JSONL append를 수행한다.
   - 권장안: 실전 운영 전에는 SQLite를 live accounting의 source of truth로 두고, JSONL은 보조 artifact로 명시한다. JSONL까지 atomic하게 맞추는 작업은 audit hash chain slice에서 다룬다.

## 7. cowork에게 확인 요청

1. `live_fills` delta idempotency 정책이 Phase 2 canary 전제에 충분히 보수적인지 봐 주세요.
2. 누적 평균가 기반 delta 체결가 계산이 실전 회계 전 단계의 임시 원장으로 허용 가능한지, 아니면 KIS 개별 체결 id 확보 전까지 `live_fills` 기록 자체를 더 보류해야 하는지 봐 주세요.
3. Phase 2 pre-submit 정책을 manager 내부에 둔 결정이 적절한지 봐 주세요. 특히 “1거래일 1개 부모 주문서”가 `filled` 이후에도 같은 날 두 번째 부모 주문을 막는 보수 정책으로 읽히는지 확인 부탁드립니다.
4. 다음 slice 우선순위는 Codex 권장 기준으로 `KIS live execution 실제 응답 fixture 확대 -> fill/order 및 unknown/stuck 알림/리뷰 절차 -> 순수 position 계산 결과를 live_positions에 명시 저장` 순서입니다. 이 순서에 이견이 있는지 봐 주세요.

## 8. 다음 작업 후보

🟢 권장 1순위: KIS live 주문/체결 조회 응답 fixture 확대와 mapper 검증.

🟢 권장 2순위: dashboard/runtime report와 신규 intent 차단까지 연결한 `live_orders.filled_qty != SUM(live_fills.fill_qty)` mismatch, `unknown`/`stuck` 미해결 주문을 장중 외부 알림/장후 review 절차로 확장.

🟢 권장 3순위: Phase 2 부분 체결 잔량 runbook. 기본은 자동 추가 주문 금지, 자동 취소는 아직 보류.

🔴 계좌 소유자/실전 운용 승인권자 결정 필요: Phase 2 주문 금액 한도, 부분 체결 잔량 자동 취소 허용 여부, audit hash chain anchor 방식.
