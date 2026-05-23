# Production Architecture / Implementation Blueprint work_ver_11-15

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: live order manager가 저장하는 broker raw response의 비밀값 노출 위험 축소

## 1. 작업 요약

- `app/services/live_order_manager.py`가 `live_orders.detail_json`과 `live_order_events.detail_json`에 broker raw response를 저장하기 전 redaction합니다.
- caller에게 반환하는 `LiveOrderManagerResult.raw_response`도 redacted payload로 맞췄습니다.
- 재사용 helper: `app/brokers/kis_response_redaction.py`
- 대상:
  - account/acct/cano 계열 key
  - token/authorization 계열 key
  - app key/app secret 계열 key
  - email/phone 등 개인 식별 가능성이 있는 key
- 안전 예외 key는 기존 helper 기준을 따릅니다. 예: `pdno`, `ord_no`.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | broker raw response가 주문 detail과 order event detail에 그대로 저장될 수 있었습니다. |
| 변경 후 | 저장 직전 raw broker response를 redaction하고, manager result로 반환하는 raw response도 redaction합니다. |
| 영향 범위 | `live_orders.detail_json.raw_broker_response`, `live_order_events.detail_json.raw_broker_response`, `LiveOrderManagerResult.raw_response` |
| 회귀 위험 | 디버깅 시 계좌/key 계열 값은 보이지 않습니다. 이는 의도된 안전 측 동작입니다. |

## 3. 검증

- `python -m py_compile app/services/live_order_manager.py tests/test_live_order_manager.py app/brokers/kis_response_redaction.py`
- `python -m unittest tests.test_live_order_manager tests.test_kis_response_redaction`
- 결과: 19개 테스트 통과.

## 4. 안전 확인

- 실제 KIS live adapter 연결 없음.
- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- runtime DB 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. order manager 저장 지점에서 raw response redaction을 적용한 범위가 충분한지 확인 부탁드립니다.
2. `app/services/live_execution_sync.py`의 `raw_output`도 같은 방식으로 redaction해야 하는지 우선순위를 봐 주세요.
3. raw response 원본을 어디에도 저장하지 않는 정책이 실전 디버깅 관점에서 과하게 보수적인지 의견 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: live execution sync의 `raw_output`도 같은 helper로 redaction해 저장하는 편이 일관적입니다. 원본 raw response는 fixture export 전용 경로에서만 redaction 후 보관하고, 운영 원장에는 redacted payload만 남기는 정책을 권장합니다.

🔴 운영자 판단 필요: 원본 broker 응답을 별도 암호화 저장소에 보관할지 여부는 Phase 2 전까지 결정하면 됩니다. 현재 권장안은 원본 저장 없이 redacted 운영 원장만 유지하는 것입니다.
