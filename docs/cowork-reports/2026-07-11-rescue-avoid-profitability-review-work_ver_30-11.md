# Rescue/Avoid Profitability Review Follow-up work_ver_30-11

## 1. 결론

2026-07-11 현재 실제 수익 후보는 없다.

- buy-avoid는 손실을 일부 줄였지만 계좌 기준으로 여전히 큰 적자이고 random control을 통과하지 못했다.
- buy-rescue는 과거의 실제 no-trade 결정 원장이 없어 검증할 수 없었고, 이제부터 정본을 축적한다.
- hold-rescue는 최신 paper replay에서 손실을 늘려 현재 규칙을 기각한다.
- linear-score는 겹치는 신호 손실 합을 더 크게 줄여 보이지만 필터 뒤 절대손익과 평균 기대값이 음수라 LightGBM을 대체할 수익 후보가 아니다.
- 모든 challenger는 강화된 수익성·표본·클래스·portfolio 관문에서 `promotable=false`다.

프로그램은 잘못된 후보를 막는 안전 시스템으로는 개선됐지만, 아직 돈을 버는 전략을 찾지 못했다. 이 사실을 숨기지 않고 평가 정본과 다음 연구 방향을 수익 중심으로 바꿨다.

## 2. 비판적 검토 결과

기존 구조의 가장 큰 문제는 `손실을 덜 냈다`와 `수익이 났다`를 구분하지 못한 점이다.

- 33,007개 분 단위 allowed-buy 신호는 서로 겹치는 15분 미래수익을 포함한다.
- 이 값을 단순 합한 `-3975%`, `+846% 개선`은 계좌 수익률이 아니다.
- baseline 자체가 적자이면 거래를 많이 제거할수록 총손실 합이 줄어드는 착시가 생긴다.
- candidate 조건이 baseline 대비 delta 중심이면 적자 전략도 후보로 보일 수 있었다.
- buy-rescue 모집단도 실제 비매수 결정이 아니라 allowed-buy가 아닌 모든 행을 섞어 safety gate와 포지션 제약을 뒤집을 위험이 있었다.
- `promotable`은 작은 거래 표본과 단일 클래스 쏠림을 충분히 차단하지 못했다.

따라서 신규 threshold 탐색보다 평가 체계를 먼저 고치는 판단이 맞다.

## 3. 구현한 변경

### 3.1 Portfolio replay 정본

- `app/services/portfolio_replay.py`를 추가했다.
- 연속 같은 종목 신호를 decision episode로 묶는다.
- 예측이 완성된 뒤 실행 가능한 다음 분봉 시가를 사용한다.
- 동일 초기 현금, 종목별 최대 비중, 최대 동시 보유, 중복 종목 차단, 정수 주식 수량을 적용한다.
- 수수료, 매도세, 양방향 슬리피지를 반영한다.
- 계좌 수익률, 순손익, 최대낙폭, turnover, 평균 거래 기대값, 일별 일관성을 계산한다.
- 같은 episode 수를 무작위로 제외하는 대조군도 지원한다.

### 3.2 Buy-avoid 판정 강화

`scripts/summarize_lightgbm_defensive_shadow.py` 후보 조건을 다음과 같이 바꿨다.

- signal-row random control 통과
- portfolio random control 통과
- 절대 비용 후 portfolio return 양수
- 평균 거래 기대값 양수
- baseline 대비 delta 양수
- 최소 100 episode/trade
- 최소 10거래일
- 비음수 거래일 2/3 이상
- prediction lineage 완전

early-exit은 같은 bar close가 아니라 다음 분봉 시가를 사용하고 날짜 범위를 동일하게 적용한다. 결과는 미래 구간 검증 전까지 진단 전용이다.

### 3.3 Prediction과 결정 lineage

- baseline, linear-score, centroid, LightGBM serving prediction에 `training_run_id`, `artifact_id`, `artifact_sha256`를 추가했다.
- lineage가 없는 LightGBM artifact는 shadow loader가 거부한다.
- 최신 실제 LightGBM artifact는 세 lineage 필드를 모두 갖고 있어 다음 runtime shadow 저장은 가능하다.
- 과거 lineage 없는 33,007개 joined prediction은 혼합 세대 진단으로만 보며 후보 판정에는 쓰지 않는다.

### 3.4 No-trade decision ledger

- SQLite `serving_decision_ledger`를 추가했다.
- active/shadow 예측과 lineage, 신호, time/spread gate, allocator, 현금, 보유 수량, pending 상태, 주문, 체결 결과를 한 결정에 보존한다.
- buy-rescue는 주문·체결이 없고 time/spread gate를 통과했으며 baseline이 매수를 허용하지 않은 `signal_blocked` 결정만 모집단으로 사용한다.
- 현금, 보유한도, pending, risk/safety gate 차단은 rescue가 뒤집지 않는다.
- 과거 행은 추정 backfill하지 않았다. 현재 0행이고 다음 정규장부터 실제 결정만 쌓인다.

### 3.5 Meta와 challenger gate

