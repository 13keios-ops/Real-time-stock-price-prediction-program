# Execution Plan

이 문서는 지금부터 어떤 순서로 작업할지, 각 단계에서 무엇을 어떻게 하고 왜 하는지를 정리한 실행 계획판이다.
큰 방향은 `docs/Roadmap.md`가 담당하고, 현재 상태판은 `docs/Production-Transition-Progress.md`가 담당한다.
이 문서는 매 작업에서 실제 다음 행동을 고르는 기준으로 쓴다.

## 1. 기본 원칙

- 현재 기본 운용은 실전 자동매매가 아니라 `paper` 검증이다.
- 실전 주문 플래그, gate 기준값, `app/risk/`, `config/`, `VERSION`은 이 계획 실행 중 임의로 바꾸지 않는다.
- 장중 수집 보호 모드에서는 코드 변경, 전체 테스트, 대시보드 재생성, live DB를 무겁게 읽는 작업을 피한다.
- 새 캐시, 다운로드, 연구 스냅샷, 대용량 산출물은 D드라이브 기준 경로에 둔다.
- 운영자는 Codex나 Claude cowork가 아니라 계좌 소유자 또는 실전 운용 승인권자를 뜻한다.
- 판단이 필요한 항목은 가능하면 권장안을 먼저 적용하고, 실제 계좌 권한, 비밀값, 실전 주문처럼 물리적으로 필요한 승인만 운영자에게 요청한다.

관련 문서/코드 경로:
`AGENTS.md`,
`docs/Codex-Operating-Feedback.md`,
`docs/Production-Transition-Progress.md`

## 2. 현재 출발점

2026-06-12 기준 현재 출발점은 아래와 같다.

- live runtime: 정규장 종료 후 정지 상태가 정상이다.
- runtime watchdog: 실행 중이다.
- dashboard: `http://127.0.0.1:8765`에서 응답 중이다.
- 단, watchdog/dashboard가 정규장 중 장시간 유지되는지는 다음 거래일 장중 증거가 필요하다.
- trading mode: `paper`.
- active model: 15분/60분 모두 baseline 계열이다.
- LightGBM: shadow와 연구 대상이며 실전 또는 paper 주문 판단에 쓰지 않는다.
- 최신 모델 판단:
  - LightGBM은 독립 holdout 심사 자격은 회복됐다.
  - 매수 신호 기대값은 아직 양수가 아니다.
  - label band `0.40`은 전체 walk-forward에서는 좋아 보였지만 기간별 재현성이 없어 정책 변경 후보가 아니다.
- 최신 운영 판단:
  - KIS `EGW00201` rate limit 과 broker paper order-fill 복구는 계속 관찰 대상이다.
  - paper/KIS local-only mismatch 원장은 자동으로 덮지 않고 추적한다.

관련 문서/코드 경로:
`runtime-data/reports/challengers/latest-challengers-h15.json`,
`runtime-data/reports/challengers/latest-lightgbm-label-band-reproducibility-h15.json`,
`runtime-data/reports/broker-paper/latest-sync.json`,
`runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`

## 3. 전체 우선순위

작업 순서는 아래가 기본이다.

1. 장중 수집과 자동화가 정상인지 먼저 확인한다.
2. Phase 0의 paper/KIS 정합성 blocker를 줄인다.
3. 모델 성능개선 트랙을 먼저 진행해 실전 운용할 가치가 있는 신호인지 확인한다.
4. 매수 알파가 없을 때는 하락/회피 신호를 방어적으로 쓰는 plan B를 검증한다.
5. 모델 평가, shadow, 승격 심사 체인을 안정화한다.
6. 예측, 신호, 주문, 체결, 손익을 한 줄 lineage로 보존한다.
7. 대시보드는 운영자가 바로 이해할 수 있게 계속 단순화한다.
8. Phase 1a/1b read-only readiness를 최신 증거로 반복한다.
9. Phase 2 canary는 모델과 운영 blocker가 닫힌 뒤에만 시작한다.
10. Phase 3 다종목 운용은 Phase 2 관측 뒤에만 검토한다.

이 순서의 이유는 명확하다.
실전 주문 안전장치가 있어도 모델의 비용 차감 기대값이 음수이면 안전하게 손실을 반복하는 시스템이 된다.
반대로 모델 후보가 좋아 보여도 paper/KIS 정합성, rate limit, 감사 원장이 불안정하면 실제 운용에서 원인 추적이 어렵다.

관련 문서/코드 경로:
`docs/Production-Architecture.md`,
`docs/Production-Implementation-Blueprint.md`,
`docs/Current-Implementation.md`

## 4. 0단계: 작업 전 안전 확인

### 방법

- 작업 시작마다 아래 상태를 먼저 확인한다.

```bash
./scripts/get_live_runtime_status.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/get_dashboard_status.sh
git status --short --branch
```

- `regular-session`, 실제 `pre-open`, `live_runtime_should_run=true`, live runtime 실행 중이면 장중 수집 보호 모드로 전환한다.
- 장중 보호 모드에서는 read-only 점검, 문서 정리, 좁은 격리 테스트만 한다.
- 장후 또는 장외에만 코드 변경, 전체 테스트, dashboard rebuild, heavy research를 진행한다.

