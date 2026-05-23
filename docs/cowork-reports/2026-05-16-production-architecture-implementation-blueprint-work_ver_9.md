# Codex 작업 리포트 work_ver_9: review_ver_8 반영 + Slice 5 live order manager 1차 구현

## 1. 작업 맥락

- 기준 리뷰: `2026-05-16-production-architecture-implementation-blueprint-review_ver_8.md`
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_8.md`
- cowork 판정: `work_ver_8`은 그대로 사용 가능, Slice 5 live order manager 진입 권장
- 작업 시각: 2026-05-16 20시대, `weekend`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| database smoke timeout | SQLite read-only smoke timeout이 2초 하드코드 | `--database-timeout-seconds` 옵션 추가, 기본 2초 유지 | `scripts/run_codex_ops_job.sh`, `scripts/script_dispatch.sh`, tests | timeout 값을 과도하게 낮추면 false negative 가능 |
| DB lock/busy 분류 | SQLite `locked`/`busy`도 `blocked`로만 분류 | lock/busy는 `unknown`, 실제 오류는 `blocked`로 구분 | premarket readiness report | lock이 반복되면 warning처럼 보일 수 있어 운영 절차에서 재시도/조사 기준 필요 |
| JSON-only readiness check | 결정은 문서화됐지만 코드 docstring 보강 여지 | `live_phase_readiness.py` module docstring에 SQL column/`checks_json` 분리 명시 | readiness service | 없음에 가까움 |
| kill switch CLI | service는 있었지만 운영자가 안전하게 ON/OFF할 wrapper 없음 | `scripts/set_live_kill_switch.sh` 추가. 기본 status/dry-run, 실제 기록은 `--apply`, OFF는 `--confirm-disable` 요구 | `scripts/`, `runtime-data/reports/live-risk/` | 잘못된 OFF 해제를 막기 위해 해제 절차가 다소 번거로움 |
| live order manager | storage/guard는 있었지만 첫 caller가 없음 | `app/services/live_order_manager.py` 추가. intent/idempotency/state transition/guard/broker 주입/unknown/recovery 구현 | `app/services/`, `app/storage/`, tests | 실제 KIS 응답 매핑은 아직 mock 기반이라 live execution sync에서 추가 검증 필요 |

## 3. 구현 세부

갱신 파일:

- `app/services/live_order_manager.py`
- `app/services/live_phase_readiness.py`
- `app/storage/sqlite_store.py`
- `scripts/script_dispatch.sh`
- `scripts/set_live_kill_switch.sh`
- `tests/test_live_order_manager.py`
- `tests/test_live_kill_switch_cli_script.py`
- `tests/test_codex_ops_job_script.py`
- `AGENTS.md`
- `README.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`
- `docs/cowork-reports/README.md`

주요 정책:

- `LiveOrderManager`는 실제 KIS client를 생성하지 않는다. `submit_cash_order`/`cancel_order` protocol을 만족하는 broker 객체를 외부에서 주입받는다.
- `submit_intent()`는 `LiveOrderGuard.assert_can_submit()`을 먼저 호출하고, guard 차단 시 broker 호출 없이 `blocked` 상태와 event를 남긴다.
- broker 제출 예외나 결과 불명확 상태는 `unknown`으로 전이한다.
- broker 응답이 즉시 `accepted` 또는 `open`을 암시해도 내부 상태는 `submit_pending -> submitted -> accepted/open` 순서로 기록한다.
- `request_cancel()`은 cancel-only guard를 통과한 뒤 `cancel_requested`로 전이한다. kill switch ON이어도 cancel-only는 허용된다.
- `recover_open_orders()`는 재시작 시 open 계열 주문을 `unknown`으로 잠그고 broker reconcile을 요구한다.
- deterministic idempotency key는 `trading_day`, phase, symbol, side, qty, order type, limit price, prediction/signal/target/gate/rule id를 기준으로 만든다.

## 4. 실행 산출물

- `./scripts/set_live_kill_switch.sh --enable --reason dry_run_validation --actor test`
  - 결과: `status=dry_run`, `applied=false`
  - 실제 kill switch 파일 기록 없음
- `./scripts/run_codex_ops_job.sh --job-type premarket-readiness --database-timeout-seconds 2.0`
  - 결과: `status=ok`, `database=status ok`, `timeout_seconds=2.0`
  - 생성/갱신: `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
- `./scripts/run_live_readiness_dry_run.sh`
  - fixture 없음 기준: `status=blocked`, 9개 check 모두 `not_verified`
  - 생성/갱신: `runtime-data/reports/live-readiness/latest-readiness.json`

## 5. 검증

- `bash -n scripts/script_dispatch.sh scripts/set_live_kill_switch.sh scripts/run_codex_ops_job.sh`
  - 통과
- `python -m unittest tests.test_codex_ops_job_script tests.test_live_kill_switch_cli_script tests.test_live_kill_switch`
  - 통과, 13개
- `python -m unittest tests.test_live_order_manager tests.test_live_storage tests.test_live_order_guard tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script`
  - 통과, 27개
- `python -m unittest tests.test_live_order_manager tests.test_live_storage tests.test_live_order_guard tests.test_live_kill_switch tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
  - 통과, 48개
- `bash -n scripts/script_dispatch.sh scripts/set_live_kill_switch.sh scripts/run_codex_ops_job.sh scripts/run_live_readiness_dry_run.sh`
  - 통과
- `python -m unittest discover -s tests -p "test_*.py"`
  - 통과, 199개
- `python -m app --build-dashboard`
  - 통과
  - 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`
- `git diff --check`
  - 통과
  - 참고: `docs/logbook.md`의 CRLF/LF 정규화 경고만 표시됨
- `git diff -- app/risk VERSION config`
  - 출력 없음

## 6. 안전 확인

- 실제 KIS live 주문 API 호출 없음
- 실제 KIS live client 생성 없음
- kill switch CLI 검증은 dry-run으로만 실행
- 운영 DB schema apply 없음
- readiness DB `--record` 실행 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 7. 다음 권장

🟢 다음 단계 권장: Slice 5-2로 live execution sync 골격을 구현한다. 권장 범위는 KIS 응답을 직접 호출하지 않는 parser/mapper 단위부터 시작해 `submitted/open/partially_filled/filled/cancelled/rejected/expired` 상태 해석과 delta fill 계산을 테스트로 잠그는 것이다.

🟢 다음 단계 권장: `LiveOrderManager`를 streaming에 연결하기 전, Phase 2의 "1일 1부모주문 / 동일 종목 pending 차단" 정책을 manager 또는 별도 policy service 중 어디에 둘지 확정한다. Codex 권장안은 manager 내부 pre-submit policy로 두되, 수치 한도는 별도 risk/live gate가 담당하게 분리하는 것이다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 운영 DB에 `apply_storage_migration.sh --apply`를 실행할 시점. Codex 권장안은 cowork가 Slice 5 상태머신 리뷰를 끝낸 뒤, 장외 시간에 dashboard/live runtime 정지 확인 후 1회 적용이다.

## 8. cowork 확인 질문

1. `LiveOrderManager`가 broker를 직접 만들지 않고 protocol 주입형으로 둔 경계가 실전 안전 기준에 맞는지.
2. guard 차단을 `blocked` 상태로 저장하는 정책이 적절한지, 아니면 intent는 유지하고 별도 audit event만 남겨야 하는지.
3. 재시작 복구에서 open 계열 주문을 즉시 `unknown`으로 잠그는 정책이 Phase 2 보수 운용에 충분히 안전한지.
4. 다음 라운드를 live execution sync parser/mapper로 진행해도 되는지.
