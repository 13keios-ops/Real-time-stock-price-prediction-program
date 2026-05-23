# Production Architecture / Implementation Blueprint work_ver_11-17

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: system clock skew check를 주문 submit guard에서 사용할 수 있는 hook으로 연결

## 1. 작업 요약

- `app/services/system_clock.py`의 `ClockSkewDecision`을 `LiveOrderGuard.assert_can_submit()`에서 선택적으로 받을 수 있게 했습니다.
- 기본 submit 동작은 아직 clock check를 강제하지 않습니다.
- caller가 `clock_skew_decision`을 넘겼고 그 decision이 차단이면 submit이 broker 호출 전에 차단됩니다.
- caller가 `require_clock_skew_check=True`를 넘겼는데 decision이 없으면 `system_clock_check_missing`으로 차단됩니다.
- `LiveOrderManager.submit_intent()`도 해당 hook을 guard에 전달할 수 있게 했습니다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | system clock helper와 readiness fixture check는 있었지만 주문 guard에는 연결되지 않았습니다. |
| 변경 후 | submit guard가 선택적으로 clock skew decision을 평가할 수 있습니다. 기준 시각 원천이 없으므로 기본 강제는 하지 않습니다. |
| 영향 범위 | `app/services/live_order_guard.py`, `app/services/live_order_manager.py`, 관련 unit test |
| 회귀 위험 | 기존 caller는 새 인자를 주지 않으면 동작이 바뀌지 않습니다. `require_clock_skew_check=True`를 쓰는 caller는 clock decision 누락 시 의도대로 차단됩니다. |

## 3. 검증

- `python -m py_compile app/services/live_order_guard.py app/services/live_order_manager.py tests/test_live_order_guard.py tests/test_live_order_manager.py app/services/system_clock.py`
- `python -m unittest tests.test_live_order_guard tests.test_live_order_manager tests.test_system_clock`
- 결과: 30개 테스트 통과.

## 4. 안전 확인

- 기준 시각 원천 연결 없음.
- 실제 KIS API 호출 없음.
- 실제 주문/취소 없음.
- 운영 DB schema apply 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. clock check를 기본 강제하지 않고 선택적 hook으로 먼저 둔 단계가 적절한지 확인 부탁드립니다.
2. Phase 1/2 전환 시점에는 `require_clock_skew_check=True`를 기본으로 올리는 게 맞는지 의견 부탁드립니다.
3. 기준 시각 원천은 KIS read-only 응답 기준, OS/NTP 기준, 둘 다 비교 중 어느 쪽을 우선해야 하는지 운영 안전 관점에서 봐 주세요.

## 6. Codex 권장안

🟢 다음 단계 권장: Phase 1에서는 readiness dry-run fixture evidence로만 통과시키고, Phase 2 주문 submit 직전부터 `require_clock_skew_check=True`를 켜는 순서를 권장합니다. 기준 시각 원천은 KIS read-only 응답 시간과 OS/NTP 관측을 모두 기록하되, 차단 판단은 더 보수적인 값을 쓰는 편이 좋습니다.

🔴 운영자 판단 필요: 현재 `±2초` 기본 후보를 유지합니다. 실제 KIS 주문 API timestamp 거부 사례가 관측되면 `±1초`로 낮추는 정책을 Phase 2 전 다시 검토하는 것이 좋습니다.
