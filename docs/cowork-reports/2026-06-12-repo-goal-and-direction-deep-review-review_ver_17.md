# 저장소 전체 심층 리뷰 review_ver_17 + Execution-Plan 검토 (2026-06-12)

## 1. 버전 맥락

- topic: `repo-goal-and-direction-deep-review`
- 이 파일: `2026-06-12-repo-goal-and-direction-deep-review-review_ver_17.md`
- 기준 작업본: `work_ver_17` + 이후 같은 날 logbook 작업 4건(KIS runbook/cooldown 2h, 성능 진단·source experiment, feature/label/calibration 실험, label band 재현성, Execution-Plan 작성)
- 추가 검토 대상: `docs/Execution-Plan.md` (2026-06-12 신설)
- 리뷰 방식: ver_3 P0/P1 전건을 최신 리포트 JSON·코드로 직접 검증, Execution-Plan 전문 검토

## 2. 요약 (핵심 발견 3가지)

1. **모델 심사 체인이 처음으로 유효하게 작동한다.** P0-1~P0-3 모두 실제 닫힘을 확인했고, 특히 anchor 기반 holdout은 6-12 장후 자동화(16:11 challenger run)에서도 자동 유지됐다 — work_ver_17이 스스로 제시한 확인 조건까지 이미 충족. 이번 라운드는 ver_1 이후 가장 실질적인 진전이다.
2. **유효해진 심사가 내린 첫 판정은 "현물 매수 알파 없음"이다.** 6종의 연구 실험이 일관되게 같은 결론을 냈다: 어떤 threshold/피처/라벨/보정 조합에서도 매수 신호의 비용 차감 기대값은 음수, 유일하게 반복되는 단서는 하락/회피 방향 신호다. 이것은 실패가 아니라 시스템이 처음 생산한 진짜 증거이며, 다음 계획은 이 증거를 중심으로 세워져야 한다.
3. **Execution-Plan.md는 우선순위 논리가 옳고 금지선 일관성도 좋으나, 두 가지 공백이 있다**: (a) 매수 알파가 끝내 안 나올 경우의 plan B(하락/회피 신호의 방어적 활용)가 단계로 없고, (b) KIS live 학습 데이터가 약 1개월·6피처·watchlist 소수 종목이라는 "데이터 자체의 한계"가 계획 변수로 다뤄지지 않는다. 한편 paper/KIS mismatch는 1종목에서 5종목으로 오히려 확대됐다.

## 3. ver_3 P0/P1 closure 매핑 (사실 검증 결과)

| 항목 | Codex 주장 | 직접 검증 결과 | 판정 |
|---|---|---|---|
| P0-1 holdout mismatch 구조 해소 | anchor 기반 평가로 닫힘 | 최신 challenger `challenger-h15-20260612161104878936`(장후 자동화)에서 `dataset_scope=challenger_holdout_training_anchor`, LightGBM `independent_challenger_holdout`, anchor_note 확인. holdout 6거래일(6-04~6-11) 21,521행 | **닫힘 + 자동화에서 유지 확인** |
| P0-2 gate walk-forward 재생성 | snapshot DB 경유로 신포맷 생성 | `walk-forward-h15-20260612042842731771`, `parameter_profile=gate_reference_v1`, folds=118, 3분류 0.4163, fold별 신지표 존재 확인. gate는 `needs_review`(성능 미달, 별개 문제) | **닫힘** |
| P0-3 매수 신호 0건 진단 | threshold sweep 리포트 생성 | `latest-lightgbm-buy-signal-diagnostics-h15.json`: `status=no_positive_expected_value_threshold`, 25,091행, `probability_up max=0.572` < 기존 threshold 0.58 → 신호 0건 원인 규명. 0.40~0.57 전 구간 비용 차감 음수 | **닫힘** |
| P0-4 daemon 장중 유지 | 열림 유지 | watchdog state: `status=running`, heartbeat `2026-06-12 23:55` (신선). 단 장중(정규장) 유지 검증은 다음 거래일 필요 | **부분** |
| P1 EGW00201 | cooldown 30분→2시간, 공식 문서 runbook | `BATCH_ORDER_FILL_RATE_LIMIT_COOLDOWN_SECONDS=2.0*60*60` 확인, `docs/KIS-Connection-Runbook.md` 신설. 그러나 6-12 17:29 sync 여전히 `rate_limited`, open order 5건 | **부분** (아래 4-C) |
| P1 373220 원장 추적 | 미착수, 자동 align 안 함 | dual-account match 6-12 16:52 `needs_review`, **only_local mismatch가 3종목 이상으로 확대** | **열림 + 악화** |

추가: 최신 challenger의 `recommended_action`이 `keep_active`→`review_required`로 바뀌었다. 이는 LightGBM이 심사 자격을 회복해 최고 후보가 되었으나 walk-forward gate(`needs_review`, 정확도 0.4163 미달)가 막고 있다는 뜻이다. 승격 신호가 아니며, 자동 승격이 일어나지 않음(`promotion_applied=false`)을 확인했다.

