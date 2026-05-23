# Codex work_ver_13-8: overnight / pre-open 상태 라벨 분리

## 배경

사용자가 2026-05-21 00~01시대에 `pre-open` 상태로 표시되는 점을 지적했다. 실제로 이 시간은 장전 워밍업이 아니라 야간 대기 시간이다.

작업 전 상태:

- `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=pre-open`, `trading_mode=paper`
- `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=pre-open`, `live_runtime_should_run=false`, `errors=[]`

## 원인

아래 세 경로가 정규장 시작 전 모든 시간을 `pre-open`으로 표시했다.

- `app/utils/time.py`
- `scripts/wsl_ops.py`
- `scripts/common_process_helpers.sh`

`scripts/wsl_ops.py`는 내부 boolean 으로 정규장 시작 60분 전 warmup 여부를 이미 계산했지만, 상태 라벨은 warmup 밖 새벽/야간에도 계속 `pre-open`으로 반환했다. 이 때문에 Codex 작업 모드 판단, dashboard 안내, watchdog action 문구가 실제 운영 상태보다 보수적으로 보였다.

## 변경

- `app/utils/time.py`
  - `get_market_session_status(..., pre_open_warmup_minutes=60)` 파라미터를 추가했다.
  - 일반 거래일 정규장 시작 60분 전부터 개장 전까지는 `pre-open`, 그보다 이른 시간은 `overnight`를 반환한다.
- `scripts/wsl_ops.py`
  - `market_settings(root, pre_open_warmup_minutes=60)`로 warmup 길이를 명시했다.
  - watchdog loop가 CLI의 `--pre-open-warmup-minutes` 값을 실제 상태 계산에 사용한다.
- `scripts/common_process_helpers.sh`
  - 공통 shell helper도 같은 기준으로 `overnight`와 `pre-open`을 구분한다.
- `app/services/kis_verification.py`
  - `overnight`를 시장 데이터 기대 없음 상태로 처리한다.
- `app/services/dashboard.py`
  - `overnight` KIS 검증 실패를 정규장 장애가 아니라 장외 안내로 낮춘다.
  - `overnight` 운영 메모를 추가했다.
- `AGENTS.md`, `README.md`, `docs/Current-Implementation.md`
  - `pre-open`은 실제 장전 워밍업 구간이고, `overnight`는 장전 워밍업 전 야간 대기 상태라고 반영했다.
- 테스트
  - `tests/test_time_utils.py` 추가.
  - `tests/test_codex_ops.py`, `tests/test_kis_ws_verification.py`, `tests/test_wsl_ops.py` 보강.

## Runtime 조치

수정 전 코드를 메모리에 들고 있던 runtime watchdog만 재시작했다.

- live runtime 은 재시작하지 않았다.
- KIS API 신규 호출 없음.
- live order submit/cancel 없음.
- 운영 DB schema apply 없음.
- 자동 commit/push 없음.

재시작 후 확인:

- `./scripts/get_live_runtime_status.sh`: `session_status=overnight`, `status=stopped`
- `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=overnight`, `live_runtime_should_run=false`, `live_runtime_action=off_session_hold_overnight`

## 검증

- `python -m unittest tests.test_time_utils tests.test_codex_ops tests.test_kis_ws_verification tests.test_wsl_ops`
  - 통과, 35개.
- `python -m py_compile app/utils/time.py app/services/kis_verification.py app/services/dashboard.py scripts/wsl_ops.py tests/test_time_utils.py tests/test_codex_ops.py tests/test_kis_ws_verification.py tests/test_wsl_ops.py`
  - 통과.
- `bash -n scripts/common_process_helpers.sh scripts/script_dispatch.sh scripts/get_live_runtime_status.sh scripts/get_runtime_watchdog_status.sh`
  - 통과.

## Cowork 확인 요청

1. `overnight`를 Codex ops 보호 세션에서 제외하고, `live_runtime_should_run=true` 또는 live runtime 실행 중일 때만 보호 모드로 올리는 해석이 운영 안전 기준에 맞는지 확인.
2. `pre-open` warmup 기본값 60분을 기존 watchdog 기본값과 맞춰 유지한 것이 충분한지 확인.
3. legacy PowerShell 스크립트(`scripts/legacy-ps1/`)에도 같은 라벨 분리를 반영해야 하는지 확인. 현재 정본 운용 명령은 WSL script 기준이라 이번 변경에서는 WSL 경로를 우선 고쳤다.

## 남은 권장 작업

🟢 Codex 권장안:

- 다음 작업에서는 Phase 1 P0 본류로 돌아가 `runtime caller/readiness runner가 fresh KIS read-only 조회 직후 system_clock decision/check를 자동 생성해 주입`하는 연결을 이어간다.
- legacy PS1 경로를 실제로 계속 쓴다면 별도 작은 작업으로 `overnight` 라벨을 맞춘다. 쓰지 않는다면 legacy는 문서상 보존 경로로 두고 WSL 정본만 유지한다.
