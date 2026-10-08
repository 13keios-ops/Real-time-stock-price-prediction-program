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

### Shadow lineage validation

daily schema `3`와 `evidence_validation_version=e7-shadow-lineage-v2-exact-id`는 원천 연결/계보 검증의 버전이다. schema 2의 tuple join validator `e7-shadow-lineage-v1` 결과와 구분한다. 공식 replay evaluator/manifest와 별개이며 전략, threshold, episode grouping 또는 평가 계산을 변경하지 않는다.

- 미래 h15 판단을 모두 읽고 shadow JSON에 저장된 유일 prediction ID를 primary-key 제한 배치 조회로 연결한다. 누락을 제외하거나 시각/종목 tuple로 대체 연결하지 않는다. 판단/예측/분봉 조회는 같은 읽기 전용 SQLite snapshot을 사용한다.
- 판단의 `shadow_predictions_json`에서 manifest 모델 항목이 정확히 1개여야 하고 prediction ID/model/run/artifact/hash 및 up/flat/down 확률이 SQLite 원장과 정확히 같아야 한다. 확률은 유한한 0~1 숫자여야 한다.
- prediction의 종목/시각/horizon도 판단과 같아야 한다. 같은 분봉의 다중 판단은 `duplicate_decision_minute`, 서로 다른 판단의 동일 shadow ID 재사용은 `shadow_prediction_reused`로 차단한다. 참조하지 않은 별도 prediction이 같은 시각에 있다는 이유만으로 잘못된 교차 연결을 만들지 않는다. malformed JSON/계보 schema 부재와 active 계보 부재도 차단한다. 오류가 있는 행만 제외해 공식 pass를 만들지 않으며 전체 `evidence_health`와 normal/2x/random/두 구간 전제를 차단한다.
- `source.shadow_lineage_validation`에 distinct 판단 검사/실패 건수, join 행 기준 reason counts, 원천 계보 fingerprint를 기록한다. 기존 `source_fingerprint`는 평가 입력용이며 새 계보 fingerprint와 역할이 다르다.
- 기존 immutable artifact는 재작성하지 않는다. 구버전 또는 검증 proof가 없는 보고서 재사용은 읽기 결과에서 `shadow_lineage_validation_not_available`로 차단하고 CLI exit 1을 반환한다. 현행 invalid artifact 재사용도 exit 1이며 잘못된 성공/검증 proof 조합은 `shadow_lineage_validation_inconsistent`다. 캐시의 observed/expected evaluator, observed/current/expected manifest와 현재 코드 상수도 다시 대조해 누락·drift를 차단한다.
- 정상 원천 입력에서는 기존 진행률과 평가 입력 의미를 유지한다. 과거 중복 판단/덮어쓴 분봉은 임의 dedup/첫 행 선택으로 구제하지 않는다. 연결 버전이 다르면 source/lineage fingerprint도 직접 혼합하지 않는다. 원본과 구버전 artifact를 보존하고 버전별 진단 비교를 분리한다.

실시간 분봉의 원본 체결은 모두 보존한다. `OnlinePipelineProcessor`는 종목별 분봉 시각을 역행하지 않으며 마감한 분봉을 다시 열지 않는다. `late_trade_events`는 과거/이미 마감한 분봉이라 파생 처리에서 제외한 원본 체결 수다. 아직 열린 분봉 안에서 초 단위 순서가 바뀐 체결은 계속 집계한다. 이 watermark는 프로세스 메모리 범위이며 재시작 간 중복 방지를 보장하지 않는다.

2026-08-31 첫 미래 거래일 데이터는 수집됐지만 당시 daily ops에는 writer가 없어 공식 artifact가 없었다. 과거 evidence는 소급 작성하지 않고 다음 안전한 post-close부터 immutable 일일 증적을 축적한다.

### Diagnostic Captured-Raw Price View

