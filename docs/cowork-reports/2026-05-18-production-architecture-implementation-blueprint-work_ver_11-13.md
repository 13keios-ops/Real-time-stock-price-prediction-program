# Production Architecture / Implementation Blueprint work_ver_11-13

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: live audit event가 핵심 trace field 없이 생성되는 위험 축소

## 1. 작업 요약

- `app/services/live_audit.py`의 `build_live_audit_event()`에 필수 trace field 검증을 추가했습니다.
- 빈 값이면 event build를 거부하는 필드:
  - `trading_day`
  - `event_type`
  - `actor`
  - `symbol`
  - `order_id`
  - `prediction_id`
  - `signal_id`
  - `gate_decision_id`
  - `rule_version`
  - `model_version`
  - `data_snapshot_id`
  - `previous_hash`
- `previous_hash`는 64자리 hex 문자열이어야 합니다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | 감사 event hash chain은 만들 수 있었지만, 핵심 trace field가 빈 문자열이어도 event가 생성될 수 있었습니다. |
| 변경 후 | 필수 trace field가 비어 있거나 `previous_hash` 형식이 잘못되면 `ValueError`로 event 생성을 거부합니다. |
| 영향 범위 | `app/services/live_audit.py`의 event build/append 입력 검증. 기존 hash 계산/verify 로직은 유지됩니다. |
| 회귀 위험 | 테스트나 후속 연결 코드가 임시 빈 `prediction_id` 등을 넣으면 실패합니다. 실전 감사 관점에서는 안전 측 동작입니다. |

## 3. 검증

- `python -m py_compile app/services/live_audit.py tests/test_live_audit.py`
- `python -m unittest tests.test_live_audit`
- 결과: 6개 테스트 통과.

## 4. 안전 확인

- 실제 주문 경로 자동 연결 없음.
- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- runtime DB 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. `symbol`과 `order_id`까지 필수로 본 현재 정책이 실전 주문 감사 event 범위에서는 적절한지 확인 부탁드립니다.
2. 향후 kill switch/global approval 같은 비주문 audit event가 필요하면 별도 builder를 둘지, `symbol="GLOBAL"`, `order_id="-"` 같은 sentinel을 둘지 의견 부탁드립니다.
3. `previous_hash` 형식 검증을 build 단계에 둔 것이 과한지 확인 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: 실전 주문 관련 audit event는 지금처럼 모든 trace field를 강제하는 편이 안전합니다. 비주문 운영 event는 같은 builder를 느슨하게 만들기보다 별도 event type/builder를 두거나 명시 sentinel 정책을 문서화한 뒤 추가하는 것을 권장합니다.

🔴 운영자 판단 필요: 외부 timestamp/서명 anchor는 Phase 2/3 전 별도 결정으로 유지하고, Phase 1에서는 로컬 append-only hash chain + NAS recovery export self-test를 1차 anchor로 쓰는 권장안을 유지합니다.
