# Codex work_ver_14-5: manual market_status snapshot readiness probe 구현

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
직전 작업: `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-4.md`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 작업 요약

`market_status` readiness가 증거 없이 자동 통과되지 않도록 유지하면서, repo 내부 수동 snapshot이 있을 때만 check를 생성하는 경로를 추가했다.

- `app/services/market_status_probe.py`: 수동 snapshot payload를 `MarketStatusSnapshot`으로 파싱하고, 기존 `app/services/market_status.py` 순수 판정 로직으로 요청 종목을 평가한다.
- `scripts/probe_market_status_snapshot.sh`: repo 내부 snapshot을 읽어 `runtime-data/reports/live-readiness/market-status-check.json` 후보를 만든다.
- `scripts/build_live_readiness_fixture_snapshot.sh`: `market-status-check.json`이 있을 때만 local fixture snapshot에 포함한다.

KIS/한국거래소 자동 market status 원천은 아직 연결하지 않았다. 이 작업은 데이터 원천 결정을 대신하지 않고, 수동 증거 파일이 없는 상태에서 통과하지 않도록 막는 안전 경로다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| market status readiness | 별도 check 파일이 없어 항상 `not_verified`였다. | 수동 snapshot 파일이 있으면 `probe_market_status_snapshot.sh`가 `market_status` check를 생성한다. | `app/services/market_status_probe.py`, `scripts/probe_market_status_snapshot.py`, `runtime-data/reports/live-readiness/market-status-check.json` | snapshot이 stale이거나 종목 누락이면 blocked 된다. 안전 측 동작이다. |
| local fixture snapshot | market status를 병합할 방법이 없었다. | `market-status-check.json`이 있을 때만 fixture에 포함한다. 파일이 없으면 기존처럼 not_verified다. | `app/services/live_readiness_fixture.py`, `scripts/build_live_readiness_fixture_snapshot.py` | 사람이 만든 snapshot 품질에 의존하므로 KIS/거래소 자동 원천 전까지는 운영자 확인이 필요하다. |
| 데이터 원천 | KIS/거래소/수동 중 결정 전이었다. | 결정 전 기본 후보를 수동 snapshot으로 제한했다. 자동 원천은 별도 slice로 남긴다. | 문서, readiness runbook | 수동 snapshot 갱신을 빼먹으면 Phase readiness가 blocked 된다. |

## 3. 실제 실행 결과

이번 작업은 실제 market status snapshot을 만들지 않았다. 따라서 현재 readiness는 그대로 blocked다.

- 통과: `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`
- 미검증: `market_status`
- 실패: `kill_switch` missing. fail-closed라 신규 submit 차단이 정상이다.
- 전체 readiness: `blocked`
- blocking reasons: `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed`

## 4. 검증

- `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager`
  - 통과, 119개.
- `python -m py_compile app/services/market_status_probe.py app/services/live_readiness_fixture.py scripts/probe_market_status_snapshot.py scripts/build_live_readiness_fixture_snapshot.py tests/test_market_status_probe.py tests/test_live_readiness_fixture_snapshot.py`
  - 통과.
- `bash -n scripts/probe_market_status_snapshot.sh scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과.

## 5. Cowork 리뷰 필요성

이제 cowork 리뷰가 이전보다 더 유효해졌다. 남은 내용은 단순 구현보다 운영 정책 판단이 섞인다.

리뷰 요청 초점:

1. 수동 market status snapshot을 Phase 1 readiness의 임시 증거로 허용해도 되는지.
2. `market_status` 자동 원천을 KIS REST, 한국거래소, 수동 snapshot 중 어떤 순서로 붙일지.
3. kill switch missing을 Phase 1 직전까지 fail-closed로 유지하는 판단이 맞는지.

## 6. 다음 권장 작업

🟢 Codex 권장안:

- Phase 1 전에는 수동 market status snapshot으로 시작한다.
- 자동 원천은 KIS REST 후보와 한국거래소 후보를 비교한 뒤 별도 slice로 붙인다.
- kill switch `OFF` 파일 생성은 readiness 통과 직전까지 미루고, 생성 시에는 계좌 소유자 또는 실전 운용 승인권자 승인 후 `scripts/set_live_kill_switch.sh --disable --apply --confirm-disable`을 사용한다.

🔴 운영자 판단 필요:

- 실제 거래일 market status snapshot을 수동으로 만들지, KIS/거래소 자동 원천 구현을 먼저 할지.
- Phase 1 직전 kill switch `OFF` 상태 파일을 생성할지.
- live account read-only probe를 언제 허용할지.