### 이유

장중 수집은 모델 개선보다 우선이다.
수집 중인 DB를 무겁게 읽거나 프로세스를 재시작하면 당일 데이터와 paper 검증 흐름이 깨질 수 있다.

### 완료 기준

- 현재 장 상태, watchdog, dashboard, git 상태가 작업 시작 기록에 남는다.
- 장중이면 변경 작업을 멈추고 안전한 범위만 수행한다.

관련 문서/코드 경로:
`scripts/get_live_runtime_status.sh`,
`scripts/get_runtime_watchdog_status.sh`,
`scripts/get_dashboard_status.sh`

## 5. 1단계: Phase 0 paper/KIS 정합성 안정화

### 방법

- 장후에 broker paper sync 리포트와 dual account match 리포트를 확인한다.
- KIS `EGW00201`이 있으면 cooldown 동안 같은 order-fill endpoint를 반복 호출하지 않는다.
- cooldown 이후 장외에 1회만 재시도하고, 계속 rate limit이면 호출량 자체를 줄이는 설계로 넘어간다.
- local-only position은 marker-only alignment로 즉시 덮지 않고 주문, 체결, 청산 원장을 먼저 추적한다.
- 실제 브로커 계좌 스냅샷과 local paper 상태가 일치할 때만 alignment를 고려한다.
- mismatch가 다음 거래일 장후까지 이어지거나 1회 cooldown 뒤에도 close fill 회수가 안 되면 P0 운영 blocker로 격상한다.
- mismatch가 남아 있는 동안에는 paper 손익과 모델 성과를 확정값처럼 해석하지 않는다.

### 이유

실전 전환 전에는 주문이 언제, 왜, 어떻게 체결됐는지 내부 기록과 브로커 기록이 맞아야 한다.
정합성 문제를 alignment로 덮으면 나중에 손익, 세금, 슬리피지, 모델 평가가 모두 흔들린다.

### 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

- 변경 전:
  - rate limit 이후 같은 order-fill 조회를 반복할 수 있고, mismatch 원인을 보기 전에 alignment 욕구가 생긴다.
- 변경 후:
  - cooldown과 단일 재시도 기준을 지키고, mismatch는 원장 추적으로 닫는다.
- 영향 범위:
  - broker paper sync, reconciliation, dashboard 계좌 카드, logbook 기록.
- 회귀 위험:
  - 너무 보수적으로 멈추면 당일 paper 상태가 오래 `needs_review`로 남을 수 있다.
  - 이 경우 자동 덮기보다 원장 추적을 우선한다.

### 완료 기준

- 최신 `latest-sync.json`이 `ok`, `no_submissions`, 또는 이유가 명확한 `rate_limited` 상태다.
- 최신 `latest-paper-dual-account-match.json`의 mismatch가 없거나, 남은 mismatch에 원장 원인이 붙어 있다.
- 대시보드 계좌 탭에 현재 상태와 이유가 통화 단위로 표시된다.
- `scripts/trace_paper_kis_mismatch.py`가 종목별 최신 local order, broker submission, broker status snapshot을 read-only 리포트로 남긴다.

관련 문서/코드 경로:
`app/services/broker_paper_sync.py`,
`scripts/trace_paper_kis_mismatch.py`,
`scripts/reconcile_paper_accounts.sh`,
`scripts/verify_paper_dual_account_match.sh`,
`runtime-data/reports/reconciliation/`

## 6. 2단계: KIS 연결 안정화

### 방법

- KIS 공식 포털과 공식 샘플 기준으로 REST rate limit, WebSocket reconnect, token refresh 기준을 계속 문서화한다.
- `EGW00201`은 단순 재시도보다 호출량 관리와 cooldown을 우선한다.
- WebSocket disconnect는 reconnect storm 여부, stable frame 여부, watchdog heartbeat를 함께 본다.
- 모의투자와 실전 read-only의 응답 shape 차이는 raw response 없이 sanitized shape만 기록한다.

### 이유

KIS 연결 문제는 모델 성능과 무관하게 실전 운용을 멈출 수 있다.
특히 모의투자 REST 제한은 짧은 시간에 여러 조회를 반복하면 쉽게 막힐 수 있으므로, 장애를 더 키우지 않는 방식이 필요하다.

### 완료 기준

- KIS 연결 문제별 runbook이 최신 코드 동작과 맞는다.
- rate limit 발생 시 dashboard와 logbook에 상태, 다음 재시도 가능 시점, 보류 주문 수가 보인다.
- token/account/system clock read-only probe가 비밀값 없이 증거를 남긴다.

관련 문서/코드 경로:
`docs/KIS-Connection-Runbook.md`,
`app/brokers/`,
`scripts/probe_kis_token_refresh.sh`,
`scripts/probe_kis_account_snapshot.sh`,
`scripts/probe_kis_clock_reference.sh`

## 7. 3단계: 모델 성능개선 스프린트

### 방법

2026-06-13 cowork 보정 기준으로, 다음 모델개선은 새 학습 실험을 즉시 늘리지 않고
`buy-avoid` shadow 관측과 재검증 기준 정의를 먼저 끝낸다.
현재 KIS live 데이터는 약 1개월 수준이고 label band 재현성에서 이미
`not_reproducible` 위험이 확인됐으므로, 보합 regime 분리나 변동성 구간별 모델 분리는
데이터 기준을 채운 뒤 진행한다.

