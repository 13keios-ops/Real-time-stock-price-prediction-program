# Production Architecture / Implementation Blueprint work_ver_11-14

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: 잘못된 live order intent가 DB에 남는 위험 축소

## 1. 작업 요약

- `app/services/live_order_manager.py`의 `create_intent()` 시작 지점에 입력 검증을 추가했습니다.
- DB write 전에 거부하는 조건:
  - `prediction_id`, `signal_id`, `gate_decision_id`, `market_status_snapshot_id`, `model_version`, `rule_version` 등 필수 trace field 누락
  - `qty <= 0`
  - side가 buy/sell 계열로 해석되지 않음
  - limit 주문인데 `limit_price <= 0`
  - `limit_price < 0`
- invalid intent는 `live_orders`와 `live_order_events`에 기록되지 않습니다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | guard가 broker 제출 직전에 막더라도, 필수 field가 비어 있거나 qty/price가 잘못된 intent가 DB에 먼저 남을 수 있었습니다. |
| 변경 후 | intent 생성 전 입력을 검증하고 invalid request는 DB write 전에 거부합니다. |
| 영향 범위 | `LiveOrderManager.create_intent()` 입력 검증, 관련 unit test |
| 회귀 위험 | 후속 연결 코드나 fixture가 임시 빈 trace field를 넣으면 실패합니다. 실전 원장 안전 관점에서는 의도된 동작입니다. |

## 3. 검증

- `python -m py_compile app/services/live_order_manager.py tests/test_live_order_manager.py`
- `python -m unittest tests.test_live_order_manager tests.test_live_order_guard`
- 결과: 22개 테스트 통과.

## 4. 안전 확인

- 실제 KIS live adapter 연결 없음.
- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- runtime DB 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. invalid intent를 `blocked` 원장으로 남기지 않고 아예 DB write 전 거부하는 정책이 적절한지 확인 부탁드립니다.
2. `side` 허용값에 `buy/sell/b/s/01/02`를 둔 것이 현재 KIS 매수/매도 코드와 충분히 맞는지 봐 주세요.
3. market 주문 intent는 아직 guard 단계에서 차단되지만, 생성 단계에서 별도 차단해야 하는지 의견 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: 필수 trace field나 qty/price가 잘못된 intent는 운영 원장에 남길 가치가 낮으므로 지금처럼 DB write 전 거부하는 정책을 유지하는 것이 좋습니다. 주문 타입 정책 위반은 `order_type_not_allowed` 감사가 필요하므로, submit guard에서 `blocked`로 남기는 현재 방향을 유지하는 편이 낫습니다.

🔴 운영자 판단 필요: Phase 2에서 신규 진입 주문은 지정가만 허용하고, 시장가 주문은 비상 청산 별도 flow에서만 허용하는 기존 권장안을 유지합니다.
