# 현재 상태

## 기준 시각

- 확인 시각: 2026-10-08 KST, 장외 E7 원천 계보 수동 검증
- 장 상태: overnight
- live runtime: 정지, `paper`; 장외에 시작하지 않음
- runtime watchdog: 실행 중, heartbeat fresh, 오류 없음; should-run false
- dashboard: 실행 중, 포트 8765 HTTP/API 응답 정상
- Windows startup launcher: 설치 및 정상
- 최신 서비스 확인은 위 기준 시각, 수집/Phase 0 누적은 10/7 공식 장후 증거, E7 원천 계보 판정은 다음 10/8 수동 검증을 기준으로 한다.

## 10/8 E7 원천 계보 검증 (공식 평가 차단)

- source-acceptance guard는 `codex/e7-source-acceptance` / `.tmp-tests/e7-source-acceptance` 격리 worktree에서 준비했다. 08:10 확인 시 runtime은 08:00:38부터 paper 워밍업 중이고 watchdog fresh/should-run true/오류 없음이다. 보호 규칙에 따라 root 코드·운영 DB/API/runtime은 건드리지 않았다. 승인 계약 없음은 기본 fail-closed이며 과거 증거와 E7 공식 평가는 계속 차단한다. 장외 전체 회귀와 root 통합 전까지 운영 적용 완료로 보지 않는다. 계약/원천 proof 및 구현 한계는 `docs/Portfolio-Replay-Evaluator.md`가 소유한다.