## 4. 모델 연구 결과 종합 — 이번 라운드의 가장 중요한 산출물

6-12 하루에 실행된 연구 실험 6종(buy-signal sweep, 성능 진단, source experiment, feature profile, label band + 재현성, calibration)의 결과를 모으면 결론이 하나로 수렴한다.

- **매수(상승) 방향**: 모든 조합에서 비용 차감 기대값 음수. threshold 0.40에서 1,845건 거래해도 단순합산 -199.8%, 0.50에서 -4.2%. 상승 적중률 16.8~26.5%.
- **하락/회피 방향**: 반복적으로 양수 단서. 하락 적중률 0.578~0.652, 진단 리포트의 하락 예측 321건 단순합산 +106.4%. calibration·source experiment 모두 `positive_downside_direction_candidate_requires_review`.
- **label band 0.40**: 전체 walk-forward에서는 +12.3%로 보이지만 기간 분리 3구간 중 양수 0개 → `not_period_reproducible`. config 변경 보류 판단은 옳다.
- **gate walk-forward fold 분포**: 평균 0.4163이지만 0.118, 0.144 같은 극단 저성능 fold 존재 — 특정 장세(regime)에서 모델이 완전히 무너진다는 단서.

**전략적 시사점 (운영자용 쉬운 설명):** 현재 시스템은 "언제 사야 오를지"는 모르지만 "언제 사면 안 되는지/언제 팔아야 하는지"는 어느 정도 안다. 현물 매수 전용 운용에서 하락 신호는 직접 돈을 벌 수 없지만, (a) baseline의 매수 신호를 거르는 **회피 필터**, (b) 보유 포지션의 **조기 청산 신호**로는 쓸 수 있다. 이 두 가지는 active model 승격 없이 paper에서 바로 검증 가능하다 — 이것이 다음 스프린트의 가장 증거 기반 경로다.

## 5. Execution-Plan.md 상세 검토

### 강점 (계획으로서 신뢰할 만한 부분)

1. **우선순위 논리가 정확하다.** "안전장치가 있어도 기대값이 음수면 안전하게 손실을 반복하는 시스템"(3절) — 이 한 문장이 ver_1 이후 리뷰 흐름의 핵심을 정확히 내재화했다. 모델 트랙(3순위)을 Phase 1a/1b(7-8순위)보다 앞에 둔 것, 18절 "Phase 2를 서두르지 않는 것"도 일관된다.
2. **각 단계에 방법/이유/완료 기준/경로가 있고, 완료 기준이 대부분 검증 가능한 파일 상태로 정의된다.** 특히 3단계 완료 기준(독립 holdout + 3분류 개선 + 클래스 균형 + 비용 차감 양수 + 기간 재현성 동시 충족)은 자기기만을 막는 좋은 설계다.
3. **중단 기준이 있다.** "3회 연속 실험에서 개선 없으면 데이터 소스/라벨 정의/전략 방향 재점검"(7절) — 연구가 무한 반복되는 것을 막는 장치.
4. **금지선·장중 보호·자동 채택 금지가 모든 단계에 일관 적용**되고, 12단계의 cowork 리뷰 시점 절제(작은 변경마다 리뷰하지 않고 안전 영향 큰 지점에서만)도 합리적이다.

### 약점·공백 (보강 권장)

1. **plan B 부재 — 가장 큰 공백.** 3단계의 성공 경로는 "매수 승격 후보 발견" 하나뿐이고, 실패 시 "다시 설계"라고만 되어 있다. 그러나 4절에서 정리했듯 현재 증거는 하락/회피 쪽에 있다. "하락/회피 신호를 회피 필터·조기 청산으로 paper 검증하는 트랙"을 3단계와 4단계 사이에 명시 단계로 추가할 것을 권장한다. 이미 6-12 logbook 스스로 "하락/회피/청산 연구 신호로 분리해서 본다"고 적었으므로 계획판에만 빠져 있는 상태다.
2. **데이터 한계가 계획 변수로 없다.** KIS live 학습 데이터는 2026-05-08~06-12 약 1개월, 60,000행, 피처 6개, watchlist 소수 종목이다. 이 양으로는 어떤 실험도 기간 재현성 기준을 통과하기 어렵다(3구간 분리 시 구간당 ~10거래일). "최소 N거래일/심볼 데이터 축적 전에는 결론을 확정하지 않는다"는 기준과, watchlist 확대(데이터 다양성) 검토를 3단계 방법에 추가해야 한다. 현재 실험들이 '모델이 나쁘다'와 '데이터가 부족하다'를 구분하지 못하고 있다.
3. **1단계 완료 기준과 현실의 충돌.** "이유가 명확한 rate_limited면 완료"로 되어 있으나, 현실은 cooldown 2시간 + 장외 1회 재시도로도 open order 5건·only_local 5종목 mismatch가 누적 중이다. 이 상태가 며칠 더 가면 paper 성과 평가 자체가 왜곡된다(로컬 장부가 브로커와 다른 채로 손익 집계). 1단계에 "mismatch가 N거래일 이상 지속되면 원장 추적을 P0로 격상"하는 시간 기준을 넣을 것을 권장한다.
4. **5단계 lineage 6개월 보존의 용량 설계 부재.** 이번 gate 재생성에 쓴 snapshot이 이미 13.3GB다. 단일 `dev.db`에 6개월 예측-체결 lineage를 쌓으면 대시보드 조회·백업·복구가 모두 느려진다. 보존은 동의하되 아카이브/파티셔닝 방식(예: 월별 분리, D드라이브 아카이브)을 5단계 방법에 추가해야 한다.
5. **2절 출발점 기술 중 "watchdog 실행 중, dashboard 응답 중"**은 작성 시점 사실이나, P0-4(정규장 중 유지)는 검증 전이다. 7단계에 들어 있으므로 치명적이지 않지만, 출발점에 "장중 유지 미검증" 단서가 있으면 더 정직하다.

