# Codex 작업 리포트 work_ver_16: review_ver_15 P1 보강

## 1. 기준 상태

- 기준 리뷰: `docs/cowork-reports/2026-05-22-production-architecture-implementation-blueprint-review_ver_15.md`
- 작업 시각 상태: `weekend`, live runtime 중지, runtime watchdog 실행 중, trading mode `paper`
- 작업 범위: review_ver_15의 P1 중 WS evidence enum 단일화, readiness freshness per-key화, manual market status `symbol_set_hash` 자동 검증, HTTP Date 정밀도 명시, dashboard WS recovery 상세 표시, paper/live HTTP Date 비교 helper, account snapshot value type drift 차단, Phase 2 모델 성능 선행 게이트 문서화
- 실행하지 않은 것: NAS 실제 package/drill, live account 조회, live order submit/cancel, runtime restart, 운영 DB schema apply

관련 문서/코드 경로: `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`, `docs/cowork-reports/2026-05-22-production-architecture-implementation-blueprint-review_ver_15.md`

## 2. 반영 내용

### A. WS recovery evidence enum 단일 소스화

- `app/services/ws_recovery_evidence.py`를 추가했다.
- `REAL_WS_RECOVERY_EVIDENCE_TYPES`와 evidence type 설명을 한 곳에 두고, `live_phase_readiness.py`와 `live_order_guard.py`가 이를 import한다.
- `real_kis_ws_observed`, `real_kis_ws_recovery`, `kis_ws_observed`의 의미를 코드 docstring/description으로 남겼다.

관련 문서/코드 경로: `app/services/ws_recovery_evidence.py`, `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py`

### B. Readiness evidence freshness per-key화

- 기존 기본 1시간 단일 기준을 key별 기준으로 바꿨다.
- 현재 기준:
  - `system_clock`: 1800초, 30분
  - `ws_recovery`: 1800초, 30분
  - `account_snapshot`: 3600초, 1시간
  - `market_status`: 3600초, 1시간
  - `token_refresh`: 14400초, 4시간
- 통과/차단 모두 `max_evidence_age_seconds`와 `evidence_age_seconds`를 남긴다.

관련 문서/코드 경로: `app/services/live_phase_readiness.py`, `tests/test_live_phase_readiness.py`

### C. Manual market_status symbol_set_hash 자동 검증

- `app/services/market_status_probe.py`에 `compute_symbol_set_hash()`를 추가했다.
- hash 규칙: `status_json.symbols` key를 정렬하고 줄바꿈으로 이어 SHA-256 digest 앞 16자를 붙인 `symbols-sha256-<16hex>` 형식.
- snapshot의 `symbol_set_hash`가 기대 hash와 다르면 check 생성 전에 failed 처리한다.
- `scripts/probe_market_status_snapshot.py`에 `--print-symbol-set-hash`를 추가해 snapshot 작성자가 기대 hash를 출력할 수 있게 했다.
- `docs/Manual-Market-Status-Runbook.md`의 placeholder를 실제 절차로 교체하고 stale 회복 절차를 추가했다.

관련 문서/코드 경로: `app/services/market_status_probe.py`, `scripts/probe_market_status_snapshot.py`, `docs/Manual-Market-Status-Runbook.md`, `tests/test_market_status_probe.py`

### D. system_clock HTTP Date 정밀도 명시

- `system_clock` readiness check details에 `reference_precision_seconds=1.0`과 precision note를 추가했다.
- HTTP `Date` header는 초 단위 정밀도이므로 표시 skew가 `0.002초`처럼 보여도 실제 의미는 밀리초 정밀도가 아니라 대략 1초 이내 여부다.

관련 문서/코드 경로: `app/services/live_phase_readiness.py`, `app/services/system_clock_probe.py`, `tests/test_kis_clock_reference_probe.py`

### E. Phase 2 모델 성능 선행 게이트 문서화