- 현행 evidence validator는 `e7-shadow-lineage-v2-exact-id`, daily schema `3`다. shadow JSON의 유일 prediction ID를 primary-key 배치 조회하고 종목/시각/horizon, model/run/artifact/hash/3종 확률을 대조한다. 누락·동일 분봉 다중 판단·prediction 재사용·잘못된 확률·active 계보 부재는 `invalid_evidence`로 fail-closed한다. evaluator/manifest, threshold, episode grouping/진입/청산/비용 계산은 변경하지 않았다. 앞선 schema 2/validator v1 결과는 별도 보존한다.
- 미래 판단 원천 `76,002`건의 기존 tuple join은 `76,006`행이었다. 9/28 `005930` 14:42/14:43에 각 판단 2건과 prediction 2건이 있어 시각/종목/horizon/model join에서 각각 2x2 교차 연결됐다. 각 판단의 shadow JSON은 정확한 prediction ID 1개와 일치하므로 모델 artifact 자체가 훼손됐다고 단정하지 않는다. 영향은 distinct 판단 4건, join 중 모호한 8행/ID·점수 불일치 4행이다.
- 앞선 v1 읽기 전용 검증은 evaluator/manifest·24거래일·모집단 11,708 episode·공식 episode/symbol 0/0·mark 수치가 기존 증거와 같음을 확인했으나 원천 계보 검증은 실패했다. 따라서 공식 수익성 평가는 차단한다. 수집과 Phase 0은 계속하며 수익성 실패로 해석하지 않는다. 근거: `.tmp-tests/e7-lineage-validation-20261008.json`.
- 10/7 이하 immutable daily/latest artifact는 바이트 해시를 보존했고 소급 작성하지 않았다. schema 1 보고서의 `valid_collecting`은 당시 검증 범위의 이력이지 새 계보 검증 통과가 아니다. 구버전 재사용은 파일을 고치지 않고 실행 결과에서 `shadow_lineage_validation_not_available`로 차단한다.
- 원인 확정: raw 체결 삽입 순서에서 9/28 `005930`의 `14:43:00 → 14:42:59` 역전 1건을 확인했다. 기존 `process_trade_record`가 다른 분봉이면 현재 분봉을 마감하고 시각을 되돌려 14:42/14:43을 재생성했다. 종목별 단조 증가/마감 watermark로 재생성을 차단했고 늦은 원본 체결은 보존하며 `late_trade_events`로 센다. 열린 분봉 내 순서 역전은 집계하고, flush 이후 마감 분봉 재입력도 차단한다. 보호는 프로세스 메모리 범위다.
- exact-ID 읽기 전용 검증은 `76,002`판단을 `76,002`행으로 연결해 교차 연결/ID·점수 불일치를 해소했다. 남은 실패는 `duplicate_decision_minute=4`뿐이다. 24거래일, 적격 38,896행, 모집단 11,708 episode, 공식 episode/symbol 0/0 및 mark 수치는 앞선 검증과 동일하다. 입력/계보 fingerprint는 연결 버전 차이로 변경됐고 혼합하지 않는다. 근거: `.tmp-tests/e7-exact-id-validation-20261008.json`; 공식 artifact 24개 바이트 해시는 보존했다.
- 과거 증거 검토 완료: 9/28 JSONL 분봉/feature/decision 각 3,803행의 종목·시각 순서가 모두 일치했다. 문제 4건의 raw 연속 구간은 각각 1,252/40/34/1,701체결이며 보존 분봉을 정확히 재현한다. 보존된 특징과 당시 해시 일치 모델로 active/shadow의 3종 확률·계보를 모두 정확히 재현했고 SQLite prediction과도 일치했다. SQLite 분봉/feature가 마지막 조각으로 덮어써진 사실도 확인했다. 근거: `runtime-data/reports/codex/e7-duplicate-minute-forensics-20261008.json`.
- 4건 모두 고정 E7 모집단에서 비적격이다. 그러나 새 watermark 규칙에서 14:43의 40+1,701=1,741체결을 합친 분봉은 과거 생성본에 없고 그 전체 분봉의 당시 예측도 없다. 주문장 값으로 보존 특징을 재현할 수 있어도 직접 feature ID/전역 trade·orderbook 수신 순서가 없으므로 원래 인과 연결 또는 가상 통합 예측을 증명하는 것은 아니다. 과거 4개 조각의 출력 검증과 정본 전체 분봉 예측 복구를 구분한다.
- 가격 의존성: 9/28 `005930` 383판단 중 적격 175행/실행 가능 모집단 57 episode를 고정 helper로 검증했다. 14:27 신호(14:28 진입~14:42 청산), 14:29 신호(14:30 진입~14:44 청산) 두 episode가 해당 분봉의 청산/보유 가격에 의존한다. 둘 다 official rescue는 미선택이지만 random-control 모집단에는 포함된다. 보존 raw 전체 기준 14:42는 1,286체결/시가 272,250원이고 SQLite는 34체결/시가 272,000원이다. 시가 차이 +250원은 첫 episode의 청산 가격 입력에 직접 영향을 줄 수 있다. 14:43은 raw 1,741체결과 SQLite 1,701체결의 시가/종가가 동일하다. 근거: `e7-duplicate-minute-impact-20261008.json`, `e7-duplicate-minute-price-provenance-20261008.json` (모두 `runtime-data/reports/codex/`). 이는 보존 raw 기준 검증이지 거래소 feed의 완전성 보장이 아니며 random simulation/수익성 계산은 실행하지 않았다.
- 진단 가격뷰 구현: `e7-captured-raw-price-view-v1`은 읽기 전용 SQLite snapshot에서 raw 조각을 보존 JSONL 생성본과 정확히 대조하고, 기존 평가 가격이 저장 분봉과 같을 때만 요청 분봉의 open/close를 별도 불변 입력뷰로 교정한다. 원천 누락·충돌·검증 중 JSONL 변경은 차단하며 입력 버전/가격 fingerprint/raw 구간 및 파일 해시를 남긴다. `official_evaluation_permitted=false`이며 공식 daily writer와 연결하지 않았다.
- 실제 영향 회귀: 9/28 `005930` 적격 175행/실행 가능 57 episode의 ID·시각·avoid와 진입 가격은 유지됐다. 14:42 시가를 272,000→272,250원으로 교정하면 14:27 episode의 청산 가격만 +250원이고 MTM mark coverage는 동일하다. 단일 모집단 episode를 선택해 가격만 시험한 진단 민감도는 normal/double 비용에서 최종 자산 차이 +1,745.71/+1,741.43원이며 14:29 episode는 두 조건 모두 0원이다. 이는 avoid를 진단 실행에서만 무시한 가상 비교이지 공식 policy 수익이나 random-control 결과가 아니다. 최종 근거: `runtime-data/reports/codex/e7-price-input-view-reviewed-20261008.json`; 입력 fingerprint `8695f9a350dd5b5cb0db4e6d1119a9678898c97e52cbeb297cd3a9820e8ae57a`. 앞선 `e7-price-input-view-validation-20261008.json`은 리뷰 전 진단 이력으로 별도 보존한다. 공식 artifact 24개를 포함한 검증 대상 파일 29개 해시와 DB 가격 행을 보존했다.
- 남은 작업: 다음 정상 세션의 분봉 재생성 방지/late 원본 보존을 관측한다. 과거 중복 판단 및 통합 정본 예측 부재는 가격뷰로 해결되지 않으며 공식 평가 차단을 유지한다. 원래 조각 예측을 임의 선택·삭제·재생성하지 않는다. 공식 평가 허용 계약 변경은 별도 범위·운영자 판단이 필요하며 기존 관측/manifest/전략과 혼합하지 않는다.
- 07:46~07:50 장전 후속 검토: runtime 정지/should-run false, watchdog fresh이며 당일 curated 산출물은 아직 없다. 오늘 세션 재발 방지 확인은 미완료다. 공식 acceptance 계약 검토는 완료했지만 활성화하지 않았다. 메모리 fixture에서 공식 package guard가 진단 전용 허가 false/원천 실패/가격 입력 혼합을 직접 거부하지 않는 경계를 확인했다. daily 원천 차단은 유지되며 실제 잘못된 공식 통과 사례를 주장하지 않는다. 다음 구현 우선순위는 공식 entrypoint/package의 source-acceptance envelope와 입력 버전/hash 강제다. 과거 교정 계약 또는 사전 고정한 복구 후 구간 계약은 별도 운영자 결정 사항이며 상세 조건은 `docs/Portfolio-Replay-Evaluator.md`가 소유한다.

## 10/7 장후 운영 확인 (수집 정상 / 연결 주의)

