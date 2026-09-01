# 현재 상태

## 기준 시각

- 확인 시각: 2026-09-01 23:30 KST
- 장 상태: post-close
- live runtime: 2026-09-01 15:30 KST 정상 종료 후 정지
- runtime watchdog: 종료 상태를 장외에 안전 복구, heartbeat fresh
- dashboard: watchdog가 안전 복구, server/API 정상, `http://127.0.0.1:8765`
- Windows startup launcher: 설치 및 정상

## 프로젝트 목표 정합성

- 현재 운영 목표는 실전 자동매매가 아니라 `paper` 기준으로 `수집 -> 특징 -> 예측 -> 판단 -> 모의주문/체결 -> KIS 모의계좌 정합 -> 비용 후 포트폴리오 검증`을 증거로 연결하는 것이다.
- 2026-09-01 decision ledger와 model artifact lineage는 완전하며, active model과 주문 정책을 자동 변경하지 않는 fail-closed 경계도 유지된다.
- 현재 통과한 수익 후보는 `0개`이고 수익화 판정은 `no_profitable_candidate`다. 시스템은 개발 목표에는 대체로 맞지만 실전 수익화 준비는 아직 통과하지 못했다.

## 운용과 수집

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 최신 KIS 거래일: `2026-09-01`
- raw market/orderbook symbol-minute: `3,818/4,057`, coverage `97.65%/103.76%`; feature closed `3,802`행, coverage `97.49%`
- serving decision ledger: `3,802`행, complete lineage `3,802/3,802`, ratio `100%`
- broker order rejected: `811`건; failure lineage `811/811` complete
- WebSocket: reconnect `29`, storm `0`
- `15:20~15:29 KST` market 공통 공백은 설정된 `forced_flat_time=15:20` 뒤 종가 동시호가 구간으로 분리한다. 이 구간만으로 수집 실패로 판정하지 않으며 예상 밖 공통 공백은 없다.
- 최신 data-quality 판정은 `watch`다. coverage와 lineage는 정상 범위지만 reconnect 29회는 연결 안정성 주의로 남긴다.
- 운영 SQLite는 약 `27.203 GiB`, journal mode `wal`이다. 대형 DB 전체 집계와 snapshot은 장외·D드라이브 기준을 유지한다.

## 학습과 수익성

- 2026-09-01 장후 ML: `status=ok`, `quick-live-train`, 18:11 KST 완료
- 2026-09-01 label refresh: `status=ok`, 19:11 KST 완료
- top challenger `linear-score-h15-v1`: 3분류 정확도 `19.88%`, buy/trade hit `20.59%`, 누적 진단 순수익 `-355.53%`, 거래 `1,467건`이다. active `baseline-h15-v1` 유지, 승격은 없다.
- buy-avoid: `2026-07-13 09:15~2026-09-01 15:00`, joined `52,336`행. threshold `0.40`의 overlapping-row 진단 delta는 `+2,815.91%p`지만 portfolio는 baseline `-52.24%`, policy `-51.14%`로 절대 손익이 음수라 기각한다.
- buy-rescue: decision ledger `131,784`행 중 eligible `66,678`행이다. 두 모델 동시 상승 threshold `0.40`은 `62건`, net `-30.42%p`로 후보가 아니다.
- hold-rescue: eligible `161 lot`; threshold `0.55`는 적용 `0 lot`, delta `0원`, threshold `0.40`은 적용 `37 lot`, delta `-26,387원`으로 후보가 아니다.
- meta-policy: `blocked_evidence`, primary candidate 없음
- 현행 비용 모델은 `krx-common-stock-2026-v1`, 왕복 `0.29%`, 2배 민감도 `0.58%`다.
- E7 buy-rescue 미래 검증은 threshold `0.55`, `2026-08-31 09:15 KST` 이후 구간, 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 비중복 2구간을 사전등록했다. 주문 정책에는 반영하지 않는다.
- 기존 `portfolio-replay-v1-entry-mark` 코드는 그대로 보존했다. 신규 `portfolio-replay-v2-minute-mtm`은 직전 completed minute close로 보유 포지션을 매분 평가하고, missing/stale mark와 v1/v2·manifest·비용·구간 혼합을 fail-closed 한다. E7 manifest hash는 `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`다.
- E7은 2026-09-01 기준 미래 거래일 `2일`, eligible population `1,300`, official policy episode/symbol `0/0`, mark observation `0`, missing/stale/invalid mark 모두 `0`이다. evidence health는 `valid_collecting`, 공식 상태는 `collecting_future_sample`이며 수익성 실패가 아니라 최소 표본 축적 단계다.

