# Codex Work Ver 20-2: Cybos Buy-Avoid Proxy / Regime Diagnostic

- 작성 시각: 2026-06-14 01:40 KST
- 범위: Cybos 5년치 기반 buy-avoid proxy 와 regime 진단
- 실행 성격: research-only, read-only DB 분석 + 리포트 생성
- 변경 금지 준수: `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음
- 주문 영향: paper/live 주문 로직 변경 없음, 실전 주문/취소 없음

## 1. cowork 의견 반영 방식

cowork 의견을 다음처럼 반영했습니다.

- KIS `down_threshold=0.40` 수치는 Cybos 로 직접 옮기지 않았습니다.
- 구조적 질문만 옮겼습니다: "bar 기반 하락 신호가 높을 때 매수를 회피하면 Cybos 5년에서도 net return 이 개선되는가?"
- Cybos `bar_context_momentum` LightGBM 프로파일을 사용했습니다.
- threshold 는 probability 값이 아니라 skip-rate coverage 로 맞췄습니다.
- KIS shadow 의 down threshold `0.40`이 약 `36.65%`를 회피한 점을 기준으로, Cybos 에서는 target skip `0.20`, `0.30`, `0.3665`, `0.40`, `0.50`을 비교했습니다.
- 기존 `latest-walk-forward-extreme-fold-regimes-h15` 리포트를 먼저 확인했습니다.
  - 해당 리포트는 gate reference 의 극단 fold 원인 진단입니다.
  - 이번 리포트는 Cybos 5년 proxy fold 기준 buy-avoid / regime 진단이라 범위가 다릅니다.
  - 따라서 중복 생성이 아니라 범위를 좁힌 별도 진단으로 진행했습니다.

## 2. 생성/수정한 파일

- 신규:
  - `scripts/summarize_cybos_buy_avoid_proxy.py`
  - `tests/test_cybos_buy_avoid_proxy.py`
  - `docs/cowork-reports/2026-06-14-repo-goal-and-direction-deep-review-work_ver_20-2.md`
- 갱신:
  - `docs/Execution-Plan.md`
  - `docs/Current-Implementation.md`
  - `docs/Production-Transition-Progress.md`
  - `docs/logbook.md`
- 생성된 runtime 리포트:
  - `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.md`
  - `runtime-data/reports/backtests/latest-cybos-regime-performance-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-regime-performance-h15.md`

## 3. Cybos buy-avoid proxy 결과

기준:

- source: `cybos-historical`
- feature set: `bar_context_momentum`
- horizon: `15`
- trade cost: `0.13%`
- folds: `12`
- test rows: `600,000`
- baseline buy policy: `predicted_label=up and probability_up >= 0.58`
- baseline trades: `7,807`

요약:

| target skip | actual skip | baseline net | kept net | net improvement | improved folds | 결론 |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0.2000 | 0.1957 | -538.040362 | -338.768927 | +199.271435 | 11/12 | coverage_out_of_bounds |
| 0.3000 | 0.3018 | -538.040362 | -202.590478 | +335.449884 | 11/12 | follow_up_candidate_proxy_only |
| 0.3665 | 0.3617 | -538.040362 | -170.325157 | +367.715205 | 12/12 | follow_up_candidate_proxy_only |
| 0.4000 | 0.3943 | -538.040362 | -158.311487 | +379.728875 | 11/12 | follow_up_candidate_proxy_only |
| 0.5000 | 0.4916 | -538.040362 | -108.495722 | +429.544640 | 12/12 | follow_up_candidate_proxy_only |

해석:

- Cybos 5년치에서도 buy-avoid 구조는 손실 축소 후보로 보입니다.
- 특히 KIS shadow 회피율과 맞춘 target skip `0.3665`는 12/12 fold 에서 개선됐습니다.
- 하지만 kept net 도 여전히 음수입니다.
- 따라서 이 결과는 `KIS live buy-avoid shadow 를 계속 쌓을 가치가 있다`는 근거이지, 모델 승격, gate 변경, paper/live 주문 정책 변경 근거가 아닙니다.

권장안:

- KIS live buy-avoid shadow 는 계속 최소 2주 또는 10거래일 이상 축적합니다.
- target skip 관점에서 `0.30~0.40` 구간을 우선 관찰합니다.
- `0.50`은 개선폭이 크지만 거래 절반 회피에 가까워, 실전 후보라기보다 상한 민감도 참고값으로 둡니다.

## 4. Cybos regime 진단 결과

정의:

- direction regime:
  - `down_bias <= q30`
  - `up_bias >= q70`
  - 나머지는 `range_bias`
- volatility regime:
  - `high_vol >= q70`
  - `low_vol <= q30`
  - 나머지는 `mid_vol`
- reference skip: `0.3665`

방향 regime:

| regime | folds | accuracy | buy signal net | virtual direction net | buy-avoid delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| down_bias | 4 | 0.507750 | -353.967156 | -477.438125 | +198.786251 |
| range_bias | 4 | 0.551380 | -139.463567 | -276.415815 | +106.176482 |
| up_bias | 4 | 0.543260 | -44.609639 | -457.641040 | +62.752472 |

변동성 regime:

| regime | folds | accuracy | buy signal net | virtual direction net | buy-avoid delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| high_vol | 4 | 0.467210 | -435.709195 | -701.108609 | +220.787918 |
| low_vol | 4 | 0.592190 | -83.605610 | -286.738960 | +94.922602 |
| mid_vol | 4 | 0.542990 | -18.725557 | -223.647410 | +52.004685 |

해석:

- 가장 취약한 구간은 `high_vol` 입니다.
- buy-avoid delta 도 high-vol 에서 가장 큽니다.
- 이는 "고변동 구간에서 모델이 무리하게 매수하는 것을 피하는 필터"가 우선 연구 가치가 있음을 시사합니다.
- 단, 이 결과만으로 regime별 모델을 새로 학습하는 것은 아직 이릅니다.

권장안:

- 새 regime별 모델 학습은 보류합니다.
- KIS live shadow 가 10거래일 이상 쌓인 뒤, high-vol 구간에서도 같은 buy-avoid 개선이 반복되는지 먼저 확인합니다.

## 5. 검증

- `python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py tests/test_cybos_buy_avoid_proxy.py`: 통과
- `python -m unittest tests.test_cybos_buy_avoid_proxy -q`: 3개 통과
- Cybos 전체 proxy 실행: 12/12 fold 완료

## 6. 남은 위험

- Cybos 는 orderbook feature 가 없으므로 KIS live 6피처 LightGBM 과 직접 비교할 수 없습니다.
- Cybos 5년 proxy 에서 손실 축소가 보여도, KIS live 환경의 호가/체결/슬리피지에서는 달라질 수 있습니다.
- buy-avoid 는 거래를 줄이는 전략이므로, 손실 감소와 동시에 missed profit 과 coverage 상한을 계속 봐야 합니다.
- 이번 결과는 `후속 관찰 후보`이지 실전 적용 후보가 아닙니다.

## 7. 다음 단계

권장안:

1. KIS live buy-avoid shadow 를 최소 10거래일 누적합니다.
2. 누적 뒤 아래 기준을 먼저 확인합니다.
   - 연결 표본 `1,000`건 이상
   - 10거래일 중 8거래일 이상 일별 `50`건 이상
   - 5종목 이상, 종목별 `50`건 이상
   - down threshold `0.40` 기준 회피 후보 `200`건 이상, 5거래일 이상 분포
3. 위 기준을 만족하면 KIS live shadow 와 Cybos proxy 를 나란히 비교합니다.
4. 그 뒤에만 high-vol 방어 필터 또는 regime별 모델 필요성을 검토합니다.
