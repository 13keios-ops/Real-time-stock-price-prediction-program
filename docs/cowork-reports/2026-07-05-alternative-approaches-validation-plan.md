# 대안 접근 검증 계획 — 예측 강화·수익화 실험 명세 (Codex 실행용)

- 작성: 2026-07-05, cowork(Claude)
- 목적: buy-avoid 해석 잠금이 끝난 지금, "예측을 강화하고 수익이 날 수 있는 구조인지"를 확인하는 실험들을 **결과를 보기 전에 판정 기준을 고정한 상태로** 순서대로 실행한다.
- 전제 필독: `docs/Buy-Avoid-Random-Control-Methodology.md`
- 성격: 전 실험 관측/진단 전용. 주문 정책·gate·active model·`app/risk/`·`config/`·`VERSION` 변경 금지.

---

## 0. 모든 실험에 공통 적용되는 규칙 (하나라도 어기면 그 실험은 무효)

1. **사전 등록(pre-registration).** 각 리포트 JSON에 `preregistered_criteria` 필드를 넣고, 이 문서에 적힌 판정 기준을 그대로 복사해 기록한다. 결과를 본 뒤 기준을 바꾸는 것 금지. 기준을 바꿔야 할 이유가 생기면 다음 관측 구간에서 새 기준으로 다시 실험한다.
2. **무작위 대조군.** 거래 부분집합을 고르는 모든 실험(E2, E3, E4)은 `scripts/buy_avoid_random_control.py`를 그대로 사용한다. 재구현 금지.
3. **다중 비교 보정.** 한 실험 안에서 파라미터 k개를 시험하면 통과 기준 z를 강화한다: k≤2는 1.6449, 3≤k≤5는 2.3263(단측 99%), k>5 금지(파라미터를 줄여라). 시험한 k를 JSON에 기록한다.
4. **look-ahead 금지.** 캘리브레이션(클래스별 평균 수익률, 분위수 경계 등)은 반드시 판정 대상 구간보다 앞선 데이터로만 추정한다. 캘리브레이션/테스트 구간 경계를 JSON에 기록한다.
5. **테스트 필수.** 새 스크립트마다 DB 없이 도는 pytest 파일을 만든다(합성 데이터로 공식 검증). 테스트 없는 스크립트의 결과는 리뷰에서 기각한다.
6. **work_ver 보고.** 실험당 실행 명령, 결과 요약, `preregistered_criteria` 대비 판정을 표로 기록한다.

## Phase 1 — 구조 진단 (먼저. 여기서 걸리면 뒤 실험은 무의미)

### E1. Information Coefficient(IC): 신호에 정보가 있긴 한가

- **질문**: LightGBM의 `probability_down`(그리고 `probability_up`)이 미래 수익률과 순위상관이 있는가. threshold를 어떻게 잡느냐 이전의 근본 질문이다.
- **방법**: shadow 스크립트와 같은 join(KIS live h15, baseline buy 신호)으로 전 표본을 얻는다. **거래일별로** Spearman 순위상관 IC_d = corr(rank(probability_down), rank(future_return_pct))를 계산하고, 일별 IC의 평균과 t-stat(= mean/std × √일수)을 구한다. pooled 전체 상관은 참고용으로만 기록(종목·시간 클러스터링 때문에 과신 금지).
- **산출**: `scripts/summarize_signal_ic.py` → `runtime-data/reports/research/latest-signal-ic-h15.{json,md}` + `tests/test_signal_ic.py`
- **사전 등록 판정**:
  - `mean_daily_ic ≤ -0.02` 그리고 `t_stat ≤ -2.0` → 신호가 올바른 방향(down 확률↑ = 수익률↓). E2/E3 진행 가치 있음.
  - `|mean_daily_ic| < 0.02` 또는 `|t_stat| < 2.0` → **신호 품질 부족**. threshold/EV 튜닝 실험(E2, E3)을 중단하고 피처·모델 개선 트랙으로 전환.
  - `mean_daily_ic ≥ +0.02` 그리고 `t_stat ≥ +2.0` → 역방향 신호 확인. E5(역발상 관찰)로.
