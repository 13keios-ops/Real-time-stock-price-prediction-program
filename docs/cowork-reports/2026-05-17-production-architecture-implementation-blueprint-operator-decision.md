# Operator Decision: production-architecture-implementation-blueprint

- date: 2026-05-17
- topic: `production-architecture-implementation-blueprint`
- decision source: 계좌 소유자 또는 실전 운용 승인권자 지시
- related review: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md`
- related work: `2026-05-17-production-architecture-implementation-blueprint-work_ver_11.md`

이 파일에서 `운영자`는 Codex나 Claude cowork가 아니라 계좌 소유자 또는 실전 운용 승인권자를 뜻한다.

## 결정 1. Phase 2 부분 체결 잔량 자동 취소

- Codex 권장안: Phase 2에서는 자동 잔량 취소를 하지 않는다.
- 결정값: 권장안 채택.
- 적용 기준:
  - 부분 체결 잔량은 유지한다.
  - 같은 종목 신규 부모 주문은 계속 차단한다.
  - 잔량 취소가 필요하면 cancel-only guard를 통과한 수동 승인 취소로 처리한다.
  - 장마감 전 자동 잔량 취소는 KIS cancel fixture, alert/review 안정화 뒤 Phase 3 전 후보로 둔다.

## 결정 2. `live_positions` 실제 저장 시점

- Codex 권장안: 순수 계산 helper는 유지하되, `live_positions` 자동 저장은 KIS 실제 응답 fixture와 alert/review 경로가 안정된 뒤 시작한다.
- 결정값: 권장안 채택.
- 적용 기준:
  - `app/services/live_position_accounting.py`의 계산 결과는 당장은 관측/검증용이다.
  - `live_positions` 정본 저장은 KIS fixture, alert outbox, 장후 review, live order/fill mismatch 0건 조건을 먼저 확인한 뒤 진행한다.
  - 첫 저장 단계에서는 리스크 게이트나 주문 수량 산정의 정본 입력으로 쓰지 않는다.

## 결정 3. Dashboard 외 알림 채널

- Codex 권장안: 로컬 outbox는 항상 남기고, 텔레그램을 기본 장중 메시지 채널로 쓰며, 중요한 이슈는 이메일도 함께 보낸다.
- 결정값: 텔레그램 + 중요 이슈 이메일 채택.
- 적용 기준:
  - 정상/정보성 상태는 dashboard와 로컬 outbox 중심으로 둔다.
  - 주의/사고성 알림은 텔레그램 outbox 대상으로 둔다.
  - `critical` 또는 중요 event type은 이메일 outbox도 함께 만든다.
  - 실제 텔레그램 bot token, 이메일 API key/SMTP password, 수신 주소는 문서와 git 추적 파일에 쓰지 않는다.
  - 실제 외부 발송기는 outbox를 읽는 후속 sender로 분리한다.

## 남은 결정

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: Phase 2 주문 금액 한도.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: audit hash chain anchor 방식, 보관 기간, NAS recovery export self-test 완료 전 운용 금지 여부.

🟢 다음 단계 권장: KIS 실제 응답 fixture를 비밀값 제거 후 확보하고, alert outbox sender는 토큰/수신자 관리 방식을 먼저 정한 뒤 별도 slice로 연결한다.