아래 순서로 진행한다.

1. 최신 KIS live 데이터 품질을 확인한다.
   - feature/bar 비율이 1.0에 가깝고 공백이 15:20~15:29 종가 동시호가에 몰려 있으면 feature pipeline 장애로 단정하지 않는다.
   - raw market coverage 만 약하고 orderbook coverage 는 유지되면, KIS WS 전체 중단보다 체결 tick 기반 분봉 약화 또는 일부 stream 지연 후보로 본다.
   - 같은 약한 구간이 재발하면 `watchdog` heartbeat, KIS WS frame, `latest-kis-live-data-quality.json`의 raw market/orderbook coverage 를 함께 비교한다.
2. 기존 LightGBM artifact를 재사용해 3분류 정확도, 클래스별 적중률, 혼동행렬, 매수 신호 기대값, 가상 방향 수익률을 재평가한다.
3. 2026-06-12에 완료한 feature source, feature profile, label band, calibration 실험은 1차 개선시험으로 본다. 현재 결과는 채택 후보가 아니라 `관찰 후보`다.
4. 즉시 다음 단계는 새 학습 실험이 아니라 `buy-avoid` shadow 관측이다.
   - 기존 LightGBM shadow serving 예측과 baseline 매수 허용 신호를 이용해, 실제 주문 판단은 바꾸지 않고 매수 회피 후보 성과를 누적한다.
   - 최소 관측 기간은 2주 또는 10거래일이다.
   - 관측 기간 중 active model, gate 기준값, 주문 판단, `config/` label threshold 는 바꾸지 않는다.
5. walk-forward 재검증은 아래 조건을 모두 만족할 때 다시 실행한다.
   - KIS live h15 labeled row 가 최소 `60,000`행 이상이다.
   - KIS live 고유 거래일이 최소 `30거래일` 이상이다.
   - buy-avoid shadow 관측이 최소 `10거래일` 이상 쌓였다.
   - baseline 매수 허용 신호와 LightGBM shadow 예측이 같은 종목/시각으로 충분히 연결되어, 회피/미회피 표본을 비교할 수 있다.
   - 연결 표본 충분성은 아래 숫자를 모두 만족해야 `충분`으로 본다.
     - `matched_buy_shadow_rows`: baseline 매수 허용 신호와 LightGBM h15 shadow 예측, 닫힌 h15 label 이 같은 `symbol/event_time`으로 연결된 행이 최소 `1,000`건 이상.
     - `matched_trade_days`: 연결 표본이 있는 거래일이 최소 `10거래일`이고, 그중 최소 `8거래일`은 일별 연결 표본이 `50`건 이상.
     - `matched_symbols`: 연결 표본이 있는 종목이 최소 `5`종목이고, 각 종목별 연결 표본이 `50`건 이상.
     - `avoid_candidate_rows`: 기준 down threshold `0.40`에서 매수 회피 후보가 최소 `200`건 이상이고, 최소 `5거래일`에 걸쳐 분포.
   - 위 조건 중 하나라도 부족하면 모델 실패로 단정하지 않고 `표본 부족`으로 분류해 관측을 연장한다.
6. Cybos 5년 buy-avoid proxy 는 KIS shadow 를 대체하지 않는 장외 보조 진단으로만 쓴다.
   - KIS `down_threshold=0.40` 수치를 Cybos 로 직접 옮기지 않는다.
   - Cybos 에서는 `bar_context_momentum` 기반 하락확률을 사용하되, threshold 는 skip-rate coverage 로 맞춘다.
   - 실용 coverage 는 `20~50%`, KIS shadow 비교 중심 구간은 `30~40%`다.
   - 성공 후보는 비용 `0.13%` 반영 뒤 순손익 개선, coverage 구간 내 위치, 전체 fold 중 최소 `2/3` 이상 개선을 동시에 만족해야 한다.
   - 최신 `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json` 기준 target skip `0.3665`는 실제 skip `0.3617`, baseline net `-538.040362%p`, kept net `-170.325157%p`, 개선 `+367.715205%p`, 개선 fold `12/12`로 구조적 손실 축소 후보를 지지한다.
   - 단, 필터 뒤 kept net 도 아직 음수이므로 이 결과는 `buy-avoid shadow 지속` 근거이지 모델 승격, gate 변경, 주문 정책 변경 근거가 아니다.
7. Cybos regime 분해는 새 모델을 만들기 전 진단으로만 쓴다.
   - 최신 `runtime-data/reports/backtests/latest-cybos-regime-performance-h15.json` 기준 고변동 구간은 정확도 `0.467210`, buy signal net `-435.709195%p`로 가장 약하고, reference skip `0.3665`의 buy-avoid delta 는 `+220.787918%p`다.
   - 기존 `latest-walk-forward-extreme-fold-regimes-h15`는 gate reference 의 극단 fold 분석이고, Cybos regime report 는 5년 proxy fold 진단이라 중복 리포트가 아니라 범위가 다르다.
   - regime별 모델 분리나 보합 전용 모델은 이 진단과 KIS live shadow / walk-forward 재검증을 함께 본 뒤 결정한다.
