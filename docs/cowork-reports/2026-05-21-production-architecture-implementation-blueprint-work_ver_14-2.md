# Codex work_ver_14-2: local readiness fixture snapshot 구현

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
직전 작업: `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-1.md`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 작업 요약

`work_ver_14-1`의 system clock probe 이후, Phase 1 readiness에서 로컬로 이미 증명 가능한 항목을 한 번에 fixture로 묶는 wrapper를 추가했다.

- `premarket-readiness` report에서 `database`, `disk_space`, `dashboard`, `storage_migration_state`만 가져온다.
- `system_clock-check.json`이 있으면 `system_clock` check로 넣는다.
- kill switch 상태 파일을 읽어 fresh `OFF`이면 통과, missing/broken/stale/enabled이면 실패로 넣는다.
- `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`는 별도 증거 없이는 넣지 않는다.

이번 작업은 JSON report/read-only 파일 처리만 수행했다. 실전 주문, live 계좌 조회, 운영 DB schema apply, runtime restart는 하지 않았다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| local readiness fixture | `run_live_readiness_dry_run.sh`는 fixture 파일을 받을 수 있었지만, premarket/system_clock/kill switch 증거를 conservative하게 묶는 표준 생성기가 없었다. | `app/services/live_readiness_fixture.py`와 `scripts/build_live_readiness_fixture_snapshot.sh`를 추가했다. 로컬 증거가 있는 항목만 fixture로 만들고, 증거 없는 항목은 absent 상태로 둔다. | `app/services/live_readiness_fixture.py`, `scripts/build_live_readiness_fixture_snapshot.py`, `scripts/script_dispatch.sh` | stale report를 최신 증거처럼 읽을 수 있으므로 wrapper 실행 전 premarket report를 갱신해야 한다. |
| kill switch readiness | kill switch 파일이 없을 때 readiness에서 단순 missing 또는 별도 fixture 없음으로 보였다. | snapshot wrapper가 missing/broken/stale/enabled를 explicit failed fixture로 만든다. | `app/services/live_kill_switch.py` 읽기 경로, `runtime-data/reports/live-risk/kill-switch.json` | 실제 `OFF` 파일 생성은 운영 행위라 아직 자동으로 하지 않는다. missing은 fail-closed로 남는다. |
| 과통과 방지 | `kis_credentials=ok` 같은 premarket check를 token refresh 통과로 오해할 여지가 있었다. | token refresh, WS recovery, account snapshot, market status는 별도 증거 없이는 fixture에 포함하지 않는다. | Phase 1 readiness 판단 | readiness가 계속 blocked로 남지만 안전 측 동작이다. |

## 3. 실제 실행 결과

실행한 순서:

1. `./scripts/run_codex_ops_job.sh --job-type premarket-readiness --report-path runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
2. `./scripts/build_live_readiness_fixture_snapshot.sh --output-path runtime-data/reports/live-readiness/local-fixture-snapshot.json`
3. `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --report-path runtime-data/reports/live-readiness/latest-readiness.json`

결과:

- 통과로 병합: `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`.
- 실패: `kill_switch`는 state file missing으로 failed.
- 미검증: `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`.
- 전체 readiness: `blocked`.

이 결과는 현재 단계에서 의도한 fail-closed 동작이다.

## 4. 검증

- `python -m unittest tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_kis_clock_reference_probe`
  - 통과, 35개.
- `python -m py_compile app/services/live_readiness_fixture.py scripts/build_live_readiness_fixture_snapshot.py tests/test_live_readiness_fixture_snapshot.py`
  - 통과.
- `bash -n scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과.

## 5. Cowork 리뷰 요청

아직 cowork 리뷰가 필수인 시점은 아니다. 다음 리뷰 때는 아래만 보면 된다.

1. `kis_credentials=ok`를 `token_refresh=true`로 승격하지 않고 미검증으로 둔 판단이 적절한지.
2. kill switch missing을 explicit failed fixture로 넣는 방식이 Phase 1 readiness UX에 적절한지.
3. premarket report 기반 local fixture는 fresh report 실행 뒤에만 쓰는 운영 절차로 충분한지.

## 6. 다음 권장 작업

🟢 Codex 권장안:

- 다음은 kill switch 상태 파일을 실제로 `OFF`로 만들지 말고, 먼저 dry-run/status UX와 문서 절차를 더 잠근다.
- 그 다음 token refresh, WS recovery, account snapshot, market status 각각의 증적 생성 경로를 분리한다.
- live account read-only header shape 확인은 Phase 1 read-only 승인 뒤에만 실행한다.

🔴 운영자 판단 필요:

- kill switch `OFF` 상태 파일을 언제 `--apply`로 생성할지.
- live account read-only probe 실행 시점.
