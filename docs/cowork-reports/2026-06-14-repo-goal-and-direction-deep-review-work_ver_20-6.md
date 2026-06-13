# Codex Work Ver 20-6 - Hold-Rescue Lifecycle Synthetic Helper

- 작성 시각: 2026-06-14 05:20 KST
- 범위: hold-rescue full 실험 전 lifecycle helper 와 synthetic tests
- 상태: helper 및 합성 테스트 구현 완료. Cybos full hold-rescue 결과 실험은 아직 미실행.

## 1. 배경

full Cybos rescue report 결과:

- buy-avoid 는 `follow_up_candidate_proxy_only`.
- buy-rescue 는 `buy_avoid_candidate_only`.
- buy-rescue target grid 는 모두 비용 반영 순손익이 음수였다.

따라서 KIS live 에 buy-rescue shadow 를 추가하지 않는다.
다만 계획서에 남아 있던 hold-rescue 는 포지션 lifecycle 설계와 synthetic test 가 선행 조건이므로, full 결과 실험 전 최소 helper 와 테스트만 구현했다.

관련 문서/코드 경로:
`docs/cowork-reports/2026-06-14-repo-goal-and-direction-deep-review-work_ver_20-5.md`

## 2. 구현

추가한 helper:

- `_simulate_hold_rescue_lifecycle`

입력:

- synthetic price path
- entry index
- baseline exit index
- up probability threshold
- max extension steps
- optional max loss percent
- trade cost percent

출력:

- baseline exit index
- rescue exit index
- extension steps
- rescue applied 여부
- rescue exit reason
- baseline net return
- rescue net return
- rescue delta
- max drawdown

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`

## 3. 테스트

추가한 synthetic lifecycle cases:

- 상승 확률이 유지되면 max extension 까지 보유 연장.
- baseline exit 시점의 상승 확률이 낮으면 rescue 미적용.
- 연장 중 상승 확률이 threshold 아래로 떨어지면 청산.
- 연장 중 max loss 를 넘으면 청산.

검증:

```bash
python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py tests/test_cybos_buy_avoid_proxy.py
python -m unittest tests.test_cybos_buy_avoid_proxy -q
python -m unittest tests.test_cybos_buy_avoid_proxy tests.test_cybos_research_suite_summary tests.test_expected_value_stability -q
python -m unittest discover -s tests -p "test_*.py" -q
git diff --check
```

결과:

- py_compile 통과.
- `tests.test_cybos_buy_avoid_proxy`: 13개 통과.
- 관련 테스트 묶음: 15개 통과.
- 전체 테스트: 399개 통과.
- `git diff --check`: 통과.

관련 문서/코드 경로:
`tests/test_cybos_buy_avoid_proxy.py`

## 4. 해석 제한

이번 작업이 의미하는 것:

- hold-rescue full 실험을 위한 lifecycle 전제 조건을 작은 합성 경로에서 잠갔다.
- 단일 row threshold 가 아니라 entry/exit/extension/stop 을 따로 본다.

이번 작업이 의미하지 않는 것:

- hold-rescue 가 수익성 있다는 뜻이 아니다.
- KIS live shadow 에 hold-rescue 를 붙여도 된다는 뜻이 아니다.
- paper/live 주문 정책을 바꿔도 된다는 뜻이 아니다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`

## 5. 다음 권장안

권장안:

1. KIS live 는 계속 buy-avoid shadow 순차 관측만 유지한다.
2. hold-rescue full Cybos 실험은 바로 실행하지 않는다.
3. 먼저 실제 paper replay 에서 entry/exit event 를 안정적으로 뽑을 수 있는지 확인한다.
4. 그 다음에만 Cybos lifecycle full simulation 으로 확장한다.

관련 문서/코드 경로:
`app/services/streaming.py`,
`app/paper_trading/`,
`runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`