- 공식 data-quality(20:24:51 KST): raw market/orderbook `3,814/4,056` symbol-minute, closed feature `3,803/3,900=97.51%`, serving decision lineage `3,803/3,803=100%`. reconnect `7`, storm `0`, 재구독 및 첫 frame 복구 각 7건이다. 로그에서 매시 정각 부근 disconnect를 확인했으나 원천은 미확정이며, 기존 PINGPONG 응답 구현이 있어 설정을 추정 변경하지 않았다.
- 공식 Phase 0 history(17:48:10 KST): 최근 유효 10거래일(9/21~10/7) matched `3`, mismatch `7`, consecutive `2`, `ready=false`. 당일 `aligned`, 수량 불일치/미확정 제출 `0`, effective cash 및 common-mark 자산 차이 각각 `-2,243.52원`이다. 이는 허용 오차 내 일치이지 정확한 0원 일치가 아니다. 구판 snapshot 자산 차이 `+9,056.48원`은 평가 시점 차이로 별도 보존한다.
- 장후 recheck(20:23:16 KST)는 기존 증거 진단만 수행해 `aligned_with_tolerated_gaps`, 회계 변경/추가 체결 반영 0건이다. 남은 비용·정산·평가 시점 원인은 미확정이며 임의 정렬이나 baseline 재생성으로 차이를 없애지 않는다. 근거: `latest-paper-account-history.json`, `latest-paper-kis-mismatch-recheck.json`.
- E7 daily evidence(20:25:05 KST): 공식 `portfolio-replay-v2-minute-mtm`과 사전등록 manifest hash 일치, 미래 거래일 `24`, 모집단 episode `11,708`, 공식 policy episode/symbol `0/0`, mark observation 및 missing/stale/invalid mark 모두 `0`이다. `valid_collecting`이며 normal/2x cost, random-control 및 두 비중복 구간은 최소 표본 대기다. 대상 0건을 가격 품질 또는 수익성 통과로 해석하지 않는다. 근거: `runtime-data/reports/research/e7/latest-e7-daily-evidence.json`.

## 9/28 수집 상태 이력 (수집 정상 / 연결 주의)

- 9/28 장후 data-quality는 raw market/orderbook `3,817/4,053` symbol-minute, closed feature `3,801`, serving decision `3,803/3,803 (100%)`이다. raw market coverage는 `3,817/3,910=97.62%`, closed feature coverage는 `3,801/3,900=97.46%`로 분모를 구분한다.
- `H0STCNT0` 다건 frame의 actual row width 보완은 실제 세션에서 수집·특징·판단 lineage 완결로 검증됐다. 과거 raw 데이터는 재작성하지 않았다.
- 9/28 WebSocket reconnect `9`, storm `0`이다. 원인은 `no close frame received or sent` 8건, 재구독 뒤 30초 무수신 1건이다. 수집 정상과 연결 주의를 분리하고, 과거 storm 이력은 별도로 보존한다.
- 수신 queue 분리는 broker REST sync가 socket frame 소비를 막지 않게 한다. 정각 disconnect의 upstream/KIS/네트워크 원천은 저장 증거만으로 확정하지 않으며 retry 정책이나 전략은 변경하지 않는다.

## 10/7 최근 품질 집계 성능 검증

- 장외 runtime 정지/should-run false 상태에서 일일 품질 집계를 최근 관측 10일 제한 조회로 분리했다. 전체 이력 합계는 `--include-history` 명시 실행에만 생성하며, 미요청값을 0이나 최근 합계로 대체하지 않는다.
- 약 30GiB 동일 운영 DB 검증은 `78.662초`였다. 10/6 기존 전체 이력 포함 실행의 약 13분과 비교한 측정이며 캐시/동시 부하가 고정된 반복 벤치마크는 아니다. 최근 일별 raw/derived/label, 최신 종목 집계, lineage/reconnect/gap, assessment는 기존 공식 보고서와 모두 일치했다. 실행 시각에 따라 변하는 raw lag만 비교에서 제외했다.
- 검증 결과는 `.tmp-tests/kis-quality-bounded-20261007.json`에 격리했고 공식 운영 report, DB/인덱스, Phase 0/E7 기준은 변경하지 않았다. 기존 장후 wrapper 명령은 유지하므로 다음 실행부터 제한 조회가 적용된다.
- 당시 관련 테스트 28건은 통과했으나 전체 720건은 기존 `tests/test_paper_reconciliation.py`의 `RuntimeWrite` import 오류 1건으로 실패했다. 10/7 후속 수동 작업에서 import를 `RuntimeWriter`로 수정했고, 정합 모듈 8건 및 전체 unittest 727건이 통과해 회귀 blocker를 해소했다. production 코드/DB/API/전략은 이 후속 수정에서 변경하지 않았다.

## 프로젝트 목표 정합성

