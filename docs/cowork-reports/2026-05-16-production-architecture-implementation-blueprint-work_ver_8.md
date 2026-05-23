# Codex 작업 리포트 work_ver_8: review_ver_7 반영 database smoke 분리

## 1. 작업 맥락

- 기준 리뷰: `2026-05-16-production-architecture-implementation-blueprint-review_ver_7.md`
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-5.md`
- cowork 권고 중 즉시 반영한 항목: `database` check를 SQLite read-only smoke로 분리, `storage_migration_state`와 의미 분리, 새 3개 readiness check의 SQL column 정책 명시
- 작업 시각: 2026-05-16 17시대, `weekend`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| `database` check 의미 | `storage_migration_state == ok`에서 함께 추론 | SQLite read-only smoke(`SELECT 1`, `sqlite_master`, `schema_version`, `journal_mode`) 결과로 별도 판단 | `app/services/codex_ops.py`, `scripts/script_dispatch.sh`, tests | DB 파일 접근 실패 시 premarket report가 blocked 또는 warning이 될 수 있음 |
| `storage_migration_state` 의미 | database와 사실상 같은 값 | migration plan/apply 상태만 담당 | premarket report, live readiness adapter | 의미 분리로 기존 fixture/report에 `database` check가 없으면 readiness가 더 보수적으로 blocked |
| SQL column 정책 | 새 3개 check가 JSON only인 이유가 명시되지 않음 | 기존 6개만 전용 SQL column, 새 check는 `checks_json` 보관. 컬럼 승격은 별도 schema migration 결정 | `app/services/live_phase_readiness.py`, blueprint | SQL filter가 필요한 후속 기능은 별도 migration 필요 |

## 3. 구현 세부

갱신 파일:

- `app/services/codex_ops.py`
- `app/services/live_phase_readiness.py`
- `scripts/script_dispatch.sh`
- `tests/test_codex_ops.py`
- `tests/test_codex_ops_job_script.py`
- `tests/test_live_phase_readiness.py`
- `tests/test_live_readiness_dry_run_script.py`
- `AGENTS.md`
- `README.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`

주요 정책:

- `run_codex_ops_job.sh --job-type premarket-readiness`는 기본 DB 경로 `runtime-data/dev.db`를 read-only URI(`mode=ro`)로 연다.
- read-only smoke는 `SELECT 1`, `sqlite_master` table 존재 확인, `PRAGMA schema_version`, `PRAGMA journal_mode`만 수행한다.
- 초기 구현에서 `PRAGMA quick_check`를 시도했지만 실제 `runtime-data/dev.db`에서 60초 timeout 위험이 확인되어 제거했다.
- `create_readiness_run_from_premarket_report()`는 `database` check를 premarket report의 `database` 상태에서 가져오며, `storage_migration_state`와 분리한다.
- `disk_space`, `dashboard`, `storage_migration_state`는 현재 `checks_json`에만 저장하고, SQL column 승격은 후속 schema migration 결정으로 남긴다.

## 4. 실행 산출물

- `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`
  - 생성/갱신: `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
  - 결과: `status=ok`, `database=status ok`, blockers/warnings 없음
- `./scripts/run_live_readiness_dry_run.sh`
  - 생성/갱신: `runtime-data/reports/live-readiness/latest-readiness.json`
  - fixture 없음 기준: `status=blocked`, 9개 check 모두 `not_verified`

## 5. 검증

- `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
  - 통과, 33개
- `bash -n scripts/script_dispatch.sh scripts/run_codex_ops_job.sh`
  - 통과
- `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_dashboard`
  - 통과, 47개
- `python -m app --build-dashboard`
  - 통과
  - 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`
- `python -m unittest discover -s tests -p "test_*.py"`
  - 통과, 188개
- `git diff --check`
  - 통과
  - 참고: `docs/logbook.md`의 CRLF/LF 정규화 경고만 표시됨
- `git diff -- app/risk VERSION config`
  - 출력 없음

## 6. 안전 확인

- SQLite smoke는 read-only 연결만 수행
- 운영 DB insert 없음
- 운영 DB schema apply 없음
- 실제 장애 주입 없음
- Codex CLI 실제 호출 없음
- KIS live 주문 API 호출 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 7. 다음 권장

🟢 다음 단계 권장: `--record` 호출 주체와 시점을 runbook에 더 구체적으로 묶는다. 권장안은 Phase 1 전환 전까지 수동 실행만 허용하고, 운영 DB schema apply 완료 후 장전 readiness 절차에서만 실행하는 것이다.

🟢 다음 단계 권장: Slice 5 live order manager 진입 전, `LiveReadinessRun`의 새 3개 check를 SQL column으로 승격할지 확정한다. Codex 권장안은 당장은 JSON only를 유지하고, dashboard/리포트에서 SQL filter가 필요해지는 시점에 migration으로 승격하는 것이다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: `--record`를 운영 DB 대상으로 자동화할 시점. Codex 권장안은 Phase 1 read-only 관측 기간 동안은 수동만 허용이다.

## 8. cowork 확인 질문

1. `database` smoke를 `PRAGMA quick_check` 없이 가벼운 read-only 연결성 확인으로 낮춘 판단이 장중 안전 기준에 맞는지.
2. 새 3개 check를 당분간 `checks_json`에만 두고 SQL column 승격을 후속 결정으로 남기는 권장안에 이견이 없는지.
3. 다음 작업을 Slice 5 live order manager로 넘어가도 되는지, 아니면 `--record` runbook을 먼저 더 잠가야 하는지.
