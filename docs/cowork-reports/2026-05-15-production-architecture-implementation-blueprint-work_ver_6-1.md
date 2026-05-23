# Codex 작업 리포트 work_ver_6-1: Slice 2b live storage 원장 구현

## 1. 작업 맥락

- 기준 작업본: `work_ver_6`
- 새 cowork 리뷰 없음. 같은 라운드의 자율 후속 작업이므로 `work_ver_6-1`로 기록한다.
- 범위: 실전 주문 전송 없이 storage contract/schema/writer/test만 추가.
- 운영 DB `runtime-data/dev.db`에 migration apply는 실행하지 않았다.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.

## 2. 구현 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| live 체결 원장 | `live_orders`, `live_order_events`만 있음 | `LiveFill` dataclass와 `live_fills` table/index/write 메서드 추가 | 향후 `live_execution_sync`가 broker fill delta를 기록할 저장소 | 실제 KIS fill field 매핑은 아직 확인 필요 |
| live 포지션 원장 | 실전 포지션 저장 테이블 없음 | `LivePosition`, `LivePortfolioSnapshot`와 table/index/write 메서드 추가 | 실전 계좌 snapshot, T+2/주문가능금액 reconcile 준비 | KIS 계좌 응답과 내부 계산식 차이는 후속 sync에서 검증 필요 |
| live 감사 원장 | 주문 trace용 audit table 없음 | `LiveAuditEvent`, `ops_live_audit_events`, `event_hash UNIQUE` 추가 | prediction/signal/gate/order/fill 추적 기반 | hash chain 생성 함수는 아직 없음. 현재는 저장 contract만 있음 |
| phase 승인 원장 | 승인 상태가 bool 후보로만 남아 있음 | `LivePhaseApproval`, `live_phase_approvals`, `approval_hash UNIQUE` 추가 | Phase 1/2 승인 기록과 한도 snapshot 저장 준비 | 승인 CLI/UI는 아직 없음 |
| readiness 원장 | Phase 통과 기준 자동 기록 없음 | `LiveReadinessRun`, `live_readiness_runs` 추가 | token refresh, WS recovery, account snapshot, DB readiness 기록 준비 | fault injection runner와 dashboard 연결은 후속 |
| migration smoke | Slice 2a 세 테이블만 sample write | Slice 2b 여섯 테이블까지 sample insert/read/delete 확장 | `apply_storage_migration.sh --apply` 안전 검증 강화 | smoke가 더 엄격해져 schema 누락을 빨리 차단 |

## 3. 추가/수정 파일

- `app/storage/contracts.py`
  - `LiveFill`
  - `LivePosition`
  - `LivePortfolioSnapshot`
  - `LiveAuditEvent`
  - `LivePhaseApproval`
  - `LiveReadinessRun`
- `app/storage/sqlite_store.py`
  - `live_fills`
  - `live_positions`
  - `live_portfolio_snapshots`
  - `ops_live_audit_events`
  - `live_phase_approvals`
  - `live_readiness_runs`
  - 관련 index와 insert/upsert 메서드
- `app/storage/runtime_writer.py`
  - live fill/position/portfolio/audit/approval/readiness JSONL + SQLite fan-out writer
- `scripts/script_dispatch.sh`
  - storage migration `REQUIRED_TABLES`, `REQUIRED_INDEXES`, sample smoke 확장
- `tests/test_live_storage.py`
  - dataclass 검증, schema-contract field 정합성, writer fan-out, audit hash unique 테스트
- `tests/test_storage_migration_apply_script.py`
  - Slice 2b smoke row cleanup 검증
- `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`
  - Slice 2b 구현 상태 반영

## 4. 검증

- `python -m unittest tests.test_live_storage tests.test_storage_migration_apply_script tests.test_storage_migration_dry_run_script tests.test_sqlite_store`
  - 결과: 통과, 21개
- `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh`
  - 결과: 통과
- `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: 통과, 155개

## 5. 남은 위험

- `LiveAuditEvent`는 `event_hash`를 저장하고 unique 제약을 둔다. 하지만 hash chain을 계산하고 previous_hash를 이어 붙이는 서비스는 아직 없다.
- `LivePhaseApproval`은 승인 snapshot 저장소만 추가했다. 승인 CLI/UI, expiry 조회, active approval 선택 로직은 아직 없다.
- `LiveReadinessRun`은 readiness 결과를 저장할 수 있지만, token refresh/WS drop/account stale fault injection runner와 dashboard 연결은 아직 없다.
- `LiveFill`/`LivePosition`은 KIS 실전 체결/계좌 응답 필드와 아직 매핑되지 않았다. 응답 매핑은 `live_execution_sync`에서 별도 검증해야 한다.

## 6. 다음 권장

🟢 다음 단계 권장: 운영 DB에 바로 apply하지 말고 먼저 `scripts/run_storage_migration_dry_run.sh`와 `scripts/apply_storage_migration.sh` plan mode로 Slice 2a/2b schema 적용 가능성을 확인한다.

🟢 다음 단계 권장: 다음 코드 slice는 Phase 1 readiness를 위해 `LivePhaseApproval`/`LiveReadinessRun`을 읽고 쓰는 작은 service 또는 report builder를 먼저 만든다. 이 경로가 있어야 Phase 1/2 통과 기준을 사람 수동 메모가 아니라 파일/DB 기록으로 남길 수 있다.

🔴 운영자 판단 필요: approval hash chain anchor 방식은 아직 미정이다. Codex 권장안은 최초 구현에서는 local append-only DB + JSONL + NAS backup self-test를 우선 잠그고, 외부 서명/타임스탬프는 Phase 2 이후로 미루는 것이다.

## 7. cowork 확인 질문

1. Slice 2b dataclass/table 필드가 Phase 2 소액 실전 canary에 필요한 최소 원장으로 충분한지.
2. `ops_live_audit_events.event_hash UNIQUE`, `live_phase_approvals.approval_hash UNIQUE`만으로 첫 단계 회귀 잠금이 충분한지.
3. 다음 순서를 phase approval/readiness service로 가는 것이 맞는지, 아니면 `live_execution_sync`를 먼저 시작해야 하는지.
