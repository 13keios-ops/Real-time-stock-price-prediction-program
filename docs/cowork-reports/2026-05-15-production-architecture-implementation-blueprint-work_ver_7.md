# Codex 작업 리포트 work_ver_7: review_ver_6 반영과 codex_ops manifest 0번 슬라이스

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- 기준 작업본: `work_ver_6-3`
- 작업 시각: 2026-05-15 장 종료 후
- 장 상태:
  - `get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`
  - `get_runtime_watchdog_status.sh`: watchdog running, `market_session_status=post-close`, `live_runtime_should_run=false`
- 범위:
  - Codex CLI를 실제 호출하지 않는다.
  - `scripts/run_codex_ops_job.sh` wrapper는 만들지 않는다.
  - 먼저 job manifest와 장 상태별 권한 모델을 순수 함수와 테스트로 잠근다.

## 2. review_ver_6 반영 요약

| review_ver_6 권고 | 반영 결과 | 파일 |
|---|---|---|
| 0번 슬라이스로 `codex_ops.py` manifest 구현 | job manifest, action enum, protected session 판정, backup/cleanup 정책 구현 | `app/services/codex_ops.py` |
| 격리를 정책이 아니라 코드로 강제 | job별 allowed action과 always-blocked action을 판정하는 `evaluate_action()` 추가 | `app/services/codex_ops.py`, `tests/test_codex_ops.py` |
| 운영 DB schema apply 자동 금지 | `run_storage_migration_apply`는 `action_requires_operator_approval`로 차단 | `app/services/codex_ops.py` |
| 장중 patch 초안 적용 금지 | `create_patch_draft`는 `.tmp-tests/codex-ops/`만 허용, root 적용은 항상 차단 | `app/services/codex_ops.py` |
| `.tmp-tests/codex-ops/` cleanup 보호 | `is_cleanup_protected_path()`와 문서 규칙 추가 | `app/services/codex_ops.py`, `AGENTS.md`, `README.md` |
| report/patch backup 정책 | job report는 backup include, patch draft는 exclude로 판정 | `app/services/codex_ops.py`, `tests/test_codex_ops.py` |
| sub-action별 권한 모델 | full test, app report, snapshot research, migration plan/apply, restart를 개별 action으로 분리 | `app/services/codex_ops.py` |

## 3. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|
| Codex CLI 운영 자동화가 설계 문구에만 있었다. | `CodexOpsManifest`와 `evaluate_action()`이 job/action/session별 허용 여부를 판정한다. | 향후 `scripts/run_codex_ops_job.sh` wrapper | manifest가 과하게 보수적이면 운영 보조 job이 자주 차단될 수 있음 |
| 장중 patch 초안 위치가 제안만 있었다. | `.tmp-tests/codex-ops/`만 patch draft 경로로 허용하고 cleanup 보호 대상으로 판정한다. | 장중 incident triage | patch 초안은 backup exclude라 장기 보존은 별도 승인 필요 |
| 운영 DB apply 자동 금지가 문서에만 있었다. | `run_storage_migration_apply` action은 항상 operator approval 필요로 차단한다. | storage migration 운영 절차 | 자동 apply는 불가능해져 운영자 명시 절차가 필요 |
| runtime restart/full test/python app 실행 금지가 일률 표현이었다. | action을 세분화해 protected session에서 heavy action을 차단하고 post-close research에서만 일부 허용한다. | Codex ops job runner | 새 action 추가 시 manifest/test 갱신 필요 |

## 4. 구현 세부

### 4.1 Job manifest

현재 job:

- `premarket-readiness`
- `postclose-research`
- `intraday-incident-triage`
- `postclose-maintenance-review`
- `cowork-handoff`

관련 문서/코드 경로: `app/services/codex_ops.py`, `tests/test_codex_ops.py`

### 4.2 장중 보호 판정

`CodexOpsContext` 기준:

