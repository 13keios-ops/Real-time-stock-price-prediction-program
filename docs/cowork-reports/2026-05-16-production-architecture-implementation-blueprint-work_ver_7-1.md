# Codex 작업 리포트 work_ver_7-1: premarket-readiness dry-run wrapper 구현

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- 직전 작업본: `2026-05-15-production-architecture-implementation-blueprint-work_ver_7.md`
- 새 cowork review 없음. 따라서 명명 규칙에 따라 `work_ver_7-1`로 기록한다.
- 작업 시각: 2026-05-16 00시대, `weekend`
- 시작 상태:
  - `get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`
  - `get_runtime_watchdog_status.sh`: watchdog running, `market_session_status=weekend`, `live_runtime_should_run=false`

## 2. 반영 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| premarket readiness | manifest만 있고 report schema가 없었다. | `build_premarket_readiness_report()`가 live runtime, watchdog, dashboard, KIS credential, storage migration state, disk, manifest policy를 JSON schema로 만든다. | `app/services/codex_ops.py`, tests | check 기준이 과하면 warning/block가 자주 뜰 수 있음 |
| Codex ops wrapper | wrapper가 없었다. | `scripts/run_codex_ops_job.sh --job-type premarket-readiness` dry-run 전용 wrapper를 추가했다. Codex CLI는 호출하지 않는다. | `scripts/`, `runtime-data/reports/codex/ops/premarket-readiness/` | report path 제한이 과하면 임의 위치 출력이 막힘 |
| storage migration dry-run | old Slice 2a table/index 일부만 확인했다. | Slice 2b 전체 live 원장 table/index 기준으로 확장했다. | `scripts/script_dispatch.sh`, `tests/test_storage_migration_dry_run_script.py` | schema 누락을 더 엄격히 잡아 기존 임시 DB 검증이 실패할 수 있음 |
| readiness record adapter | premarket report와 `LiveReadinessRun`이 분리되어 있었다. | `create_readiness_run_from_premarket_report()`를 추가했다. report만으로는 통과시키지 않고 fault injection/상태 override가 있어야 통과한다. | `app/services/live_phase_readiness.py`, tests | override 의미가 느슨하면 readiness 통과가 과대평가될 수 있음 |

## 3. 구현 세부

신규/갱신 파일:

- `app/services/codex_ops.py`
- `scripts/run_codex_ops_job.sh`
- `scripts/script_dispatch.sh`
- `tests/test_codex_ops.py`
- `tests/test_codex_ops_job_script.py`
- `tests/test_storage_migration_dry_run_script.py`
- `app/services/live_phase_readiness.py`
- `tests/test_live_phase_readiness.py`

`premarket-readiness` check key:

- `live_runtime`
- `runtime_watchdog`
- `dashboard`
- `kis_credentials`
- `storage_migration_state`
- `disk_space`
- `manifest_policy`

wrapper 정책:

- dry-run only
- Codex CLI 호출 없음
- report path는 `runtime-data/reports/codex/ops/premarket-readiness/` 하위만 허용
- `--execute`, `--apply`는 즉시 거부
- fixture status path를 받을 수 있어 테스트와 운영 리포트 생성을 분리 가능

## 4. 실행 결과

- `./scripts/apply_storage_migration.sh`
  - plan 모드
  - `status=planned`
  - `apply=false`
  - 운영 DB 변경 없음
- `./scripts/run_storage_migration_dry_run.sh`
  - 임시 DB 대상
  - `status=ok`
- `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`
  - report: `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
  - `status=ok`
  - blockers/warnings 없음

## 5. 검증

- `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script`
  - 통과, 16개
- `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script tests.test_storage_migration_dry_run_script tests.test_storage_migration_apply_script`
  - 통과, 22개
- `python -m unittest tests.test_live_phase_readiness tests.test_codex_ops tests.test_codex_ops_job_script`
  - 통과, 22개
- `python -m unittest tests.test_live_phase_readiness tests.test_codex_ops tests.test_codex_ops_job_script tests.test_storage_migration_dry_run_script tests.test_storage_migration_apply_script`
  - 통과, 28개
- `python -m unittest discover -s tests -p "test_*.py"`
  - 통과, 177개
- `bash -n scripts/script_dispatch.sh scripts/run_codex_ops_job.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh`
  - 통과
- `git diff --check`
  - 통과
  - 참고: `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
- `git diff -- app/risk VERSION config`
  - 출력 없음

## 6. 안전 확인

- Codex CLI 실제 호출 없음
- KIS live 주문 API 호출 없음
- 운영 DB schema apply 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 7. 남은 위험과 다음 권장

✅ 반영 완료: `premarket-readiness` report를 `LiveReadinessRun`으로 변환하는 작은 adapter를 만들었다. 단, fault injection 또는 별도 상태 점검 override 없이 readiness를 통과시키지 않는다.

🟢 다음 단계 권장: fault injection runner는 실제 장애를 만들기보다 fixture 기반 dry-run으로 시작한다. 첫 대상은 token refresh, WebSocket recovery, account snapshot stale, storage migration state 확인이다.

🟢 다음 단계 권장: `run_storage_migration_dry_run.sh`는 Slice 2b 전체 table/index를 보게 됐지만 sample insert/read/delete smoke는 apply wrapper에만 있다. dry-run에도 lightweight sample smoke를 넣을지 다음 라운드에서 검토한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 없음. 이번 작업은 dry-run report와 테스트만 추가했다.

## 8. cowork 확인 질문

1. `premarket-readiness` check key 7개가 Phase 1 장전 자동 점검의 최소 단위로 충분한지.
2. disk free threshold 후보인 warning 10GB, block 5GB가 이 저장소 산출물 규모에 맞는지.
3. storage migration state가 `planned`여도 readiness `ok`로 보는 정책이 적절한지. Codex 권장안은 `planned + apply=false`는 ok, `failed/blocked`는 warning 이상이다.
4. 다음 구현을 readiness record adapter로 갈지, dashboard 카드 노출로 갈지. Codex 권장안은 record adapter 먼저다.
