# rescue/avoid profitability review 후속 — work_ver_31

- 작성 시각: 2026-07-12 14:22 KST
- 기준 리뷰: `2026-07-11-rescue-avoid-profitability-review-review_ver_30-11.md`
- 작업 모드: 주말 장외, live runtime 정상 정지
- 범위: review 검증, 비용 모델 교정, 평가 gate 보강, 문서/리포트 재생성
- 제외: 실전 주문/취소, threshold/EV tuning, active model/gate 변경, `app/risk/`, `config/`, `VERSION`, NAS 백업

## 1. 리뷰 판단

리뷰의 수치 검산과 큰 방향은 맞았다. 겹치는 신호 퍼센트 합을 계좌 수익률에서 분리하고,
절대 비용 후 수익과 random control을 함께 보라는 판단도 유지한다.

다만 두 항목은 그대로 적용하지 않고 비판적으로 수정했다.

1. `sell_tax_rate=0.00018`은 문서 근거가 부족한 수준이 아니라 실제로 잘못 낮았다.
   2026 국내 보통주의 총 매도세는 KOSPI가 증권거래세 0.05% + 농어촌특별세 0.15%,
   KOSDAQ이 증권거래세 0.20%라 현재 watchlist에는 모두 총 0.20%가 적용된다.
2. "연속 2회 promotable"은 같은 holdout을 두 번 실행해도 채울 수 있어 시간 재현성이 아니다.
   서로 겹치지 않는 평가 구간 최소 2개 증거만 인정하도록 fail-closed로 바꿨다.