- `app/services/e7_price_input_view.py`의 `build_verified_price_input_view`는 `e7-captured-raw-price-view-v1` 입력뷰만 만든다. 공식 daily writer나 원장 수정 경로에 연결하지 않는다.
- 반환할 전체 ReplayBar의 종목/분 시각/유한 양수 가격을 검증하고, 명시한 미래 분봉의 기존 open/close가 SQLite와 같아야 한다. 단일 읽기 전용 snapshot에서 해당 분봉의 첫~마지막 `kis-ws` capture rowid 사이 같은 종목/소스의 모든 분 경계를 유지한다. 조각별 OHLC/volume/count가 보존 JSONL 생성본과 정확히 일치해야 하며 마지막 생성본도 저장 분봉과 같아야 한다. 새 읽기 전용 snapshot으로 관련 raw/저장 분봉을 재확인한 뒤 JSONL을 재확인한다. 원천 누락·불일치·잘못된 가격/시각·검증 중 관련 DB/파일 변경은 `PriceInputViewError`다. DB 연결은 성공/실패 모두 닫는다. 증거는 검증 시점의 snapshot이며 반환 뒤 원본의 영구 불변성을 보장하지 않는다.
- 증명된 요청 분봉의 모든 보존 체결을 event time/capture rowid 순으로 합쳐 open/close만 별도 불변 mapping에 덮어 놓는다. 기존 입력, DB, 과거 JSONL/예측은 바꾸지 않는다. 보존 feed 전체 집계이지 거래소 feed 완전성 또는 정본 feature/예측 복구가 아니다.
- proof는 입력 버전, 원래/교정 가격 fingerprint, raw capture 구간 해시, 생성 파일 해시, evaluator/manifest 및 `official_evaluation_permitted=false`를 기록한다. 진단 결과는 이 입력 버전과 fingerprint를 함께 보존해야 한다. 같은 evaluator/manifest라도 기존 공식 결과와 합산하거나 공식 pass 근거로 사용할 수 없다. 일반 replay compatibility guard만으로 입력뷰 호환성을 보장하지 않는다.
- 영향 회귀는 고정 episode ID/시각/avoid와 비용/제약을 유지한다. 가격 민감도 확인을 위해 모집단 episode의 avoid를 무시한 단일 진단 실행은 공식 rescue policy 또는 random-control simulation과 구분한다. 중복 판단 차단을 풀거나 과거 판단을 삭제·선택·재생성하는 권한은 이 입력뷰에 없다.

### Official Evidence Acceptance Review (2026-10-08, Not Activated)

이 절은 공식 사용 조건의 검토 결과이며 현행 사전등록/manifest/validator 변경이나 과거 증거 사용 승인 자체가 아니다.