8. Cybos buy-rescue 는 `docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md` 기준으로만 진행한다.
   - Cybos 5년 백테스트에서는 `buy-avoid`와 `buy-rescue`를 같은 리포트에서 함께 보되, 사전에 정한 threshold grid 와 성공/실패 기준을 바꾸지 않는다.
   - 2026-06-14 Step 0 확인 결과, Cybos bar row 는 `BaselineDirectionModel`이 요구하는 live orderbook 피처 `bid_ask_imbalance`, `spread_bps`를 갖지 않는다.
   - 따라서 1차 Cybos rescue 실험은 `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로 진행한다.
   - `proxy_buy_rescue`는 no-buy pool 중 `probability_up` 상위 `0.05`, `0.10`, `0.20`, `0.30` coverage 를 고정 grid 로 계산하고, 결과는 `latest-cybos-rescue-proxy-h15.{json,md}`에 별도로 쓴다.
   - 1 fold smoke 기준 새 rescue report 생성과 `runtime_baseline_replay.status=not_replayed_orderbook_features_missing` 출력은 확인했다. 전체 12 fold 최신 runtime report 재생성은 아직 별도 장외 저부하 작업으로 남긴다.
   - buy-rescue 는 상승 신호 품질 확인용 2순위 탐색 가설이며, 결과가 좋아도 KIS live shadow 없이 모델 승격이나 주문 정책 변경으로 연결하지 않는다.
   - hold-rescue 는 진입, 보유, 청산을 추적하는 포지션 lifecycle 시뮬레이션이 필요하므로 이번 1차 Cybos 통합 실행에는 결과 실험으로 넣지 않고 별도 설계부터 한다.
9. walk-forward 재검증 뒤에만 보합 regime 분리, 변동성 구간별 모델 분리, 새 feature 조합 학습을 검토한다.
10. label band는 바로 변경하지 않고 후보별 기간 분리 재현성을 본다.
11. probability calibration은 NLL/Brier 개선과 실제 방향 수익률 개선을 분리해서 본다.
12. KIS live 학습 데이터가 최소 `60거래일` 이상 쌓이기 전에는 최종 결론이 아니라 provisional 판단으로 둔다.
13. 기간 분리 재현성은 가능하면 3구간 각각 최소 `20거래일`에 가까워진 뒤 강하게 해석한다.
14. watchlist 확대는 거래 universe 확대가 아니라 데이터 다양성 확보용 수집 후보로 먼저 검토한다. 수집 후보가 늘어도 Phase 2 실전 canary 종목 수와 주문 한도는 별도 승인 전까지 그대로 둔다.
15. 3회 연속 실험에서 개선 없으면 데이터 소스, 라벨 정의, 전략 방향을 다시 점검한다.

### 이유

현재 병목은 안전장치보다 예측력이다.
LightGBM이 하락/회피 쪽 단서는 일부 보이지만, 현물 매수 승격 근거는 부족하다.
따라서 threshold를 낮춰 거래를 늘리는 방식보다, 상승/보합/하락을 실제로 더 잘 구분하는 피처와 라벨을 찾아야 한다.
현재 KIS live 데이터는 약 1개월, 소수 watchlist, 제한된 피처에서 나온 결과라 모델 부재와 데이터 부족을 분리해 해석해야 한다.
다만 데이터가 적은 상태에서 새 모델 실험을 계속 늘리면 우연히 잘 나온 숫자를 신호로 착각할 위험이 커진다.
따라서 다음 1순위는 새 모델 학습이 아니라, 이미 가능한 buy-avoid shadow 를 2주 이상 축적해 같은 판단이 반복되는지 확인하는 것이다.

### 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

- 변경 전:
  - 모델 후보가 좋아 보이는 단일 지표와 실제 매수 기대값이 섞여 보일 수 있다.
- 변경 후:
  - 모델 자체 평가, 가상 방향 거래 평가, 실제 paper 실행 평가를 분리한다.
  - 2026-06-13 이후 새 모델 실험은 buy-avoid shadow 관측과 walk-forward 재검증 기준 충족 뒤로 미룬다.
  - Cybos buy-rescue 는 runtime baseline replay 가 아니라 proxy buy-rescue 로 표시한다.
- 영향 범위:
  - `app/services/research.py`, `app/__main__.py`, `scripts/summarize_cybos_buy_avoid_proxy.py`, dashboard ML 카드, research tests.
- 회귀 위험:
  - 연구용 지표가 실제 수익률처럼 오해될 수 있다.
  - dashboard 문구에서 `연구용`, `단순합산`, `실제 체결 아님`을 계속 표시한다.
  - Cybos proxy baseline 을 runtime baseline 으로 오해하지 않도록 report metadata 와 테스트로 잠근다.

### 완료 기준

- 최소 1개 후보가 아래 조건을 동시에 만족해야 한다.
  - 독립 holdout 평가.
  - 3분류 정확도 개선.
  - 상승/하락 한쪽에만 치우치지 않는 클래스별 적중률.
  - 비용 차감 후 양수 기대값.
  - 기간 분리 재현성.
- 조건을 만족하지 못하면 active model은 baseline을 유지한다.

관련 문서/코드 경로:
`app/services/research.py`,
`runtime-data/reports/challengers/`,
`python -m app --run-lightgbm-performance-diagnostics --horizon-min 15`,
`python -m app --run-lightgbm-feature-profile-experiment --horizon-min 15`,
`python -m app --run-lightgbm-label-band-reproducibility-review --horizon-min 15`,
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`,
`runtime-data/reports/backtests/latest-cybos-regime-performance-h15.json`

