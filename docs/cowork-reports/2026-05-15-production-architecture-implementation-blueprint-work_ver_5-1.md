# production architecture implementation blueprint work_ver_5-1

작성자: Codex
기준 리뷰: 새 `review_ver_5` 없음. `work_ver_5` 이후 Codex 자율 후속 작업.
작성일: 2026-05-15

## 1. 시작 전 확인

- 장 상태 확인: `./scripts/get_live_runtime_status.sh` 기준 `session_status=post-close`, live runtime `stopped`.
- watchdog 확인: `./scripts/get_runtime_watchdog_status.sh` 기준 `market_session_status=post-close`, `live_runtime_should_run=false`.
- 최신 cowork 리뷰: `review_ver_4`가 최신이며, `review_ver_5`는 아직 없음.
- 작업 경계: 운영 DB apply 실행 없음, KIS live 주문 호출 없음, `ALLOW_LIVE_ORDERS` 변경 없음, `app/risk/` 변경 없음, `VERSION` 변경 없음.

## 2. 이번 반영 범위

`work_ver_5`에서 다음 권장 단계로 남긴 운영 DB 적용 wrapper를 보강했습니다. 이 작업은 Slice 2b schema 자체가 아니라, Slice 2b처럼 운영 DB에 schema를 적용해야 하는 작업이 들어오기 전에 적용/백업/롤백 절차를 먼저 잠그는 안전 장치입니다.

## 3. 변경 파일

- `scripts/apply_storage_migration.sh`
  - 새 wrapper. 기본은 plan mode라 DB를 변경하지 않습니다.
  - `--apply`가 있을 때만 실제 schema 초기화를 수행합니다.
- `scripts/script_dispatch.sh`
  - `storage_migration_apply()` dispatch 함수 추가.
  - 서비스 상태 확인, backup, schema 적용, smoke query, 실패 시 backup restore를 포함합니다.
- `tests/test_storage_migration_apply_script.py`
  - plan mode가 DB를 바꾸지 않는지 검증.
  - `.tmp-tests` 안의 임시 기존 DB에 apply하면 sentinel table이 유지되고 live table/index가 생기며 backup이 생성되는지 검증.
  - 저장소 밖 DB 경로를 거부하는지 검증.
  - 기본 `runtime-data/dev.db`에는 `--skip-service-check`가 거부되는지 검증.
- `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`, `docs/cowork-reports/README.md`
  - apply wrapper 구현 상태와 다음 권장 순서 반영.

## 4. wrapper 정책

기본 명령은 plan mode입니다.

```bash
./scripts/apply_storage_migration.sh
```

실제 적용은 명시 플래그가 필요합니다.

```bash
./scripts/apply_storage_migration.sh --apply
```

안전 규칙:

- `runtime-data/dev.db`에 대해서는 `--skip-service-check`를 허용하지 않습니다.
- 실제 apply 전에 live runtime과 dashboard가 실행 중이면 block합니다.
- apply 전 backup을 만들고, smoke query 실패 또는 예외 발생 시 backup에서 복구합니다.
- 필수 smoke 대상은 `market_status_snapshots`, `live_orders`, `live_order_events`와 관련 index입니다.

## 5. Codex 판단

이제 Slice 2b로 들어갈 최소 안전 발판은 마련됐습니다. 다만 이 wrapper는 현재 Slice 2a live table/index를 기준으로 smoke check를 합니다. Slice 2b에서 `live_fills`, `live_positions`, `ops_live_audit_events` 등이 추가되면 wrapper의 필수 table/index 목록도 함께 늘려야 합니다.

권장 다음 순서:

1. Slice 2b live fill/position/audit schema와 storage contract 구현.
2. `apply_storage_migration.sh` smoke 대상에 Slice 2b table/index 추가.
3. audit hash chain 또는 phase approval 저장 구조 중 하나를 다음 작은 slice로 분리.

## 6. 현재 남은 위험

- 실제 운영 DB에 apply는 실행하지 않았습니다.
- dashboard 상태 확인은 wrapper 내부에서 실행하지만, watchdog 자체는 stop 조건으로 보지 않습니다.
- Slice 2b table/index는 아직 없습니다.
- wrapper의 rollback은 DB 파일 복구 중심이며 WAL/SHM 고급 복구 정책은 별도 검토가 필요합니다.

## 7. 검증 결과

- `python -m unittest tests.test_storage_migration_apply_script tests.test_storage_migration_dry_run_script`: 통과, 6개.
- `bash -n scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh scripts/script_dispatch.sh`: 통과.
- `python -m unittest tests.test_storage_migration_apply_script tests.test_storage_migration_dry_run_script tests.test_live_kill_switch tests.test_live_order_guard`: 통과, 17개.
- `python -m unittest discover -s tests -p "test_*.py"`: 통과, 152개.
- `git diff --check`: 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됨.
- `git diff -- app/risk VERSION config`: 출력 없음.
