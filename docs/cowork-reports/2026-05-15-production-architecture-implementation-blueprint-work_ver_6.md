# Codex 작업 리포트 work_ver_6: review_ver_5 반영 보강

## 1. 작업 맥락

- 기준 리뷰: `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_5.md`
- 작업 시각: 2026-05-15 장 종료 후
- 장 상태 확인:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=post-close`, `live_runtime_should_run=false`, watchdog 실행 중
- 금지 준수:
  - 실전 주문 API 호출 없음
  - 운영 DB `runtime-data/dev.db`에 storage migration apply 실행 없음
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음
  - 자동 commit/push 없음

## 2. review_ver_5 반영 요약

| review_ver_5 항목 | 반영 결과 | 파일 |
|---|---|---|
| `backup_database()`가 copy 기반이면 WAL 일관성 위험 | `shutil.copy2` 제거, SQLite native backup API `Connection.backup()` 사용 | `app/storage/sqlite_store.py`, `tests/test_sqlite_store.py` |
| apply wrapper에 watchdog 정지 검증 부재 | `get_runtime_watchdog_status.sh` 확인 추가. runtime watchdog이 running이면 apply 차단 | `scripts/script_dispatch.sh` |
| smoke check가 table/index 존재만 확인 | sample insert/read/delete smoke check 추가 | `scripts/script_dispatch.sh`, `tests/test_storage_migration_apply_script.py` |
| rollback도 copy 기반일 수 있음 | 실패 시 복구도 SQLite native restore 함수로 변경 | `scripts/script_dispatch.sh` |
| `READONLY_PHASES` 하드코드와 phase 오타 silent bypass | phase 정규화, known phase 검증, 미등록 phase는 `phase_unknown`으로 차단 | `app/services/live_order_guard.py`, `tests/test_live_order_guard.py` |
| kill switch 24시간 stale default 설명 부족 | `write_state()` docstring에 24시간 default 명시 | `app/services/live_kill_switch.py` |
| 기준 문서가 구현 전 표현 일부 유지 | 구현 상태와 cancel-only 의미를 갱신 | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md` |

## 3. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|
| `backup_database()`가 WAL checkpoint 뒤 DB 본 파일을 복사했다. | SQLite native backup API로 committed WAL page를 포함한 일관 snapshot을 만든다. | storage migration backup, 연구 snapshot류에서 이 메서드를 쓰는 경로 | 파일 copy보다 느릴 수 있으나 운영 DB 안전성은 증가. `tests/test_sqlite_store.py`로 회귀 잠금 |
| apply wrapper가 live runtime/dashboard만 확인했다. | runtime watchdog도 running이면 apply 차단한다. | `scripts/apply_storage_migration.sh --apply` | watchdog을 먼저 stop해야 하므로 운영 절차가 한 단계 늘어남. race condition은 감소 |
| smoke check가 schema 존재만 봤다. | `market_status_snapshots`, `live_orders`, `live_order_events`에 sample row를 쓰고 읽고 지운다. | storage migration apply | 실제 쓰기 권한/제약 오류를 더 빨리 잡음. smoke row 잔류는 테스트로 0건 확인 |
| 실패 복구가 backup file copy 후보였다. | backup DB를 source로 native restore한다. | migration 실패 rollback | target DB가 열려 있으면 restore 실패 가능성이 있으므로 service stop check가 더 중요해짐 |
| phase 문자열이 비어 있지 않으면 대부분 통과했다. | known phase 목록에 없으면 `phase_unknown`으로 차단한다. | live order guard submit/cancel/read-only preflight | 새 phase 이름을 추가할 때 guard 목록도 갱신해야 함. 오타 bypass 위험은 감소 |
| `ALLOW_LIVE_ORDERS=false`와 cancel-only 의미가 문서에 약했다. | 신규 위험 증가 submit 차단 플래그로 정의하고, 보호성 cancel-only 후보는 별도 경로로 둔다고 문서화했다. | Phase 2 live order manager 설계 | 자동 cancel과 명시 승인 cancel 분리는 아직 Slice 5에서 추가로 잠가야 함 |

## 4. 구현 세부

### 4.1 SQLite backup / restore

- `SQLiteRuntimeStore.backup_database()`:
  - `shutil.copy2` 제거
  - `source.backup(target)` 사용
  - committed WAL page 포함 일관 snapshot을 기대하는 경로로 변경
