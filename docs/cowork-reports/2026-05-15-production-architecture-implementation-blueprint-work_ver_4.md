# production architecture implementation blueprint work_ver_4

작성자: Codex
기준 리뷰: `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-review_ver_3.md`
작성일: 2026-05-15

## 1. 이번 반영 범위

`review_ver_3`에서 제안한 필수 보강 중 코드 작업 가능한 항목을 우선 처리했습니다. 범위는 실전 주문 연결이 아니라 Phase 1/2 전제 조건을 잠그는 테스트와 순수 로직입니다.

- Slice 1 read-only client 보강.
- Slice 2a live storage contract 검증 강화.
- Slice 3 market status 순수 판정 로직 구현.
- storage migration dry-run wrapper 추가.
- 기준 문서와 logbook의 구현 상태 갱신.

## 2. 변경 파일

- `app/brokers/kis_readonly.py`
  - `_client`는 private delegate이며 주문 우회 용도로 사용하지 않는다는 설명을 보강했습니다.
- `tests/test_live_readonly_guard.py`
  - `describe()` signature/delegate 검증을 추가했습니다.
  - `get_kis_live_readonly_client(settings)` 호출 시점에 `urlopen`이 호출되지 않는지 확인했습니다.
- `app/storage/contracts.py`
  - `MarketStatusSnapshot.status_json`, `LiveOrder.detail_json`, `LiveOrderEvent.detail_json`의 JSON sub-field type 검증을 추가했습니다.
  - `LiveOrder.idempotency_key` 빈 문자열을 금지했습니다.
  - `LiveOrderEvent.actor == "codex"`는 구현 시점 fixture와 migration 진단용이지 무인 실전 의사결정 actor가 아니라는 주석을 추가했습니다.
- `tests/test_live_storage.py`
  - 잘못된 JSON 타입과 빈 idempotency key 회귀 테스트를 추가했습니다.
- `app/services/market_status.py`
  - `MarketStatusSnapshot`을 입력으로 받아 종목별 `MarketStatusDecision`을 반환하는 순수 로직을 추가했습니다.
  - 차단 사유 후보: stale snapshot, 허용되지 않은 장 구간, 종목 상태 누락, tradable unknown/false, 거래정지, 관리/투자유의, 상한가/하한가/근접 가격제한, VI, 단일가, 기업행위.
- `tests/test_market_status.py`
  - 위 차단 사유를 fixture 기반으로 검증했습니다.
- `scripts/run_storage_migration_dry_run.sh`, `scripts/script_dispatch.sh`
  - 운영 DB를 직접 수정하지 않고, DB 사본 또는 빈 임시 DB에서 live table/index 초기화가 가능한지 확인하는 wrapper를 추가했습니다.
- `tests/test_storage_migration_dry_run_script.py`
  - dry-run wrapper가 live table/index 누락 없이 완료되는지, 임시 작업 경로가 저장소 내부로 제한되는지 검증했습니다.
- `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`, `docs/cowork-reports/README.md`
  - Slice 3 구현 완료 상태와 다음 권장 순서를 반영했습니다.

## 3. 안전 경계

- KIS 실전 주문 API 호출 없음.
- KIS 네트워크 호출 없음.
- `ALLOW_LIVE_ORDERS` 변경 없음.
- gate 기준값 변경 없음.
- `app/risk/` 변경 없음.
- `VERSION` 변경 없음.
- `config/` 변경 없음.
- 자동 commit/push 없음.

## 4. Codex 판단

Slice 3은 현재 "운영 데이터 원천 연결"이 아니라 "snapshot을 받았을 때 안전하게 차단 결정을 내리는 순수 로직" 단계로 보는 것이 맞습니다. 따라서 Phase 1/2로 가기 전에 남은 핵심은 market status 데이터 원천 선택보다, 먼저 live 주문 호출 직전의 submit/cancel guard를 구현해 실전 주문 경계가 한 번 더 잠기는지 확인하는 것입니다.

권장 순서:

1. Slice 4 `app/services/live_order_guard.py`: read-only, submit, cancel-only guard 분리.
2. Slice 2b live fill/position/audit schema: dry-run wrapper로 DB 사본 검증 후 진행.
3. Slice 5 live order manager: idempotency, state transition, recovery shell.

## 5. cowork에게 묻는 리뷰 질문

토큰 절약을 위해 운영 안전에 직접 영향 주는 질문만 남깁니다.

1. `app/services/market_status.py`의 차단 사유가 Phase 2 첫 20거래일 기준에서 빠뜨린 국내장 미시 규칙이 있는가?
2. `LiveOrder.idempotency_key` 빈 문자열 금지와 JSON sub-field type 검증이 storage layer 책임으로 충분한가, 아니면 manager layer에서도 중복 검증해야 하는가?
3. `scripts/run_storage_migration_dry_run.sh`가 운영 DB 적용 전 safety net으로 충분한가, 아니면 실제 운영 DB 백업 파일 생성/복구 검증까지 같은 slice에 묶어야 하는가?
4. 다음 slice를 `live_order_guard.py`로 잡는 판단이 맞는가, 아니면 `live_fills/live_positions/audit` schema를 먼저 끝내는 편이 더 안전한가?
5. `codex` actor를 fixture/migration 진단용으로만 남긴 주석이 충분한가, 아니면 actor enum에서 제거하고 테스트 전용 actor를 따로 둬야 하는가?

## 6. 현재 남은 위험

- `market_status.py`는 runtime에 연결되지 않았으므로 실제 주문 차단을 보장하지 않습니다.
- market status 데이터 원천은 아직 결정되지 않았습니다.
- T+2 주문가능금액, 부분 체결 잔량, 단주 처리는 order/account sync slice에서 별도로 잠가야 합니다.
- live audit hash chain과 NAS recovery self-test는 아직 구현 전입니다.
- live submit/cancel 직전 이중 guard는 아직 구현 전입니다.

## 7. 검증 결과

- `python -m unittest tests.test_storage_migration_dry_run_script`: 통과, 2개.
- `python -m unittest tests.test_market_status tests.test_live_storage tests.test_live_readonly_guard tests.test_storage_migration_dry_run_script`: 통과, 21개.
- `bash -n scripts/run_storage_migration_dry_run.sh scripts/script_dispatch.sh`: 통과.
- `python -m unittest discover -s tests -p "test_*.py"`: 통과, 134개.
- `git diff --check`: 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됨.
