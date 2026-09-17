# 현재 상태

## 기준 시각

- 확인 시각: 2026-09-17 22:16 KST
- 장 상태: post-close
- live runtime: 정지, `paper`; 15:30 KST 정상 종료
- runtime watchdog: 실행 중, heartbeat 정상, `live_runtime_should_run=false`
- dashboard: 실행 중, server/API 정상
- Windows startup launcher: 설치 및 정상
- 수집 상태는 2026-09-17 장후 스냅샷을 반영한다.

## 2026-09-17 수집 상태 (복구 검증 중)

- 최신 장후 data-quality는 raw market/orderbook `543/572` of expected `3,910`, closed bar/feature/serving decision `94/94/94`, WebSocket reconnect `3`, storm `0`이다. lineage는 `94/94 (100%)`지만 공통 수집 결손으로 `CRITICAL/실패`다.
- KIS JSON PINGPONG pong 보완 뒤 reconnect storm은 해소됐지만, `H0STCNT0` 다건 체결 frame의 문서상 46개 필드 뒤 provider trailing field가 다음 row 시작으로 잘못 해석됐다. runtime 로그의 invalid timestamp `1,195`건이 이 정렬 오류를 뒷받침한다.
- parser는 advertised record count와 실제 token 수가 일치할 때 actual row width로 다음 row 경계를 이동하고, 문서상 prefix만 저장해 trailing field를 무시한다. 다건 frame 회귀 테스트를 추가했다.
- 이 수정은 수집 transport 계약만 다루며 E7 threshold/model/manifest, signal/gate/allocator, 주문·Phase 0 baseline은 변경하지 않았다.
- 다음 실제 세션에서 invalid timestamp 경고, common gap, coverage, closed feature와 decision lineage가 정상이어야 복구 완료로 판정한다.

## 프로젝트 목표 정합성

- 현재 운영 목표는 실전 자동매매가 아니라 `paper` 기준으로 `수집 -> 특징 -> 예측 -> 판단 -> 모의주문/체결 -> KIS 모의계좌 정합 -> 비용 후 포트폴리오 검증`을 증거로 연결하는 것이다.
- 2026-09-15 수집 중 시각 범위 ValueError와 listener 반복 종료가 확인됐고 market/orderbook coverage는 `1.99%/6.01%`, bars/features/decision rows는 `0`이었다. 잘못된 시각 레코드의 종료 경로를 재현해 격리했으며 다음 실제 세션 검증 전까지 운영 심각도는 `CRITICAL/실패`다.
- 2026-09-17에는 `H0STCNT0` 다건 frame 정렬 오류를 확인하고 보완했지만, raw market/orderbook coverage가 `13.89%/14.63%`에 그쳐 수집 정상 판정에는 이르지 않았다.
- 현재 통과한 수익 후보는 `0개`이고 수익화 판정은 `no_profitable_candidate`다. 시스템은 개발 목표에는 대체로 맞지만 실전 수익화 준비는 아직 통과하지 못했다.

## 운용과 수집

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 최신 KIS 거래일: `2026-09-17`
- raw market/orderbook symbol-minute: `543/572` of expected `3,910`; minute bar/feature closed `94/94`, coverage `2.41%`
- serving decision ledger: `94`행, complete lineage `94/94 (100%)`
- WebSocket: reconnect `3`, storm `0`; `H0STCNT0` invalid timestamp 경고 `1,195`건은 다건 frame의 trailing field 정렬 오류로 확인됐다.
- 최신 data-quality 판정은 `CRITICAL/실패`다. parser가 actual row width를 사용하도록 보완했으며, 과거 raw 데이터를 재작성하지 않는다. 다음 실제 세션 coverage와 decision lineage가 정상이어야 복구 완료로 판정한다.
- 시각 파서는 5자리 값을 leading-zero로 정규화하고 유효하지 않은 HHMMSS 레코드만 경고 후 건너뛴다.
- 운영 SQLite는 약 `29.062 GiB`, journal mode `wal`이다. 대형 DB 전체 집계와 snapshot은 장외·D드라이브 기준을 유지한다.

## 학습과 수익성