- Phase 2 진입 조건에 모델 성능 선행 게이트를 명시했다.
- 현재 active model은 `baseline-h15-v1`이고 LightGBM은 challenger 상태다.
- Phase 2 실전 주문 전에는 단순 accuracy가 아니라 독립 holdout, 비용 반영 net return, 거래 수, paper 성과, walk-forward gate, active model 승인 상태를 함께 본다.
- baseline fallback 또는 최신 challenger의 `recommended_action=keep_active` 상태에서는 Phase 2 신규 실전 주문을 내지 않는 것을 기본 후보로 문서화했다.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Transition-Progress.md`, `runtime-data/ml/registry.json`, `runtime-data/reports/challengers/latest-challengers-h15.json`

### F. Dashboard WS recovery 상세 표시

- `app/services/dashboard.py`의 live readiness 카드에 `WS recovery 상태`, `WS evidence type`, 실제 WS evidence 여부, evidence freshness, stable state/frame, reconnect count, observed time을 표시하도록 보강했다.
- synthetic evidence가 dashboard에서 단순 ok/차단으로만 보이지 않고, Phase 2/3 submit guard가 요구하는 실제 KIS WS evidence와 구분된다.
- 기존 readiness JSON shape가 없을 때는 `-`로 표시해 dashboard 생성 자체가 실패하지 않도록 했다.

관련 문서/코드 경로: `app/services/dashboard.py`, `tests/test_dashboard.py`, `runtime-data/reports/live-readiness/latest-readiness.json`

### G. paper/live HTTP Date reference 비교 helper

- `app/services/system_clock_probe.py`에 `build_system_clock_reference_comparison()`을 추가했다.
- `scripts/probe_kis_clock_reference.sh --compare-paper-live`는 주문 메서드 없는 read-only quote로 paper/live HTTP `Date` reference를 각각 1회 확인하고, raw header 없이 `reference_delta_seconds`만 담은 sanitized 진단 JSON을 만들 수 있다.
- 기본 실행은 여전히 paper 단일 probe이며, 비교 probe는 명시적으로 flag를 줄 때만 동작한다.
- 이번 작업에서는 live account 조회를 실행하지 않았다.

관련 문서/코드 경로: `app/services/system_clock_probe.py`, `scripts/probe_kis_clock_reference.py`, `scripts/probe_kis_clock_reference.sh`, `tests/test_kis_clock_reference_probe.py`

### H. account_snapshot value type drift 차단

- `app/services/kis_account_probe.py`가 `position_row_count`, `summary_row_count`, `cash_balance`, `stock_evaluation_amount`, `total_asset_amount`의 존재뿐 아니라 타입도 확인하도록 보강했다.
- row count는 non-negative int, 금액 계열은 number 타입이어야 한다.
- 차단 detail에는 원문 값이 아니라 `attribute`, `expected`, `actual_type`만 남긴다. 계좌번호, 상품코드, 금액 원문은 저장하지 않는다.

관련 문서/코드 경로: `app/services/kis_account_probe.py`, `tests/test_kis_account_probe.py`

## 3. 최신 readiness 재확인

기존 local fixture snapshot으로 `run_live_readiness_dry_run.sh`를 다시 실행했다.

- 현재 날짜가 `2026-05-23` 주말이고, 어제 만든 증거는 key별 freshness 기준을 초과했다.
- `token_refresh`는 4시간 기준 안이라 통과했다.
- `ws_recovery`, `account_snapshot`, `system_clock`은 stale로 차단됐다.
- `market_status`는 여전히 not_verified, `kill_switch`는 missing으로 차단됐다.
- 이는 Phase 1 장전마다 fresh probe를 다시 만들어야 한다는 fail-closed 동작으로 정상이다.

관련 문서/코드 경로: `runtime-data/reports/live-readiness/latest-readiness.json`, `runtime-data/reports/live-readiness/local-fixture-snapshot.json`

## 4. 검증

- `python -m unittest tests.test_live_phase_readiness tests.test_live_order_guard tests.test_live_order_manager tests.test_market_status_probe tests.test_kis_clock_reference_probe`
  - 61 tests OK
- `python -m unittest tests.test_live_phase_readiness tests.test_live_order_guard tests.test_live_order_manager tests.test_market_status_probe tests.test_kis_clock_reference_probe tests.test_live_readiness_dry_run_script`
  - 72 tests OK
- `python -m py_compile app/services/ws_recovery_evidence.py app/services/live_phase_readiness.py app/services/live_order_guard.py app/services/market_status_probe.py scripts/probe_market_status_snapshot.py tests/test_live_phase_readiness.py tests/test_market_status_probe.py tests/test_kis_clock_reference_probe.py tests/test_live_readiness_dry_run_script.py`
  - OK
- `bash -n scripts/probe_market_status_snapshot.sh scripts/run_live_readiness_dry_run.sh`
  - OK
- `python -m unittest tests.test_kis_clock_reference_probe tests.test_dashboard`
  - 24 tests OK
- `python -m py_compile app/services/system_clock_probe.py scripts/probe_kis_clock_reference.py app/services/dashboard.py tests/test_kis_clock_reference_probe.py tests/test_dashboard.py`
  - OK
- `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_guard tests.test_live_order_manager tests.test_kis_live_order_adapter tests.test_dashboard`
  - 166 tests OK
- `python -m app --build-dashboard`
  - OK. `runtime-data/reports/dashboard/latest-dashboard.html`에 WS recovery 상세 row가 표시되는 것을 확인했다.
- `python -m unittest tests.test_kis_account_probe tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness`
  - 35 tests OK
- `python -m py_compile app/services/kis_account_probe.py tests/test_kis_account_probe.py`
  - OK
- account snapshot value type 검증 반영 후 같은 관련 전체 묶음 재실행
  - 167 tests OK
- 최종 `py_compile`와 readiness 관련 `bash -n`
  - OK
- `git diff --check`
  - OK. CRLF/LF 안내 warning만 있었고 whitespace error는 없었다.
- `git diff --name-only -- app/risk config VERSION` / `git status --short -- app/risk config VERSION`
  - 출력 없음. 금지 경로 변경 없음.

관련 문서/코드 경로: `tests/test_live_phase_readiness.py`, `tests/test_market_status_probe.py`, `tests/test_kis_clock_reference_probe.py`, `tests/test_dashboard.py`, `tests/test_kis_account_probe.py`

## 5. 남은 항목과 권장안

🔴 운영자 승인 필요: NAS 실제 package/recovery drill

- 반영된 운영 기준: 기존 NAS 전체 백업은 이전 저장소 유실 사고 대응을 위한 재난 복구용 이중 보관으로 유지한다.
- 확인 결과: WSL `/mnt/backup` 마운트와 기존 repo 백업 폴더 접근이 가능하다. `run_forced_nas_backup.sh --backup-share-root /mnt/backup --backup-reason phase1-readonly-drill-check --dry-run`은 실제 package 생성 없이 통과했다.
- 권장안: Phase readiness/cowork 증거에는 기존 전체 백업을 직접 쓰지 않고, 별도 `recovery-drills/phase1-readonly` 폴더에서 비밀값 제외 sanitized recovery export 표본만 확인한다.

🔴 운영자 승인 필요: live account read-only probe 1회

- 권장안: Phase 1 직전, 주문 메서드 없는 read-only client로 1회 실행한다. 실행 결과는 row count와 shape status만 저장한다.

🔴 운영자 승인 필요: Phase 1 kill switch OFF 파일 생성

- 권장안: Phase 1 당일 장전 승인 절차에서만 `--disable --apply --confirm-disable` 조합으로 생성한다.

🟢 다음 단계 권장: HTTP Date paper/live 동기화 비교 실행 증적 확보

- 권장안: Phase 1 live read-only 승인 뒤 `scripts/probe_kis_clock_reference.sh --compare-paper-live`를 1회 실행한다. raw header는 저장하지 않고 delta와 status만 보관한다.

🟢 다음 단계 권장: live account shape baseline 확보

- 권장안: live 첫 read-only 실행 후 shape baseline을 저장하고, 후속 실행에서 attribute 추가/삭제와 핵심 값 타입 drift를 비교한다. value type drift 차단 helper는 이번 작업에서 구현됐다.

관련 문서/코드 경로: `scripts/set_live_kill_switch.sh`, `app/services/kis_account_probe.py`, `app/services/ws_recovery_evidence.py`, `docs/Production-Transition-Progress.md`

## 6. cowork에게 꼭 확인받을 지점

아직 다음 cowork 리뷰가 꼭 필요한 지점은 아니다. 다음 리뷰는 아래 중 하나가 끝난 뒤가 좋다.

1. live account read-only probe 1회 실행 결과 생성
2. paper/live HTTP Date reference 비교 실행 결과 생성
3. sanitized NAS drill 표본 확인 결과 생성

관련 문서/코드 경로: `app/services/dashboard.py`, `app/services/reporting.py`, `docs/cowork-reports/`
