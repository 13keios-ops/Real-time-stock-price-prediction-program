# rescue/avoid profitability review 후속 — work_ver_32

- 작성 시각: 2026-07-12 17:08 KST
- 기준 리뷰: `2026-07-12-rescue-avoid-profitability-review-review_ver_31.md`
- 작업 모드: 일요일 장외, live runtime 정지
- 범위: E6 신 비용 재생성, 비용 세대 메타데이터, 문서·리포트 정합, 전체 회귀
- 제외: 실전 주문/취소, 신규 threshold/EV tuning, h60 주문 정책, active model/gate 변경, `app/risk/`, `config/`, `VERSION`, NAS 백업

## 1. 리뷰에 대한 Codex 판단

review_ver_31의 P0와 P1은 모두 타당하다.

- 과거 E6가 왕복 비용 `0.108%`를 사용했으므로, 2026 보통주 비용 정본 `0.29%`로 반드시 다시 계산해야 했다.
- 편도 수수료 `0.015%`와 편도 슬리피지 3bp는 세금처럼 법정 확정값이 아니다. 브로커 조건과 실제 체결 품질에 따라 달라지는 연구 가정으로 표시해야 한다.
- 구형 리포트와 새 리포트가 섞이지 않도록 비용 세대 식별자가 필요하다.

다만 리뷰의 문구를 한 단계 보수적으로 수정했다.

`median_abs_future_return_pct < 2 * round_trip_cost_pct`는 비용 여유가 얇다는 경고다.
이 조건 하나로 “h15 구조적 흑자 불가”를 증명할 수는 없다.
분포 상위 구간, 신호의 선별력, 거래 빈도, 실제 체결과 portfolio replay가 별도 변수이기 때문이다.

따라서 이번 결론은 아래 두 가지다.

1. 현행처럼 빈번한 h15 진입은 비용에 취약하다.
2. h60의 상대 연구 우선순위는 높아졌지만 주문 정책 전환 근거는 아니다.

## 2. 코드 조치

### 2.1 비용 세대 메타데이터

`app/paper_trading/costs.py`에 공통 메타데이터 생성기를 추가했다.

- 현재 버전: `krx-common-stock-2026-v1`
- 현재 연구 총비용: `0.29%`
- 현재 가정: 편도 수수료 `0.015%`, 매도세 `0.20%`, 편도 슬리피지 3bp
- 구형/custom 버전: `legacy_or_custom_unversioned`
- Phase 2 canary 실측 재검증 필요: `true`

버전은 총비용 숫자만 같다고 현재 버전으로 판정하지 않는다.
수수료, 세금, 슬리피지 세 요소와 총비용이 모두 현재 기본값과 일치해야 한다.

### 2.2 구형 fallback 제거

아래 두 생성기는 diagnostics 파일이 없으면 구형 `0.108%`로 조용히 되돌아갔다.

- `scripts/summarize_lightgbm_defensive_shadow.py`
- `scripts/summarize_model_overlay_comparison.py`

fallback을 공통 현재 비용 `0.29%`로 바꾸고 출처를 `shared_current_default`로 기록한다.
diagnostics 파일이 있으면 그 비용과 원본 report version을 함께 기록한다.

### 2.3 공통 report field

아래 새 리포트에 `cost_model_version`을 기록한다.

- E6 cost/horizon
- LightGBM defensive shadow
- model overlay
- signal IC
- LightGBM buy diagnostics
- LightGBM performance diagnostics
- feature profile/source
- label band/reproducibility
- probability calibration

과거 JSON은 소급 재작성하지 않는다.
새로 생성될 때만 비용 세대가 붙으며, custom 비용은 현재 버전으로 오인되지 않는다.

## 3. 실제 재생성 결과

E6 생성 시각은 `2026-07-12T16:39:50+09:00`이다.

- `trade_cost_pct=0.29`
- `two_x_trade_cost_pct=0.58`
- `cost_model_version=krx-common-stock-2026-v1`
- decision: `kis_live_h15_median_move_below_2x_cost`
- `filter_tuning_only_warning=true`

| 범위 | horizon | rows | 중위 절대변동 | p75 절대변동 | 2배 비용 통과 |
| --- | ---: | ---: | ---: | ---: | --- |
| KIS live | 15분 | 79,422 | 0.376648% | 0.721772% | 아니오 |
| KIS baseline-buy join | 15분 | 33,007 | 0.365344% | 0.699301% | 아니오 |
| KIS live | 60분 | 69,962 | 0.739523% | 1.415094% | 예 |
| KIS baseline-buy join | 60분 | 29,159 | 0.718133% | 1.373365% | 예 |
| Cybos historical | 15분 | 6,219,637 | 0.188324% | 0.367985% | 아니오 |
| Cybos historical | 60분 | 5,473,019 | 0.339847% | 0.655022% | 아니오 |

LightGBM performance diagnostics도 학습·승격 없이 재평가했다.