- 보존 조각의 예측 재현, 보존 raw 가격 재구성, 공식 원천 증거 통과는 별개의 주장이다. 가격뷰만으로 통합 정본의 당시 feature/예측 또는 전역 수신 순서를 복구하지 못한다. 고정 모집단 밖 중복 판단이어도 random-control 청산 가격에 영향이 있으므로 4행 삭제나 첫/마지막 행 선택으로 통과시키지 않는다.
- `run_e7_portfolio_replay`, `stamp_e7_result`, `validate_e7_official_result_set`와 일반 `assert_replay_results_compatible`는 현재 원천 증거/가격 입력 버전/공식 사용 허가를 강제하는 경계가 아니다. 테스트 fixture `_complete_package`의 16개 결과에 `official_evaluation_permitted=false`, 원천 실패 및 서로 다른 `input_source_version/input_fingerprint`를 넣어도 package guard가 `compatible`을 반환하는 것을 메모리에서 재현했다. 실제 공식 artifact가 잘못 통과했다는 증거는 아니며 현행 daily 경로의 원천 차단은 유지한다.
- 다음 안전 구현은 별도 source-acceptance envelope와 공식 entrypoint/package guard다. 검증 버전/통과 상태/판정 구간, 원천 ledger·prediction·모집단 fingerprint, 가격 입력 버전/fingerprint, 공식 사용 허가와 승인된 acceptance 계약 hash가 필수다. 진단 전용·누락·원천 실패·입력 혼합은 수익 계산/공식 stamp 전에 차단해야 한다. 단순 Boolean 허가 필드만으로 승격하지 않는다.
- 같은 구간 안의 baseline/policy/actual/random 및 두 비용 조건은 동일 원천 모집단과 가격 입력을 사용해야 한다. 역할별 선택 episode fingerprint는 정책 차이를 반영할 수 있으므로 모집단 fingerprint와 구분한다. 서로 다른 두 구간의 원천 fingerprint까지 같게 요구하지 않는다. 공식 package identity에도 구간/acceptance/입력 identity를 포함하며 기존 결과와 직접 합산하지 않는다.
- 과거 구간을 살리는 경로는 별도 historical-capture acceptance 개정이다. 수정 분봉의 raw/생성본 proof, 고정 모든 모집단의 진입·청산·mark 영향, 정확한 원래 prediction 연결과 미복구 한계, 제외 규칙을 결과와 무관하게 고정해야 한다. 현재 증거는 무조건 허용을 뒷받침하지 못한다. 기존 원장/보고서/원래 사전등록 결과를 덮지 않고 운영자 승인된 새 계약의 별도 결과로만 다룬다.
- 더 보수적인 대안은 원래 미래 시작과 과거 이력을 그대로 보존하고, 복구 후의 사전에 고정한 두 비중복 구간을 별도 acceptance 계약으로 평가하는 것이다. 구간별 strict 원천 검증과 동일 최소 표본을 다시 만족해야 하며, 그 구간이 깨지면 임의로 시작일을 옮기거나 수익이 나쁜 날만 제외하지 않는다. 전체 누적 구간을 검증하는 현행 daily loader에는 구간별 계약이 없으므로 오늘 정상 수집만으로 과거 차단이 자동 해소되지 않는다. 아직 두 대안 중 어느 것도 활성화하거나 구간 경계를 변경하지 않았다.
- 최소 회귀: 진단/허가 없음/실패 proof/구버전/변조 hash 거부, 같은 구간의 source/price 혼합 거부, 역할별 선택과 두 구간의 합법적인 차이 허용, 16개 비교의 동일 입력 유지, 과거 원본 해시 보존, 정상 입력의 기존 수학/비용/threshold 불변이다.

### Source Acceptance Guard Implementation (Integrated, Contract Not Activated)

- `E7EvidenceAcceptanceContract`는 두 고정 구간, 현행 exact-ID validator, stored-minute 가격 입력 버전과 기존 manifest를 묶는다. 계약 객체 생성은 운영자 승인이 아니다. 공식 함수는 신뢰된 호출자가 별도로 전달한 `approved_contract_hash`와 계약 hash가 일치해야 하며 기본값은 승인 없음이다. 10/9 아래 별도 미래 구간의 준비를 승인받았지만 trusted producer 연동 및 운영 활성화는 아직 하지 않았다.
- `e7-source-acceptance-v1` proof는 구간/scope, validator 통과와 빈 reason_counts, ledger/prediction/모집단/가격 fingerprint, 공식 허가 및 proof hash를 요구한다. 실제 immutable context의 모집단과 가격 index/timeline을 실행 전 대조한다. 원천 ledger/prediction hash와 통과 판정의 진위는 trusted producer에서 원천 validator로 확인해야 한다. hash는 데이터 식별/변조 탐지이지 자체 승인 또는 전자서명이 아니다.
- 공식 replay/random-control/stamp/package는 진단·누락·구버전·실패·변조와 동일 구간 입력 혼합을 거부한다. 결과 구간 본문과 hash를 함께 검사하고 기존 출처의 다른 proof로 재스탬프하지 않는다. 표본 부족 random-control은 비공식 상태로 반환하고 공식 stamp/package로 승격하지 않는다. 역할별 선택과 두 구간 간 원천 차이는 유지한다.
- 계산 결과 lineage에 `portfolio-replay-input-binding-v1`, 실제 모집단과 context 가격 fingerprint를 기록한다. 공식 stamp/package/random-control 선행 검사는 계산 lineage와 proof의 일치를 요구하므로 다른 입력으로 계산한 결과에 정상 proof만 붙일 수 없다. 가격 fingerprint는 context 생성 때 한 번 계산해 1,000회 시뮬레이션이 같은 불변 값을 재사용한다. 이는 v2 결과 metadata의 추가이며 수익/비용/MTM 수학 변경이 아니다.
- package identity에는 구간과 source proof/계약 identity가 포함된다. 기존 result package와 혼합하지 않는다. generic v2 계산/진단 가격뷰/daily 원천 validator 및 E7 threshold/model/manifest/비용은 불변이다. 운영 경로에 승인 proof를 자동 주입하거나 과거 차단을 해제하지 않는다.
- 10/8 워밍업 보호 중 별도 WSL worktree에서 구현·focused test를 수행했다. 10/9 휴장/장외 runtime 정지 상태에서 전체 unittest 779건(40.304초)을 통과하고 `d8f9e20`을 root main에 fast-forward 통합했다. 운영 승인 proof 자동 생성과 공식 평가 활성화는 하지 않았다.

