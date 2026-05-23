# Codex work_ver_11-4: KIS 실제 응답 fixture redaction helper

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_11-4`
- 기준 리뷰: `review_ver_10`
- 사유: 다음 1순위인 KIS 실제 응답 fixture 확대는 계좌 소유자/실전 운용 승인권자의 sample 제공이 필요하다. sample을 받기 전 민감정보 제거 절차를 코드와 테스트로 먼저 잠갔다.

## 변경 요약

1. `app/brokers/kis_response_redaction.py`
   - `redact_kis_payload()`
   - `redact_kis_json_text()`
   - token, app key/secret, authorization, 계좌번호, 계좌상품코드, 고객 식별값으로 보이는 key를 `<REDACTED>`로 바꾼다.
   - 주문번호(`odno`, `ord_no`), 종목코드(`pdno`, `shtn_pdno`), 수량/가격 필드는 mapper 검증에 필요하므로 유지한다.

2. `tests/test_kis_response_redaction.py`
   - 민감 field가 제거되는지 확인한다.
   - 주문번호/종목코드/수량이 유지되는지 확인한다.
   - redaction 결과가 유효한 JSON인지 확인한다.

3. 문서
   - `docs/Production-Architecture.md`
   - `docs/Production-Implementation-Blueprint.md`
   - `docs/cowork-reports/README.md`
   - `docs/logbook.md`

## 검증

- `python -m py_compile app/brokers/kis_response_redaction.py app/services/live_alerting.py app/services/reporting.py app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py` 통과.
- `python -m unittest tests.test_kis_response_redaction tests.test_live_alerting tests.test_reporting tests.test_live_order_manager tests.test_dashboard` 통과, 38개.
- `python -m unittest discover -s tests -p "test_*.py"` 통과, 237개.
- `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
- `git diff -- app/risk VERSION config` 출력 없음.

## 의도적으로 하지 않은 것

- 실제 KIS live 조회/주문/취소 호출 없음.
- 실제 응답 sample을 저장소에 추가하지 않음.
- 계좌번호, token, app key/secret 기록 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.

## cowork 리뷰 요청

1. redaction key 목록이 KIS 실제 주문/체결 fixture 제공 전에 충분히 보수적인가?
2. 주문번호와 종목코드를 유지하는 것이 mapper 검증 관점에서 적절한가?
3. KIS 실제 응답 sample을 받을 때 추가로 반드시 제거해야 할 field명이 있는가?

## 다음 단계 권장

🟢 다음 단계 권장: 계좌 소유자/실전 운용 승인권자가 실제 KIS 주문/체결 조회 JSON sample 1~3건을 로컬에서 redaction한 뒤 fixture 후보로 제공한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: sample 제공 시 실제 계좌번호, token, app key/secret, 고객명/전화/email 등 개인정보가 남지 않았는지 최종 육안 확인.
