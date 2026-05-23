# Codex work_ver_14-4: account snapshot + synthetic WS recovery readiness probe 구현

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
직전 작업: `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-3.md`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 작업 요약

Phase 1 readiness 10개 check 중 로컬에서 안전하게 증명 가능한 항목을 더 채웠다.

- `account_snapshot`: KIS 모의투자 paper 계좌 snapshot read-only 조회 1회로 sanitized check 생성.
- `ws_recovery`: 실제 WebSocket 네트워크를 열지 않는 synthetic fault injection으로 reconnect metric 상태 전이 검증.
- `local-fixture-snapshot`: token, account, synthetic WS, system clock, premarket report, kill switch 상태를 한 번에 묶어 readiness dry-run에 넣도록 확장.

실전 주문, live 계좌 조회, 운영 DB schema apply, runtime restart는 하지 않았다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| account snapshot 증적 | readiness에서 `account_snapshot`은 fixture가 없어 `not_verified`였다. | `scripts/probe_kis_account_snapshot.sh`가 read-only 계좌 snapshot 조회 뒤 계좌번호 없이 `account_snapshot` check를 저장한다. | `app/services/kis_account_probe.py`, `scripts/probe_kis_account_snapshot.py`, `runtime-data/reports/live-readiness/account-snapshot-check.json` | KIS 계좌 조회 실패 시 readiness가 blocked 된다. 안전 측 동작이다. |
| WS recovery 증적 | readiness에서 `ws_recovery`는 fixture가 없어 `not_verified`였다. | `scripts/probe_kis_ws_recovery.sh`가 실제 네트워크 없이 reconnect metric을 synthetic fault injection으로 검증한다. | `app/services/kis_ws_recovery_probe.py`, `scripts/probe_kis_ws_recovery.py`, `runtime-data/reports/live-readiness/ws-recovery-check.json` | 실제 KIS WebSocket 복구 증거가 아니므로 Phase 2 submit guard 기준으로 쓰면 안 된다. Phase 1 관측용 기초 check로만 둔다. |
| fixture snapshot | token/system/local premarket 중심이었다. | token, account, synthetic WS, system clock, kill switch, premarket checks를 병합한다. | `app/services/live_readiness_fixture.py`, `scripts/build_live_readiness_fixture_snapshot.py` | market status가 없으면 계속 blocked 된다. 자동 통과를 막는 의도된 동작이다. |

## 3. 실제 실행 결과

실행:

1. `./scripts/probe_kis_account_snapshot.sh --mode paper --output-path runtime-data/reports/live-readiness/account-snapshot-check.json`
2. `./scripts/probe_kis_ws_recovery.sh --output-path runtime-data/reports/live-readiness/ws-recovery-check.json`
3. `./scripts/build_live_readiness_fixture_snapshot.sh --output-path runtime-data/reports/live-readiness/local-fixture-snapshot.json`
4. `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --report-path runtime-data/reports/live-readiness/latest-readiness.json`

결과:

- 통과: `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`
- 미검증: `market_status`
- 실패: `kill_switch` missing. fail-closed라 신규 submit 차단이 정상이다.
- 전체 readiness: `blocked`

## 4. 검증

- `python -m unittest tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager`
  - 통과, 107개.
- `python -m py_compile app/services/kis_account_probe.py app/services/kis_ws_recovery_probe.py app/services/kis_token_probe.py app/services/system_clock_probe.py app/services/live_readiness_fixture.py scripts/probe_kis_account_snapshot.py scripts/probe_kis_ws_recovery.py scripts/probe_kis_token_refresh.py scripts/probe_kis_clock_reference.py scripts/build_live_readiness_fixture_snapshot.py tests/test_kis_account_probe.py tests/test_kis_ws_recovery_probe.py tests/test_live_readiness_fixture_snapshot.py`
  - 통과.
- `bash -n scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과.
- `git diff --check`
  - 통과. CRLF/LF warning만 있고 whitespace error는 없다.
- `git diff -- app/risk config VERSION`
  - 출력 없음.

## 5. Cowork 리뷰 필요성

아직은 cowork 리뷰 필수 시점이 아니다. 이번 작업은 review_ver_13의 권장 흐름 안에서 로컬 증적을 추가한 것이다.

다음 cowork 리뷰가 유효해지는 시점은 아래 중 하나다.

1. `market_status` 데이터 원천과 stale 정책 후보를 코드/문서로 고정한 뒤.
2. kill switch `OFF` 상태 파일 생성 절차를 실제 적용할지 결정한 뒤.
3. Phase 1 live account read-only 조회 허용 뒤 live response shape를 확인한 뒤.

## 6. 다음 권장 작업

🟢 Codex 권장안:

- `market_status`는 자동 통과시키지 말고 KIS/거래소 원천 또는 운영자 수동 snapshot 중 하나로 증거 파일을 만든 뒤 readiness에 넣는다.
- kill switch missing은 당분간 fail-closed로 유지한다. Phase 1 진입 직전 운영자 승인권자가 `OFF` 파일 생성을 승인할 때만 `scripts/set_live_kill_switch.sh --disable --apply --confirm-disable`을 사용한다.
- synthetic WS recovery는 Phase 1 관측 전 submit guard 기준으로 쓰지 않는다. 실제 WS reconnect baseline은 Phase 1 read-only 운영 중 dashboard/readiness 노출로 수집한다.

🔴 운영자 판단 필요:

- Phase 1 직전 kill switch `OFF` 상태 파일을 생성할지.
- market status 원천을 KIS, 한국거래소, 수동 snapshot 중 무엇으로 시작할지.
- live account read-only probe를 언제 허용할지.