### Post-Recovery Future Contract (Prepared, Not Activated)

- 2026-10-09 운영자가 복구 후 두 비중복 미래 구간을 별도 계약으로 준비하는 권장안을 승인했다. 원래 E7의 `2026-08-31 09:15 KST` 시작, manifest와 과거 실패 증거는 유지한다. 정본 계약은 `docs/e7-post-recovery-acceptance-20261009.json`이며 기존 누적 결과와 합산하지 않는다.
- 구간 1은 `2026-10-12 09:15 KST <= t < 2026-10-24 00:00 KST`, 구간 2는 `2026-10-26 09:15 KST <= t < 2026-11-07 00:00 KST`다. 현재 저장소 달력 기준 각각 10거래일이며 끝 경계는 exclusive다. 데이터가 아직 관측되지 않은 구간만 사전에 고정했다.
- 계약 본문의 canonical JSON SHA-256은 `16a22ce5801cd1f38d21aee98bfe806fa809a3c4061d2f61e4bdb5b16b20e740`이다. 외부 approval metadata를 포함한 파일 전체 해시와 구분한다. `approved_contract_hash`는 향후 신뢰된 실행 경로가 승인 기록과 원천 proof를 대조한 뒤 전달해야 하며 이 파일만으로 자동 활성화하지 않는다.
- 각 구간은 원래 최소 10거래일/100 official episode/5종목과 동일 normal/2x cost, random-control 1,000회 및 16개 결과 계약을 충족해야 한다. 표본 부족은 `observe_more`이지 경계 이동, 사후 기간 연장, 나쁜 날 제외 또는 threshold 변경의 허가가 아니다. 추가 기간은 관측 전에 별도 계약으로 고정해야 한다.
- trusted producer가 고정 구간의 exact-ID 원천을 검증하고 모집단/가격 fingerprint를 계산해 승인 hash와 연결하는 후속 구현이 남아 있다. 기존 전체 누적 daily loader를 새 구간 통과로 바꿔 부르지 않으며 원래 daily의 `invalid_evidence`를 유지한다. 새 구간 진행 리포트와 공식 proof/package는 아직 생성하지 않았다.

### Next-Session Observation Contract

- 당일 runtime이 watchdog의 정상 워밍업으로 시작했는지 읽기 전용 상태/로그로 확인한다. 시작 전 당일 산출물 없음은 수집 실패나 재발 방지 성공으로 해석하지 않는다. 수집기를 임의로 켜거나 재시작하지 않는다.
- 실제 세션의 append-only 분봉/feature/h15 decision을 종목·분별로 확인해 분봉 재생성/중복 판단 0건을 검사한다. prediction은 서로 다른 모델/horizon이 공존하므로 단순 분별 행 수로 중복을 판단하지 않고 decision의 정확한 prediction ID/계보를 검사한다.
- late 발생 시 raw 보존과 `late_trade_events` 증가, 파생 분봉/판단 재생성 없음까지 대조한다. late가 없으면 정상 세션 무중복만 관측한 것이며 late 경로 실증은 미관측으로 표시한다. 이미 통과한 격리 회귀를 실수집 검증으로 바꿔 부르지 않는다.
- 마감 후 보호 해제 상태에서 당일 품질과 계보 검증을 확인한다. 과거 전체 누적 실패와 당일 원천 건강을 분리하며 공식 허용 상태는 자동 승격하지 않는다. watermark는 메모리 범위라 restart 간 idempotency는 별도 검증 대상이다.