## Phase 0과 readiness

- 2026-08-15 계좌 소유자 승인 clean baseline marker 뒤 현재 KIS/local 보유 3종목과 현금은 mismatch `0`이다. 최신 total asset gap은 `+39,500원`이며 현재 mark/evaluation 차이로 별도 관찰한다.
- 현재 epoch는 `0/10`, matched `0`, mismatch `0`, remaining `10`이다. baseline 뒤 실제 mirrored submission이 있는 유효 거래일만 분모를 늘리며 무거래일을 강제로 채우지 않는다.
- 2026-08-31의 `broker_account_not_orderable=871`은 실제 KIS cash-order network call 11건과 circuit 차단 860건, 2026-09-01의 811건은 실제 call 12건과 circuit 차단 799건이다. 두 날 모두 failure lineage 100%, 성공 submission 0이며 current Phase 0 epoch는 계속 `0/10`이다.
- 국내주식 paper 주문 계약은 공식 `order_cash` 예제와 일치한다. 계좌 소유자는 paper 자격정보 연결과 2027-04-10 만료를 확인했고, `VTTC8908R` read-only orderability는 `ORD_DVSN=01/00` 모두 `orderability_ok/positive`였다. `ORDER_TYPE_DIFFERENCE_NOT_CAUSAL`이며 KIS paper cash-order endpoint별 entitlement/policy 문제를 강하게 의심하되 서버 결함으로 단정하지 않는다.
- 동일 계좌 hard rejection circuit은 정상 동작했고 local paper 판단과 E7 원장은 계속 기록됐다. 성공 submission 전에는 Phase 0 준비 완료로 판정하지 않는다.
- 과거 epoch는 유효 `10/10`, matched `0`, mismatch `10`, 종목 `035420/086520/105560/247540`로 미통과 이력을 보존한다.
- full-period sanitized account activity는 22페이지/329행, pagination 완결이며 320행 local-linked와 9행 broker-only로 이전 divergence 원인을 확정했다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: bounded live read-only 관측 1회 통과 이력은 있으나 latest readiness가 2026-07-11 생성물이라 현재 승격 증거로는 stale하다.
- Phase 2/3: 미시작. 실제 WebSocket recovery evidence와 fresh readiness, 수익 후보, Phase 0 통과 전에는 진입하지 않는다.

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

## 현재 blocker와 다음 순서

1. `docs/evidence/KIS-Paper-Orderability-Support-Evidence-2026-09-01.md`의 tracked sanitized 증적으로 KIS 지원에 cash-order entitlement/service 상태를 문의한다. KIS 회신 전 추가 orderability probe와 강제 cash order를 반복하지 않는다.
2. 다음 안전한 거래일 post-close부터 E7 immutable daily artifact를 축적하고 최소 10거래일·100 episode·5종목을 기다린다.
3. 성공 submission 확인 뒤 Phase 0 clean baseline 이후 실제 유효 거래일 `10/10`을 모두 matched로 채운다.
4. 성공 submission/fill 뒤 B2 broker-paper cumulative→delta partial-fill economics를 진행한다.
5. B2 뒤 B3 SQLite accounting transaction atomicity를 별도 storage 작업으로 진행한다.
6. reconnect/storm/coverage/lineage와 fresh Phase 1b/real WebSocket recovery 증거를 계속 관찰한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 연구 사전등록: `docs/Model-Research-PreRegistration.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
