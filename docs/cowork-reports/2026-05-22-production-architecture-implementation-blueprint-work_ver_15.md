# Codex 작업 리포트 work_ver_15: review_ver_14 P0 반영

## 1. 기준 상태

- 기준 리뷰: `docs/cowork-reports/2026-05-22-production-architecture-implementation-blueprint-review_ver_14.md`
- 작업 시각 상태: `post-close`, live runtime 중지, runtime watchdog 실행 중, trading mode `paper`
- 작업 범위: review_ver_14의 P0 중 synthetic WS evidence 누수, account snapshot shape drift, readiness evidence stale 위험 보강, P1 중 manual market_status runbook/source enum 보강
- 실행하지 않은 것: NAS 실제 package/drill, live account 조회, live order submit/cancel, runtime restart, 운영 DB schema apply

관련 문서/코드 경로: `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`, `docs/cowork-reports/2026-05-22-production-architecture-implementation-blueprint-review_ver_14.md`

## 2. 반영 내용

### A. Phase 2/3 WS recovery evidence guard

- `app/services/live_phase_readiness.py`
  - `REAL_WS_RECOVERY_EVIDENCE_TYPES`를 추가했다.
  - Phase 2/3 readiness에서는 `ws_recovery`가 passed여도 `details.evidence_type`이 실제 KIS WS 관측 계열이 아니면 `invalid_evidence`로 바꾼다.
  - synthetic `ws_recovery=true`가 Phase 1 dry-run 증거로는 남을 수 있지만 Phase 2/3 submit readiness 증거로 silent 재사용되지 않는다.
- `app/services/live_order_guard.py`, `app/services/live_order_manager.py`
  - live submit guard도 Phase 2/3에서 실제 WS recovery evidence type을 기본 요구한다.
  - caller가 증거를 넘기지 않거나 `synthetic_fault_injection`이면 broker 호출 전에 `ws_recovery_real_evidence_required`로 차단한다.

관련 문서/코드 경로: `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py`, `app/services/live_order_manager.py`, `tests/test_live_phase_readiness.py`, `tests/test_live_order_guard.py`, `tests/test_live_order_manager.py`

### B. Account snapshot shape drift 차단

- `app/services/kis_account_probe.py`
  - 필수 shape: `position_row_count`, `summary_row_count`, `cash_balance`, `stock_evaluation_amount`, `total_asset_amount`
  - 필수 attribute가 없으면 `shape_status=missing_required_attributes`, `passed=false`로 차단한다.
  - 계좌번호, 금액 raw value, raw response는 저장하지 않고 존재 여부와 row count만 남긴다.

관련 문서/코드 경로: `app/services/kis_account_probe.py`, `tests/test_kis_account_probe.py`, `scripts/probe_kis_account_snapshot.sh`

### C. Readiness evidence freshness guard

