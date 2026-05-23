# Codex 작업 리포트 work_ver_6-2: phase approval/readiness record service

## 1. 작업 맥락

- 기준 작업본: `work_ver_6-1`
- 새 cowork 리뷰 없음. 같은 라운드의 자율 후속 작업이므로 `work_ver_6-2`로 기록한다.
- 범위: Phase 1/2 승인과 readiness 결과를 hash record로 생성하고 저장소에서 active approval을 조회하는 작은 service.
- 실전 주문 API 호출 없음. 운영 DB apply 없음.

## 2. 구현 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| phase approval | `LivePhaseApproval` 저장 contract만 있음 | `create_phase_approval()`이 approval payload를 만들고 SHA-256 `approval_hash`를 계산 | Phase 1/2 승인 기록 생성 | 외부 서명/anchor는 아직 없음 |
| readiness run | `LiveReadinessRun` 저장 contract만 있음 | `create_readiness_run()`이 필수 check key와 blocking reason을 받아 passed/status/hash를 계산 | Phase 1 readiness 기록 생성 | fault injection 실행 자체는 후속 |
| active approval 조회 | insert만 있고 조회 helper 없음 | `fetch_active_live_phase_approvals()` 추가 | guard/manager가 승인 상태를 읽을 기반 | timezone/날짜 정책은 후속 운영 runner에서 더 검증 필요 |

## 3. 추가/수정 파일

- `app/services/live_phase_readiness.py`
  - `create_phase_approval()`
  - `create_readiness_run()`
  - `READINESS_CHECK_KEYS`
- `app/storage/sqlite_store.py`
  - `fetch_active_live_phase_approvals()`
- `tests/test_live_phase_readiness.py`
  - approval hash 안정성
  - active/expired approval 조회
  - readiness blocked 상태
  - 필수 readiness check key 검증
- `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`
  - 구현 상태 반영

## 4. 검증

- `python -m unittest tests.test_live_phase_readiness tests.test_live_storage tests.test_storage_migration_apply_script`
  - 결과: 통과, 13개
- `python -m unittest tests.test_live_order_guard tests.test_live_kill_switch tests.test_market_status`
  - 결과: 통과, 20개
- `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh`
  - 결과: 통과
- `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: 통과, 158개

## 5. 남은 위험

- approval/readiness record 생성만 구현됐다. 실제 장전 fault injection runner, dashboard card, CLI/UI는 아직 없다.
- hash는 local payload hash다. append-only chain anchor나 외부 timestamp는 아직 없다.
- active approval 조회는 `phase`, `trading_day`, `approved_at <= as_of <= expires_at` 기준이다. 월요일 장전/휴장/시차 정책은 runner에서 더 잠가야 한다.

## 6. 다음 권장

🟢 다음 단계 권장: `live_phase_readiness.py`를 사용하는 장전 readiness runner를 추가한다. 첫 버전은 실제 KIS fault injection을 실행하지 말고, 기존 상태 파일과 storage 상태를 읽어 readiness record/report를 만드는 dry-run으로 시작하는 것이 안전하다.

🟢 다음 단계 권장: 운영 DB apply 전에는 `scripts/run_storage_migration_dry_run.sh`와 `scripts/apply_storage_migration.sh` plan mode 결과를 먼저 확인한다.

🔴 운영자 판단 필요: approval hash를 외부에 anchor할지 여부. Codex 권장안은 Phase 1/2 초기에는 local DB + JSONL + NAS backup self-test로 시작하고, 외부 서명/타임스탬프는 Phase 2 안정화 후 검토하는 것이다.

## 7. cowork 확인 질문

1. approval/readiness service를 order manager보다 먼저 둔 순서가 맞는지.
2. `READINESS_CHECK_KEYS` 6개가 Phase 1 read-only 진입 전 최소 항목으로 충분한지.
3. active approval 조회 조건에 `phase`, `trading_day`, `approved_at/expires_at` 외에 scope나 max limit 검증을 이 단계에서 함께 넣어야 하는지.
