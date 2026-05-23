# Codex work_ver_11-1: audit hash chain helper + runtime report integrity

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_11-1`
- 기준 작업본: `2026-05-17-production-architecture-implementation-blueprint-work_ver_11.md`
- 새 cowork review 없이 진행한 Codex 추가 작업이다.

## 시작 전 상태

- `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
- `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`.
- 실전 주문 API 호출 없음. KIS live 조회 호출 없음.

## 작업 이유

review_ver_10에서 남은 운영 안전 축 중 `audit hash chain anchor`가 계속 운영자 결정 항목으로 남아 있었다. 외부 anchor와 보관 기간은 계좌 소유자/실전 운용 승인권자 결정이 필요하지만, 내부 append-only hash chain 생성/검증 helper는 독립적으로 구현할 수 있어 먼저 진행했다.

## 코드 변경

- 추가: `app/services/live_audit.py`
  - `GENESIS_HASH`
  - `LiveAuditLog.append()`
  - `LiveAuditLog.latest_hash()`
  - `LiveAuditLog.verify()`
  - `build_live_audit_event()`
  - `compute_live_audit_hash()`
  - `verify_live_audit_chain()`
- 변경: `app/storage/sqlite_store.py`
  - `fetch_live_audit_events(trading_day=None)` 추가.
  - `ops_live_audit_events`를 `event_time ASC, audit_event_id ASC` 순서로 읽어 chain 검증에 쓴다.
- 변경: `app/services/reporting.py`
  - runtime report에 `Live Audit Integrity` 절 추가.
  - `summary.live_audit_integrity_issues`, `report_payload.live_audit_integrity` 추가.
- 추가: `tests/test_live_audit.py`
  - append 시 첫 event는 `GENESIS_HASH`, 두 번째 event는 첫 event hash를 `previous_hash`로 참조하는지 검증.
  - JSONL과 SQLite 동시 기록 검증.
  - payload tamper와 previous_hash gap을 검출하는지 검증.
  - sqlite store 없이 append하면 실패하는지 검증.
- 변경: `tests/test_reporting.py`
  - runtime report가 audit integrity summary를 JSON/Markdown에 표시하는지 검증.

## 현재 경계

- 구현 완료:
  - 내부 hash chain event 생성.
  - SQLite/JSONL 기록.
  - 거래일 기준 chain 검증.
  - runtime report read-only integrity 요약.
- 후속:
  - live order manager, guard, execution sync의 모든 의사결정을 audit chain에 자동 append.
  - 운영자 승인 이벤트와 audit chain 연결.
  - 외부 anchor 방식 결정.
  - NAS recovery export self-test.
  - audit 저장 실패 시 주문 차단/보류 정책 결정.

## 검증

- `python -m py_compile app/services/live_audit.py app/services/reporting.py app/storage/sqlite_store.py` 통과.
- `python -m unittest tests.test_live_audit tests.test_live_storage tests.test_sqlite_store` 1차 실패 후 fixture를 기존 `LiveAuditEvent` 계약(`reason/source/gate_decision`)에 맞춰 수정.
- `python -m unittest tests.test_live_audit tests.test_live_storage tests.test_sqlite_store` 통과, 19개.
- `python -m unittest tests.test_live_audit tests.test_reporting tests.test_live_storage tests.test_sqlite_store` 통과, 20개.
- 전체 테스트와 `git diff --check`는 최종 라운드에서 다시 실행 예정.

## 의도적으로 하지 않은 것

- 외부 anchor 구현 없음.
- 실제 KIS live 주문/취소/조회 호출 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.

## cowork 리뷰 질문

1. `audit_event_id`를 hash에서 제외하고 event payload + previous_hash만 hash 대상으로 둔 현재 방식이 충분한가?
2. 첫 event의 `previous_hash = GENESIS_HASH` 정책이 운영 원장에 적절한가?
3. runtime report에 read-only integrity summary를 먼저 노출하고, 주문 경로 자동 append는 후속으로 두는 순서가 안전한가?
4. 외부 anchor는 git tag/commit, 별도 signed file, NAS snapshot metadata 중 어느 쪽을 우선 검토하는 것이 좋은가?

## 다음 단계 권장

🟢 다음 단계 권장: order manager의 주요 전이(`blocked`, `submitted`, `unknown`, `cancel_requested`)를 audit chain에 자동 append할지 별도 slice로 설계한다.

🟢 다음 단계 권장: NAS recovery export self-test를 추가해 `runtime-data/ops/`, `runtime-data/reports/alerts/`, `runtime-data/reports/live-risk/`가 복구 패키지에 포함되는지 잠근다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: audit external anchor 방식과 보관 기간.
