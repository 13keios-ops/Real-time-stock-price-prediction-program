# Production Architecture / Implementation Blueprint work_ver_11-16

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: live execution sync가 저장하는 broker raw output의 비밀값 노출 위험 축소

## 1. 작업 요약

- `app/services/live_execution_sync.py`가 order/fill/event detail에 broker raw output을 저장하기 전 redaction합니다.
- 적용 위치:
  - `live_orders.detail_json.raw_broker_response`
  - `live_fills.detail_json.raw_broker_fill`
  - `live_order_events.detail_json.raw_broker_response`
- 재사용 helper: `app/brokers/kis_response_redaction.py`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | KIS daily order/fill record 기반 snapshot의 `raw_output`이 order/fill/event detail에 그대로 저장될 수 있었습니다. |
| 변경 후 | 저장 직전 raw broker output을 redaction합니다. |
| 영향 범위 | execution sync가 쓰는 order/fill/event detail JSON. DB schema 변경 없음. |
| 회귀 위험 | 원본 broker output의 민감 key 값은 운영 원장에서 보이지 않습니다. 이는 의도된 안전 측 동작입니다. |

## 3. 검증

- `python -m py_compile app/services/live_execution_sync.py tests/test_live_execution_sync.py app/brokers/kis_response_redaction.py`
- `python -m unittest tests.test_live_execution_sync tests.test_kis_response_redaction`
- 결과: 14개 테스트 통과.

## 4. 안전 확인

- 실제 KIS REST 조회 없음.
- 실제 주문/취소 없음.
- 운영 DB schema apply 없음.
- runtime DB 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. order manager와 execution sync 모두 저장 시점 redaction을 적용한 범위가 충분히 일관적인지 확인 부탁드립니다.
2. `LiveOrderSyncDecision.raw_output` 자체는 메모리상 원본을 유지하고, 저장 시점에서만 redaction하는 방식이 적절한지 봐 주세요.
3. 향후 실제 KIS response fixture를 만들 때 운영 원장에는 redacted payload만 저장하고, fixture export도 redaction된 샘플만 남기는 정책이 충분한지 의견 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: 운영 원장에는 redacted payload만 남기는 정책을 유지하는 것이 좋습니다. 원본 broker response가 꼭 필요하다면 git 추적 밖 암호화 저장소와 별도 보존 기간을 정한 뒤에만 추가하는 것을 권장합니다.

🔴 운영자 판단 필요: 현재는 원본 raw response 별도 보관을 하지 않는 권장안을 유지합니다. 실제 장애 분석에서 원본 보관 필요성이 생기면 Phase 2 전 별도 결정을 받는 편이 안전합니다.