## 8. 4단계: 하락/회피 신호 방어적 활용 검증

### 방법

- 현물 매수 알파가 검증되지 않은 동안에는 LightGBM을 매수 모델로 승격하지 않는다.
- 반복적으로 보이는 하락/회피 단서를 아래 두 용도로 분리해 paper shadow로 검증한다.
  - baseline 매수 신호를 거르는 회피 필터.
  - 이미 보유한 paper position을 조기 청산하는 방어 신호.
- 첫 단계는 실제 주문 로직을 바꾸지 않고 replay/paper shadow 리포트로만 비교한다.
- 비교 항목은 손실 거래 감소, 최대 낙폭, 연속 손실, 기회비용, 거래 수 감소, 비용 차감 순손익이다.
- 방어 신호가 좋아 보여도 active model 교체나 gate 기준값 변경 없이 별도 후보로만 둔다.
- 기존 진단에서 후보를 추릴 때는 `scripts/summarize_lightgbm_defensive_signal_candidates.py`로 하락 예측 양수 후보를 먼저 요약한다.
- 실제 baseline 매수 신호에 적용한 첫 비교는 `scripts/summarize_lightgbm_defensive_shadow.py`로 수행한다.
- 같은 하락/회피 단서라도 `buy-avoid`와 `early-exit`은 분리해서 판정한다. 2026-06-13 기준 첫 shadow 결과는 `buy-avoid`는 손실 축소 후보지만, 조기 청산은 실제 paper 청산보다 악화되어 보류다.

### 이유

현재 증거는 “언제 사야 하는가”보다 “언제 사면 안 되는가” 쪽에 더 강하다.
현물 계좌에서 하락 예측은 신규 숏으로 바로 쓸 수 없지만, 잘못된 매수를 줄이거나 손실 포지션을 빨리 닫는 데는 쓸 수 있다.
이 경로는 실전 주문을 건드리지 않고도 paper shadow에서 검증할 수 있다.

### 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

- 변경 전:
  - 매수 알파가 없으면 모델 연구가 다시 피처 실험만 반복될 수 있다.
- 변경 후:
  - 하락/회피 신호를 방어적 필터와 조기 청산 후보로 별도 검증한다.
- 영향 범위:
  - research report, dashboard ML 카드, prediction lineage, paper replay.
- 회귀 위험:
  - 회피 필터가 손실을 줄이면서 수익 기회도 과도하게 줄일 수 있다.
  - 따라서 순손익뿐 아니라 거래 수, missed profit, drawdown을 함께 본다.

### 완료 기준

- baseline 단독과 baseline+방어 필터를 같은 기간에서 비교한 리포트가 있다.
- 방어 필터가 비용 차감 후 손실 거래, 최대 낙폭, 연속 손실 중 최소 하나를 의미 있게 줄인다.
- 수익 기회 감소가 허용 범위 안인지 별도로 표시된다.
- 조기 청산 후보는 실제 closed paper lot 기준 delta 가 양수로 바뀌기 전까지 적용하지 않는다.

관련 문서/코드 경로:
`runtime-data/reports/challengers/latest-lightgbm-performance-diagnostics-h15.json`,
`runtime-data/reports/challengers/latest-lightgbm-calibration-experiment-h15.json`,
`runtime-data/reports/challengers/latest-lightgbm-defensive-signal-candidates-h15.json`,
`runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`,
`scripts/summarize_lightgbm_defensive_signal_candidates.py`,
`scripts/summarize_lightgbm_defensive_shadow.py`,
`app/services/research.py`,
`app/services/reporting.py`

## 9. 5단계: 모델 심사와 승격 체인 고정

### 방법

- LightGBM 학습 시점의 holdout 경계를 challenger 평가 anchor로 유지한다.
- gate reference walk-forward는 새 3분류 지표와 가상 방향 지표를 포함한 최신 포맷으로 유지한다.
- 극단 저성능 fold는 `scripts/summarize_walk_forward_extreme_folds.py`로 먼저 고르고, `scripts/analyze_walk_forward_extreme_fold_regimes.py`로 label imbalance, prediction bias, 기간 수익률, 분봉 변동성을 확인한다.
- 2026-06-13 기준 최저 fold 후보는 flat 라벨 비중이 높지만 flat 적중률이 붕괴한 고변동 구간이다. 따라서 단순 label/gate threshold 변경보다 보합 regime 분리와 변동성 피처 검증을 먼저 본다.
- `promotable=true`는 실제 승격이 아니라 심사 자격으로만 표시한다.
- 실제 승격은 아래 모두가 충족될 때만 검토한다.
  - 독립 holdout 유효.
  - walk-forward gate 통과.
  - 비용 차감 기대값 양수.
  - paper shadow에서 충분한 관측.
  - 운영자 승인.

### 이유

