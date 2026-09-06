# 현재 상태

## 기준 시각

- 확인 시각: 2026-09-06 09:39 KST
- 장 상태: weekend
- live runtime: 2026-09-04 15:30 KST 정상 종료 후 정지, `paper`
- runtime watchdog: stale, process 정지, `live_runtime_should_run=false`
- dashboard: stale, server/API 정지
- Windows startup launcher: 설치 및 정상
- 시장·ML·E7은 2026-09-04 장후 스냅샷, KIS order-fill은 2026-09-05 후속 확인을 반영한다.

## 프로젝트 목표 정합성

- 현재 운영 목표는 실전 자동매매가 아니라 `paper` 기준으로 `수집 -> 특징 -> 예측 -> 판단 -> 모의주문/체결 -> KIS 모의계좌 정합 -> 비용 후 포트폴리오 검증`을 증거로 연결하는 것이다.
- 2026-09-04 decision ledger와 model artifact lineage는 완전하다. WebSocket reconnect는 많았지만 storm과 예상 밖 공통 공백 없이 모두 재구독·첫 프레임 복구가 확인돼 운영 심각도는 `ATTENTION/주의`이며, active model과 주문 정책은 변경하지 않는다.
- 현재 통과한 수익 후보는 `0개`이고 수익화 판정은 `no_profitable_candidate`다. 시스템은 개발 목표에는 대체로 맞지만 실전 수익화 준비는 아직 통과하지 못했다.

## 운용과 수집

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 최신 KIS 거래일: `2026-09-04`
- raw market/orderbook symbol-minute: `3,811/4,049`; feature closed `3,800`행, coverage `97.44%`
- serving decision ledger: `3,800`행, complete lineage `3,800/3,800`, ratio `100%`
- WebSocket: reconnect `28`, storm `0`; 재구독 완료 `28/28`, 복구 후 첫 프레임 `28/28`이 같은 process에서 확인됐다.
- 전 종목 공통 market 공백은 예상 종가 동시호가 `15:20~15:29 KST`뿐이다. `086520` market에 `12:08`, `14:12` 단일 분 공백이 있었고 orderbook 공백은 없다.
- 최신 data-quality 판정은 `ATTENTION/주의`다. 수집 coverage와 lineage는 정상이며 반복 reconnect만 연결 주의로 분리한다.
- 운영 SQLite는 약 `27.203 GiB`, journal mode `wal`이다. 대형 DB 전체 집계와 snapshot은 장외·D드라이브 기준을 유지한다.

## 학습과 수익성

- 2026-09-04 장후 ML: `status=ok`, `quick-live-train`, 18:14 KST 완료
- 2026-09-04 label refresh: `status=ok`, 19:13 KST 완료
- top challenger `linear_score_builtin`: 3분류 정확도 `19.61%`, buy/trade hit `18.35%`, 누적 진단 순수익 `-400.65%`, 거래 `1,477건`이다. active `baseline-h15-v1` 유지, 승격은 없다.
- buy-avoid: `2026-07-13 09:15~2026-09-04 15:00`, joined `56,601`행. threshold `0.40`의 overlapping-row 진단 delta는 양수지만 절대 portfolio 수익은 계속 음수여서 `rejected_no_absolute_portfolio_profit`이다.
- buy-rescue: decision ledger `143,105`행 중 eligible `72,730`행이며 `diagnostic_only_no_order_policy_change`다. Cybos proxy도 `buy_avoid_candidate_only`로 buy-rescue 주문 반영을 권하지 않는다.
- hold-rescue: eligible `175 lot`; threshold `0.40` 적용 `38 lot`, delta `-26,887원`으로 `diagnostic_only_no_hold_rescue_candidate`다.
- meta-policy: primary candidate 없음. rescue/avoid는 관측 전용으로 유지한다.
- 현행 비용 모델은 `krx-common-stock-2026-v1`, 왕복 `0.29%`, 2배 민감도 `0.58%`다.
- E7 buy-rescue 미래 검증은 threshold `0.55`, `2026-08-31 09:15 KST` 이후 구간, 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 비중복 2구간을 사전등록했다. 주문 정책에는 반영하지 않는다.
- 기존 `portfolio-replay-v1-entry-mark`는 보존했다. 공식 `portfolio-replay-v2-minute-mtm`과 manifest `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`는 일치한다.
- E7은 2026-09-04 기준 미래 거래일 `5일`, 실행 가능 모집단 episode `3,119`, official policy episode/symbol `0/0`, mark observation `0`, missing/stale/invalid mark 모두 `0`이다. evaluator/manifest는 일치하고 evidence health는 `valid_collecting`, 공식 상태는 `collecting_future_sample`이다. threshold는 episode 첫 판단의 entry score에 적용되므로 이후 분의 일시적 `0.55` 상향을 새 episode로 재해석하지 않는다.