- `session_status`가 `pre-open`, `regular`, `regular-session` 계열이면 protected session
- `live_runtime_should_run=true`이면 protected session
- `live_runtime_running=true`이면 protected session

protected session에서 자동 차단되는 대표 action:

- `run_full_test`
- `run_snapshot_research`
- `run_python_app_readonly_report`
- `run_storage_migration_apply`
- `apply_patch_to_root`
- `restart_dashboard`
- `restart_live_runtime`
- `change_live_flag`
- `change_gate_threshold`
- `send_live_order`

관련 문서/코드 경로: `app/services/codex_ops.py`, `AGENTS.md`

### 4.3 경로 정책

- job report root: `runtime-data/reports/codex/ops/{job_type}/`
- incident patch draft root: `.tmp-tests/codex-ops/`
- cowork handoff report: `docs/cowork-reports/`

`backup_policy_for_job()` 기본값:

- report는 backup include
- patch draft는 backup exclude

관련 문서/코드 경로: `app/services/codex_ops.py`, `README.md`, `AGENTS.md`

## 5. 검증

- `python -m unittest tests.test_codex_ops`
  - 결과: 통과, 10개
- `python -m unittest tests.test_live_phase_readiness tests.test_live_order_guard`
  - 결과: 통과, 10개
- `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: 통과, 168개
- `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh`
  - 결과: 통과
- `git diff --check`
  - 결과: 통과
  - 참고: `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.

최종 상태:

- `get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`
- `get_runtime_watchdog_status.sh`: watchdog running, `market_session_status=weekend`, `live_runtime_should_run=false`

## 6. 남은 위험

- 실제 Codex CLI wrapper는 아직 없다. 따라서 이 단계는 실행 자동화가 아니라 권한 모델 기반이다.
- `READINESS_CHECK_KEYS` 확장은 아직 하지 않았다. review_ver_6의 후보(`disk_space`, `dashboard`, `storage_migration_state`)는 premarket-readiness runner 구현 전 검토한다.
- `.tmp-tests/codex-ops/` cleanup 보호는 문서와 순수 함수로 반영했지만, 실제 cleanup 스크립트가 생기면 skip 로직을 코드로 한 번 더 잠가야 한다.
- NAS backup export self-test는 아직 없다. report include/patch exclude 정책은 manifest 수준이다.

## 7. 다음 권장

🟢 다음 단계 권장: `scripts/run_codex_ops_job.sh`를 바로 만들기 전에, premarket-readiness runner가 읽을 입력 파일 목록과 report schema를 먼저 정의한다.

🟢 다음 단계 권장: `tests/test_codex_ops.py`에 wrapper dry-run contract를 추가한 뒤 `scripts/run_codex_ops_job.sh`를 plan/dry-run only로 구현한다.

🟢 다음 단계 권장: `READINESS_CHECK_KEYS`에 `disk_space`, `dashboard`, `storage_migration_state`를 넣을지 premarket-readiness runner 전에 결정한다. Codex 권장안은 premarket runner에는 추가하고 기존 `LiveReadinessRun` storage field에는 `checks_json`으로 우선 수용하는 것이다.

🔴 운영자 판단 필요: Codex ops patch draft를 backup에서 제외하는 정책을 확정할지. Codex 권장안은 report는 backup include, patch draft는 backup exclude다.

## 8. cowork 확인 질문

1. `evaluate_action()` 중심의 manifest 구조가 wrapper 구현 전 0번 슬라이스로 충분한지.
2. `NEVER_AUTOMATED_ACTIONS` 목록이 운영 안전 관점에서 충분한지.
3. protected session에서 `run_storage_migration_plan`과 `run_isolated_unit_test`를 허용한 것이 과하지 않은지.
4. report backup include / patch draft backup exclude 정책이 적절한지.
5. 다음 단계가 premarket-readiness report schema 정의인지, 아니면 wrapper dry-run 구현인지.
