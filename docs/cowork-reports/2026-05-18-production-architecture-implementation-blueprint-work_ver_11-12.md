# Production Architecture / Implementation Blueprint work_ver_11-12

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: live position 계산에서 알 수 없는 fill side가 조용히 묻히는 위험 축소

## 1. 작업 요약

- `app/services/live_position_accounting.py`는 기록된 `live_fills`만 입력으로 받아 long-only 평균단가 포지션을 순수 계산합니다.
- 기존에는 side가 buy/sell로 해석되지 않으면 계산에 반영되지 않았고, 그 사실이 결과에 드러나지 않았습니다.
- 이번 보강으로 알 수 없는 side는 포지션 수량을 바꾸지 않고 `invalid_side_count`에 기록됩니다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | unknown side fill은 buy/sell 분기 어디에도 들어가지 않아 조용히 무시될 수 있었습니다. |
| 변경 후 | unknown side fill은 `LivePositionAccountingResult.invalid_side_count`와 `LivePosition.detail_json["accounting"]["invalid_side_count"]`에 기록됩니다. |
| 영향 범위 | 순수 position 계산 결과와 detail JSON. DB schema 변경 없음. |
| 회귀 위험 | 기존 계산 수량은 바뀌지 않습니다. 다만 invalid side가 있는 fixture/test에서 새 field를 확인할 수 있습니다. |

## 3. 검증

- `python -m py_compile app/services/live_position_accounting.py tests/test_live_position_accounting.py`
- `python -m unittest tests.test_live_position_accounting`
- 결과: 5개 테스트 통과.

## 4. 안전 확인

- 실제 포지션 저장 없음.
- 브로커 조회 없음.
- runtime DB 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. unknown fill side를 즉시 예외로 중단하지 않고 카운트만 남기는 현재 단계가 Phase 2 관측용 position 계산에 적절한지 확인 부탁드립니다.
2. 실제 `live_positions` 저장 단계에서는 `invalid_side_count > 0`이면 저장 차단 또는 저장은 하되 `untrusted` 상태 표시 중 무엇이 더 안전한지 의견 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: 실제 `live_positions` 저장 전까지는 카운트만 남기고 계산을 유지하는 현재 방식을 권장합니다. 저장 단계가 생기면 `invalid_side_count > 0` 또는 `broker_qty_mismatch=true`인 position은 정본으로 저장하지 않고 review 대상 snapshot으로만 남기는 정책이 안전합니다.

🔴 운영자 판단 필요: `live_positions` 정본 저장을 시작할 시점은 기존 권장안대로 KIS 실제 응답 fixture, alert outbox, 장후 review 경로가 안정되고 live order/fill mismatch가 0임을 확인한 뒤로 유지하는 편이 좋습니다.
