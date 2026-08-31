# Portfolio Replay Evaluator

## 목적

이 문서는 비용 후 포트폴리오 연구에 사용하는 replay evaluator의 시간 의미와 버전 경계를 고정한다.
E7 전략, 모델, threshold를 설명하는 문서가 아니라 동일 전략을 어떤 평가 엔진으로 계산했는지 구분하는 기준이다.

## evaluator version

### portfolio-replay-v1-entry-mark

- 기존 `app/services/portfolio_replay.py` 구현과 과거 산출물의 의미다.
- 체결은 완성된 signal 다음 분봉의 open, 청산은 horizon 또는 15:20 forced-flat 분봉의 open을 사용한다.
- 보유 중인 포지션은 다음 의사결정 또는 청산 전까지 entry raw price로 평가한다.
- 따라서 intratrade minute drawdown이 equity curve에 없고, 보유 중 손익이 다음 position sizing에 반영되지 않는다.
- 기존 코드와 과거 결과는 변경하거나 v2로 소급 대체하지 않는다. evaluator metadata가 없는 기존 결과는 이 legacy version으로 해석한다.

### portfolio-replay-v2-minute-mtm

- 구현: `app/services/portfolio_replay_v2.py`
- E7 identity와 공식 비교 guard: `app/services/e7_portfolio_evaluator.py`
- 활성 포지션이 있는 동안 매 분 경계에서 portfolio equity를 mark-to-market으로 관측한다.
- MTM equity를 peak, maximum drawdown, 신규 position sizing, gross exposure, concentration 계산에 함께 사용한다.
- v1과 같은 commission, domestic common-stock sell tax, slippage, current-minute open entry/exit 의미를 유지한다.

## 시간과 정보 가용성

`ReplayBar.bar_time=T`는 T분 봉의 시작 시각이다.
현재 streaming 경로는 다음 분 tick이 들어올 때 직전 분 봉을 finalize하므로 T분 봉의 close는 T+1분 경계부터 사용할 수 있다.

v2의 시각 T 계산 순서는 다음과 같다.

1. T 이전부터 보유한 포지션을 T-1분 completed bar close로 mark한다.
2. 거래 전 MTM equity, exposure, concentration을 관측한다.
3. T에 청산할 포지션을 기존 의미와 같은 T분 open으로 청산한다.
4. T에 진입할 포지션을 현재 MTM equity로 sizing하고 T분 open으로 진입한다.
5. 거래 후 equity를 다시 관측한다.

아직 완성되지 않은 T분 close, high, low는 T valuation에 사용하지 않는다.
진입 직후 새 포지션은 실제 transaction-minute open으로 mark하며 다음 분 경계부터 completed close를 사용한다.
이 규칙 때문에 T 이후 급등락 또는 T분 자체 close가 T valuation으로 역류하지 않는다.

## mark coverage와 fail-closed

E7 manifest의 stale tolerance는 0초다.
각 잠재 decision episode의 entry+1분부터 exit 시각까지 exact completed-minute close가 모두 있어야 한다.

- exact mark 없음, 이전 mark도 없음: `missing_active_position_mark`
- 이전 mark만 있고 0초 tolerance를 초과: `stale_active_position_mark_beyond_tolerance`
- NaN, 무한대, 0 이하, 상충하는 동일 시각 close: invalid
- invalid coverage에서는 entry price fallback이나 부분 episode 선별을 하지 않고 전체 evaluation을 `invalid_evaluation`으로 종료한다.

결과는 `mark_observation_count`, `missing_mark_count`, `stale_mark_count`, `invalid_mark_count`, `invalid_evaluation_reason`, `equity_observation_count`를 additive metadata로 기록한다.

## E7 immutable manifest

정본 객체는 `E7_PORTFOLIO_REPLAY_MANIFEST`다.
현재 SHA-256은 `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`다.

