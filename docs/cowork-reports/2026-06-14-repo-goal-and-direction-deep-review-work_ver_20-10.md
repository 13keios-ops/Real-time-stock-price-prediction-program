# Codex Work Ver 20-10 - Cybos Buy-Rescue Precision Review

- 작성 시각: 2026-06-14 22:20 KST
- 범위: buy-rescue 실패 원인 재검토, 정밀 rescue grid 추가, full 12 fold 리포트 재생성
- 상태: 코드/문서 보강, smoke/full 실행 완료. KIS live shadow/order 정책 변경 없음.

## 1. 작업 판단

사용자 지적은 맞다.

`buy-avoid`만 계속 강화하면 모델이 손실 회피 장치로만 굳어질 수 있다. 그래서 `buy-rescue`, 즉 기존 proxy 기준이 매수하지 않았던 후보 중 LightGBM 상승 확률이 높은 것을 되살렸을 때 수익 기회가 있는지 다시 봐야 한다.

다만 기존 full 결과의 문제는 단순히 `buy-rescue`를 넓게 잡은 것일 수 있었다. 기존 grid 는 `0.05`, `0.10`, `0.20`, `0.30`이라 최소 5% 후보를 되살렸다. 따라서 이번 작업은 더 좁은 `0.001`, `0.0025`, `0.005`, `0.01`, `0.02`, `0.03`, `0.05` grid 를 추가해 고확신 상승 후보만 따로 봤다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`

## 2. 구현 내용

추가한 항목:

- `DEFAULT_PRECISION_TARGET_RESCUE_RATES`
- `buy_rescue_precision_definition`
- `buy_rescue_precision_target_summaries`
- 거래당 평균 총수익 `rescued_avg_gross_return_pct`
- 거래당 평균 순수익 `rescued_avg_net_return_pct`
- 비용 드래그 `rescued_cost_drag_pct`
- 비용 대비 초과 수익 `gross_minus_cost_per_trade_pct`

precision 후보 통과 기준:

- rescued trade 최소 `100`건
- rescue coverage `0.001~0.05`
- 거래당 평균 순수익 최소 `0.03%`
- fold `2/3` 이상 비음수
- 단일 positive fold 집중도 `0.50` 이하

이 기준을 통과해도 결론은 `precision_follow_up_candidate_proxy_only`까지만 허용한다. KIS live 주문, paper 주문 판단, gate, active model 은 바꾸지 않는다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`tests/test_cybos_buy_avoid_proxy.py`

## 3. full 12 fold 결과

최신 리포트:

- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
- generated_at: `2026-06-14T22:02:31+09:00`
- decision: `buy_avoid_candidate_only`

wide rescue:

| target | rescued | avg gross/trade | avg net/trade | total net | conclusion |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0.05 | 33,135 | 0.023559% | -0.106441% | -3,526.921975%p | diagnostic_only_negative_net |
| 0.10 | 66,340 | 0.020861% | -0.109139% | -7,240.276049%p | diagnostic_only_negative_net |
| 0.20 | 130,233 | 0.018854% | -0.111146% | -14,474.937432%p | diagnostic_only_negative_net |
| 0.30 | 192,843 | 0.015946% | -0.114054% | -21,994.446349%p | coverage_out_of_bounds |

precision rescue:

| target | rescued | avg gross/trade | avg net/trade | total net | nonnegative folds | conclusion |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0.001 | 727 | 0.005543% | -0.124457% | -90.480155%p | 0.1667 | diagnostic_only_cost_drag |
| 0.0025 | 1,732 | 0.009514% | -0.120486% | -208.681769%p | 0.0833 | diagnostic_only_cost_drag |
| 0.005 | 3,337 | 0.022004% | -0.107996% | -360.382392%p | 0.1667 | diagnostic_only_cost_drag |
| 0.01 | 6,769 | 0.047194% | -0.082806% | -560.512600%p | 0.1667 | diagnostic_only_cost_drag |
| 0.02 | 13,076 | 0.041280% | -0.088720% | -1,160.097836%p | 0.0833 | diagnostic_only_cost_drag |
| 0.03 | 19,667 | 0.031164% | -0.098836% | -1,943.810402%p | 0.0000 | diagnostic_only_cost_drag |
| 0.05 | 33,135 | 0.023559% | -0.106441% | -3,526.921975%p | 0.0000 | coverage_out_of_bounds |

해석:

- 가장 좁은 `0.001`에서도 거래당 평균 총수익은 `0.005543%`로 비용 `0.13%`에 크게 못 미친다.
- `0.01`이 gross 기준으로는 상대적으로 좋아 보이지만, 그래도 평균 총수익 `0.047194%`라 비용을 넘지 못한다.
- 따라서 기존 buy-rescue 실패는 grid 가 넓어서 생긴 문제가 아니라, 현재 Cybos proxy 기준 LightGBM 상승 신호가 비용을 이길 정도로 강하지 않은 문제로 보는 것이 맞다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.md`,
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`

## 4. 운영 판단

권장안:

- KIS live 에 buy-rescue shadow 를 추가하지 않는다.
- 기존 buy-avoid shadow 순차 관측을 유지한다.
- buy-rescue 는 폐기하지 않고 후순위 연구 질문으로 둔다.
- 후속 조건은 KIS live 에서 baseline 비매수/차단 판단을 기록하는 `no-trade decision ledger` 가용성 확인과, 상승 후보 표본 확보다.

이 판단은 `손실 회피만 하자`가 아니다. 현재 증거 기준으로는 상승 rescue 신호가 비용을 못 이기므로, 주문 흐름을 늘리기 전에 상승 신호 품질을 먼저 개선해야 한다는 뜻이다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`