- `storage_migration_apply()`:
  - 실패 rollback에서 `restore_sqlite_backup()`을 호출
  - `restore_sqlite_backup()`도 SQLite native backup API를 역방향으로 사용

관련 문서/코드 경로: `app/storage/sqlite_store.py`, `scripts/script_dispatch.sh`, `tests/test_sqlite_store.py`, `tests/test_storage_migration_apply_script.py`

### 4.2 apply wrapper service guard

- `services_are_stopped()`가 아래 세 프로세스를 모두 확인한다.
  - `scripts/get_live_runtime_status.sh`
  - `scripts/get_dashboard_status.sh`
  - `scripts/get_runtime_watchdog_status.sh`
- watchdog이 실행 중이면 schema apply는 `blocked_services_running`으로 실패한다.
- `--skip-service-check`는 여전히 기본 운영 DB `runtime-data/dev.db`에서는 금지다.

관련 문서/코드 경로: `scripts/script_dispatch.sh`, `scripts/apply_storage_migration.sh`, `tests/test_storage_migration_apply_script.py`

### 4.3 schema smoke check

- 기존 table/index 존재 확인에 더해 sample insert/read/delete를 수행한다.
- 대상:
  - `market_status_snapshots`
  - `live_orders`
  - `live_order_events`
- smoke id는 `__storage_migration_smoke__` 고정값이고, 성공/실패 후 cleanup을 시도한다.
- 테스트에서 smoke row 잔류가 0건임을 확인한다.

관련 문서/코드 경로: `scripts/script_dispatch.sh`, `tests/test_storage_migration_apply_script.py`

### 4.4 live order guard phase 검증

- phase 문자열은 lower/strip 후 공백과 hyphen을 `_`로 정규화한다.
- 현재 known phase:
  - read-only 계열: `phase0`, `phase0_paper`, `phase1`, `phase1_readonly`, `read_only`
  - submit 후보 계열: `phase2`, `phase2_conservative`, `phase3`, `phase3_daily_limits`
- alias:
  - `phase1_read_only` -> `phase1_readonly`
  - `readonly` -> `read_only`
- 미등록 phase는 `phase_unknown`으로 차단한다.

관련 문서/코드 경로: `app/services/live_order_guard.py`, `tests/test_live_order_guard.py`

## 5. 검증

- `python -m unittest tests.test_sqlite_store tests.test_storage_migration_apply_script tests.test_live_order_guard tests.test_live_kill_switch`
  - 결과: 통과, 25개
- `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh`
  - 결과: 통과
- `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: 통과, 154개

## 6. 남은 위험과 다음 권장

🟢 다음 단계 권장: Slice 2b live fill / live position / live audit schema로 진행한다. 단, 운영 DB 적용은 `run_storage_migration_dry_run.sh`와 `apply_storage_migration.sh` plan/apply 절차를 분리해서 확인한 뒤 수행한다.

🟢 다음 단계 권장: Slice 5 live order manager에 들어가기 전에 자동 cancel과 명시 승인 cancel을 구분한다. 현재 guard는 cancel-only를 보호성 후보로 열어 둔 상태다.

🔴 운영자 판단 필요: `ALLOW_LIVE_ORDERS=false`의 운영 의미는 권장안 A로 문서화했다. 즉, 신규 위험 증가 submit은 차단하고 보호성 cancel-only는 별도 경로 후보로 둔다. 이 의미를 바꾸려면 Slice 5 전에 별도 플래그(`ALLOW_PROTECTIVE_CANCELS` 후보)를 검토해야 한다.

🔴 운영자 판단 필요: kill switch ON/OFF CLI 또는 수동 파일 편집 중 어떤 운영 절차를 1차로 쓸지 결정이 필요하다. Codex 권장안은 CLI를 만들고 수동 파일 편집은 복구용으로만 남기는 것이다.

## 7. cowork에게 확인받고 싶은 점

1. SQLite native backup/restore로 WAL/SHM 일관성 우려가 충분히 줄었는지.
2. runtime watchdog running 시 apply 차단이 운영상 과도하지 않은지.
3. sample insert/read/delete smoke check가 Slice 2a 적용 안전성 검증으로 충분한지.
4. phase known-list 방식이 Slice 5 전 임시 방어선으로 충분한지.
5. 다음 작업을 Slice 2b schema로 진행해도 되는지, 아니면 phase approval 저장소를 먼저 잠가야 하는지.
