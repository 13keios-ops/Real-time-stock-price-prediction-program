# Codex 통합 작업 리포트 work_ver_9-2: review_ver_8 이후 Slice 5/5-2 통합본

## 1. 전달 맥락

- 기준 리뷰: `2026-05-16-production-architecture-implementation-blueprint-review_ver_8.md`
- 통합 대상:
  - `work_ver_9`: database smoke 보강, kill switch CLI, Slice 5 live order manager
  - `work_ver_9-1`: Slice 5-2 live execution sync mapper/status apply
- cowork 토큰 절약용 통합본이다. 세부 이력이 필요하면 위 두 파일을 보면 된다.
- 작업 시각: 2026-05-16 20~22시대, `weekend`

## 2. 반영 요약

| 영역 | 반영 내용 | 안전 경계 |
|---|---|---|
| database smoke | `--database-timeout-seconds` 옵션 추가, lock/busy는 `unknown`, 실제 오류는 `blocked`로 분류 | read-only SQLite smoke만 수행 |
| readiness JSON-only 정책 | 새 3개 check는 SQL column 승격 전까지 `checks_json`에 보관한다는 결정을 code docstring/docs에 명시 | schema migration 없음 |
| kill switch CLI | `scripts/set_live_kill_switch.sh` 추가. 기본 status/dry-run, 실제 기록은 `--apply`, OFF는 `--confirm-disable` 필요 | 검증은 dry-run만 수행 |
| live order manager | `app/services/live_order_manager.py` 추가. intent/idempotency/state transition/guard/broker 주입/cancel/recovery 구현 | 실제 KIS client 생성 없음 |
| live execution sync | `app/services/live_execution_sync.py` 추가. KIS daily order/fill record를 live status/delta fill로 해석하고 `live_orders` status/quantity + event까지 반영 | 실제 KIS REST 호출 없음, `live_fills`/position 미반영 |

## 3. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| live order caller | guard/storage는 있었지만 첫 caller 없음 | `LiveOrderManager`가 `LiveOrderGuard` 첫 caller가 됨 | `app/services/`, `app/storage/` | guard 차단을 `blocked` 상태로 저장하는 정책 검토 필요 |
| idempotency | storage unique constraint만 있음 | deterministic idempotency key 생성과 중복 intent 재사용 | live order lifecycle | 동일 신호 재시도와 의도적 재주문 구분 정책 추가 필요 |
| broker submit/cancel | 실제 연결 전 설계만 있음 | broker protocol 주입형 submit/cancel 구현 | 향후 KIS adapter 연결부 | 실제 KIS 응답 field variation은 fixture 필요 |
| unknown/recovery | 문서상 목표만 있음 | broker 예외/불명확 응답은 `unknown`, 재시작 open 계열은 `unknown` 잠금 | live order manager | 너무 보수적이면 수동 복구 빈도 증가 |
| execution sync | 상태 해석 없음 | `accepted/open/partially_filled/filled/cancelled/cancelled_partial/expired/rejected/unknown` 매핑 | live execution sync | `accepted`/`open` 구분은 실제 KIS field로 추가 보강 필요 |
| DB status apply | live sync가 DB에 닿지 않음 | `live_orders` status/filled/remaining/avg_fill + `live_order_events` 반영 | SQLite live order tables | 아직 `live_fills`/position과 회계 원장이 분리됨 |

## 4. 주요 구현 파일

- `app/services/live_order_manager.py`
- `app/services/live_execution_sync.py`
- `app/services/live_phase_readiness.py`
- `app/storage/sqlite_store.py`
- `scripts/script_dispatch.sh`
- `scripts/set_live_kill_switch.sh`
- `tests/test_live_order_manager.py`
- `tests/test_live_execution_sync.py`
- `tests/test_live_kill_switch_cli_script.py`
- `tests/test_codex_ops_job_script.py`
- `AGENTS.md`
- `README.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`

## 5. 핵심 정책