- **함정**: Spearman은 동순위(tie) 처리 주의. scipy가 있으면 `scipy.stats.spearmanr`, 없으면 순위 변환 후 Pearson을 직접 구현하고 테스트로 scipy 결과와 대조(작은 고정 배열).

### E6. cost/horizon 구조: 흑자가 산술적으로 가능한 구조인가

- **질문**: 15분 horizon의 평균 가격 변동폭이 왕복 비용 0.108%를 감당할 수 있는가. baseline 평균이 -0.106%인 이유가 모델이 아니라 비용 구조일 가능성 확인.
- **방법**: `feature_labels`에서 h15의 `|future_return_pct|` 분포(평균, 중위, p75, p90)를 구하고, `2×trade_cost` 및 `label_threshold(0.35)`와 비교한다. breakeven 필요 승률 = cost 포함 손익분기 적중률을 클래스별 평균 수익폭으로 계산한다. DB에 h30/h60 라벨이 있으면 같은 표를 만들고, 없으면 "라벨 없음"만 기록(라벨 신규 생성은 이번 범위 아님 — 장시간 작업 금지선).
- **산출**: `scripts/summarize_cost_horizon_diagnostics.py` → `runtime-data/reports/research/latest-cost-horizon-diagnostics.{json,md}` + 테스트
- **사전 등록 판정**:
  - h15 `median(|future_return|) < 2×0.108 = 0.216%` 이면 → "h15에서는 중위 거래가 왕복 비용을 못 넘는다: 필터 튜닝만으로 흑자 전환 불가" 구조 결론을 명기.
  - 이 경우 향후 트랙 우선순위를 (a) horizon 연장 검토, (b) 거래 빈도 축소(고신뢰 신호만), (c) 비용 재협상/체결 개선 순으로 운영자에게 보고.

## Phase 2 — 필터 개선 실험 (Phase 1을 통과했거나, 통과 실패의 정도를 보고 운영자가 진행 승인한 경우만)

### E2. EV(기댓값) 기반 필터 shadow

- **질문**: 단일 threshold 대신 3클래스 확률 전부를 쓰면 무작위 대조군을 이기는가.
- **방법**: `EV = p_up·r̄_up + p_flat·r̄_flat + p_down·r̄_down − cost`. 클래스별 평균 수익률 r̄는 **캘리브레이션 구간(2026-06-11~06-24)**에서만 추정하고, **판정은 테스트 구간(06-25~07-03)**에서만 한다. skip 규칙: `EV < 0`. 커버리지가 0.05 미만이거나 0.60 초과면 "커버리지 부적합"으로 자동 기각.
- **산출**: `scripts/summarize_ev_filter_shadow.py` → `runtime-data/reports/research/latest-ev-filter-shadow-h15.{json,md}` + 테스트. 리포트 구조는 shadow 리포트와 동일(baseline/filtered/skipped/random_control).
- **사전 등록 판정** (k=1이므로 z 1.6449):
  - 테스트 구간 random_control verdict = `filter_better_than_random_p95` → 통과. 07-04~07-18 out-of-sample 재검으로.
  - 그 외 → 미통과 기록. EV 변형 재시도는 다음 관측 구간에서.
- **함정**: r̄ 추정에 테스트 구간 데이터가 한 건이라도 섞이면 무효. 구간 경계를 JSON `calibration_range`/`test_range`로 기록.

### E3. regime 조건부 필터 (고변동 구간 한정)

- **질문**: 전 구간 일괄 적용이 아니라 고변동 구간에서만 걸면 통과하는가 (Cybos 진단에서 high_vol이 가장 취약했음).
- **방법**: 전이성 리뷰와 같은 정의로 최근 15분 실현변동성 상위 30%(경계는 캘리브레이션 구간 분위수로 고정)를 high_vol로 분류. **high_vol 부분집합 안에서만** down_threshold 0.40 필터를 적용.
- **⚠ 최대 함정**: 무작위 대조군의 모집단도 **high_vol 부분집합**이어야 한다. 전체 모집단으로 대조군을 만들면 비교가 무효다. `random_control_report(high_vol_returns, n_skip_in_highvol, ...)` — 이 부분을 테스트로 강제할 것.
- **산출**: `scripts/summarize_regime_conditional_shadow.py` → `latest-regime-conditional-shadow-h15.{json,md}` + 테스트
- **사전 등록 판정** (변동성 경계 1개 × threshold 1개 = k=1, z 1.6449): high_vol 내 random_control verdict better → 통과. low/mid_vol에는 적용하지 않는다.

