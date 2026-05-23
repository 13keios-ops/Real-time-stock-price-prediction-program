# Codex Work Ver 11-5

## 범위

`review_ver_10` 이후 cowork 토큰 대기 중 진행한 추가 작업입니다. 이번 파일은 `work_ver_11-4` 이후의 delta만 요약합니다.

## 반영한 결정

- Phase 2 부모 주문 금액 한도는 Codex 권장안으로 적용했습니다.
  - 기본값: `min(100,000원, 운용 배정금의 10%)`
  - 운용 배정금이 전달되지 않는 초기 경로: 100,000원
  - 후속 조정 키: `order_policy.max_order_notional`, `allocation_amount` 또는 `phase2_allocation_amount`, `max_order_allocation_pct` 또는 `max_order_allocation_ratio`
- 실전 감사 원장 1차 anchor는 로컬 append-only hash chain과 recovery export/NAS 백업 포함 self-test로 시작합니다.
  - 외부 timestamp/서명 anchor는 Phase 2/3 전 별도 후보로 미룹니다.
  - 장기 보관 기간과 실제 NAS 복구 drill 주기는 후속 운영 정책입니다.

## 코드 변경

- `app/services/live_order_manager.py`
  - Phase 2 pre-submit 정책에 부모 주문 금액 한도를 추가했습니다.
  - 한도 초과 부모 주문 intent는 broker 호출 전에 `phase2_order_notional_limit_exceeded` 사유로 `blocked` 처리합니다.
  - 차단 context에 `order_notional`, `effective_max_order_notional`, `allocation_amount`, `max_order_allocation_pct`를 남깁니다.
- `tests/test_live_order_manager.py`
  - 기본 100,000원 한도 초과 차단.
  - `order_policy`로 200,000원까지 완화되는 경로.
  - 운용 배정금 500,000원과 10% 비율로 50,000원까지 조이는 경로를 추가했습니다.
- `app/brokers/kis_response_redaction.py`
  - KIS paper status snapshot에서 확인된 `ctac_tlno`, `inqr_ip_addr`, `ordr_empno` 계열을 redaction하기 위해 `tlno`, `ip_addr`, `empno` key part를 추가했습니다.
- `scripts/export_kis_paper_fixture_candidates.py`
  - `runtime-data/dev.db`를 SQLite read-only URI로 열어 broker paper 주문 제출/상태 snapshot에서 fixture 후보를 export합니다.
  - KIS API를 호출하지 않습니다.
  - 출력 기본 경로: `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json`
- `tests/test_kis_paper_fixture_export_script.py`
  - read-only export와 redaction, repo 밖 output 차단을 검증합니다.

## 실제 DB 확인 결과

- `broker_paper_order_submissions`: 530 rows
- `broker_paper_order_status_snapshots`: 164,508 rows
- 제출 응답 후보 detail key: `message`, `message_code`, `raw_output`
- 상태 snapshot 후보 detail key: KIS 일별 주문/체결 조회 raw field 다수
- status snapshot 후보에서 redaction된 값: 3개
  - 전화번호 계열
  - 조회 IP 계열
  - 직원번호 계열

주의: 주문번호와 종목코드는 mapper 검증을 위해 보존합니다. cowork 전달 전 계좌 소유자/실전 운용 승인권자가 fixture JSON을 직접 공유할지 여부를 한 번 더 확인하는 편이 안전합니다.

## 문서 반영

- `docs/Production-Architecture.md`
  - Phase 2 주문금액 한도 결정 완료.
  - KIS paper fixture 후보 export 스크립트 추가.
  - audit 1차 anchor 결정을 반영.
- `docs/Production-Implementation-Blueprint.md`
  - 구현 키와 차단 상태, fixture export 절차를 코드 작업 가능한 수준으로 반영.
- `docs/logbook.md`
  - `work_ver_11-5` entry 추가.
- `docs/cowork-reports/README.md`
  - 리포트 목록 추가.

## 검증

- `python -m py_compile scripts/export_kis_paper_fixture_candidates.py app/services/live_order_manager.py app/brokers/kis_response_redaction.py`
- `python scripts/export_kis_paper_fixture_candidates.py`
- `python -m unittest tests.test_kis_paper_fixture_export_script tests.test_kis_response_redaction`
- `python -m unittest tests.test_live_order_manager`
- `python -m unittest tests.test_live_execution_sync tests.test_live_order_manager`
  - 1차 실패: 기존 체결 sync 테스트 fixture가 Phase 2 기본 주문금액 한도보다 큰 주문을 만들었다.
  - 보정: 이미 제출된 주문의 체결 sync 검증 목적에 맞게 테스트 fixture에 `order_policy.max_order_notional=1_000_000`을 명시했다.
  - 보정 후 통과, 23개.
- `python -m unittest discover -s tests -p "test_*.py"` 통과, 242개.
- `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
- `git diff -- app/risk VERSION config` 출력 없음.

## cowork에 묻고 싶은 부분

1. Phase 2 부모 주문 금액 한도 `min(100,000원, 운용 배정금의 10%)`가 첫 실전 20거래일 기준으로 너무 크거나 작은지.
2. fixture 후보에서 주문번호/종목코드를 보존하는 정책이 mapper 검증과 보안 사이에서 적절한지.
3. audit 1차 anchor를 로컬 hash chain + recovery export/NAS 포함 self-test로 시작하고 외부 timestamp/서명을 후속으로 미루는 것이 Phase 1/2 안전 기준에 충분한지.

## 안전 메모

- 실제 KIS live 주문/취소/조회 호출 없음.
- 실전 계좌 접근 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.
