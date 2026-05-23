# Codex work_ver_14-3: token refresh readiness probe 구현

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
직전 작업: `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-2.md`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 작업 요약

Phase 1 readiness의 `token_refresh` 항목을 fixture 추정이 아니라 실제 KIS 인증 refresh 증거로 만들 수 있게 했다.

- `app/services/kis_token_probe.py`가 token 원문 없이 `token_refresh` check를 만든다.
- `scripts/probe_kis_token_refresh.sh`가 paper/live mode별 auth-only token refresh check JSON을 생성한다.
- `build_live_readiness_fixture_snapshot.sh`가 `token-refresh-check.json`을 읽어 local fixture snapshot에 포함한다.
- KIS 모의투자 paper token refresh 1회를 실제 실행해 `token_refresh=true` 증적을 확보했다.

실전 주문, live 계좌 조회, 운영 DB schema apply, runtime restart는 하지 않았다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| token refresh 증적 | `kis_credentials=ok`는 있었지만 실제 token refresh 성공 증거와는 달랐다. | `probe_kis_token_refresh.sh`가 KIS token refresh를 수행하고 token 원문 없이 status, expiry, mode, force_refresh 여부만 저장한다. | `app/services/kis_token_probe.py`, `scripts/probe_kis_token_refresh.py`, `runtime-data/reports/live-readiness/token-refresh-check.json` | KIS auth endpoint rate limit이나 credential 오류가 있으면 readiness가 blocked 된다. 안전 측 동작이다. |
| local fixture snapshot | token refresh는 별도 증거가 없어 absent/not_verified로 남았다. | `build_live_readiness_fixture_snapshot.sh`가 `token-refresh-check.json`을 읽어 `token_refresh` fixture로 병합한다. | `app/services/live_readiness_fixture.py`, `scripts/build_live_readiness_fixture_snapshot.py` | token check 파일이 오래된 경우 freshness 정책이 필요하다. 현재는 operator/runbook 절차로 fresh 실행 뒤 사용해야 한다. |
| 보안 | token refresh 결과를 기록하려면 token 노출 위험이 있었다. | token 원문, app key, app secret, 계좌번호는 payload에 쓰지 않는다. 실패 시에도 exception message는 저장하지 않고 error type만 남긴다. | report JSON, cowork 공유 | 디버깅 정보는 줄어들지만 보안 측 동작이다. |

## 3. 실제 실행 결과

실행:

1. `./scripts/probe_kis_token_refresh.sh --mode paper --output-path runtime-data/reports/live-readiness/token-refresh-check.json`
2. `./scripts/build_live_readiness_fixture_snapshot.sh --output-path runtime-data/reports/live-readiness/local-fixture-snapshot.json`
3. `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --report-path runtime-data/reports/live-readiness/latest-readiness.json`

결과:

- `token_refresh=true`
- `system_clock=true`
- `database=true`, `disk_space=true`, `dashboard=true`, `storage_migration_state=true`
- `kill_switch=false`: state file missing으로 fail-closed
- `ws_recovery=false`, `account_snapshot=false`, `market_status=false`: 별도 증거 없음
- 전체 readiness: `blocked`

## 4. 검증

- `python -m unittest tests.test_kis_token_probe tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_kis_clock_reference_probe`
  - 통과, 38개.
- `python -m py_compile app/services/kis_token_probe.py app/services/live_readiness_fixture.py scripts/probe_kis_token_refresh.py scripts/build_live_readiness_fixture_snapshot.py tests/test_kis_token_probe.py tests/test_live_readiness_fixture_snapshot.py`
  - 통과.
- `bash -n scripts/probe_kis_token_refresh.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh`
  - 통과.

## 5. Cowork 리뷰 요청

아직 cowork 리뷰 필수 시점은 아니다. 다음 리뷰 때는 아래만 보면 된다.

1. token refresh check에 expiry와 mode만 남기고 token 원문/오류 메시지를 숨기는 방식이 충분한지.
2. token refresh check freshness 정책을 runbook으로 둘지, check 자체에 max age를 넣을지.
3. 다음 blocker를 kill switch OFF 파일 생성 승인으로 보는 것이 맞는지.

## 6. 다음 권장 작업

🟢 Codex 권장안:

- 다음 단계는 kill switch `OFF` 상태 파일 생성 절차를 dry-run/status UX로 먼저 정리한다.
- 실제 `--apply` OFF 파일 생성은 운영 결정이므로 자동 실행하지 않는다.
- 이후 WS recovery, account snapshot, market status 증적 경로를 각각 분리한다.

🔴 운영자 판단 필요:

- kill switch `OFF` 상태 파일을 언제 `--apply`로 생성할지.
- live account read-only probe 실행 시점.