### E4. 단순 규칙 벤치마크 (ML 없이)

- **질문**: "최근 변동성 상위 X% 회피" 같은 해석 가능한 규칙이 ML 필터보다 나은가. ML의 존재 가치 확인용 벤치마크.
- **방법**: 규칙 2개만 시험(k=2, z 1.6449): (a) 최근 15분 실현변동성 상위 30% 회피, (b) `spread_bps` 상위 30% 회피. 경계는 캘리브레이션 구간 분위수. 같은 리포트 구조 + random_control.
- **산출**: `scripts/summarize_rule_filter_shadow.py` → `latest-rule-filter-shadow-h15.{json,md}` + 테스트
- **사전 등록 판정**: 규칙이 통과하고 ML(E2/E3)이 미통과면 → "ML 필터 대신 규칙 기반 관측 전환"을 운영자 결정 안건으로 상정. 둘 다 미통과면 필터 트랙 전체를 보류하고 Phase 1 결론(구조 문제)으로 회귀.

## Phase 3 — 관찰만 (실행 금지)

### E5. 역발상(신호 반전) 재현성 관찰

- **질문**: KIS live에서 down 신호가 오히려 나은 거래를 가리키는 역선별(excess>0, z+4.6)이 다음 구간에도 반복되는가.
- **방법**: 07-18 장후, 07-04~07-18 구간만으로 shadow 리포트를 다시 뽑아 threshold 0.40의 excess 부호와 z를 기록. **새 코드 불필요** — 기존 스크립트에 기간 필터 옵션(`--start-date/--end-date`)만 추가.
- **사전 등록 판정**: 2개 구간 연속 `excess > 0` 그리고 `z ≥ +1.6449` → "역발상 가설 수립"까지만 허용. 정책 검토는 3구간 연속 + 운영자 명시 승인 후에만. 그 전에 반전 신호로 주문 로직을 만드는 것 절대 금지.

## 실행 순서와 요약표

| 순서 | 실험 | 선행 조건 | 신규 스크립트 | 판정 통과 시 | 판정 실패 시 |
|---|---|---|---|---|---|
| 1 | E1 IC | 없음 | summarize_signal_ic.py | E2/E3 진행 | 필터 튜닝 중단, 피처/모델 트랙 |
| 2 | E6 cost/horizon | 없음 | summarize_cost_horizon_diagnostics.py | 필터 트랙 유효 | "구조적 흑자 불가" 보고, 우선순위 재편 |
| 3 | E2 EV 필터 | E1 통과 | summarize_ev_filter_shadow.py | 07-04~07-18 재검 | 다음 구간 재시도 |
| 4 | E3 regime 조건부 | E1 통과 | summarize_regime_conditional_shadow.py | 07-04~07-18 재검 | 기록 후 종료 |
| 5 | E4 규칙 벤치마크 | 없음 (E2/E3와 병행 가능) | summarize_rule_filter_shadow.py | ML 대비 비교표 | 필터 트랙 보류 |
| 6 | E5 역발상 관찰 | 07-18 이후 | 없음 (기간 옵션만) | 가설 수립 | 가설 폐기 |

## Codex에게 — 작업 방식

1. 한 work_ver에 실험 1~2개까지만. E1+E6을 work_ver_25로 묶는 것을 권장.
2. 각 실험 전에 이 문서의 해당 절과 방법론 문서를 읽고, `preregistered_criteria`를 코드에 하드코딩으로 넣어라(런타임 인자로 바꿀 수 있게 하지 말 것).
3. 모든 신규 리포트는 `runtime-data/reports/research/` 아래에. 기존 리포트 덮어쓰기 금지.
4. 기존 금지선 전부 유지: app/risk/, config/, VERSION, ALLOW_LIVE_ORDERS, gate 임계값, 자동 commit/push, 장시간 재학습.
5. cowork 리뷰 요청 시점: Phase 1 완료 직후(E1·E6 결과가 이후 방향을 결정하므로).