학습과 평가 사이에 데이터가 추가되면 holdout 경계가 바뀌어 심사가 무효가 된다.
또 `승격 가능`이라는 표현이 실제 활성 모델 교체처럼 보이면 운영자가 위험을 과소평가할 수 있다.

### 완료 기준

- challenger report에서 `evaluation_independence_status=independent_challenger_holdout`가 유지된다.
- dashboard는 `심사 자격`, `권장 액션`, `실제 승격 여부`를 분리해 보여준다.
- active model 교체는 자동으로 일어나지 않는다.

관련 문서/코드 경로:
`runtime-data/reports/challengers/latest-challengers-h15.json`,
`runtime-data/reports/backtests/latest-walk-forward-h15.json`,
`runtime-data/reports/backtests/latest-walk-forward-extreme-folds-h15.json`,
`runtime-data/reports/backtests/latest-walk-forward-extreme-fold-regimes-h15.json`,
`scripts/summarize_walk_forward_extreme_folds.py`,
`scripts/analyze_walk_forward_extreme_fold_regimes.py`,
`app/models/`,
`app/services/research.py`

## 10. 6단계: 예측-신호-주문-체결 lineage 보존

### 방법

- 예측 1건을 기준으로 다음 흐름을 한 줄로 연결한다.
  - 예측 시각.
  - 종목.
  - baseline 예측.
  - LightGBM shadow 예측.
  - 15분/60분 실제 결과.
  - 신호.
  - 주문.
  - 체결.
  - 청산 손익.
  - 차단 이유.
- 최소 6개월은 조회 가능하게 보존한다.
- 용량이 작고 유용하면 장기 보관한다.
- 다른 PC로 옮겨도 흐름이 유지되도록 SQLite 원장과 dashboard 조회를 함께 맞춘다.
- 6개월 이상 보존은 단일 `dev.db` 무한 증가가 아니라 월별 archive 또는 D드라이브 장기 보관 파티션을 기본 후보로 둔다.
- 운영 dashboard는 최근 기간을 우선 조회하고, 오래된 lineage는 archive 조회로 분리한다.

### 이유

모델의 예측이 실제 주문과 손익으로 이어졌는지 보려면 예측, 신호, 주문, 체결이 분리된 표로는 부족하다.
한 줄 lineage가 있어야 모델 개선, 장애 분석, 손익 복기, cowork 리뷰가 쉬워진다.

### 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

- 변경 전:
  - 예측, 신호, 주문, 체결, 손익이 각각 다른 화면과 테이블에 흩어진다.
- 변경 후:
  - 같은 예측 흐름을 날짜별로 한 줄에서 본다.
- 영향 범위:
  - dashboard query, reporting, prediction/order/fill read model.
- 회귀 위험:
- 조인 비용이 커져 dashboard가 느려질 수 있다.
- 우선 최근 기간 조회와 인덱스 확인부터 적용한다.
- 장기 보관을 단일 DB에 계속 누적하면 backup/recovery 시간이 커질 수 있다.

### 완료 기준

- 날짜 선택 시 해당 거래일의 예측 흐름 전체가 장 시작 순서로 보인다.
- `결과 없음`, `대기 중`, `차단`, `미체결`, `부분 체결`, `청산 손익`이 구분된다.
- 통화 표시가 필요한 손익과 금액은 원화로 표시된다.

관련 문서/코드 경로:
`app/services/dashboard.py`,
`app/services/reporting.py`,
`runtime-data/dev.db`

## 11. 7단계: 대시보드 운영 화면 정리

### 방법

- 첫 화면은 운영 콘솔로 유지한다.
- 상단에는 지금 당장 봐야 하는 상태만 둔다.
  - 런타임.
  - 계좌 정합성.
  - KIS 연결.
  - 데이터 품질.
  - 모델 상태.
  - 실전 주문 안전 상태.
- 긴 표는 내부 스크롤로 제한한다.
- 연구 지표와 실제 손익 지표를 같은 이름으로 부르지 않는다.
- 원화 금액은 통화 표시를 빠뜨리지 않는다.

### 이유

운영자가 매일 보는 화면은 연구 리포트가 아니라 의사결정 화면이어야 한다.
무엇이 정상이고 무엇을 조치해야 하는지 한눈에 보이지 않으면 자동화가 있어도 운영 부담이 커진다.

### 완료 기준

- 대시보드에서 `오늘 조치 필요`, `관찰`, `정상`을 쉽게 구분한다.
- 모델 승격, 실전 주문 가능, paper 성과가 서로 헷갈리지 않는다.
- 모바일/좁은 화면에서도 텍스트가 겹치지 않는다.

관련 문서/코드 경로:
`app/services/dashboard.py`,
`tests/test_dashboard.py`,
`runtime-data/reports/dashboard/latest-dashboard.html`

## 12. 8단계: 자동화와 런타임 유지 검증

### 방법

- 12시간 간격 운영 체크는 08:20~08:40, 20:20~20:40 조건으로 유지한다.
- PC 재부팅 뒤 runtime watchdog, dashboard, startup launcher 상태를 항상 확인한다.
- 장중에는 watchdog heartbeat가 10분 이내로 유지되는지 확인한다.
- 장후에는 quick maintenance, label refresh, dashboard snapshot, paper reconciliation 결과를 확인한다.
- Codex heartbeat와 Windows 작업 스케줄러 결과를 혼동하지 않도록 근거 파일을 같이 본다.