- `app/services/live_phase_readiness.py`
  - timestamp가 있는 `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `system_clock` 증거는 기본 1시간을 넘으면 `stale_evidence`로 차단한다.
  - 통과 증거에는 `evidence_age_seconds`를 남겨 사후 리뷰가 가능하게 했다.
  - timestamp가 없는 legacy/bool fixture는 기존 테스트 호환을 위해 freshness 판단을 하지 않는다. 실제 wrapper가 만드는 probe JSON은 timestamp를 가진다.

관련 문서/코드 경로: `app/services/live_phase_readiness.py`, `scripts/build_live_readiness_fixture_snapshot.sh`, `scripts/run_live_readiness_dry_run.sh`, `tests/test_live_phase_readiness.py`

## 3. 최신 readiness 재확인

fresh paper/read-only probe를 다시 실행했다.

- `token_refresh`: paper auth-only, token 원문 미저장
- `account_snapshot`: paper read-only, 계좌번호/raw response 미저장, `shape_status=ok`
- `ws_recovery`: offline synthetic, `network_called=false`, `evidence_type=synthetic_fault_injection`
- `system_clock`: KIS paper 현재가 read-only 1회, HTTP Date 기반 skew 약 0.002초

fixture snapshot 기반 `latest-readiness.json`은 계속 `blocked`다. `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`에는 `evidence_age_seconds`가 기록됐고, 남은 blocker는 `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed` 두 개다.

관련 문서/코드 경로: `runtime-data/reports/live-readiness/latest-readiness.json`, `runtime-data/reports/live-readiness/local-fixture-snapshot.json`

## 4. Manual Market Status Runbook

- `docs/Manual-Market-Status-Runbook.md`를 추가했다.
- 수동 snapshot `source`는 `manual_operator_snapshot`, `manual_krx_snapshot`, `manual_kis_snapshot`만 허용한다.
- `app/services/market_status_probe.py`는 자유 문자열 source를 readiness 증거로 인정하지 않는다.
- runbook에는 snapshot 양식, 장전 절차, stale 기본 차단, KRX/KIS 자동 원천 전환 후보를 적었다.

관련 문서/코드 경로: `docs/Manual-Market-Status-Runbook.md`, `app/services/market_status_probe.py`, `tests/test_market_status_probe.py`, `scripts/probe_market_status_snapshot.sh`

## 5. 검증

- `python -m unittest tests.test_live_order_guard tests.test_live_order_manager tests.test_live_phase_readiness tests.test_kis_account_probe`
  - 52 tests OK
- `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_guard tests.test_live_order_manager tests.test_kis_live_order_adapter`
  - 143 tests OK
- `python -m py_compile app/services/live_order_guard.py app/services/live_order_manager.py app/services/live_phase_readiness.py app/services/kis_account_probe.py tests/test_live_order_guard.py tests/test_live_order_manager.py tests/test_live_phase_readiness.py tests/test_kis_account_probe.py`
  - OK
- 관련 Python 파일과 probe wrapper `py_compile` 통과
- `bash -n scripts/probe_market_status_snapshot.sh scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - OK
- `git diff --check`
  - OK. `docs/Current-Implementation.md`, `docs/logbook.md`의 CRLF/LF warning만 있고 whitespace error는 없음.
- `git diff -- app/risk config VERSION`
  - 출력 없음

관련 문서/코드 경로: `tests/test_live_order_guard.py`, `tests/test_live_order_manager.py`, `tests/test_live_phase_readiness.py`, `tests/test_kis_account_probe.py`, `tests/test_market_status_probe.py`

## 6. 남은 P0와 권장안

🔴 운영자 승인 필요: NAS 실제 package/recovery drill

- 권장안: 자동 실행하지 않는다. 장외 시간에 용량과 NAS 연결 상태를 먼저 확인한 뒤, partial drill과 full package 중 어느 범위로 할지 결정한다.

🔴 운영자 승인 필요: live account read-only probe 1회

- 권장안: 이번 shape guard가 들어간 뒤 Phase 1 직전에 주문 메서드 없는 read-only client로 1회 실행한다. 실행 결과는 row count와 shape status만 저장한다.

🔴 운영자 승인 필요: kill switch OFF 파일 생성 시점

- 권장안: Phase 1 직전 당일 승인 절차에서만 `--disable --apply --confirm-disable` 조합으로 생성한다. 지금 missing 상태는 fail-closed로 정상이다.

🟢 다음 단계 권장: actual market_status snapshot 생성

- 권장안: Phase 1 전 임시로 repo-local 수동 snapshot을 허용하되, 새 runbook의 source enum과 stale 정책을 따른다. KRX/KIS 자동 원천은 별도 slice로 둔다.

관련 문서/코드 경로: `scripts/set_live_kill_switch.sh`, `app/services/market_status_probe.py`, `scripts/probe_market_status_snapshot.sh`, `docs/Production-Transition-Progress.md`

## 7. cowork에게 꼭 확인받을 지점

토큰 제약이 있으면 아래 3개만 보면 된다.

1. Phase 2/3 synthetic WS evidence 차단이 readiness와 live submit guard 양쪽에서 충분한지.
2. account snapshot shape 검증의 필수 attribute 5개가 live read-only 진입 전 기준으로 충분한지.
3. timestamped evidence freshness 기본 1시간이 Phase 1 장전 readiness 기준으로 너무 짧거나 길지 않은지.

관련 문서/코드 경로: `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py`, `app/services/kis_account_probe.py`