| 항목 | 고정값 |
| --- | --- |
| evaluator | `portfolio-replay-v2-minute-mtm` |
| valuation | prior completed minute close, transaction minute open |
| cost model | `krx-common-stock-2026-v1` |
| model | `lightgbm-h15-v1` |
| threshold | `0.55` |
| horizon | `15분` |
| future start | `2026-08-31 09:15 KST` |
| forced flat | `15:20 KST` |
| initial cash | `25,000,000원` |
| position constraints | 종목당 `8%`, 최대 `5`개 |
| normal cost | slippage 3bp/side, commission 0.015%/side, sell tax 0.20%; round trip 0.29% |
| double cost | 모든 canonical cost component 2배; round trip 0.58% |
| random control | 거래일/종목/시간대 층별 same-count, `1,000`회, seed `202608310915` |
| minimum sample | 10거래일, 100 episode, 5종목 |
| future intervals | 사전 고정된 서로 겹치지 않는 2개 구간 |

두 미래 구간의 실제 start/end는 공식 평가 전에 `E7FutureInterval`로 고정한다.
2026-08-31 09:15 KST 이전 구간, timezone 없는 경계, 겹치는 구간은 거부한다.

## 공식 비교 호환성

각 미래 구간마다 normal/double cost에 대해 다음 네 역할이 모두 필요하다.

- baseline
- e7_policy
- actual_portfolio_replay
- random_control

총 2구간 x 2비용 x 4역할 = 16개 결과가 하나의 공식 package다.
하나라도 누락되거나 중복되면 통합 pass/fail을 만들지 않는다.

다음 혼합은 예외로 차단한다.

- v1과 v2
- 다른 manifest hash
- 다른 valuation identity
- 다른 cost model 또는 cost scenario 값
- 다른 initial cash, position limit, forced-flat
- 다른 future interval definition
- random simulation 수, seed, strata 차이
- actual policy veto lineage와 random-control same-count 기준의 차이
- invalid mark coverage 결과

random control은 한 번 만든 immutable minute mark index와 timeline을 1,000회 재사용한다.
각 simulation은 market mark를 다시 구축하지 않으며 동일 input, manifest, seed에서 동일 결과 hash를 만든다.

## E7 운용 경계

v2 evaluator 구현은 E7 전략 변경이 아니다.
`lightgbm-h15-v1`, threshold 0.55, signal/gate, allocator, 주문 정책, active model은 변경하지 않는다.
미래 데이터를 이용한 threshold, feature, model, symbol, exit, horizon 재탐색도 하지 않는다.

신규 targeted test, 기존 관련 test, 전체 suite, no-look-ahead, missing/stale, manifest isolation, synthetic manual check가 모두 통과해야 공식 evaluator 준비 상태로 표시할 수 있다.
하나라도 실패하면 미래 원장 수집은 계속하되 공식 수익성 판정만 보류한다.

## E7 daily evidence artifact

- entrypoint: `./scripts/generate_e7_daily_evidence.sh`
- service: `app/services/e7_daily_evidence.py`
- immutable daily path: `runtime-data/reports/research/e7/daily/YYYY-MM-DD.json`
- latest path: `runtime-data/reports/research/e7/latest-e7-daily-evidence.json`
- 입력 SQLite는 URI `mode=ro`로 열며 원장·평가 입력을 수정하지 않는다.
- 실제 거래일 post-close, live runtime 정지, current trading day 조건에서만 생성한다. 같은 날짜 재실행은 immutable 파일을 재사용한다.

artifact는 evaluator/manifest identity, 미래 거래일·episode·종목, mark 관측과 missing/stale/invalid, normal/2x cost 전제, random control, 두 미래구간, 최소 표본 진행률을 기록한다.
`evidence_health`와 `profitability_assessment`는 별도다. 최소 10거래일/100 episode/5종목 전에는 `collecting_future_sample`이며 전략 성공/실패를 만들지 않는다.
공식 evaluator 또는 manifest 상수, 비용·제약·random·구간 identity, mark coverage가 다르면 `invalid_evidence`로 fail-closed한다.
2026-08-31 첫 미래 거래일 데이터는 수집됐지만 당시 daily ops에는 writer가 없어 공식 artifact가 없었다. 과거 evidence는 소급 작성하지 않고 다음 안전한 post-close부터 immutable 일일 증적을 축적한다.