## Phase 0과 readiness

- 현재 paper account epoch는 `paper-2026-09-03`이다. 활성일 `2026-09-03`, 만료일 `2026-12-03`, 갱신 경고 시작 `2026-11-03`, 긴급 경고 시작 `2026-11-26`으로 관리한다.
- 새 APP 자격정보의 auth-only token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` read-only orderability가 모두 통과했다. 실제 주문·취소는 실행하지 않았다.
- 새 계좌에서 2026-09-03 자연 KIS cash-order submission 36건이 성공했다. 이전 `broker_account_not_orderable`은 만료·무효 상태였던 이전 계좌가 주원인으로 사실상 확인됐고 endpoint entitlement case는 같은 오류가 새 계좌에서 재발할 때까지 닫는다.
- 같은 날 invalid tick 4건과 network timeout 1건을 분리했다. invalid tick은 KRX 일반주권 500원 단위 위반이며 `broker_invalid_request/invalid_price_tick`으로 교정한다.
- 2026-09-06 계좌 소유자 승인으로 현재 KIS paper snapshot 기준 marker-only clean baseline을 생성했다. baseline은 current epoch와 `compatible`이고 immutable backup을 보존했다. `SyncInitialCash`, 주문·취소, order-fill 재조회는 실행하지 않았다.
- 직후 reconciliation은 `aligned_waiting_first_submission`, mismatch `0`, effective cash gap `0원`, total asset gap `0원`이다. current view는 `005930` 1주·`035420` 2주, 유효현금 `9,319,451원`, 총자산 `10,001,951원`이며 raw cash gap `-1,850원`은 KIS 현금 표시 정의 차이로 분리한다.
- 2026-09-05 장외 order-fill sync는 paper 1.0초 페이지 간격으로 3페이지/38행을 완결했다. submission 38/38 exact-linked, open 0/final 38/pending 0이고 `068270` 매도 체결 1건·2주를 적용했다. 이 one-off는 account snapshot/reconciliation을 다시 호출하지 않았으며 자동 정렬·삭제·reset도 하지 않았다.
- 과거 epoch는 유효 `10/10`, matched `0`, mismatch `10`, 종목 `035420/086520/105560/247540`로 미통과 이력을 보존한다.
- 현재 epoch는 `no_history`, 유효일 `0/10`, remaining `10`이다. 휴장일인 2026-09-06 baseline 생성일은 분모에 넣지 않고 기준선 뒤 첫 정상 거래일부터 누적한다.
- full-period sanitized account activity는 22페이지/329행, pagination 완결이며 320행 local-linked와 9행 broker-only로 이전 divergence 원인을 확정했다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: bounded live read-only 관측 1회 통과 이력은 있으나 latest readiness가 2026-07-11 생성물이라 현재 승격 증거로는 stale하다.
- Phase 2/3: 미시작. 2026-09-04 실제 WebSocket 재구독·첫 프레임 복구 증거는 확보했지만 Phase 1b readiness artifact는 stale/synthetic이므로 fresh real-evidence linkage, 수익 후보, Phase 0 통과 전에는 진입하지 않는다.

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

## 현재 blocker와 다음 순서

1. 현재 계좌 clean baseline은 완료됐다. 같은 baseline을 반복 생성하거나 과거 epoch 증거를 현재 분모와 섞지 않는다.
2. 다음 정상 거래일부터 post-close·broker snapshot 성공·실제 mirrored submission 존재 조건을 만족한 유효일 10개를 모두 matched로 확인한다.
3. E7 immutable daily artifact는 기준을 바꾸지 않고 최소 10거래일·100 episode·5종목까지 축적한다.
4. 다음 거래일에는 tick rejection 재발 여부와 WebSocket subscription/first-frame 복구 증적을 관찰한다.
5. B2 cumulative→delta partial-fill economics와 B3 SQLite accounting atomicity는 완료했다. 다음 구현은 별도 범위 확인 뒤 fresh Phase 1b evidence linkage와 Phase 2 live-canary 안전 항목 순서로 진행한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 연구 사전등록: `docs/Model-Research-PreRegistration.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