공식 근거:
[국가법령정보센터 2026 증권거래세 신고서 작성방법](https://law.go.kr/LSW/flDownload.do?bylClsCd=110202&flSeq=162621569)

## 2. 추가 발견한 P0 오류

- `PaperTradingEngine`과 broker paper fill sync도 `0.00018`을 사용했다.
- paper engine은 매도뿐 아니라 매수 체결에도 세금을 붙이고 있었다.
- LightGBM 연구 비용은 왕복 `0.108%`로 과소 계산됐다.
- Cybos의 고정 `0.13%`는 역사적 구조 비교용이며 2026 KIS 절대수익 정본으로 사용할 수 없다.

과거 체결과 snapshot은 소급 재작성하지 않았다. 2026-07-12 전후 비용 모델은 직접 이어 붙이지 않는다.

## 3. 구현

### 3.1 비용 모델 통합

`app/paper_trading/costs.py`에 아래를 한 곳으로 모았다.

- 비용 모델: `krx-common-stock-2026-v1`
- 편도 수수료: `0.015%`
- 매도세: `0.20%`
- 매수세: `0%`
- 편도 슬리피지 3bp 기준 왕복 연구 비용: `0.29%`

paper engine, broker paper fill sync, LightGBM 연구, portfolio replay가 이 helper를 사용한다.
ETF/ETN 등 상품별 과세는 현재 universe 밖이며 추가 전 별도 분기가 필요하다.

### 3.2 portfolio random control

- executable decision episode에서 같은 veto 개수를 무작위로 제외한다.
- 시행 `200`회, 고정 seed `42`, p95 초과만 통과한다.
- simulation을 생략해도 requested count와 seed를 JSON에 기록한다.
- `docs/Buy-Avoid-Random-Control-Methodology.md`에 §5.5, 9개 candidate 조건,
  현재 비용 정본 anchor와 구형 anchor 단절을 반영했다.

### 3.3 challenger 시간 재현성

- `nonoverlapping_temporal_reproducibility`를 promotion 필수 check로 추가했다.
- 최소 2개 비중복 구간, `passed=true`, `non_overlapping=true`가 모두 필요하다.
- 현재 evidence 생성기가 없으므로 모든 후보는 fail-closed다.
- 실제 생성기 설계 여부는 2026-07-20 E1/E5 결과 뒤 판정한다.

### 3.4 07-20 lineage 표시

- E1은 `legacy_or_mixed_lineage_diagnostic_only`로 기록한다.
- E5는 defensive shadow가 실제 선택한 prediction lineage 상태를 기록한다.
- 두 결과 모두 candidate/policy lineage로 사용할 수 없다고 JSON/Markdown에 명시한다.

### 3.5 소표본 양수 상태 오표기 교정

- threshold grid 중 양수인 행이 하나라도 있으면 거래 수와 무관하게 candidate라고 표시하던 경로를 확인했다.
- 기존 challenger 최소 표본 30거래를 진단 상태에도 재사용했다. 새 threshold나 주문 gate를 만든 것이 아니다.
- 30거래 미만 양수는 `positive_*_small_sample_insufficient_evidence`로 표시하고 수치 자체는 그대로 공개한다.
- 회귀 테스트는 9거래 양수의 후보 차단과 30거래 downside 후보 유지 두 경계를 함께 고정한다.

## 4. 비용 보정 후 실제 결과

LightGBM 진단은 학습이나 승격 없이 저장 artifact를 다시 평가했다.
`trade_cost_pct`는 `0.29`로 바뀌었다.

| 항목 | 구형 비용 결과 | 2026 비용 정본 |
|---|---:|---:|
| baseline 계좌수익 | -16.4010% | -38.1734% |
| threshold 0.40 filtered | -15.3384% | -36.3645% |
| filtered 순손익 | -1,341,838원 | -3,181,241원 |
| baseline 대비 delta | +1.0626%p | +1.8089%p |
| filtered 평균 거래 | 약 -0.101% | -0.285710% |
| filtered 비음수 거래일 | 9.09% | 0/22, 0.0% |

추가 정본 수치:

- joined rows `33,007`
- decision/executable episodes `15,711/15,707`
- baseline 거래 `2,601`, turnover `26,625.37%`
- filtered 거래 `2,477`, turnover `25,435.07%`
- signal-row random excess `+238.2658%p`, z `4.1266`
- signal-row verdict `filter_worse_than_random_p95`
- 최종 status `rejected_random_control`
- portfolio random simulation은 절대수익·기대값·일관성 실패로 미실행

덜 잃게 한 효과는 있으나 잔여 손실이 약 318만원이고 모든 거래일이 음수다.
따라서 buy-avoid는 현재 수익 전략도, 주문 정책 후보도 아니다.

LightGBM 자체의 최신 진단 상태도 다시 확인했다.

- 기본 threshold 0.58: 53거래, 평균 `-0.348534%`, 누적 `-18.472324%p`
- threshold 0.66: 9거래, 평균 `+0.502851%`, 누적 `+4.525659%p`
- 최종 상태: `positive_direction_small_sample_insufficient_evidence`

즉 9건의 양수 관찰은 숨기지 않지만, 수익 후보나 downside 후보로 부르지 않는다.

## 5. challenger 재평가

- active: `baseline-h15-v1`
- recommended action: `keep_active`
- promotion applied: `false`
- top fresh centroid: 거래 4건, 3분류 정확도 `0.314705`, 누적 신호합 `+4.716049%p`
- linear-score: 156거래, 평균 `-0.301488%`, 누적 `-47.032194%p`
- latest LightGBM: 3분류 정확도 `0.346248`, 매수 거래 0건

top 후보의 양수 값은 거래 4건뿐이고 클래스 편향, portfolio replay, 비중복 시간 재현성을
모두 실패했다. 승격 후보가 갑자기 바뀐 것이 아니라 정렬상 첫 행일 뿐이다.

## 6. Codex 의견

이번 리뷰에서 가장 중요한 결론은 모델이 약한 것만이 아니라 비용 모델 자체가 낙관적으로
잘못돼 있었다는 점이다. 이를 바로잡은 뒤 손실이 크게 늘었으므로 "조금만 튜닝하면 수익"이라는
해석은 더 이상 허용할 수 없다.

현재 수익 개선 우선순위는 다음과 같다.

1. 다음 거래일부터 완전 lineage와 no-trade decision ledger를 정확히 쌓는다.
2. 07-20 사전등록 E1/E5로 신호 정보가 재현되는지 확인한다.
3. 그 뒤에만 거래 빈도 축소와 episode 정의 강화 실험을 설계한다.
4. 신호 정보가 없으면 threshold가 아니라 feature/label/horizon 방향을 다시 설계한다.
5. entry와 exit는 별도 목적함수와 별도 replay로 검증한다.

지금 신규 threshold 실험을 늘리는 것은 정답 탐색이 아니라 과거 데이터에 맞춘 숫자 고르기가
될 가능성이 높다. 동결을 유지하는 것이 맞다.

## 7. 남은 한계와 다음 gate

- KIS daily order/fill adapter에는 세금·수수료 분리 필드가 없어 Phase 2 전 canary 계좌 변화와 대조가 필요하다.
- partial fill, 주문 거부, 호가 queue는 portfolio replay에 없다.
- buy-rescue 실제 no-trade ledger는 아직 0행이다. 10거래일 조기 진단 때 decision stage/차단 사유 분포를 먼저 본다.
- temporal evidence 생성기는 07-20 결과 뒤에 설계 여부를 결정한다.
- Phase 0 paper/KIS 10거래일 정합성 누적은 다음 거래일 장후부터 계속한다.
- 다음 cowork 리뷰는 이 비용 교정과 현재 anchor가 타당한지 확인할 때 필요하다.

## 8. 검증

- 관련 pytest: `53 passed`
- 소표본 상태 회귀 pytest: `17 passed`
- 전체 pytest: `513 passed, 67 subtests passed`
- 전체 unittest: `Ran 513 tests ... OK`
- LightGBM performance diagnostics: 정상 완료, `trade_cost_pct=0.29`
- 최신 진단 상태: `positive_direction_small_sample_insufficient_evidence`
- buy-avoid shadow 재생성: 정상 완료, `rejected_random_control`
- challenger 재평가: `keep_active`, `promotion_applied=false`
- dashboard 재생성·응답: 2026-07-12 14:48 KST 정상, `http://127.0.0.1:8765`
- live runtime: `stopped/weekend/paper`
- watchdog: `running/fresh`
- cleanup helper: 테스트 임시물/허용 pycache 86개, 398,891,028 bytes 정리; `.tmp-tests/codex-ops`, `app/risk/`, runtime-data 보존
