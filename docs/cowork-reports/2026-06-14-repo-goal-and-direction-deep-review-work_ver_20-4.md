# Codex Work Ver 20-4 - Cybos Proxy Buy-Rescue Implementation

- 작성 시각: 2026-06-14 04:20 KST
- 범위: `proxy_buy_rescue` 계산과 통합 rescue report 구현
- 상태: 구현 및 1 fold smoke 완료. full 12 fold 최신 runtime report 는 아직 미생성.

## 1. 이번 작업 결론

결론:

- `baseline_replay_buy_rescue`는 사용하지 않는다.
- Cybos 1차 rescue 는 `proxy_buy_rescue`로 구현했다.
- 기존 `latest-cybos-buy-avoid-proxy-h15`와 `latest-cybos-regime-performance-h15`는 유지한다.
- 같은 script 실행에서 새 `latest-cybos-rescue-proxy-h15.{json,md}`를 추가로 생성한다.
- `hold-rescue`는 결과 실험이 아니라 `hold_rescue_lifecycle_spec`으로만 report 에 남긴다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`

## 2. proxy_buy_rescue 정의

정의:

- no-buy pool: Cybos LightGBM self-filter 기준으로 매수 후보가 아닌 row.
- rescue 후보: no-buy pool 중 `probability_up` 상위 고정 coverage.
- coverage grid: `0.05`, `0.10`, `0.20`, `0.30`.
- 수익 계산: 가상 현물 매수 기준 `future_return_pct - trade_cost_pct`.
- 현재 비용 기준: `0.13%`.

성공 후보 조건:

- rescued trade 최소 `500`건 이상.
- 비용 차감 rescued net 양수.
- fold `2/3` 이상에서 net 이 0 이상.
- 단일 양수 fold 가 전체 양수 fold net 의 `50%`를 넘기면 concentration risk.
- 결과가 좋아도 KIS live shadow 없이 모델 승격, gate 변경, 주문 정책 변경 금지.

관련 문서/코드 경로:
`tests/test_cybos_buy_avoid_proxy.py`

## 3. 구현 변경

변경 전:

- Cybos script 는 buy-avoid 와 regime 진단만 생성했다.
- buy-rescue 는 계획 문서에만 있었고 코드 계산 경로가 없었다.
- hold-rescue lifecycle 분리는 report 에 아직 고정되지 않았다.

변경 후:

- `_up_threshold_for_target_rescue_rate` 추가.
- `_buy_rescue_fold_result` 추가.
- `summarize_rescue_targets` 추가.
- `_overall_rescue_decision` 추가.
- `render_rescue_markdown` 추가.
- CLI 옵션 `--target-rescue-rates` 추가.
- 출력 파일 `latest-cybos-rescue-proxy-h15.json`, `latest-cybos-rescue-proxy-h15.md` 추가.
- rescue report 에 아래를 포함한다.
  - `hypothesis_rank`
  - `multiple_testing_guardrails`
  - `runtime_baseline_replay`
  - `buy_avoid_definition`
  - `buy_rescue_definition`
  - `hold_rescue_lifecycle_spec`

영향 범위:

- `scripts/summarize_cybos_buy_avoid_proxy.py`
- `tests/test_cybos_buy_avoid_proxy.py`
- `docs/Current-Implementation.md`
- `docs/Execution-Plan.md`
- `docs/Production-Transition-Progress.md`
- `docs/logbook.md`

회귀 위험:

- 기존 buy-avoid JSON/MD 파일은 계속 생성되지만, script 실행 시간이 더 길어질 수 있다.
- full 12 fold 실행은 이미 10분 제한을 넘긴 적이 있으므로, 다음에는 저부하 시간에 충분한 timeout 으로 실행하거나 script 성능 최적화가 필요하다.
- 1 fold smoke 결과는 구현 검증일 뿐이며, 모델 판단 근거가 아니다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/`

## 4. 검증

실행:

```bash
python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py tests/test_cybos_buy_avoid_proxy.py
python -m unittest tests.test_cybos_buy_avoid_proxy -q
python -m unittest tests.test_cybos_buy_avoid_proxy tests.test_cybos_research_suite_summary tests.test_expected_value_stability -q
python -m unittest discover -s tests -p "test_*.py" -q
git diff --check
python scripts/summarize_cybos_buy_avoid_proxy.py --horizon-min 15 --feature-set-name bar_context_momentum --trade-cost-pct 0.13 --train-max-rows 500 --walk-forward-test-rows 100 --walk-forward-step-rows 1000 --walk-forward-gap-rows 15 --walk-forward-max-folds 1 --calibration-rows 100 --output-dir .tmp-tests/cybos-rescue-proxy-smoke
```

결과:

- py_compile 통과.
- `tests.test_cybos_buy_avoid_proxy`: 9개 통과.
- 관련 테스트 묶음: 11개 통과.
- 전체 단위 테스트: 395개 통과.
- `git diff --check`: 통과.
- 1 fold smoke 완료.
- smoke report:
  - `review=cybos_rescue_proxy`
  - `decision.status=diagnostic_only_no_rescue_candidate`
  - `runtime_baseline_replay.status=not_replayed_orderbook_features_missing`
  - `buy_rescue_definition.experiment_mode=proxy_buy_rescue`
  - `hold_rescue_lifecycle_spec.status=not_executed_in_this_report`

아직 미완료:

- full 12 fold 최신 runtime report 재생성.

권장안:

- full 12 fold report 는 기능 검증과 별개로 장외 저부하 시간에 충분한 timeout 으로 다시 생성한다.

관련 문서/코드 경로:
`.tmp-tests/cybos-rescue-proxy-smoke/latest-cybos-rescue-proxy-h15.json`

## 5. 다음 단계

권장안:

1. 관련 테스트 묶음과 전체 테스트를 실행한다.
2. full 12 fold 실행 시간이 계속 길면 script 성능 병목을 먼저 줄인다.
3. 그 뒤 full rescue report 를 생성해 buy-rescue 가 실제 12 fold 에서도 후보인지 확인한다.
4. full 결과가 나오기 전까지 KIS live shadow 는 buy-avoid 순차 관측만 유지한다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`