- 현재 운영 목표는 실전 자동매매가 아니라 `paper` 기준으로 `수집 -> 특징 -> 예측 -> 판단 -> 모의주문/체결 -> KIS 모의계좌 정합 -> 비용 후 포트폴리오 검증`을 증거로 연결하는 것이다.
- 2026-09-15 시각 범위 ValueError와 listener 종료로 coverage `1.99%/6.01%`, bars/features/decision `0`의 수집 손실이 있었다. 격리 수정 이후 최근 거래일 수집은 회복됐지만 과거 손실 데이터를 복원하거나 정상으로 재분류하지 않는다.
- 2026-09-17에는 `H0STCNT0` 다건 frame 정렬 오류를 확인하고 보완했지만, raw market/orderbook coverage가 `13.89%/14.63%`에 그쳐 수집 정상 판정에는 이르지 않았다.
- 2026-09-18에는 parser 복구가 확인됐으나 reconnect 9/storm 1로 당일 실패였다. 최신 무storm 거래일과 이 장애 이력을 혼합하지 않는다.
- 현재 통과한 수익 후보는 `0개`이고 수익화 판정은 `no_profitable_candidate`다. 시스템은 개발 목표에는 대체로 맞지만 실전 수익화 준비는 아직 통과하지 못했다.

## 운용과 수집

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 9/28 확인 시점 KIS 거래일: `2026-09-28`
- 9/23 역사 raw market/orderbook rows: `587,003/554,796`; 최신 coverage와 lineage는 위 수집 상태를 기준으로 한다.
- 9/28 data-quality는 `watch/ATTENTION`이었다. 다음 정상 세션에서도 reconnect/storm과 복구 증적을 함께 확인한다.
- 시각 파서는 5자리 값을 leading-zero로 정규화하고 유효하지 않은 HHMMSS 레코드만 경고 후 건너뛴다.
- 운영 SQLite는 약 `30 GiB`, WAL은 확인 시점 0바이트이며 D드라이브 여유는 약 458GiB다. 대형 DB 전체 집계와 snapshot은 장외·D드라이브 기준을 유지한다.

## 학습과 수익성

- 2026-09-28 장후 ML: `status=ok`, `quick-live-train`, 17:22:51 KST 완료; label refresh `status=ok`, 17:48:34 KST 완료.
- top challenger `linear_score_builtin`: 3분류 정확도 `15.33%`, buy/trade hit `7.81%`, 누적 진단 순수익 `-490.15%`, 거래 `1,678건`이다. 이는 계좌 수익률이 아니며 active `baseline-h15-v1` 유지, 승격은 없다.
- buy-avoid: 최신 9/28 갱신, joined `72,053`행. threshold `0.40`의 overlapping-row 진단 delta는 양수지만 절대 portfolio 수익은 음수여서 `rejected_no_absolute_portfolio_profit`이다.
- buy-rescue: 실제 serving decision ledger `181,236`행 중 eligible `91,863`행이다. 6/11 이후 탐색 포함 LightGBM threshold `0.55` 진단 77행, precision `57.14%`이며 portfolio/random-control 미충족으로 후보가 아니다. Cybos proxy는 7/5의 stale `buy_avoid_candidate_only`로 별도 보존한다.
- hold-rescue: replay 가능 `383 lot`; threshold `0.40` 적용 `38 lot`, delta `-26,887원`; `0.45` 적용 5 lot, delta `-7,696원`이다. `diagnostic_only_no_hold_rescue_candidate`를 유지한다.
- meta-policy: primary candidate 없음. rescue/avoid는 관측 전용으로 유지한다.
- 현행 비용 모델은 `krx-common-stock-2026-v1`, 왕복 `0.29%`, 2배 민감도 `0.58%`다.
- E7 buy-rescue 미래 검증은 threshold `0.55`, `2026-08-31 09:15 KST` 이후 구간, 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 비중복 2구간을 사전등록했다. 주문 정책에는 반영하지 않는다.
- 기존 `portfolio-replay-v1-entry-mark`는 보존했다. 공식 `portfolio-replay-v2-minute-mtm`과 manifest `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`는 일치한다.
- E7은 9/28 장후 artifact 기준 미래 거래일 `18일`, 실행 가능 모집단 episode `8,861`, official policy episode/symbol `0/0`, mark observation 및 missing/stale/invalid mark 모두 `0`이다. `valid_collecting`, normal/2x cost 및 random control·두 비중복 구간은 최소 표본 대기다. mark 0은 평가 대상이 없다는 뜻이지 가격 품질 통과 증거가 아니다.
- read-only 원장 재집계: 미래 join `53,101`행, 적격 `26,863`행, threshold 통과 적격 행 1건, 최초 판단 유지 grouping 후 선택 episode 0건이다. 9/3 `086520` 12:29 점수 `0.552476`은 12:25 최초 점수 `0.369073`인 같은 episode에 묶인다. 현재 구현 결과와 일치하며 사후 grouping/threshold 변경으로 표본을 만들지 않는다.
- 과거 독립 교차검사에서는 당시 검사 범위의 누락/중복/불일치 0건을 보고했다. 10/8 강화 검증에서는 9/28 두 분봉의 교차 join을 발견했고 daily writer에 shadow identity·중복 fail-closed 검증을 추가했다. 과거 검사 결과를 현재 검증 통과로 재사용하지 않으며 현재 공식 평가 차단과 후속 작업은 위 10/8 단락을 따른다.

## 외부 shadow의 실제 상태