## 5. 검증

실행:

```bash
python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py tests/test_cybos_buy_avoid_proxy.py
python -m unittest tests.test_cybos_buy_avoid_proxy -q
python -m unittest tests.test_cybos_buy_avoid_proxy tests.test_cybos_research_suite_summary tests.test_expected_value_stability -q
python scripts/summarize_cybos_buy_avoid_proxy.py --horizon-min 15 --feature-set-name bar_context_momentum --trade-cost-pct 0.13 --walk-forward-max-folds 1 --output-dir .tmp-tests/cybos-rescue-precision-smoke
python scripts/summarize_cybos_buy_avoid_proxy.py --horizon-min 15 --feature-set-name bar_context_momentum --trade-cost-pct 0.13
python -m unittest discover -s tests -p "test_*.py" -q
git diff --check
```

결과:

- py_compile 통과.
- `tests.test_cybos_buy_avoid_proxy`: 15개 통과.
- 관련 research suite 테스트: 17개 통과.
- 1 fold smoke 통과.
- full 12 fold 통과, 실행 시간 약 `1,610`초.
- 전체 테스트 412개 통과.
- `git diff --check` 통과. CRLF/LF 경고만 확인.

관련 문서/코드 경로:
`tests/test_cybos_buy_avoid_proxy.py`

## 6. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

변경 전:

- buy-rescue 가 실패했지만, 너무 넓은 5~30% rescue grid 때문에 실패했는지 상승 신호 자체가 약한지 분리하기 어려웠다.

변경 후:

- 0.1~5% 정밀 rescue grid 를 별도로 기록하고, 거래당 총수익/순수익/비용 드래그를 함께 본다.
- full 결과상 정밀 grid 도 모두 비용을 이기지 못했다.

영향 범위:

- Cybos 연구 리포트 생성 스크립트
- Cybos buy-avoid/rescue 테스트
- `docs/Current-Implementation.md`
- `docs/Execution-Plan.md`
- `docs/Production-Transition-Progress.md`
- `docs/logbook.md`

회귀 위험:

- Cybos proxy 는 실제 runtime baseline replay 가 아니다.
- 따라서 결과가 좋아도 KIS live shadow 나 주문 정책으로 바로 연결하면 안 된다.
- 이번 결과는 더 보수적으로, buy-rescue shadow 를 추가하지 않는 쪽으로만 사용한다.

관련 문서/코드 경로:
`app/models/baseline.py`,
`app/services/research.py`,
`scripts/summarize_cybos_buy_avoid_proxy.py`

## 7. 남은 질문

🟢 다음 단계 권장:

- KIS live buy-avoid shadow 10거래일 누적을 계속한다.
- 장외에 `no-trade decision ledger` 설계를 검토해 baseline 비매수/차단 판단을 나중에 buy-rescue 검증에 쓸 수 있게 한다.
- hold-rescue 는 기존 synthetic lifecycle helper 다음 단계로, 실제 paper replay 또는 Cybos position lifecycle 설계를 별도로 진행한다.

🔴 운영자 판단 필요:

- 없음. 이번 작업은 연구 리포트와 문서 보강이며, 주문 정책 변경을 요구하지 않는다.

관련 문서/코드 경로:
`docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`,
`docs/Production-Transition-Progress.md`