- `trade_cost_pct=0.29`
- `cost_model_version=krx-common-stock-2026-v1`
- status: `positive_direction_small_sample_insufficient_evidence`
- 양수처럼 보인 threshold 0.66은 9거래뿐이라 후보가 아니다.

Defensive shadow와 model overlay도 재생성했다.

- Defensive shadow: `rejected_random_control`, threshold `0.40`, portfolio return `-36.3645%`, 후보 없음
- Model overlay: LightGBM/linear-score 모두 `observe_only`, `best_policy=None`
- 두 리포트 모두 `trade_cost_pct=0.29`, `cost_model_version=krx-common-stock-2026-v1`

## 4. 쉬운 해석

15분 뒤 가격이 보통 약 0.38% 움직이는데, 보수적으로 필요한 비용 여유는 0.58%로 잡았다.
평범한 15분 움직임은 이 여유에 못 미친다.
매우 잘 고른 상위 구간은 0.72% 정도 움직이므로 가능성이 완전히 0인 것은 아니다.

60분은 보통 약 0.74% 움직여 0.58%보다 크다.
그래서 같은 신호 품질이라면 60분 쪽이 비용을 이길 공간은 더 크다.
하지만 현재 60분 신호가 방향을 잘 맞힌다는 증거와 실제 보유·청산 replay는 없다.

E6의 breakeven win rate는 “이 크기의 평균 이익/손실이라면 비용을 넘기 위해 어느 정도 승률이 필요한가”라는 참고 계산이다.
현재 모델이 그 승률을 달성했다는 뜻이 아니다.

## 5. rescue/avoid에 미치는 영향

- buy-avoid는 여전히 기각이다. 손실을 조금 줄였지만 절대 손익이 음수이고 무작위 회피보다 나쁘다.
- buy-rescue는 실제 no-trade decision ledger가 아직 없으므로 KIS live 수익 후보가 아니다.
- hold-rescue threshold `0.40`은 기존 replay에서 `-26,387원`이라 기각을 유지한다.
- h15 비용 경고 때문에 threshold를 새로 탐색하지 않는다. 같은 데이터에서 숫자만 고르면 과적합 위험이 커진다.
- h60도 바로 rescue/avoid에 붙이지 않는다. h15와 동일한 lineage, random control, portfolio replay 기준으로 비교해야 한다.

## 6. Codex 의견과 다음 방향

이번 결과는 “15분을 버리고 60분으로 가자”가 아니다.
현재 문제를 더 정확히 세 부분으로 나눈 결과다.

1. h15는 거래 빈도를 낮추거나 정말 강한 구간만 고르는 능력이 필요하다.
2. h60은 비용 여유가 있지만 방향 신호와 보유 lifecycle이 검증되지 않았다.
3. 두 horizon 모두 비용 후 절대수익이 양수인 동일 portfolio replay가 최종 정본이어야 한다.

진행 순서는 유지한다.

1. 다음 거래일부터 새 비용·완전 lineage의 decision ledger를 축적한다.
2. Phase 0 paper/KIS 10거래일 정합성을 계속 확인한다.
3. 2026-07-20 장후 사전등록 E1/E5 한 라운드를 실행한다.
4. 그 결과 뒤 h15 저빈도 후보와 h60 후보를 같은 미래 구간, 같은 현금·보유·비용 replay로 비교하도록 사전등록한다.
5. entry 모델과 exit 모델은 별도 목적함수로 설계한다.

보류 기준:

- 07-20 전 신규 threshold/EV tuning 금지
- h60 주문 정책 금지
- 단일 중위값 또는 소표본 양수로 후보 선언 금지
- 실제 신호 정보량이 없으면 비용 필터 튜닝 대신 feature/label/horizon 재설계

다음 cowork 리뷰는 이번 비용 세대 분류와 E6 해석 경계가 타당한지 확인하는 데 유용하다.
그 다음 실질적 연구 리뷰 시점은 2026-07-20 E1/E5 결과와 새 lineage 표본이 나온 뒤다.

## 7. 검증

- 관련 targeted pytest: `32 passed`
- 전체 pytest: `515 passed, 67 subtests passed`
- 전체 unittest: `Ran 515 tests ... OK`
- Python compile: 통과
- `git diff --check`: 통과
- E6 실제 재생성: 통과
- LightGBM performance diagnostics 실제 재생성: 통과
- defensive shadow/model overlay 실제 재생성: 통과
- cleanup: 총 102개, 105,108,302 bytes 정리
- dashboard: `2026-07-12 17:10 KST` snapshot 갱신, server/API 정상
- runtime: `stopped/weekend/paper`, watchdog `running/fresh`
- 보존: `.tmp-tests/codex-ops`, `app/risk/`, `runtime-data/`

## 8. 안전 확인

- 실전 주문/취소: 없음
- KIS 주문 네트워크 호출: 없음
- 모델 학습/승격: 없음
- threshold/EV/gate/active model 변경: 없음
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS` 변경: 없음
- NAS 백업: 실행하지 않음