### 계획과 실행의 정합성

6-12 실제 작업 순서(모델 진단 → 연구 실험 → KIS runbook → 계획 문서화)는 Execution-Plan의 우선순위와 일치한다. 계획이 사후 정당화가 아니라 실제 행동 기준으로 쓰이고 있다는 좋은 신호다. 다만 하루 5개 작업 분량이 work_ver_17 이후 하위 번호(`work_ver_17-1...`) 없이 logbook에만 쌓였다 — 12단계 규칙대로 다음 cowork 전달 전 통합본 1개를 만들면 된다.

## 6. 종합 표

| 영역 | 상태 | 비고 |
|---|---|---|
| 모델 심사 체인 (P0-1~3) | 닫힘 | anchor 자동화 유지까지 확인 |
| 모델 알파 (매수) | 증거상 부재 | 6개 실험 일관. 데이터 부족 가능성 미분리 |
| 모델 알파 (하락/회피) | 후보 단서 반복 | plan B 트랙 신설 권장 |
| gate walk-forward | 신포맷, needs_review | 극단 저성능 fold 원인 분석 가치 |
| paper/KIS 정합성 | **악화** (1→5종목 mismatch) | 시간 기준 격상 규칙 필요 |
| KIS rate limit | 대응 보강, 미해소 | 2h cooldown 실효성 다음 거래일 판정 |
| daemon 유지 (P0-4) | 부분 (현재 running) | 정규장 중 심박 검증 남음 |
| Execution-Plan | 방향 타당 | plan B·데이터 한계·용량 설계 보강 |
| 안전 금지선 | 전 작업 준수 확인 | 자동 승격/config 변경 없음 |

## 7. 다음 단계 권장

| 우선순위 | 항목 |
|---|---|
| Codex P0 | (a) 5종목 only_local mismatch 원장 추적 — 정합성 악화가 현재 가장 시급. order-fill 감사 복구 후 종목별 생성 경로 기록. (b) 다음 거래일 정규장 중 watchdog 심박 + 장후 EGW00201 재발 여부 실측 |
| Codex P1 | (a) Execution-Plan 보강: plan B(하락/회피 신호의 회피 필터·조기 청산 paper 검증 트랙), 데이터 축적 최소 기준, lineage 용량 설계, 1단계 mismatch 시간 격상 규칙. (b) gate walk-forward 극단 저성능 fold(0.118, 0.144)의 기간/장세 특성 분석 |
| Codex P2 | watchlist 확대 검토(데이터 다양성), KIS 포털 공식 호출 제한 수치 확인 |
| 운영자 결정 | (a) plan B 트랙(방어적 신호 활용) 승인 여부 — 매수 알파 연구와 병행할지. (b) 데이터 축적 기간 동안의 기대치 설정 — 향후 수 주는 "승격 후보 발견"보다 "데이터·검증 체계 축적"이 현실적 목표 |

## 8. 신뢰 수준

이번 라운드도 주장-실제 일치율 100%(P0/P1 검증 6건 + 연구 리포트 4건 전건 일치)다. ver_1에서 지적한 "알파 연구 부재"는 단 하루 만에 6종 실험으로 닫혔고, 그 결과 시스템은 처음으로 자신의 예측력에 대한 정직한 증거를 갖게 됐다. 증거의 내용(매수 알파 없음)은 실망스러울 수 있으나, 이를 숨기지 않고 `no_positive_expected_value_threshold` 같은 상태로 고정한 것이 이 시스템의 가장 큰 자산이다. 다음 리뷰 권장 시점: (1) 5종목 mismatch 원장 추적 완료, (2) plan B 트랙 첫 결과, (3) 다음 거래일 장중 daemon·rate limit 실측 — 셋 중 둘 이상이 모인 뒤 work_ver_18 통합본으로.
