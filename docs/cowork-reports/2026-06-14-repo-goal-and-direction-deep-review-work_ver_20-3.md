# Codex Work Ver 20-3 - Cybos Baseline Replay Step 0

- 작성 시각: 2026-06-14 03:05 KST
- 범위: cowork 리뷰 후 Step 0 확인과 반영
- 상태: 코드/문서 반영 완료. 모델, gate, 주문 정책 변경 없음.

## 1. 확인한 질문

cowork 리뷰의 핵심 질문은 다음이었다.

- `app.models.baseline.BaselineDirectionModel`이 Cybos bar feature row 에서 바로 예측 가능한가?
- 가능하다면 `baseline_replay_buy_rescue`로 갈 수 있는가?
- 불가능하다면 `proxy_buy_rescue`로 명시해야 하는가?

관련 문서/코드 경로:
`app/models/baseline.py`,
`app/services/research.py`,
`scripts/summarize_cybos_buy_avoid_proxy.py`

## 2. 코드 기준 결론

결론:

- `BaselineDirectionModel` 호출 자체는 가능하다.
- 하지만 Cybos bar row 에 live orderbook 피처가 없으므로 runtime baseline replay 로 인정할 수 없다.
- 따라서 1차 Cybos rescue 실험은 `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로 진행해야 한다.

근거:

- `BaselineDirectionModel` 사용 피처:
  - `return_1m_pct`
  - `bid_ask_imbalance`
  - `spread_bps`
- Cybos bar row 생성 경로:
  - `return_1m_pct`는 생성한다.
  - `bid_ask_imbalance`, `spread_bps`는 생성하지 않는다.
- 모델은 누락 피처를 기본값 `0.0`으로 처리하므로 예외 없이 실행될 수 있다.
- 그러나 이 값은 실제 KIS live orderbook 이 반영된 runtime baseline 이 아니다.

관련 문서/코드 경로:
`app/models/baseline.py`,
`app/services/research.py`

## 3. 반영한 변경

변경 전:

- Cybos buy-avoid report 의 `baseline`이 실제 runtime baseline 처럼 오해될 수 있었다.
- Step 1에서 `baseline_replay_buy_rescue`와 `proxy_buy_rescue` 중 어느 쪽으로 갈지 코드로 잠겨 있지 않았다.

변경 후:

- `scripts/summarize_cybos_buy_avoid_proxy.py`에 `runtime_baseline_replay` 메타데이터를 추가했다.
- Cybos report 는 앞으로 아래 값을 기록한다.
  - `available=false`
  - `status=not_replayed_orderbook_features_missing`
  - `recommended_experiment_mode=proxy_buy_rescue`
- markdown report 에도 `baseline`은 Cybos LightGBM self-filter candidate set 이며 runtime baseline order decision 이 아니라고 표시한다.
- `tests/test_cybos_buy_avoid_proxy.py`에 orderbook 피처 누락 시 runtime baseline replay 를 금지하는 테스트를 추가했다.

영향 범위:

- `scripts/summarize_cybos_buy_avoid_proxy.py`
- `tests/test_cybos_buy_avoid_proxy.py`
- `docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`
- `docs/Execution-Plan.md`
- `docs/Production-Transition-Progress.md`
- `docs/logbook.md`

회귀 위험:

- 기존 JSON consumer 가 새 필드를 몰라도 기존 필드는 유지되므로 하위 호환 위험은 낮다.
- 다만 기존 report 를 사람이 읽을 때 과거 `baseline` 표현을 잘못 해석할 수 있어, 다음 report 재생성 때 새 metadata 를 포함시키는 것이 좋다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`tests/test_cybos_buy_avoid_proxy.py`

## 4. 검증

실행:

```bash
python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py tests/test_cybos_buy_avoid_proxy.py
python -m unittest tests.test_cybos_buy_avoid_proxy -q
python -m unittest tests.test_cybos_buy_avoid_proxy tests.test_cybos_research_suite_summary tests.test_expected_value_stability -q
python -m unittest discover -s tests -p "test_*.py" -q
git diff --check
python scripts/summarize_cybos_buy_avoid_proxy.py --horizon-min 15 --feature-set-name bar_context_momentum --trade-cost-pct 0.13 --train-max-rows 500 --walk-forward-test-rows 100 --walk-forward-step-rows 1000 --walk-forward-gap-rows 15 --walk-forward-max-folds 1 --calibration-rows 100 --output-dir .tmp-tests/cybos-buy-avoid-proxy-smoke
```

결과:

- py_compile 통과.
- `tests.test_cybos_buy_avoid_proxy`: 5개 통과.
- 관련 테스트 묶음: 7개 통과.
- 전체 단위 테스트: 391개 통과.
- `git diff --check`: 통과.
- 1 fold smoke report 에서 `runtime_baseline_replay.status=not_replayed_orderbook_features_missing`와 `recommended_experiment_mode=proxy_buy_rescue` 출력 확인.

미완료:

- 전체 Cybos 12 fold runtime report 재생성은 10분 제한 안에 끝나지 않아 중단했다.
- 기존 `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`은 아직 `generated_at=2026-06-14T01:38:54+09:00` 산출물이라 새 metadata 는 없다.

권장안:

- 다음 장외 저부하 시간에는 `latest-cybos-buy-avoid-proxy-h15` full report 를 다시 생성해 새 metadata 를 runtime report 에도 반영한다.
- Step 1 구현은 full report 재생성 완료 여부와 독립적으로 진행 가능하지만, 결과 리포트에는 반드시 `proxy_buy_rescue`를 명시한다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`

## 5. 다음 단계

권장안:

1. `proxy_buy_rescue` helper 를 설계한다.
2. coverage 후보는 계획 문서 기준 `0.05`, `0.10`, `0.20`, `0.30`으로 고정한다.
3. 결과 label 은 `follow_up_candidate_proxy_only`, `sample_insufficient`, `coverage_out_of_bounds`, `fold_concentration_risk` 중 하나로 제한한다.
4. `hold-rescue`는 아직 구현하지 말고 lifecycle spec 과 synthetic test 부터 만든다.

관련 문서/코드 경로:
`docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`,
`scripts/summarize_cybos_buy_avoid_proxy.py`
