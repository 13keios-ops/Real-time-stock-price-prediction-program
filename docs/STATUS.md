# 현재 상태

## 기준 시각

- 확인 시각: 2026-09-24 21:44 KST, Phase 0 전체기간 주문·체결 확인
- 장 상태: holiday
- live runtime: 정지, `paper`; 휴장 중 시작하지 않음
- runtime watchdog: 실행 중, heartbeat 정상, `live_runtime_should_run=false`
- dashboard: 실행 중, server/API 정상
- Windows startup launcher: 설치 및 정상
- 수집·학습·E7은 2026-09-23 장후, 계좌 비교는 2026-09-24 16:40 KST 스냅샷을 반영한다.

## 최신 수집 상태 (수집 정상 / 연결 주의)

- 최신 장후 data-quality는 raw market/orderbook `3,809/4,060` symbol-minute, closed bar/feature `3,798/3,798`, serving decision `3,798/3,798 (100%)`이다. raw market coverage는 `3,809/3,910=97.42%`, closed feature coverage는 `3,798/3,900=97.38%`로 분모를 구분한다.
- `H0STCNT0` 다건 frame의 actual row width 보완은 실제 세션에서 수집·특징·판단 lineage 완결로 검증됐다. 과거 raw 데이터는 재작성하지 않았다.
- WebSocket은 `no close frame received or sent` reconnect `7`, storm `0`이다. 재구독 및 첫 프레임 복구가 각각 7건 확인됐으며 마지막 복구는 15:00:11 KST다. 최근 거래일은 수집 정상과 연결 주의를 분리하고, 과거 storm 이력은 별도로 보존한다.
- 수신 queue 분리는 broker REST sync가 socket frame 소비를 막지 않게 한다. 정각 disconnect의 upstream/KIS/네트워크 원천은 저장 증거만으로 확정하지 않으며 retry 정책이나 전략은 변경하지 않는다.

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
- 최신 KIS 거래일: `2026-09-23`
- raw market/orderbook rows: `587,003/554,796`; coverage와 lineage는 위 최신 수집 상태를 기준으로 한다.
- 최신 data-quality는 `watch/ATTENTION`이다. 다음 정상 세션에서도 reconnect/storm과 복구 증적을 함께 확인한다.
- 시각 파서는 5자리 값을 leading-zero로 정규화하고 유효하지 않은 HHMMSS 레코드만 경고 후 건너뛴다.
- 운영 SQLite는 약 `30 GiB`, WAL은 확인 시점 0바이트이며 D드라이브 여유는 약 458GiB다. 대형 DB 전체 집계와 snapshot은 장외·D드라이브 기준을 유지한다.

## 학습과 수익성

- 2026-09-23 장후 ML: `status=ok`, `quick-live-train`, 17:25:29 KST 완료; label refresh `status=ok`, 17:50:16 KST 완료.
- top challenger `linear_score_builtin`: 3분류 정확도 `14.80%`, buy/trade hit `9.39%`, 누적 진단 순수익 `-461.61%`, 거래 `1,630건`이다. 이는 계좌 수익률이 아니며 active `baseline-h15-v1` 유지, 승격은 없다.
- buy-avoid: 최신 9/23 갱신, joined `70,563`행. threshold `0.40`의 overlapping-row 진단 delta는 양수지만 절대 portfolio 수익은 음수여서 `rejected_no_absolute_portfolio_profit`이다.
- buy-rescue: 실제 serving decision ledger `177,433`행 중 eligible `89,908`행이다. 6/11 이후 탐색 포함 LightGBM threshold `0.55` 진단 77행, precision `57.14%`이며 portfolio/random-control 미충족으로 후보가 아니다. Cybos proxy는 7/5의 stale `buy_avoid_candidate_only`로 별도 보존한다.
- hold-rescue: replay 가능 `382 lot`; threshold `0.40` 적용 `38 lot`, delta `-26,887원`; `0.45` 적용 5 lot, delta `-7,696원`이다. `diagnostic_only_no_hold_rescue_candidate`를 유지한다.
- meta-policy: primary candidate 없음. rescue/avoid는 관측 전용으로 유지한다.
- 현행 비용 모델은 `krx-common-stock-2026-v1`, 왕복 `0.29%`, 2배 민감도 `0.58%`다.
- E7 buy-rescue 미래 검증은 threshold `0.55`, `2026-08-31 09:15 KST` 이후 구간, 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 비중복 2구간을 사전등록했다. 주문 정책에는 반영하지 않는다.
- 기존 `portfolio-replay-v1-entry-mark`는 보존했다. 공식 `portfolio-replay-v2-minute-mtm`과 manifest `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`는 일치한다.
- E7은 최신 장후 artifact 기준 미래 거래일 `17일`, 실행 가능 모집단 episode `8,258`, official policy episode/symbol `0/0`, mark observation 및 missing/stale/invalid mark 모두 `0`이다. `valid_collecting`, normal/2x cost 및 random control·두 비중복 구간은 최소 표본 대기다. mark 0은 평가 대상이 없다는 뜻이지 가격 품질 통과 증거가 아니다.
- read-only 원장 재집계: 미래 join `53,101`행, 적격 `26,863`행, threshold 통과 적격 행 1건, 최초 판단 유지 grouping 후 선택 episode 0건이다. 9/3 `086520` 12:29 점수 `0.552476`은 12:25 최초 점수 `0.369073`인 같은 episode에 묶인다. 현재 구현 결과와 일치하며 사후 grouping/threshold 변경으로 표본을 만들지 않는다.
- 미래 join 전체에서 shadow prediction ID·training run·artifact·hash·score를 독립 교차검사해 누락/중복/불일치 0건을 확인했다. 다만 daily writer 자체는 active lineage 존재 여부만 검사하므로 공식 평가 전 shadow identity·중복의 fail-closed 검증을 보강해야 한다. 평가 계약 변경이 필요하면 기존 공식 결과와 버전을 분리한다.