### 이유

자동화가 “실행된 것처럼 보이는 것”과 실제로 학습, 점검, 재기동이 된 것은 다르다.
장전/장후 자동화가 눈에 보이지 않으면 운영자가 매번 의심하게 되므로, 근거 파일 중심으로 확인해야 한다.

### 완료 기준

- 장전/장후 자동화 결과가 스레드, logbook, 상태 파일 중 최소 하나에서 확인 가능하다.
- dashboard/watchdog이 재부팅 뒤 자동 복구된다.
- 장중 heartbeat stale이 재발하면 원인과 조치가 남는다.

관련 문서/코드 경로:
`.agents/skills/daily-ops-check/SKILL.md`,
`runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`,
`runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`,
`runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`

## 13. 9단계: Phase 1a 모의투자 read-only 반복

### 방법

- 모의투자 계좌로 token refresh, account snapshot, system clock, database, dashboard readiness를 다시 생성한다.
- market status와 kill switch는 Phase 1a에서는 비차단 관측으로 둔다.
- readiness evidence freshness가 만료되면 이전 통과 결과를 재사용하지 않는다.

### 이유

실전 계좌를 연결하기 전에 같은 절차가 모의투자 read-only에서 반복 가능해야 한다.
Phase 1a는 주문 없는 리허설이므로 실전 자금 위험 없이 운영 절차를 검증할 수 있다.

### 완료 기준

- `phase1a_paper_readonly` readiness가 최신 증거로 통과한다.
- 증거 파일에는 token, 계좌번호, app secret이 남지 않는다.

관련 문서/코드 경로:
`scripts/run_live_readiness_dry_run.sh`,
`scripts/build_live_readiness_fixture_snapshot.sh`,
`runtime-data/reports/live-readiness/latest-readiness.json`

## 14. 10단계: Phase 1b 실전 계좌 read-only

### 방법

- 실전 계좌는 주문 메서드가 없는 read-only client로만 연결한다.
- `ALLOW_LIVE_ORDERS=false`를 유지한다.
- token, account snapshot, current price, system clock만 조회한다.
- raw response와 계좌번호는 저장하지 않고 shape와 count만 sanitized 증거로 남긴다.
- 모의투자 응답과 실전 응답의 필드 차이를 문서화한다.

### 이유

모의투자와 실전 계좌는 응답 shape, 예수금, 주문가능금액, T+2 정산 필드가 다를 수 있다.
이 차이를 모른 채 Phase 2로 가면 주문 가능 금액과 position 계산이 틀어질 수 있다.

### 완료 기준

- 실전 read-only 조회가 주문 함수 없이 통과한다.
- 실전 계좌 응답 shape 차이가 문서화된다.
- 주문 관련 함수 호출은 0건이다.

관련 문서/코드 경로:
`app/brokers/`,
`app/services/live_phase_readiness.py`,
`docs/Production-Architecture.md`

## 15. 11단계: Phase 2 소액 canary 준비

### 방법

- 1종목, 소액, 1일 주문 수 제한으로 시작한다.
- 부분 체결 잔량은 Phase 2에서는 자동 취소 허용 기준을 둔다.
- 비상 청산은 일반 신규 주문 게이트와 분리하되, 감사 로그에는 별도 이유를 남긴다.
- Telegram을 기본 알림으로 쓰고, 중요한 사고는 email을 병행한다.
- kill switch OFF 파일은 live-submit readiness에서만 요구한다.

### 이유

Phase 2의 목표는 수익 극대화가 아니라 실제 주문 lifecycle과 감사 추적이 안전하게 작동하는지 확인하는 것이다.
처음부터 다종목을 열면 문제 원인이 모델, 체결, 계좌, 시장상태 중 어디인지 분리하기 어렵다.

### 완료 기준

- Phase 1b 통과.
- 모델 승격 또는 canary용 전략이 비용 차감 양수 기대값과 재현성을 보인다.
- submit guard, order manager, audit ledger, alert, kill switch가 테스트를 통과한다.
- 운영자가 실전 canary 시작을 승인한다.

관련 문서/코드 경로:
`docs/Production-Implementation-Blueprint.md`,
`app/services/live_order_guard.py`,
`app/services/live_order_manager.py`,
`app/services/live_audit.py`

## 16. 12단계: Phase 3 다종목 일일 한도 운용

### 방법

- Phase 2를 최소 20~60거래일 관측한 뒤 확장한다.
- 일일 손실 한도, 종목별 손실 한도, 단일 종목 비중, 섹터 노출, 슬리피지 budget을 코드와 dashboard에서 확인한다.
- 여러 종목을 열기 전에 paper-vs-live 격차, 슬리피지, 미체결, unknown order가 기준 안에 있어야 한다.

### 이유

다종목 운용은 수익 기회를 늘리지만 사고 표면도 넓힌다.
Phase 2에서 주문 lifecycle과 계좌 정합성을 충분히 관측하지 않으면 Phase 3에서 장애가 누적된다.

### 완료 기준