- `LiveOrderManager`는 KIS live client를 직접 만들지 않는다. `submit_cash_order`/`cancel_order` protocol을 만족하는 객체를 외부에서 주입받는다.
- submit 전에는 반드시 `LiveOrderGuard.assert_can_submit()`을 호출한다.
- guard 차단은 broker 호출 없이 `blocked`로 기록한다.
- broker 제출 예외 또는 결과 불명확은 `unknown`으로 기록한다.
- broker 응답이 즉시 `accepted`/`open`을 암시해도 내부 이벤트는 `submit_pending -> submitted -> accepted/open` 순서로 남긴다.
- kill switch ON 상태에서도 cancel-only 경로는 허용한다.
- live execution sync에서 broker 조회 unmatched는 paper의 `pending_lookup`이 아니라 live 안전 기본값인 `unknown`으로 둔다.
- `LiveExecutionSync.apply_order_snapshot()`은 주문 상태와 수량만 반영한다. `live_fills`, 포지션, 세금/수수료/정산일은 후속이다.

## 6. 실행 산출물

- `./scripts/set_live_kill_switch.sh --enable --reason dry_run_validation --actor test`
  - `status=dry_run`, `applied=false`
  - 실제 kill switch 파일 기록 없음
- `./scripts/run_codex_ops_job.sh --job-type premarket-readiness --database-timeout-seconds 2.0`
  - `status=ok`, `database=status ok`, `timeout_seconds=2.0`
  - 생성/갱신: `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
- `./scripts/run_live_readiness_dry_run.sh`
  - fixture 없음 기준 `status=blocked`, 9개 check 모두 `not_verified`
  - 생성/갱신: `runtime-data/reports/live-readiness/latest-readiness.json`

## 7. 검증

- `python -m unittest tests.test_live_order_manager tests.test_live_storage tests.test_live_order_guard tests.test_live_kill_switch tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
  - 통과, 48개
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

## 8. 안전 확인

- 실제 KIS live 주문 API 호출 없음
- 실제 KIS REST 조회 호출 없음
- 실제 KIS live client 생성 없음
- 운영 DB schema apply 없음
- 운영 DB write 실행 없음. DB 반영 검증은 `.tmp-tests/` 아래 SQLite에서만 수행
- readiness DB `--record` 실행 없음
- kill switch CLI 검증은 dry-run으로만 실행
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 9. 다음 권장

🟢 다음 단계 권장: `live_fills` 생성과 delta fill idempotency를 구현한다. 권장 범위는 `LiveFill` record 생성과 중복 delta 차단 테스트까지이며, position/portfolio 반영은 그 다음 slice로 분리한다.

🟢 다음 단계 권장: `LiveOrderManager`를 streaming에 연결하기 전, Phase 2의 "1일 1부모주문 / 동일 종목 pending 차단" 정책을 manager 내부 pre-submit policy로 둘지 별도 policy service로 둘지 cowork 검토를 받는다. Codex 권장안은 manager 내부 pre-submit policy, 수치 한도는 risk/live gate 분리다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 운영 DB에 `apply_storage_migration.sh --apply`를 실행할 시점. Codex 권장안은 cowork가 Slice 5/5-2 상태머신 리뷰를 끝낸 뒤, 장외 시간에 dashboard/live runtime 정지 확인 후 1회 적용이다.

## 10. cowork 확인 질문

1. `LiveOrderManager`가 broker를 직접 만들지 않고 protocol 주입형으로 둔 경계가 실전 안전 기준에 맞는지.
2. guard 차단을 `blocked` 상태로 저장하는 정책이 적절한지, 아니면 intent는 유지하고 별도 audit event만 남겨야 하는지.
3. live unmatched 상태를 `pending_lookup` 대신 `unknown`으로 두는 보수 정책이 맞는지.
4. 주문 상태 업데이트와 `live_fills`/position 반영을 분리한 경계에 이견이 없는지.
5. 다음 라운드를 `live_fills` delta idempotency로 진행해도 되는지.
