# 현재 상태

## 기준 시각

- 확인 시각: 2026-08-29 10:43 KST
- 장 상태: weekend
- live runtime: 휴장 정상 정지
- runtime watchdog: PC 재부팅 뒤 안전 복구, heartbeat fresh
- dashboard: PC 재부팅 뒤 안전 복구, 10:40 KST 실제 snapshot 재생성, `http://127.0.0.1:8765`
- Windows startup launcher: 설치 및 정상

## 프로젝트 목표 정합성

- 현재 운영 목표는 실전 자동매매가 아니라 `paper` 기준으로 `수집 -> 특징 -> 예측 -> 판단 -> 모의주문/체결 -> KIS 모의계좌 정합 -> 비용 후 포트폴리오 검증`을 증거로 연결하는 것이다.
- 2026-08-28 decision ledger와 model artifact lineage는 완전하며, active model과 주문 정책을 자동 변경하지 않는 fail-closed 경계도 유지된다.
- 현재 통과한 수익 후보는 `0개`이고 수익화 판정은 `no_profitable_candidate`다. 시스템은 개발 목표에는 대체로 맞지만 실전 수익화 준비는 아직 통과하지 못했다.

## 운용과 수집

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 최신 KIS 거래일: `2026-08-28`
- raw market/orderbook symbol-minute: `3,816/4,062`; raw market 전체 session coverage `97.5959%`, feature closed coverage `97.4872%`
- serving decision ledger: `3,802`행, complete lineage `3,802/3,802`, ratio `100%`
- 판단 단계: allocator 258, order rejected 832, position/pending 483, signal blocked 2,229건
- WebSocket: reconnect `28`, storm `0`, 사유는 모두 `no close frame`
- `15:20~15:29 KST` market 공통 공백은 설정된 `forced_flat_time=15:20` 뒤 종가 동시호가 구간으로 분리한다. 이 구간만으로 수집 실패로 판정하지 않으며 예상 밖 공통 공백은 없다.
- 최신 data-quality 판정은 `watch`다. coverage와 lineage는 정상 범위지만 reconnect 28회는 연결 안정성 주의로 남긴다.
- 운영 SQLite는 약 `27.203 GiB`, journal mode `wal`이다. 대형 DB 전체 집계와 snapshot은 장외·D드라이브 기준을 유지한다.

## 학습과 수익성

- 2026-08-28 장후 ML: `status=ok`, `quick-live-train`, 17:21 KST 완료
- 2026-08-28 label refresh: `status=ok`, 17:44 KST 완료
- top challenger `lightgbm-h15-v1`: 3분류 정확도 `0.467882`, buy/trade hit `0`, 누적 순수익 `-0.757017%`, 거래 `1건`. 표본 부족과 비용 후 음수로 승격 불가다.
- rank 2 linear-score는 거래 1,455건이지만 누적 순수익 `-366.306839%`라 수익 후보가 아니다.
- buy-avoid: `2026-07-13 09:15~2026-08-28 15:00`, joined 49,067행. threshold `0.40` portfolio는 baseline `-50.893232%`에서 policy `-49.442452%`로 `+1.450780%p` 완화했지만 절대 손익이 음수라 기각한다.
- buy-rescue: LightGBM threshold `0.55`의 탐색 관측은 76건/9거래일, 누적 신호행 순손익 `+13.073707%p`, 평균 `+0.172022%p`, precision `0.578947`이다. 겹치는 신호행 합이며 포트폴리오·random-control 검증이 없어 `research_lead`일 뿐 수익 후보가 아니다.
- hold-rescue: canonical `15분/최대손실 2.0%/15:20 강제청산` 기준에서 실제 적용된 최선도 LightGBM 5 lot `-7,696원`, linear-score 15 lot `-7,999원`으로 후보가 아니다.
- meta-policy: `blocked_evidence`, primary candidate 없음
- 현행 비용 모델은 `krx-common-stock-2026-v1`, 왕복 `0.29%`, 2배 민감도 `0.58%`다.
- E7 buy-rescue 미래 검증은 threshold `0.55`, `2026-08-31 09:15 KST` 이후 구간, 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 비중복 2구간을 사전등록했다. 주문 정책에는 반영하지 않는다.

## Phase 0과 readiness

- 2026-08-15 계좌 소유자 승인 clean baseline marker 뒤 현재 KIS/local 보유 3종목, 현금, 총자산은 mismatch `0`이다.
- 현재 epoch는 `0/10`, matched `0`, mismatch `0`, remaining `10`이다. baseline 뒤 실제 mirrored submission이 있는 유효 거래일만 분모를 늘리며 무거래일을 강제로 채우지 않는다.
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

## 현재 blocker와 다음 순서

1. E7 미래 구간에서 최소 10거래일·100 episode를 확보하고 portfolio/random-control/2배 비용/비중복 2구간을 검증한다.
2. Phase 0 clean baseline 뒤 실제 유효 거래일 `10/10`을 모두 matched로 채운다.
3. 다음 거래일 reconnect 수와 storm 0 유지, coverage 95% 이상, lineage 100%를 함께 확인한다.
4. Phase 1b fresh read-only readiness와 실제 WebSocket recovery 증거를 별도로 갱신한다.
5. E7이 3회 고정 평가에서 개선되지 않으면 threshold 재탐색 없이 h60 또는 entry/exit 분리 가설로 이동한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 연구 사전등록: `docs/Model-Research-PreRegistration.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