## 외부 shadow의 실제 상태

- 수급·OpenDART 공시·KRX 공매도는 운영자 공식 export를 읽는 평가 경로만 구현돼 있다. 입력 JSONL 3종이 모두 없으며 자동 수집 중이 아니다.
- 수급은 `no_observations_file`, SNS는 `no_events_file`; 공시/공매도 최신 report는 아직 없다. 입력 확보와 실제 no-look-ahead 평가가 다음 단계이며 네트워크 collector나 새 소스는 이번 감사에서 추가하지 않았다.

## Phase 0과 readiness

- 현재 paper account epoch는 `paper-2026-09-03`이다. 활성일 `2026-09-03`, 만료일 `2026-12-03`, 갱신 경고 시작 `2026-11-03`, 긴급 경고 시작 `2026-11-26`으로 관리한다.
- 새 APP 자격정보의 auth-only token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` read-only orderability가 모두 통과했다. 실제 주문·취소는 실행하지 않았다.
- 새 계좌에서 2026-09-03 자연 KIS cash-order submission 36건이 성공했다. 이전 `broker_account_not_orderable`은 만료·무효 상태였던 이전 계좌가 주원인으로 사실상 확인됐고 endpoint entitlement case는 같은 오류가 새 계좌에서 재발할 때까지 닫는다.
- 같은 날 invalid tick 4건과 network timeout 1건을 분리했다. invalid tick은 KRX 일반주권 500원 단위 위반이며 `broker_invalid_request/invalid_price_tick`으로 교정한다.
- 2026-09-06 계좌 소유자 승인으로 현재 KIS paper snapshot 기준 marker-only clean baseline을 생성했다. baseline은 current epoch와 `compatible`이고 immutable backup을 보존했다. `SyncInitialCash`, 주문·취소, order-fill 재조회는 실행하지 않았다.
- baseline 직후의 `aligned_waiting_first_submission`, mismatch/effective cash/total asset gap 0은 9/6 역사 스냅샷이며 현재 정합 상태가 아니다.
- 2026-09-07 장후 order-fill sync는 9페이지/124행을 완결했다. submission 124/124 exact-linked, final 123/open 1이며 pending `005930` 2주 지정가 주문은 실제 broker-authoritative 미체결 상태로 보존한다.
- 과거 epoch는 유효 `10/10`, matched `0`, mismatch `10`, 종목 `035420/086520/105560/247540`로 미통과 이력을 보존한다.
- 현재 epoch의 최근 유효 10거래일(9/10~9/23)은 matched `0`, mismatch `10`, consecutive matched `0`이다. 이는 거래 0건이 아니라 로컬·KIS 계좌의 수량·잔고·총자산이 모두 일치한 날이 0일이라는 뜻이다. `373220` local 1주/broker 0주가 지속된다. 9/24 snapshot의 effective cash gap은 `-350,593.78원`, total asset gap은 `-31,093.78원`이며 자동 정렬하지 않는다.
- 현재 누적 broker submissions는 `349`; 9/23 신규 local order와 broker submission은 모두 0건이다. decision은 signal 차단 2,251 / allocator zero 366 / position·pending 제약 1,181건이며 제출 단계에 이르지 않았다. 최근 자연 주문인 9/21 `247540` 6주는 decision→prediction/signal/target→local order→broker submission→9/21 14:48:59 fill로 연결된다.
- 현행 Phase 0 유효일 코드는 당일 신규 주문 수가 아니라 current-baseline 누적 mirrored submission 이력과 post-close snapshot을 사용한다. 따라서 신규 제출 0건인 보유 관측일도 유효일이 될 수 있다. baseline 이후 제출 이력이 전혀 없는 날·weekend/holiday는 제외하며 이번 감사에서 분모 규칙을 바꾸지 않았다.
- 9/24 bounded 3일 조회는 반환 0행이다. 별도 승인으로 current baseline `9/6`부터 최신 계좌 snapshot `9/24`까지 KIS 주문·체결을 장외에 정확히 1회 조회했다. 24페이지/351행에서 `pagination_complete=true`; 로컬 submission 349건과 연결되고 2행은 연결되지 않았다. 중복 exact key 0, 모호한 fallback key 3건이다. 전체기간 체결 재구성 수량은 KIS snapshot의 5종목과 모두 일치하지만 로컬 장부는 `373220` 1주가 남는다. 후속 read-only KIS 표본 조회에서 미연결 2행을 특정했다: 9/8 `373220` 매도 1주 체결 1주(349,500원), `005930` 매도 2주 체결 0주. 같은 날 로컬 `373220` 매도 1주(349,500원)는 KIS 요청 타임아웃 후 `broker_network_error`/`rejected`로 기록되어 submission·fill 연결이 없다. 종목·방향·수량·가격이 일치하고 다른 미연결 체결이 없어, 응답을 잃은 주문이 브로커에서는 접수·체결된 것이 수량 차이의 강한 원인 증거다. 응답이 없어 브로커 주문 ID의 직접 연결은 미확정이며 자동 정렬 근거로 쓰지 않는다.
- 22페이지/329행 full-period activity는 `2026-08-14`의 이전 계좌 증거로 현재 계좌 판단에 쓰지 않는다. 현재 계좌 보고서의 `external_or_unlinked_broker_activity`와 trace의 `cause_identified_clean_baseline_still_required`는 개별 미연결 행을 조회하기 전의 포괄적·낡은 분류다. 위의 9/8 timeout/체결 증거가 더 구체적이며, 이 상태 문자열을 자동 baseline 재생성 허가로 해석하지 않는다.
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
2. `373220` 차이는 9/8 KIS 매도 1주 체결과 같은 종목·수량·가격의 로컬 timeout/rejected 주문 사이의 미확정 제출 결과가 가장 강한 원인이다. `005930` 미연결 매도 2주는 미체결이어서 수량 차이를 만들지 않았다. KIS 응답/주문 ID가 유실된 상태이므로 exact identity로 연결됐다고 주장하거나 자동 정렬·baseline 재생성을 하지 않는다. 먼저 broker submit timeout을 최종 거절이 아닌 unknown outcome으로 보존하고, 기존 계좌 이력과 로컬 attempt를 안전하게 연결하는 복구 계약을 설계·검증한다. 과거 9/8 장부 교정은 중복 적용·당시 snapshot 보존을 검토한 별도 승인 작업으로 분리한다. 이후 동일 시점 잔고·현금·총자산을 재검증하고 새 정합 유효 거래일 10일을 확인해야 하므로 "3일만 더 관찰"해서 통과하는 상태가 아니다.
3. E7은 threshold/model/manifest를 바꾸지 않고 official episode와 종목 표본을 축적한다.
4. 다음 거래일에는 정각 reconnect와 storm 재발, 재구독/첫 프레임 회복, 예상 밖 공통 gap, coverage와 lineage를 함께 확인한다.
5. B2/B3, live-canary C1~C4 service 안전 계약, real WS evidence 연결기는 완료했다. 다음 실제 세션에서 30분 이내 fresh Phase 1b artifact를 만들고, Phase 2 runtime 조립 시 C4 단일 recovery 엔트리포인트를 연결해야 한다.
6. 공식 export 입력이 없는 외부 shadow는 기다리기만 해서는 축적되지 않는다. 승인된 입력 확보 경로를 구체화하고 E7/주문 정책과 분리한 상태로 평가한다.

### 이번 감사 근거

- 수집: `runtime-data/reports/data-quality/latest-kis-live-data-quality.json` (9/23 20:35 KST)
- 정합: `runtime-data/reports/reconciliation/latest-paper-account-history.json`, `latest-paper-account-sync.json` (9/24 16:40), `latest-paper-account-activity.json` (9/24 21:37), `latest-paper-kis-mismatch-trace.json` (9/24 21:39)
- E7: `runtime-data/reports/research/e7/latest-e7-daily-evidence.json` (9/23 20:36) 및 동일 기간 SQLite read-only 교차검사
- 검증: `.tmp-tests/full-check-20260924-focused.log`, `.tmp-tests/full-check-20260924-unittest.log`

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 연구 사전등록: `docs/Model-Research-PreRegistration.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
