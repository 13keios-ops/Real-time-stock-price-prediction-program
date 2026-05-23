# Codex work_ver_14: review_ver_13 P0 후속 보강

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 작업 요약

`review_ver_13`에서 권장한 P0 후속 중 코드로 바로 잠글 수 있는 두 항목을 반영했다.

- HTTP `Date` parser가 timezone 없는 값이나 알 수 없는 timezone을 조용히 허용하지 않도록 invalid 처리.
- `run_live_readiness_dry_run.sh`가 외부 sanitized `system_clock` check JSON을 `--system-clock-check-path`로 받아 fixture보다 우선 병합하도록 연결.

KIS API 신규 호출, 실전 주문, 운영 DB schema apply, runtime restart는 하지 않았다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| HTTP `Date` timezone 처리 | `email.utils.parsedate_to_datetime()`이 timezone 없는 값이나 `KST` 같은 알 수 없는 timezone을 naive datetime으로 반환하면 UTC처럼 정규화될 수 있었다. | `reference_time_from_http_date_header()`가 parsed datetime에 timezone이 없으면 `ValueError`로 차단한다. 숫자 offset처럼 parser가 인식하는 timezone은 UTC로 정규화한다. | `app/services/system_clock.py`, `tests/test_system_clock.py` | 비표준 header는 readiness가 false negative로 막힐 수 있다. 안전 측 동작이다. |
| readiness `system_clock` 자동 병합 연결 | `run_live_readiness_dry_run.sh`는 fixture 파일 안의 `system_clock`만 평가했다. probe가 만든 sanitized check를 별도 파일로 넣을 연결이 없었다. | `--system-clock-check-path` 옵션을 추가했다. 이 파일에 `key=system_clock` check 또는 `{system_clock: {...}}` payload가 있으면 fixture의 `system_clock`보다 우선 병합한다. | `scripts/script_dispatch.sh`, `tests/test_live_readiness_dry_run_script.py` | check 파일 shape가 틀리면 readiness가 blocked 된다. 안전 측 동작이며 경로는 repo 내부로 제한된다. |
| 기준 문서/진행판 | `review_ver_13` 반영 상태가 문서에 없었다. | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`에 반영했다. | 기준 문서 | 실제 fresh KIS 조회 probe가 완료된 것처럼 보이지 않도록 남은 작업을 분리해 적었다. |

## 3. 현재 닫힌 항목과 남은 항목

닫힘:

- HTTP `Date` timezone 강건성 테스트.
- readiness dry-run이 외부 sanitized `system_clock` check를 병합하는 연결.
- `system_clock_check_path` repo 내부 경로 제한.

남음:

- fresh KIS read-only 조회 직후 sanitized `system_clock` check를 자동 생성하는 probe/caller.
- live account read-only header shape 확인.
- NAS 실제 package/복구 drill.
- WS reconnect snapshot readiness/dashboard read-only 노출.
- legacy PowerShell `overnight` 라벨 처리 방식 결정.

## 4. 검증

- `python -m unittest tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
  - 통과, 36개.
- `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과.
- `python -m py_compile app/services/system_clock.py app/services/live_phase_readiness.py tests/test_system_clock.py tests/test_live_readiness_dry_run_script.py`
  - 통과.

## 5. Cowork 리뷰 요청

다음 리뷰에서는 아래만 보면 된다.

1. timezone 없는 HTTP `Date`와 알 수 없는 timezone을 invalid로 차단하는 것이 Phase 1/2 안전 기준에 맞는지.
2. `--system-clock-check-path`로 sanitized check를 fixture보다 우선 병합하는 방식이 probe와 readiness runner 사이의 경계로 적절한지.
3. 다음 P0를 fresh KIS read-only probe/caller 구현으로 잡아도 되는지.

## 6. 다음 권장 작업

🟢 Codex 권장안:

- 다음 작업은 `scripts/probe_kis_clock_reference.py` 또는 동등 wrapper를 만들어 KIS read-only quote 조회 직후 `build_system_clock_check_from_http_date_headers()` 결과를 repo 내부 JSON으로 저장하고, `run_live_readiness_dry_run.sh --system-clock-check-path`에 연결한다.
- 실제 KIS 호출은 장외 read-only로만 수행하고, raw header 원문은 저장하지 않는다.

🔴 운영자 판단 필요:

- live account read-only header shape 확인 허용 여부.
- NAS 실제 package/복구 drill 실행 시점과 용량/경로 제한.