- 2026-09-15 장후 ML: `status=ok`, `quick-live-train`, 17:24 KST 완료
- 2026-09-15 label refresh: `status=ok`, 17:50 KST 완료
- top challenger `linear_score_builtin`: 3분류 정확도 `17.60%`, buy/trade hit `13.50%`, 누적 진단 순수익 `-443.21%`, 거래 `1,696건`이다. active `baseline-h15-v1` 유지, 승격은 없다.
- buy-avoid: `2026-07-13 09:15~2026-09-04 15:00`, joined `56,601`행. threshold `0.40`의 overlapping-row 진단 delta는 양수지만 절대 portfolio 수익은 계속 음수여서 `rejected_no_absolute_portfolio_profit`이다.
- buy-rescue(2026-09-07 확인 이력): decision ledger `143,105`행 중 eligible `72,730`행이며 `diagnostic_only_no_order_policy_change`다. Cybos proxy도 `buy_avoid_candidate_only`로 buy-rescue 주문 반영을 권하지 않는다.
- hold-rescue(2026-09-07 확인 이력): eligible `175 lot`; threshold `0.40` 적용 `38 lot`, delta `-26,887원`으로 `diagnostic_only_no_hold_rescue_candidate`다.
- meta-policy: primary candidate 없음. rescue/avoid는 관측 전용으로 유지한다.
- 현행 비용 모델은 `krx-common-stock-2026-v1`, 왕복 `0.29%`, 2배 민감도 `0.58%`다.
- E7 buy-rescue 미래 검증은 threshold `0.55`, `2026-08-31 09:15 KST` 이후 구간, 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 비중복 2구간을 사전등록했다. 주문 정책에는 반영하지 않는다.
- 기존 `portfolio-replay-v1-entry-mark`는 보존했다. 공식 `portfolio-replay-v2-minute-mtm`과 manifest `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`는 일치한다.
- E7은 2026-09-15 기준 미래 거래일 `11일`, 실행 가능 모집단 episode `6,182`, official policy episode/symbol `0/0`, mark observation `0`, missing/stale/invalid mark 모두 `0`이다. evaluator/manifest는 일치하고 evidence health는 `valid_collecting`이다. 거래일 기준만 충족했고 episode/종목 기준은 미충족이라 공식 수익성 평가는 시작하지 않는다.

## Phase 0과 readiness

- 현재 paper account epoch는 `paper-2026-09-03`이다. 활성일 `2026-09-03`, 만료일 `2026-12-03`, 갱신 경고 시작 `2026-11-03`, 긴급 경고 시작 `2026-11-26`으로 관리한다.
- 새 APP 자격정보의 auth-only token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` read-only orderability가 모두 통과했다. 실제 주문·취소는 실행하지 않았다.
- 새 계좌에서 2026-09-03 자연 KIS cash-order submission 36건이 성공했다. 이전 `broker_account_not_orderable`은 만료·무효 상태였던 이전 계좌가 주원인으로 사실상 확인됐고 endpoint entitlement case는 같은 오류가 새 계좌에서 재발할 때까지 닫는다.
- 같은 날 invalid tick 4건과 network timeout 1건을 분리했다. invalid tick은 KRX 일반주권 500원 단위 위반이며 `broker_invalid_request/invalid_price_tick`으로 교정한다.
- 2026-09-06 계좌 소유자 승인으로 현재 KIS paper snapshot 기준 marker-only clean baseline을 생성했다. baseline은 current epoch와 `compatible`이고 immutable backup을 보존했다. `SyncInitialCash`, 주문·취소, order-fill 재조회는 실행하지 않았다.
- 직후 reconciliation은 `aligned_waiting_first_submission`, mismatch `0`, effective cash gap `0원`, total asset gap `0원`이다. current view는 `005930` 1주·`035420` 2주, 유효현금 `9,319,451원`, 총자산 `10,001,951원`이며 raw cash gap `-1,850원`은 KIS 현금 표시 정의 차이로 분리한다.
- 2026-09-07 장후 order-fill sync는 9페이지/124행을 완결했다. submission 124/124 exact-linked, final 123/open 1이며 pending `005930` 2주 지정가 주문은 실제 broker-authoritative 미체결 상태로 보존한다.
- 과거 epoch는 유효 `10/10`, matched `0`, mismatch `10`, 종목 `035420/086520/105560/247540`로 미통과 이력을 보존한다.
- 현재 epoch는 유효 거래일 `7일`, matched `1`, mismatch `6`, consecutive matched `0`이다. 2026-09-08 이후 `373220`이 local 1주/broker 0주로 불일치하며 계좌 snapshot과 bounded 주문·체결 원장도 서로 충돌한다. 자동 정렬 없이 원천 증거 재확인이 필요하다.
- full-period sanitized account activity는 22페이지/329행, pagination 완결이며 320행 local-linked와 9행 broker-only로 이전 divergence 원인을 확정했다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: bounded live read-only 관측 1회 통과 이력은 있으나 latest readiness가 2026-07-11 생성물이라 현재 승격 증거로는 stale하다. 2026-09-17 data-quality도 수집 실패이고 30분 freshness도 초과했으므로 새 실제 세션의 정상 증거 없이는 readiness를 통과하지 않는다.
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

## 현재 blocker와 다음 순서

1. 현재 계좌 clean baseline은 완료됐다. 같은 baseline을 반복 생성하거나 과거 epoch 증거를 현재 분모와 섞지 않는다.
2. `373220` local 1주/broker 0주 차이를 KIS 계좌 snapshot과 완결 주문·체결 원장으로 재확인한다. 현재 consecutive matched가 0이므로 "3일만 더 관찰"하면 Phase 0이 통과하는 상태가 아니다.
3. E7은 threshold/model/manifest를 바꾸지 않고 official episode와 종목 표본을 축적한다.
4. 다음 거래일에는 `H0STCNT0` timestamp skip 경고 수, runtime 재시작 여부, market/orderbook coverage, bars/features와 decision lineage를 함께 확인한다.
5. B2/B3, live-canary C1~C4 service 안전 계약, real WS evidence 연결기는 완료했다. 다음 실제 세션에서 30분 이내 fresh Phase 1b artifact를 만들고, Phase 2 runtime 조립 시 C4 단일 recovery 엔트리포인트를 연결해야 한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 연구 사전등록: `docs/Model-Research-PreRegistration.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
