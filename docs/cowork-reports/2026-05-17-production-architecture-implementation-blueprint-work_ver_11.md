# Codex work_ver_11: review_ver_10 반영 + 운영자 결정 3건 적용 + alert outbox

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_11`
- 기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md`
- 운영자 결정 기록: `2026-05-17-production-architecture-implementation-blueprint-operator-decision.md`

## 시작 전 상태

- `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
- `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 주말 대기.
- 실전 주문 API 호출 없음. KIS live 조회 호출 없음.

## 반영한 운영자 결정

1. Phase 2 부분 체결 잔량 자동 취소:
   - 결정: Codex 권장안 채택.
   - Phase 2에서는 자동 잔량 취소를 하지 않는다.
   - 잔량 유지, 같은 종목 신규 부모 주문 차단, 필요 시 cancel-only guard + 수동 승인 취소로 처리한다.
   - 장마감 전 자동 잔량 취소는 KIS cancel fixture와 alert/review 안정화 뒤 Phase 3 전 후보로 둔다.

2. `live_positions` 실제 저장 시점:
   - 결정: Codex 권장안 채택.
   - `app/services/live_position_accounting.py` 순수 계산 helper는 유지한다.
   - `live_positions` 자동 저장은 KIS 실제 응답 fixture, alert outbox, 장후 review, live order/fill mismatch 0건 조건을 먼저 확인한 뒤 시작한다.
   - 첫 저장은 관측용 snapshot으로만 쓰고, 리스크 게이트나 주문 수량 산정의 정본 입력으로 쓰지 않는다.

3. Dashboard 외 알림 채널:
   - 결정: 텔레그램 + 중요 이슈 이메일 채택.
   - 로컬 outbox는 항상 남긴다.
   - warning/critical은 텔레그램 outbox 대상이다.
   - critical 또는 중요 event type은 이메일 outbox도 함께 만든다.
   - 실제 텔레그램 bot token, 이메일 API key/SMTP password, 수신 주소는 저장소에 쓰지 않는다.

## 코드 변경

- 추가: `app/services/live_alerting.py`
  - `LiveAlert`, `LiveAlertRoute`, `LiveAlertOutbox`
  - `route_live_alert()`
  - `build_live_monitoring_alerts()`
  - `render_telegram_alert()`, `render_email_alert()`
- 변경: `app/services/reporting.py`
  - runtime report 생성 시 live fill mismatch와 live order attention을 alert로 변환한다.
  - `runtime-data/reports/alerts/{local,telegram,email}/alerts-YYYY-MM-DD.jsonl`에 `delivery_mode=outbox_only` record를 쓴다.
  - 실제 외부 발송은 하지 않는다.
- 변경: `tests/test_live_alerting.py`
  - warning -> local + telegram
  - important warning -> local + telegram + email
  - critical -> local + telegram + email
  - monitoring alert와 outbox JSONL 생성 검증
- 변경: `tests/test_reporting.py`
  - runtime report가 alert outbox summary를 JSON/Markdown에 기록하는지 확인.
  - mismatch/attention 상황에서 local/telegram/email JSONL이 생성되는지 확인.

## 문서 변경

- `docs/Production-Architecture.md`
  - Phase 2 부분 체결 잔량 자동 취소 금지 결정 반영.
  - `live_positions` 실제 저장 시점 결정 반영.
  - dashboard 외 알림 채널을 텔레그램 + 중요 이슈 이메일로 확정.
  - alert 상태 저장 위치를 `runtime-data/reports/alerts/{local,telegram,email}/alerts-YYYY-MM-DD.jsonl`로 구체화.
- `docs/Production-Implementation-Blueprint.md`
  - `live_alerting.py` outbox 구조와 report 연결을 Slice 8 범위에 반영.
  - 남은 결정 항목에서 부분 체결 자동 취소, `live_positions`, 알림 채널을 결정 완료로 이동.
- `docs/cowork-reports/README.md`
  - `review_ver_10`, `work_ver_11`, `2026-05-17 operator-decision` 추가.
- `docs/logbook.md`
  - 이번 작업 entry 추가.

## 검증

- `python -m py_compile app/services/live_alerting.py app/services/reporting.py` 통과.
- `python -m unittest tests.test_live_alerting tests.test_reporting` 통과, 7개.
- `python -m unittest tests.test_live_alerting tests.test_live_order_manager tests.test_live_execution_sync tests.test_live_position_accounting tests.test_dashboard tests.test_reporting` 통과, 46개.
- `python -m unittest discover -s tests -p "test_*.py"` 통과, 226개.
- `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
- `git diff -- app/risk VERSION config` 출력 없음.

## 의도적으로 하지 않은 것

- 실제 텔레그램/이메일 발송기 구현 없음.
- 텔레그램 token, 이메일 credential, 수신 주소 기록 없음.
- KIS live 주문/취소 API 호출 없음.
- KIS live 조회 호출 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 운영 DB schema apply 없음.
- 자동 commit/push 없음.

## cowork 리뷰 요청

1. 텔레그램/이메일 outbox routing이 운영 안전 관점에서 충분히 보수적인가?
2. 실제 sender를 붙이기 전 `delivery_mode=outbox_only`로 report 경로에 연결한 경계가 적절한가?
3. Phase 2 부분 체결 잔량 자동 취소 금지와 `live_positions` 저장 지연 결정이 문서에서 오해 없이 보이는가?
4. 다음 우선순위는 `KIS 실제 응답 fixture 확대`를 계속 1순위로 보면 되는가, 아니면 alert sender/hysteresis를 먼저 봐야 하는가?

## 다음 단계 권장

🟢 다음 단계 권장: KIS 실제 주문/체결 조회 응답 sample을 비밀값 제거 후 fixture로 추가해 `snapshot_from_kis_daily_order_fill()` field mapping을 더 잠근다.

🟢 다음 단계 권장: alert sender는 outbox reader로 별도 slice를 만들고, 비밀값은 환경변수 또는 로컬 secrets 파일에서만 읽게 한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: Phase 2 주문 금액 한도, audit hash chain anchor 방식과 보관 기간.