- Phase 2 기간 동안 unknown/stuck order가 없다.
- 일일 손실 한도 미발동 또는 발동 시 기대한 동작 확인.
- paper/live 격차가 운영 기준 안에 있다.
- 월요일 장전 readiness와 장후 review가 반복 가능하다.

관련 문서/코드 경로:
`docs/Production-Architecture.md`,
`docs/Account-Safety.md`,
목표 경로 확인 필요: `runtime-data/reports/live-risk/`

## 17. 13단계: cowork 리뷰와 문서 관리

### 방법

- 꼭 필요한 리뷰 지점에서만 cowork 전달용 리포트를 만든다.
- `work_ver_N`은 Codex 작업 통합본, `review_ver_N`은 cowork 리뷰로 맞춘다.
- 작은 후속 작업이 여러 개이면 `work_ver_N-1`, `work_ver_N-2`처럼 쌓고, 전달 전 통합본을 만든다.
- 기준 문서에는 현재 사실만 남기고, 긴 리뷰 전문은 `docs/cowork-reports/`에 둔다.

### 이유

cowork 토큰이 제한되어 있으므로 매 작은 변경마다 리뷰를 요청하면 중요한 검토가 흐려진다.
대신 P0 모델 트랙, 실전 계좌 read-only, live submit 전환처럼 안전 영향이 큰 지점에서 비판적 검토를 받는 것이 낫다.

### 완료 기준

- cowork에게 전달할 파일이 하나로 명확하다.
- 리뷰 지적은 `적용`, `보류`, `반박`, `확인 필요`로 분류된다.
- 반영 결과는 logbook과 필요 시 progress 문서에 남는다.

관련 문서/코드 경로:
`docs/cowork-reports/README.md`,
`docs/cowork-reports/`,
`docs/logbook.md`

## 18. 14단계: 백업과 복구

### 방법

- NAS 백업은 사용자가 해당 작업에서 명시적으로 지시한 경우에만 실행한다.
- 실전 전환 검증용 sanitized recovery export는 비밀값, token cache, runtime log, private key를 제외한다.
- 재난 복구용 전체 백업은 별도 개념으로 유지하되 cowork 전달이나 readiness 증거로 쓰지 않는다.
- 중요한 구조 변경 뒤에는 commit/push를 먼저 하고, NAS 백업은 명시 지시가 있을 때만 한다.

### 이유

NAS 백업은 용량과 시간이 크고, 너무 자주 실행하면 운영 부담이 된다.
반면 commit/push는 변경 이력을 작고 자주 남기는 데 적합하다.

### 완료 기준

- git 상태가 clean 이다.
- 민감정보가 git 추적 파일에 들어가지 않는다.
- NAS 백업은 명시 지시가 있을 때만 실행됐고, 실행했다면 경로와 결과가 기록된다.

관련 문서/코드 경로:
`RECOVERY.md`,
`scripts/run_weekly_nas_backup.sh`,
`scripts/run_forced_nas_backup.sh`

## 19. 지금 바로 이어갈 권장 순서

현재 기준 다음 실제 작업 순서는 아래가 권장안이다.

1. broker paper sync rate limit과 local-only mismatch 원장을 `scripts/trace_paper_kis_mismatch.py`로 확인한다.
2. 다음 거래일 장후에도 mismatch가 남으면 P0 운영 blocker로 보고 order-fill 호출량 설계를 줄인다.
3. KIS live feature 후보를 더 좁히는 모델 실험을 진행하되, 현재 데이터 한계 때문에 provisional 판단으로 둔다.
4. 하락/회피 신호를 baseline 매수 회피 필터와 조기 청산 후보로 paper shadow 검증한다.
5. gate walk-forward 극단 저성능 fold를 `scripts/summarize_walk_forward_extreme_folds.py`로 추적하고, 원인 분석 후보 기간을 고른다.
6. dashboard/watchdog 장시간 유지 상태를 다음 장중에 read-only로 확인한다.
7. 모델 후보가 개선되면 shadow 관측 기간을 시작하고, 개선되지 않으면 label/feature/전략 방향을 다시 설계한다.
8. Phase 1a readiness 증거를 최신화한다.
9. Phase 1b 실전 read-only는 주문 메서드 없는 client 준비와 비밀값 로컬 준비가 끝난 뒤 진행한다.

이 순서의 핵심은 Phase 2를 서두르지 않는 것이다.
지금은 실전 주문 기능보다 “이 전략이 실제 비용을 이길 수 있는가”를 먼저 증명해야 한다.

관련 문서/코드 경로:
`docs/Current-Implementation.md`,
`docs/Production-Transition-Progress.md`,
`runtime-data/reports/challengers/`

## 20. 작업 종료 기준

각 작업은 아래 조건을 만족해야 끝난 것으로 본다.

- 시작 시점의 장 상태와 runtime 상태를 확인했다.
- 변경 범위가 장중 보호 규칙과 금지선에 맞다.
- 필요한 테스트 또는 문서 검증을 실제로 실행했다.
- dashboard나 runtime을 건드렸다면 최종 상태를 확인했다.
- `docs/logbook.md`에 오늘의 조치와 다음 작업이 남았다.
- commit/push가 필요한 변경이면 같은 턴에서 처리했다.

관련 문서/코드 경로:
`docs/logbook.md`,
`AGENTS.md`