- 수급·OpenDART 공시·KRX 공매도는 운영자 공식 export를 읽는 평가 경로만 구현돼 있다. 입력 JSONL 3종이 모두 없으며 자동 수집 중이 아니다.
- 수급은 `no_observations_file`, SNS는 `no_events_file`; 공시/공매도 최신 report는 아직 없다. 입력 확보와 실제 no-look-ahead 평가가 다음 단계이며 네트워크 collector나 새 소스는 이번 감사에서 추가하지 않았다.

## Phase 0과 readiness
- 과거 공식 Phase 0 관측(10/2): 현재 epoch 최근 유효 10거래일 matched `1`, mismatch `9`, consecutive `0`, `ready=false`. 당시 `035420` 로컬 3주/KIS 0주와 미확정 제출 1건이 있었다. 최신 누적은 위 10/7 요약을 따르며 과거 일별 판정은 재작성하지 않는다.
- 10/3 별도 승인 KIS 읽기 전용 1회 조회는 9/29 `035420` 주문·체결 4행/1페이지, pagination complete였다. 10:48:21 매도 3주, 주문가 194,600원, 체결 평균 194,700원/총액 584,100원 1행만 로컬 submission과 미연결이다. 로컬 10:47 `submission_unknown` 매도 3주와 종목·방향·수량·주문가가 일치하지만 timeout으로 broker ACK의 정확한 ID 연결은 없다.
- 반복 불일치의 원인은 이 미확정 체결이 확정 ID 전용 일일 sync에서 제외된 점과, 9/29 로컬 평가 snapshot을 10/2 KIS 현재 평가액과 직접 비교한 점이다. 전자는 자동 추정 반영하지 않으며, 후자는 `paper-account-reconciliation-v2-common-mark`로 동일 KIS mark 기준 비교/구판 snapshot gap 별도 보고를 구현했다.
- 10/3 계좌 소유자 승인 후 `recover_paper_035420_sell_once.py --execute --owner-approved`를 정확히 1회 실행했다. 원본 백업과 감사 이벤트를 남기고 현재 주문을 `externally_reconciled`, `035420` 보유를 3주에서 0주로 변경했으며 현금에 연구용 비용 가정에 따른 순매도대금 `582,844.185원`을 반영했다. 합성 fill/submission, 과거 snapshot, E7 fill 원장, Phase 0 이력은 변경하지 않았다. 직접 broker ACK ID와 실제 비용은 미확정이다.
- 보정 후 읽기 전용 DB 검증은 `035420` 0주, 현금 `7,586,616.2575원`, 열린 포지션 4종목, 감사 이벤트 1건, 합성 fill 0건이다. 10/2 캐시 KIS 계좌와 current epoch baseline을 적용한 오프라인 비교는 수량 불일치 0, 미확정 제출 0, 현금 및 common-mark 자산 차이 각각 `-1,927.7425원`으로 `aligned`다. 이는 새 KIS 조회나 공식 유효일 판정이 아니며 다음 실제 거래일 장후의 fresh 계좌 snapshot으로 재검증해야 한다.

