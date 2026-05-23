# Codex 작업 리포트 work_ver_7-4: live readiness 9개 check 확장

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-3.md`
- 새 cowork review 없음. 따라서 명명 규칙에 따라 `work_ver_7-4`로 기록한다.
- 작업 시각: 2026-05-16 02시대, `weekend`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| readiness check key | `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `kill_switch`, `database` 6개 중심 | `disk_space`, `dashboard`, `storage_migration_state`를 추가해 9개 check로 확장 | `app/services/live_phase_readiness.py`, script fixture, dashboard 표시 | 기존 6개 fixture만 넣으면 dry-run이 `blocked`로 남음 |
| premarket adapter | disk/storage는 `database`에 묶여 있었고 dashboard는 live readiness 판단에 직접 나오지 않았다. | premarket report가 확인한 `disk_space`, `dashboard`, `storage_migration_state`를 별도 check로 기록한다. | readiness JSON, dashboard payload | premarket report의 해당 check가 없으면 차단 사유가 더 늘어남 |
| dashboard 카드 | token/WS/account/market/kill/database만 표시 | disk space, dashboard, storage migration도 표시 | `app/services/dashboard.py`, `tests/test_dashboard.py` | 카드 행 증가 외 동작 영향 없음 |

## 3. 구현 세부

갱신 파일:

- `app/services/live_phase_readiness.py`
- `app/services/dashboard.py`
- `tests/test_live_phase_readiness.py`
- `tests/test_live_readiness_dry_run_script.py`
- `tests/test_dashboard.py`
- `AGENTS.md`
- `README.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`

현재 live readiness dry-run check key:

- `token_refresh`
- `ws_recovery`
- `account_snapshot`
- `market_status`
- `kill_switch`
- `database`
- `disk_space`
- `dashboard`
- `storage_migration_state`

보수 정책:

- `build_fault_injection_dry_run_report()`는 9개 check 모두 fixture에서 `ok/passed/healthy/ready` 또는 `true`로 명시되어야 통과한다.
- fixture가 없으면 `not_verified`이며 readiness는 `blocked`다.
- `create_readiness_run_from_premarket_report()`는 premarket report에서 확인 가능한 token/dashboard/disk/storage/database 상태를 반영하지만, WebSocket 복구/계좌 snapshot/market status/kill switch는 계속 별도 override가 있어야 통과한다.
- 운영 DB insert는 여전히 하지 않는다. dry-run JSON만 생성한다.

## 4. 실행 산출물

- `./scripts/run_live_readiness_dry_run.sh`
  - 생성/갱신: `runtime-data/reports/live-readiness/latest-readiness.json`
  - fixture를 주지 않았으므로 결과는 `status=blocked`
  - 9개 check 모두 `not_verified`

## 5. 검증

- `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_dashboard`
  - 통과, 26개

## 6. 안전 확인

- 실제 장애 주입 없음
- Codex CLI 실제 호출 없음
- 운영 DB insert 없음
- 운영 DB schema apply 없음
- KIS live 주문 API 호출 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 7. 다음 권장

🟢 다음 단계 권장: `run_live_readiness_dry_run.sh`는 계속 JSON only로 유지하고, readiness DB 저장은 별도 명시 옵션으로 분리한다. 권장안은 `--record` 옵션을 새로 설계하되 기본값은 `false`다.

🟢 다음 단계 권장: 운영 DB 적용 전에는 `run_storage_migration_dry_run.sh`와 `apply_storage_migration.sh` plan 결과를 dashboard 또는 premarket report에 같이 노출한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 없음. 이번 작업은 dry-run check 확장과 표시 보강만 수행했다.

## 8. cowork 확인 질문

1. Phase 1 readiness의 필수 check를 9개로 확장한 판단이 보수적 기준에 맞는지.
2. `database`와 `storage_migration_state`를 둘 다 남긴 것이 중복이지만 운영자가 보기 쉬운지, 또는 `database`를 SQLite 연결성으로 더 좁히는 후속 분리가 필요한지.
3. readiness DB 저장을 기본 동작에서 제외하고 별도 명시 옵션으로 유지하는 권장안에 이견이 없는지.