- meta-policy에 defensive random control을 필수 입력으로 추가했다.
- 입력 freshness, 데이터 종료일, lineage, random control, 절대수익 양수 portfolio 후보가 없으면 primary candidate를 만들지 않는다.
- challenger `promotable`은 독립 holdout, 최소 30거래, 각 예측 클래스 5% 이상, 다수 클래스 정확도 초과, 비용 후 평균·누적 수익 양수, 현금·포지션 제약 portfolio replay 양수를 모두 요구한다.
- 실제 재평가에서 모든 후보가 `promotable=false`가 됐다.

## 4. 최신 실제 결과

### LightGBM buy-avoid

- 기간: 2026-06-11~2026-07-10, 22거래일.
- joined signal rows: 33,007.
- decision episodes: 15,711.
- threshold `0.40` baseline account return: `-16.4010%`.
- threshold `0.40` filtered account return: `-15.3384%`.
- 차이: `+1.0626%p`.
- filtered 평균 거래 순수익: `-0.10134%`.
- filtered 비음수 거래일 비율: `9.09%`.
- signal-row random verdict: `filter_worse_than_random_p95`.
- lineage: 기존 joined row 33,007개 모두 legacy lineage missing.
- 최종 status: `rejected_random_control`.

해석: 약 93,000원의 손실을 줄였지만 약 134만원 손실이 남았다. 방어 효과 후보조차 무작위보다 낫다고 입증되지 않았고, 수익 전략은 아니다.

### Buy-rescue

- Cybos proxy fixed/precision grid는 모두 비용 후 음수다.
- KIS `serving_decision_ledger`는 신규라 현재 0행이다.
- 과거 overlay의 작은 양수는 실제 no-trade 의사결정이 아니므로 폐기했다.
- 현재 판정: 평가 시작 전, 주문 정책 후보 아님.

### Hold-rescue

- eligible lot: 161.
- threshold `0.40` 적용: 37.
- 현금손익 차이: `-26,387원`.
- 개선 13, 악화 22, unchanged 2.
- 비음수 거래일 비율: `21.43%`.
- 현재 판정: `diagnostic_only_no_hold_rescue_candidate`, 규칙 기각.

### Challenger

- active: `baseline-h15-v1`.
- action: `keep_active`.
- promotion applied: false.
- fresh centroid: 거래 4건, 클래스 쏠림, 다수 클래스 정확도 미달, portfolio 증거 없음.
- linear-score: 거래 156건이지만 평균 `-0.11949%`, 누적 `-18.6402%p`, 클래스/다수 기준과 portfolio 증거 미달.
- LightGBM: 매수 거래 0건, 절대수익과 portfolio 증거 없음.
- 모든 후보: `promotable=false`.

## 5. Codex 의견

현재 가장 큰 병목은 모델 종류가 부족한 것이 아니라 entry baseline의 비용 후 기대값이 음수라는 점이다. buy-avoid만 계속 다듬으면 `덜 잃는 모델`에는 가까워질 수 있어도 `버는 모델`이 되지는 않는다.

따라서 다음 연구는 각 모델을 독립적으로 같은 portfolio replay에 태우고, 비용 후 기대값·하방위험·거래하지 않음을 직접 목표로 해야 한다. entry와 exit도 분리해야 한다. hold-rescue 실패는 entry 확률을 exit 판단에 재사용하는 설계가 약하다는 증거다.

현재 active baseline 유지도 성능 승인 의미가 아니다. 다른 후보가 더 나쁘거나 증거가 없어서 안전하게 유지하는 상태다.

## 6. 다음 진행 방향

1. 다음 정규장부터 decision ledger와 완전한 prediction lineage를 축적한다.
2. 2026-07-20 장후 사전등록 E1/E5 라운드를 고정 기준으로 한 번 실행한다.
3. no-trade ledger는 10거래일에 조기 진단하고 20/30/60거래일에 재현성을 계속 본다.
4. 각 challenger가 동일 현금·포지션·비용 portfolio replay evidence를 직접 생성하도록 승격 파이프라인에 연결한다.
5. 그 뒤 비용 후 기대수익, 하방 quantile, no-trade zone을 직접 목표로 하는 entry 모델과 별도 exit 모델을 사전등록한다.
6. 절대 비용 후 수익이 양수이고 random/기간/종목 구간에서 재현되기 전에는 Phase 2 주문 canary를 시작하지 않는다.

## 7. Cowork 리뷰 요청 시점

이번 변경은 평가 의미, runtime ledger schema, prediction lineage, challenger 승격 gate를 함께 바꾼 cross-cutting 변경이므로 지금 cowork 리뷰가 필요하다.

확인 요청:

- portfolio replay의 비용·현금·보유 제약이 충분한지
- buy-rescue eligibility가 safety/allocator 제약을 올바르게 보존하는지
- lineage 없는 과거 예측을 진단 전용으로 제한한 판단이 타당한지
- challenger promotion gate가 과도하거나 빠진 조건이 없는지
- 2026-07-20 전 실험 동결을 유지하면서 다음 정규장 ledger 축적만 하는 범위가 적절한지

## 8. 검증과 안전 범위

- 전체 unittest: `508 tests OK`.
- 전체 pytest: `508 passed, 67 subtests passed`.
- changed Python compile 통과.
- runtime report와 dashboard build 통과.
- `git diff --check` 통과.
- 실전 주문/취소, KIS 주문 네트워크, threshold/EV tuning, active model, gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, NAS 백업 변경 없음.