- 현재 paper account epoch는 `paper-2026-09-03`이다. 활성일 `2026-09-03`, 만료일 `2026-12-03`, 갱신 경고 시작 `2026-11-03`, 긴급 경고 시작 `2026-11-26`으로 관리한다.
- 새 APP 자격정보의 auth-only token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` read-only orderability가 모두 통과했다. 실제 주문·취소는 실행하지 않았다.
- 새 계좌에서 2026-09-03 자연 KIS cash-order submission 36건이 성공했다. 이전 `broker_account_not_orderable`은 만료·무효 상태였던 이전 계좌가 주원인으로 사실상 확인됐고 endpoint entitlement case는 같은 오류가 새 계좌에서 재발할 때까지 닫는다.
- 같은 날 invalid tick 4건과 network timeout 1건을 분리했다. invalid tick은 KRX 일반주권 500원 단위 위반이며 `broker_invalid_request/invalid_price_tick`으로 교정한다.
- 2026-09-06 계좌 소유자 승인으로 현재 KIS paper snapshot 기준 marker-only clean baseline을 생성했다. baseline은 current epoch와 `compatible`이고 immutable backup을 보존했다. `SyncInitialCash`, 주문·취소, order-fill 재조회는 실행하지 않았다.
- baseline 직후의 `aligned_waiting_first_submission`, mismatch/effective cash/total asset gap 0은 9/6 역사 스냅샷이며 현재 정합 상태가 아니다.
- 2026-09-07 장후 order-fill sync는 9페이지/124행을 완결했다. submission 124/124 exact-linked, final 123/open 1이며 pending `005930` 2주 지정가 주문은 실제 broker-authoritative 미체결 상태로 보존한다.
- 과거 epoch는 유효 `10/10`, matched `0`, mismatch `10`, 종목 `035420/086520/105560/247540`로 미통과 이력을 보존한다.
- 현재 epoch의 최근 유효 10거래일(9/10~9/23)은 matched `0`, mismatch `10`, consecutive matched `0`인 역사 기록으로 보존한다. 이는 거래 0건이 아니라 로컬·KIS 계좌의 수량·잔고·총자산이 모두 일치한 날이 0일이라는 뜻이다. 당시 `373220` local 1주/broker 0주였고, 9/24 snapshot의 effective cash gap `-350,593.78원`, total asset gap `-31,093.78원`도 과거 비교다. 현재 보정 결과는 아래와 분리한다.
- 9/28 당시 누적 broker submissions는 `352`; 9/28 자연 제출은 `035420` 매수/매도 각 3주와 `105560` 매수 3주의 총 3건이다. `035420` 양방향은 체결됐고 `105560`은 21:16 재조회에서도 체결 0/잔량 3인 `open`으로 확인했다. 당시 미확정 local submission은 0건이었다. 강제 거래나 취소는 하지 않았다.
- 현행 Phase 0 유효일 코드는 당일 신규 주문 수가 아니라 current-baseline 누적 mirrored submission 이력과 post-close snapshot을 사용한다. 따라서 신규 제출 0건인 보유 관측일도 유효일이 될 수 있다. baseline 이후 제출 이력이 전혀 없는 날·weekend/holiday는 제외하며 이번 감사에서 분모 규칙을 바꾸지 않았다.
- 9/24 bounded 3일 조회는 반환 0행이다. 별도 승인으로 current baseline `9/6`부터 최신 계좌 snapshot `9/24`까지 KIS 주문·체결을 장외에 정확히 1회 조회했다. 24페이지/351행에서 `pagination_complete=true`; 로컬 submission 349건과 연결되고 2행은 연결되지 않았다. 중복 exact key 0, 모호한 fallback key 3건이다. 전체기간 체결 재구성 수량은 KIS snapshot의 5종목과 모두 일치하지만 로컬 장부는 `373220` 1주가 남는다. 후속 read-only KIS 표본 조회에서 미연결 2행을 특정했다: 9/8 `373220` 매도 1주 체결 1주(349,500원), `005930` 매도 2주 체결 0주. 같은 날 로컬 `373220` 매도 1주(349,500원)는 KIS 요청 타임아웃 후 `broker_network_error`/`rejected`로 기록되어 submission·fill 연결이 없다. 종목·방향·수량·가격이 일치하고 다른 미연결 체결이 없어, 응답을 잃은 주문이 브로커에서는 접수·체결된 것이 수량 차이의 강한 원인 증거다. 응답이 없어 브로커 주문 ID의 직접 연결은 미확정이며 자동 정렬 근거로 쓰지 않는다.
- 22페이지/329행 full-period activity는 `2026-08-14`의 이전 계좌 증거로 현재 계좌 판단에 쓰지 않는다. 현재 계좌 보고서의 `external_or_unlinked_broker_activity`와 trace의 `cause_identified_clean_baseline_still_required`는 개별 미연결 행을 조회하기 전의 포괄적·낡은 분류다. 위의 9/8 timeout/체결 증거가 더 구체적이며, 이 상태 문자열을 자동 baseline 재생성 허가로 해석하지 않는다.
- 9/24 미래 주문 보호 코드: 새 broker paper submit의 network/unknown 응답은 `submission_unknown`과 보류 종목으로 남겨 중복 제출을 막고, sync report는 미확정 로컬 제출 수를 따로 기록한다. 미확정 주문이 있으면 수치상 계좌 일치에도 reconciliation을 `needs_review`로 둔다. 기존 9/8 rejected 주문·포트폴리오·과거 snapshot은 변경하지 않았으며 현재 Phase 0 matched 0/10도 그대로다.
- 9/24 추가 확인: 9/8 373220 매도는 승인된 KIS read-only 조회 1회(1페이지/10행, pagination complete)에서 9건이 기존 로컬 제출과 연결되고, 15:03:22의 1주·349,500원 전량 체결 1건만 미연결이었다. 같은 거래일의 동일 종목·방향·수량·가격 로컬 주문 후보는 15:01 분봉 시각의 timeout/rejected 1건뿐이다. 15:01은 실제 전송 시각이 아닌 분봉 이벤트 시각이므로 브로커 접수 시각과 직접 일치 검사는 불가하다. 9/7과 9/8 장후 cash gap은 -615.81원에서 -349,965.76원으로 이동했다. 연구용 비용 가정의 매도 순유입 348,748.575원을 단순 반영하면 9/8 gap은 약 -1,217.18원이지만 실제 브로커 수수료·세금과 유실된 주문번호 직접 연결은 미확인이다. 9/21 로컬 평가 snapshot과 9/24 브로커 snapshot은 동시점이 아니며 현재 포지션 mark 합계와 로컬 최신 평가 snapshot 사이에도 26,500원 차이가 있어 총자산 gap을 해당 매도 손익으로 단정하지 않는다. 계좌/DB/과거 snapshot/Phase 0 기준은 변경하지 않았다.
- 9/27 계좌 소유자는 직접 매도한 적이 없음을 확인하고 1회 로컬 보정을 승인했다. `recover_paper_timeout_sell_once.py`로 현재 `373220`만 0주로 정리하고 기존 연구용 비용 가정(commission 52.425원, sell tax 699원)의 순현금 348,748.575원을 반영했다. 현금은 7,597,135.795원, 보유 종목은 4개다. 단일 SQLite transaction에 현재 포지션 변경과 보정 이벤트/새 snapshot을 함께 저장했고, exclusive 0600 preimage backup을 먼저 보존했다. 원래 rejected 주문·실제 fill·broker submission·과거 snapshot과 9/6 baseline은 재작성하지 않았다. 주문번호 연결은 `inferred_owner_approved_not_exact`이며 합성 fill이나 submission을 만들지 않았다.
- 9/27 보정 직후 수량은 9/25 cached KIS snapshot과 일치했고 effective cash gap 약 -1,845.205원, total asset gap 약 -6,845.205원이었다. 이는 역사 cached 비교이며 실제 KIS 비용은 미확인이다. 보정은 E7 평가 fill 원장이나 manifest를 변경하지 않았다.
- 9/28 20:28 정기 recheck는 order-fill GET timeout으로 중단됐다. 예외 시 `latest-sync`가 이전 성공으로 남는 보고 누락을 수정하고, 별도 승인 후 21:16 장외 검증을 논리적 1회 수행했다. 1페이지/3행 모두 기존 제출에 연결됐고 추가 fill/주문 변경은 0건이다. 보고서는 `runtime-data/reports/codex/manual-recheck-20260928.json`이며 정기 실패 산출물은 보존한다.
- 9/28 당시 공식 account sync는 `aligned`, 보유 수량 mismatch `0`, effective cash gap `-1,865.905원`, 구판 snapshot total asset gap `+8,434.095원`이었다. 기존 10,000원 미만 허용 판정의 이력이며 정확한 0원 일치를 뜻하지 않는다. 현재 판정은 위 10/7 요약과 구분한다.
- 9/28 당시 최근 유효 10거래일(9/11~9/28)은 matched `1`, mismatch `9`, consecutive matched `1`, `ready=false`였다. 과거 불일치를 지우지 않으며 최신 누적은 위 10/7 요약을 따른다.
- 장후 자동화는 확정 체결만 기존 동기화로 반영한 뒤 수량/현금/평가액 원인과 남은 조사를 보고한다. 당일 유효 기록이 있으면 KIS를 다시 부르지 않고 diagnose-only로 전환한다. identity/원장/조회 완결성이 불명확하면 반영을 차단하며 임의 정렬·기준선·과거 이력 교정은 하지 않는다. 구체 절차는 daily-ops skill과 KIS runbook이 소유한다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: bounded live read-only 관측 1회 통과 이력은 있으나 latest readiness가 2026-07-11 생성물이라 현재 승격 증거로는 stale하다. 최신 수집 회복만으로 stale readiness를 통과 처리하지 않는다.
- Phase 2/3: 미시작. real-evidence 연결기는 완료됐지만 새 실제 세션의 fresh Phase 1b readiness, 수익 후보, Phase 0 통과 전에는 진입하지 않는다.

## FULL CHECK 조치

1. 종가 동시호가 예상 공백과 예상 밖 공통 수집 공백을 분리해 false failure를 제거했다.
2. hold-rescue 기본값을 현재 설정과 일치시키고 적용 lot 0인 threshold가 최선으로 선택되지 않게 했다.
3. Phase 0 clean baseline 이전/이후 epoch를 분리하고 dashboard의 로컬 손익을 Phase 0 통과 전 수익 증거로 보지 않게 했다.
4. E7 LightGBM buy-rescue 미래 검증을 사전등록해 사후 threshold 탐색을 막고 실제 수익화 검증 순서를 고정했다.
5. runtime/watchdog/dashboard/startup launcher를 확인했고 재부팅 뒤 watchdog과 dashboard만 장외에 안전 복구했다. live runtime은 시작하지 않았다.
6. 2026-08-28 broker 실패 832건을 830건 계좌 hard rejection과 2건 rate limit으로 분리하고, 30분 account circuit과 decision→attempt→failure 계보를 추가했다. E7 threshold/model/gate/allocator는 변경하지 않았다.
7. 기존 replay v1 결과를 보존하고 minute MTM v2, exact-mark coverage, E7 immutable manifest, 1,000회 shared-context random control, 16개 공식 결과 compatibility guard를 추가했다. 관련 targeted 21건과 전체 586건을 통과했다.
8. E7 일일 read-only artifact writer와 identity/mark/sample fail-closed 상태를 추가했다.
9. KIS paper `VTTC8908R` 매수가능조회 dry-run/명시 실행 probe와 sanitized taxonomy를 추가했다.
10. targeted 56건과 전체 605건, repository audit 오류 0건을 통과하고 장외에 watchdog/dashboard만 안전 복구했다.
11. KRX 지정가 호가단위를 single-source로 정규화하고 실제 request/evidence/submission 가격을 일치시켰다.
12. WebSocket 재구독 완료·첫 프레임 복구 로그와 storm/common-gap 우선 `CRITICAL/실패` 판정을 추가했다.
13. 2026-09-04 current account reconciliation과 2026-09-05 order-fill 완결을 교차 검증해 새 계좌 정합 blocker가 API 미완결이 아니라 이전 계좌 baseline 호환성임을 확인했다.
14. 2026-09-06 승인 marker-only clean baseline을 생성하고 직후 reconciliation에서 position/effective cash/total asset gap 0을 확인했다.
15. broker paper 부분체결은 KIS 누적 체결대금에서 이미 기록한 local fill 대금을 빼 delta 체결가를 계산하도록 수정했다. E7/Phase 0 기준과 과거 원장은 변경하지 않았다.
16. broker paper sync의 주문 상태·체결·이벤트·포지션·portfolio/broker snapshot SQLite 쓰기를 local order 단위 단일 transaction으로 묶었다. 중간 실패 시 DB와 메모리 portfolio를 함께 원복한다.
17. Phase 2용 live 주문 계약을 교정했다. manager의 `limit`을 KIS `ORD_DVSN=00`으로 변환하고, cancel에 미체결 잔량을 전달하며, market-data freshness 판정을 submit guard까지 연결했다. 실전 주문은 실행하지 않았다.
18. restart live order recovery는 inflight 주문을 `UNKNOWN`으로 전환한 뒤 live 계좌의 해당 거래일 order-fill history가 완결되고 broker identity가 정확히 일치할 때만 상태·누적 fill delta를 복구한다. 누락·중복·불일치·불완전 pagination은 추정 없이 `UNKNOWN`을 유지한다.
19. Phase 1b readiness cycle이 최신 data-quality의 실제 KIS WebSocket recovery를 strict lineage와 30분 freshness로 검증해 우선 사용하도록 연결했다. 연결기 자체는 네트워크를 호출하지 않으며 오래된 2026-09-04 증거는 통과시키지 않는다.
20. WebSocket 수신을 stdlib queue와 단일 worker로 기존 직렬 processor에서 분리해 느린 broker REST sync가 socket frame 소비를 막지 않도록 했다. 2026-09-07 공백 원인은 교정했으며 다음 실제 세션 데이터로 효과를 확인한다.
21. KIS WebSocket 시각을 신뢰 경계에서 검증하고 잘못된 레코드만 격리했다. 유효한 5자리 시각은 leading-zero로 보정하며 listener 전체 종료를 막는 회귀 테스트를 추가했다.
22. KIS `H0STCNT0` 다건 frame은 advertised record count와 실제 token 수로 row 경계를 계산하고 문서상 필드 prefix만 저장하도록 보완했다. provider trailing field가 다음 row symbol/time으로 밀려드는 수집 결손을 차단한다.
23. 계좌 activity의 timezone-aware alignment/snapshot scope 검증을 추가해 이전 계좌 성공/실패가 현재 판정을 덮지 않도록 했다. nonempty bounded lookup도 partial evidence로 분류한다. malformed JSON 자료형은 제외하고 비선택 과거 증거는 별도로 보존한다. 집중 31건, 전체 664건 통과; structure audit 오류 0/기존 대형 모듈 경고 2건이다.

## 현재 blocker와 다음 순서

1. 현재 계좌 clean baseline은 완료됐다. 같은 baseline을 반복 생성하거나 과거 epoch 증거를 현재 분모와 섞지 않는다.
2. `373220` 수량 차이는 승인된 현재 상태 보정으로 해소했다. 타임아웃 주문의 exact broker identity는 여전히 미확정이며 과거 원장은 보존한다. 다음 정상 post-close에서 동시점 잔고·현금·총자산과 잔여 비용/평가 gap을 확인하고 이후 최근 10개 유효 거래일 모두 matched를 확인한다. 자동 정렬·baseline 재생성이나 강제 주문은 하지 않는다.
3. E7은 threshold/model/manifest를 바꾸지 않고 official episode와 종목 표본을 축적한다.
4. 다음 거래일에는 정각 reconnect와 storm 재발, 재구독/첫 프레임 회복, 예상 밖 공통 gap, coverage와 lineage를 함께 확인한다.
5. B2/B3, live-canary C1~C4 service 안전 계약, real WS evidence 연결기는 완료했다. 다음 실제 세션에서 30분 이내 fresh Phase 1b artifact를 만들고, Phase 2 runtime 조립 시 C4 단일 recovery 엔트리포인트를 연결해야 한다.
6. 공식 export 입력이 없는 외부 shadow는 기다리기만 해서는 축적되지 않는다. 승인된 입력 확보 경로를 구체화하고 E7/주문 정책과 분리한 상태로 평가한다.

### 이번 감사 근거

- 수집: `runtime-data/reports/data-quality/latest-kis-live-data-quality.json` (9/23 20:35 KST)
- 정합: `runtime-data/reports/reconciliation/latest-paper-account-history.json`, `latest-paper-account-sync.json` (9/24 16:40), `latest-paper-account-activity.json` (9/24 21:37), `latest-paper-kis-mismatch-trace.json` (9/24 21:39)
- E7: `runtime-data/reports/research/e7/latest-e7-daily-evidence.json` (9/23 20:36) 및 동일 기간 SQLite read-only 교차검사
- 검증: `.tmp-tests/full-check-20260924-focused.log`, `.tmp-tests/full-check-20260924-unittest.log`
- 승인 보정: `runtime-data/reports/codex/paper-account-recovery-20260908-373220-v1-before.json`, 동일 prefix의 `-result.json`; 집중 11건과 전체 679건 통과 (`.tmp-tests/paper-timeout-recovery-unittest.log`)

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 연구 사전등록: `docs/Model-Research-PreRegistration.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
