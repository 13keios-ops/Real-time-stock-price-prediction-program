# 작업 기록

## 역할

이 파일은 현재 상태, 활성 체크리스트, 최신 검증만 유지한다.
긴 과거 기록은 `docs/logbook_archive/`와 `docs/archive/`에 보관한다.

## 현재 스냅샷

- 기준 시각: 2026-09-01 23:30 KST
- 장 상태: post-close
- live runtime: 2026-09-01 15:30 KST 정상 종료 후 정지
- watchdog/dashboard: 장외 안전 복구 후 정상; startup launcher 정상
- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 2026-09-01 post-close ML은 `status=ok`, 18:11 KST `quick-live-train`; label refresh는 `status=ok`, 19:11 KST 완료했고 모델 승격은 없다.
- 현재 통과한 수익 후보: `0개`
- 수익화 판정: `no_profitable_candidate`
- Phase 0 current epoch: 2026-08-15 clean baseline 뒤 `0/10`, matched 0일, mismatch 0일, remaining 10일. 실제 mirrored submission이 있는 post-close 유효일만 센다.
- 최신 reconciliation은 `waiting_first_submission`; 보유수량과 현금은 일치하고 total asset gap은 `+39,500원`, 성공 submission은 0건이다.
- 2026-08-31 broker account rejection 871건은 network call 11건과 circuit 차단 860건, 2026-09-01 811건은 network call 12건과 circuit 차단 799건이다. 두 날 모두 성공 submission 0건이며 Phase 0 준비 완료가 아니다.
- Phase 0 prior epoch: `10/10`, matched 0일, mismatch 10일과 `035420/086520/105560/247540` 불일치 이력을 보존한다.
- Phase 1b: bounded read-only 관측 1회 통과 이력은 있으나 latest readiness는 stale. 반복 자동화 preflight는 네트워크·주문 호출 0회다.
- runtime 원장: 2026-09-01 decision ledger `3,802/3,802`, complete lineage 100%, market/orderbook `3,818/4,057` symbol-minute와 coverage `97.65%/103.76%`, feature `3,802`행/`97.49%`다.
- WebSocket: reconnect 29, storm 0. 수집 정상과 연결 주의를 분리한다.
- KIS paper 자격정보-모의계좌 연결과 2027-04-10 만료는 확인됐다. `VTTC8908R` read-only orderability는 `ORD_DVSN=01/00` 모두 `orderability_ok/positive`다. 주문구분 차이는 원인이 아니며 KIS paper cash-order endpoint별 entitlement/policy 문제를 지원 문의 대상으로 남긴다.
- 수익성: top challenger linear-score는 3분류 정확도 `19.88%`, buy hit `20.59%`, 누적 진단 순수익 `-355.53%`, 거래 `1,467건`이다. buy-avoid threshold 0.40 portfolio `-51.14%`, buy-rescue 두 모델 동시 상승 62건 `-30.42%p`, hold-rescue threshold 0.40 `-26,387원`으로 모두 후보가 아니다.
- 비용 구조: 현행 왕복 0.29%, 2배 민감도 0.58%. active model/gate/threshold/주문 정책은 동결한다.
- E7 evaluator: 기존 v1은 보존하고 `portfolio-replay-v2-minute-mtm`과 manifest `1d61b288...e0dd3fa`를 검증했다.
- E7은 2026-09-01 기준 future trading days `2`, eligible population `1,300`, official policy episode/symbol `0/0`, invalid mark `0`, evidence health `valid_collecting`, 공식 상태 `collecting_future_sample`이다. 수익성 실패가 아니라 표본 축적 단계다.

상세 현재값은 `docs/STATUS.md`, Phase 상태는 `docs/Production-Transition-Progress.md`를 기준으로 한다.

## 활성 체크리스트

- [x] 2026-08-28 raw→feature→decision ledger와 complete lineage 100% 확인
- [x] 종가 동시호가 예상 gap과 unexpected common gap 분리
- [x] reconnect 28/storm 0을 수집 정상 범위와 연결 주의로 분리
- [x] Phase 0 clean baseline 이전/이후 epoch 분리
- [x] broker 실패 taxonomy, account hard-rejection circuit, stable failure lineage 추가
- [x] KIS paper 자격정보 연결/만료 확인과 read-only orderability probe 구현
- [x] 명시 승인된 `ORD_DVSN=01/00` orderability 결과 해석
- [x] KIS support용 runtime evidence packet과 Git-tracked sanitized snapshot 작성
- [ ] KIS support의 paper cash-order entitlement/service 답변 확인
- [ ] 다음 정상 거래 성공 submission 확인
- [ ] Phase 0 current epoch 유효 거래일 10개 모두 matched 확인
- [x] hold-rescue canonical 15분/2.0%/15:20 기준 통일과 no-op threshold 선택 차단
- [x] buy-avoid/hold-rescue 절대 손익 음수 판정 유지
- [x] E7 LightGBM buy-rescue threshold 0.55 미래 검증 사전등록
- [x] replay v1 보존, minute MTM v2, immutable E7 manifest와 혼합 차단 검증
- [x] E7 daily read-only artifact writer와 sample/drift/mark/idempotency 검증
- [ ] 2026-08-31 이후 E7 최소 10거래일/100 episode/5종목 확보
- [ ] E7 portfolio replay, random control 1,000회, 2배 비용, 비중복 두 구간 판정
- [ ] fresh Phase 1b readiness와 real WebSocket recovery evidence 확보

현재 상세 작업 범위는 `docs/SPRINT_CURRENT.md`를 따른다.

## 최신 검증

- A1 targeted unittest: `49 tests OK`
- A2/B1 replay targeted unittest: `21 tests OK`
- full unittest: `586 tests OK` in 32.523s
- repository structure audit: errors 0/warnings 2. 기존 대형 모듈 `app/services/dashboard.py`, `app/services/research.py`
- 실제 KIS data-quality 재생성: latest trade date 2026-08-28, assessment `watch`
- raw market session coverage: `97.5959%`; feature closed coverage: `97.4872%`
- decision ledger: 3,802행, complete lineage 3,802행, ratio 1.0
- WebSocket: reconnect 28, storm 0, reason `no close frame` 28회
- Phase 0 history 재생성: current epoch 0/10, matched 0, mismatch 0; prior epoch 10/10, matched 0, mismatch 10
- model overlay/meta-policy 재생성: buy-rescue research lead, hold-rescue actual-best 음수, meta-policy `blocked_evidence`
- 실제 dashboard 빌드: 2026-08-29 10:40 KST; current epoch와 수익 증거 차단 문구 확인
- dashboard server/API, runtime watchdog, startup launcher 정상; live runtime은 휴장 정지
- 작업 시작 시 git: `main`과 `origin/main` 동기화

## [2026-09-01] KIS paper cash-order 지원 증적 작성

- 계좌 소유자 승인으로 `ORD_DVSN=01`과 실제 주문과 같은 `ORD_DVSN=00` 매수가능조회를 각각 read-only 1회 실행했다. 두 결과 모두 `orderability_ok`, `rt_cd=0`, value presence `positive`이고 실제 주문·취소는 0회다.
- 저장 DB를 read-only 재검산해 2026-08-31 account rejection 871건이 network 11/circuit 860, 2026-09-01 811건이 network 12/circuit 799임을 확인했다. 두 날짜 failure lineage는 모두 100%이고 성공 submission은 0건이다.
- 현행 `order-cash` endpoint, paper buy/sell TR ID, body field, 문자열 수량/가격, KRX, hashkey/header shape를 한국투자증권 공식 현재 예제와 다시 비교해 contract drift 근거를 찾지 못했다.
- 결론은 `ORDER_TYPE_DIFFERENCE_NOT_CAUSAL`이며 `KIS paper cash-order endpoint-specific entitlement/policy issue strongly suspected`로 제한한다. KIS 서버 결함으로 단정하지 않는다.
- `runtime-data/reports/broker-paper/kis-support-paper-orderability-evidence.md`에 운영 원본을 유지하고 `docs/evidence/KIS-Paper-Orderability-Support-Evidence-2026-09-01.md`에 credential-free 영구 snapshot을 만들었다. KIS 회신 전 추가 orderability execute, 다른 symbol/order type probe, 강제 주문·취소, circuit 완화는 중지한다.
- application code, 전략, E7, Phase 0 baseline, `app/risk/`, `config/`, `VERSION`은 변경하지 않았다. 이번 packet 작성 중 KIS API, 주문, 취소 호출은 0회다.

## [2026-09-01] 장전 자동화 시간 조정

- Codex heartbeat 한 개 제한을 유지하면서 장전 실행만 KST 07:25로 앞당기고 장후 실행은 KST 20:25로 유지했다.
- daily ops Skill의 pre-open 허용 구간만 07:20~07:40으로 맞췄으며 post-close 20:20~20:40과 장후 절차는 변경하지 않았다.
- application code, 전략, 설정, DB, runtime-data, VERSION은 변경하지 않았다.

## [2026-09-01] E7 daily evidence와 KIS orderability 진단 경로

- 2026-08-31 첫 E7 미래 거래일은 market/orderbook/feature coverage와 decision lineage가 정상 범위였지만 기존 daily ops에 공식 artifact writer가 없어 E7 진행 필드가 `not available yet`이었다.
- `app/services/e7_daily_evidence.py`와 post-close entrypoint를 추가했다. future start 이후 자료만 SQLite read-only로 읽고 current trading day immutable report를 1회 생성하며, 같은 날 재실행은 기존 파일을 재사용한다.
- evaluator/manifest 고정 상수, mark validity, lineage, 최소 10거래일/100 episode/5종목을 evidence health로 기록한다. 표본 부족은 `collecting_future_sample`이고 수익성 실패가 아니다. 2026-08-31 artifact는 소급 생성하지 않는다.
- KIS 공식 `inquire-psbl-order` paper TR `VTTC8908R`을 쓰는 read-only client/probe를 추가했다. dry-run은 network 0회, 명시 승인 실행은 read-only 1회/order·cancel 0회다.
- 계좌 식별자·자격정보·exact 현금은 기록하지 않고 positive/zero/unavailable 및 sanitized `rt_cd/msg_cd/msg1`과 taxonomy만 남긴다.
- daily ops skill을 common/pre-open/post-close/Phase0/E7/orderability/ML/recovery/protected/classification/report 구조로 정리했다. 종료된 날짜 one-off는 자동 재실행 금지와 canonical history 링크만 남겼다.
- threshold 0.55, active model, feature/signal/gate/allocator, portfolio/cost/manifest, Phase 0 baseline, live 설정, `app/risk/`, `VERSION`은 변경하지 않았다.
- targeted 56건과 전체 605건, Python compile, Bash parse, repository audit 오류 0건/warning 2건, diff check를 통과했다.
- 02:33 KST overnight에 종료된 watchdog를 기존 helper로 안전 복구했고 dashboard server/API도 정상화했다. live runtime은 시작하지 않았다.

## [2026-08-30] E7 portfolio replay v2와 evaluator manifest

- 기존 `app/services/portfolio_replay.py`는 변경 없이 보존해 과거 `portfolio-replay-v1-entry-mark` 결과의 의미를 유지했다.
- 신규 v2는 `ReplayBar.bar_time`을 minute start로 해석하고 시각 T에 T-1분 completed close만 사용한다. T분 close/high/low는 아직 미래 정보이므로 쓰지 않으며 entry/exit는 기존대로 T분 open이다.
- 보유 중 매분 MTM equity를 관측해 peak/MDD, 다음 position sizing, gross exposure, concentration에 같은 값을 사용한다. exact mark 누락, stale, invalid close는 fallback 없이 evaluation 전체를 invalid 처리한다.
- E7 frozen manifest는 LightGBM h15 v1, threshold 0.55, 2026-08-31 09:15 KST, 15:20 forced-flat, 2,500만원, 8%/5포지션, canonical/2배 비용, 층화 random 1,000회 seed 202608310915, 최소 표본과 두 비중복 구간을 hash `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`로 잠갔다.
- baseline/policy/actual/random x normal/double cost x 두 구간의 16개 결과가 동일 identity가 아니면 통합 E7 판정을 만들지 않는다. random control은 immutable mark index와 timeline을 1,000회 공유하고 actual effective-veto lineage와 같은 count만 허용한다.
- synthetic 1,000원 사례에서 100 진입→80 하락→110 청산은 v1 MDD 0%, v2 중간 equity 800원/MDD 20%, 두 버전 최종 equity 1,100원으로 손검산과 일치했다. 하락 MTM에서 두 번째 주문 qty 23, 상승 MTM에서 qty 26도 기대값과 일치했다.
- 관련 targeted 21건, 전체 586건, repository structure audit errors 0/warnings 2, Python compile, `git diff --check`를 통과했다. E7 전략, active model, threshold, signal/gate, allocator, Phase 0, live 코드는 변경하지 않았다.

## [2026-08-30] Phase 0 broker account rejection 원인 규명과 호출 보호

- 2026-08-28 risk/decision/order 원장을 sanitized 상태로 재분석했다. `order_rejected=832` 중 830건은 `모의투자 주문이 불가한 계좌`, 2건은 `EGW00201`이며, 830건은 gate/allocator 차단이 아니라 KIS `order-cash` 실제 호출 뒤 응답이다.
- 대표 표본의 symbol/side/qty/order type/limit, paper profile shape, TR ID, 비밀값 제외 body를 비교했다. 저장소의 `VTTC0012U/VTTC0011U`와 요청 필드는 한국투자증권 공식 국내주식 paper 주문 예제와 일치해 repository 구현 오류 근거는 발견되지 않았다.
- root cause는 KIS가 현재 paper 계좌를 국내주식 주문 불가로 판정한 계좌/환경 상태까지 확정했다. paper app 자격정보-모의계좌 연결 또는 계좌 활성/주문 가능 상태 중 어느 쪽인지는 비밀값 없이 코드만으로 확정할 수 없다.
- 정확한 계좌 hard rejection 1회 뒤 30분 동안 broker paper network 제출만 fail-closed하는 process-local circuit을 추가했다. rate limit, auth, invalid request, 일반 order rejection, network, unknown 오류는 별도로 분류하고 account circuit을 열지 않는다.
- `decision_id/prediction_id/signal_id/target_id/local_order_id/attempt_id`와 sanitized request shape를 failure risk event와 성공 submission에 연결했다. local paper/E7 수집은 계속되며 성공 응답이 없을 때 broker submission 행을 만들지 않아 Phase 0 no-submission day 의미는 유지된다.
- E7 threshold 0.55, active model, signal/gate, allocator, trading mode, live flag, `app/risk/`, Phase 0 baseline은 변경하지 않았다.
- broker/streaming/Phase 0 targeted unittest 49건과 전체 unittest 569건, Python 문법, `git diff --check`, repository structure audit errors=0을 통과했다.

## [2026-08-29] FULL CHECK 수집·판단·수익화 근거 교정

- 프로젝트 목표를 raw 수집부터 비용 후 portfolio까지의 증거 체인으로 재검수했다. 2026-08-28 수집 coverage와 lineage는 정상 범위지만 검증된 절대 양수 수익 후보는 0개다.
- data-quality가 `15:20~15:29 KST` 종가 동시호가 예상 market gap을 실패로 세던 문제를 고쳤다. orderbook gap과 forced-flat 전 unexpected common gap은 계속 fail-closed이며 reconnect 28/storm 0은 별도 `watch`다.
- model overlay의 hold-rescue 기본값을 standalone/config와 같은 15분, 최대손실 2.0%, 15:20 강제청산으로 통일했다. 적용 lot 0인 threshold가 최선으로 선택되던 문제도 차단했다.
- Phase 0 history가 clean baseline 이전 불일치 10일과 이후 관측을 섞던 문제를 epoch로 분리했다. dashboard는 current epoch가 통과하기 전 로컬 누적손익을 수익 증거로 사용하지 않는다.
- buy-avoid는 baseline 대비 손실을 1.450780%p 완화했지만 policy return -49.442452%라 기각한다. hold-rescue도 음수다.
- LightGBM buy-rescue threshold 0.55는 76행/9거래일에서 신호행 합 +13.073707%p, 평균 +0.172022%p, precision 0.578947이지만 실제 계좌 수익률이 아니다. 2026-08-31 이후 최소 10거래일/100 episode/5종목, portfolio replay, random control 1,000회, 2배 비용, 비중복 두 구간을 E7으로 사전등록했다.
- 실전 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, active model/gate/threshold, NAS 백업은 변경하지 않았다.

## [2026-08-15] E1/E5 승인 장시간 상한 완결 실행

- KST 01:50 휴장·live runtime 정지 상태에서 계좌 소유자의 새 명시 승인으로 `./scripts/run_preregistered_e1_e5_round.sh --snapshot-timeout-seconds 1800 --execute`를 정확히 1회 실행했다.
- 26GB SQLite snapshot은 830.5초 안에 복사와 `quick_check=ok` 검증을 마쳤고, 고정 구간 `2026-07-04~2026-07-18`의 `latest-completed-round.json`은 `status=ok`다. 네트워크·주문·학습 호출 및 정책/model/gate 변경은 모두 0회다.
- E1은 14,004행/9거래일, 후보 재현 `0/3`, 전체 probability_down IC `-0.019927`, t `-0.730524`로 `signal_quality_insufficient`다. `105560` p_down/p_up 상관 `0.897613`은 독립 방향 신호가 아니라 공통 확률 움직임 가능성을 강화한다.
- E5는 유효 temporal lineage 6,195행/4거래일에서 threshold 0.40의 random 대비 excess `-96.7921%`, z `-3.4051`로 second interval 재현에 실패했다.
- 기존 E1/E5를 threshold·EV·종목별 정책으로 구제하지 않는다. 다음 연구는 orderbook×regime/시간대/변동성/source/horizon을 새로 사전등록하고 current cost, 동일 portfolio replay, same-count random, 비중복 구간으로만 검증한다.
- 성공 경로 뒤 남은 partial SQLite `-wal/-shm` sidecar를 정리하도록 snapshot helper를 보강하고 성공 회귀 테스트를 추가했다.

## [2026-08-15] E1/E5 180초 승인 실행 안전 종료

- KST 01:13 휴장·live runtime 정지와 중복 프로세스 부재를 확인한 뒤 계좌 소유자의 새 명시 승인으로 `./scripts/run_preregistered_e1_e5_round.sh --execute`를 정확히 1회 실행했다.
- gate와 2026-08-14 label refresh는 통과했지만 26GB SQLite를 repo-local `runtime-data/research-snapshots/`에 일관 복사하고 검증하는 단계가 180초를 초과해 `snapshot_failed/research_snapshot_timeout`으로 종료됐다.
- 네트워크·주문 호출은 각각 0회다. final snapshot/manifest와 `latest-completed-round.json`은 생성되지 않았고 partial 및 실행 프로세스도 남지 않았다.
- 같은 승인 범위에서 재실행하지 않았다. 다음 실행 전에는 26GB 전체 snapshot에 맞는 bounded 장시간 상한 또는 고정 기간 전용 read-only snapshot 방식을 별도로 검증해야 한다.

## [2026-08-15] Phase 0 승인 clean baseline 생성

- KST 00:20 휴장·live runtime 정지를 확인한 뒤 계좌 소유자 승인 범위로 `python3 -m app --align-local-paper-to-broker`를 정확히 1회 실행했다. KIS paper account snapshot 조회만 사용했고 실전/모의 주문·취소와 `SyncInitialCash`는 실행하지 않았다.
- 기준선은 KIS 보유 `086520 5주`, `247540 10주`, `373220 1주`와 현금/총자산을 반영했다. 오프라인 reconciliation 결과 mismatch 0, cash gap 0원, total asset gap 0원, `aligned_waiting_first_submission`이다.
- 과거 SQLite 원장과 과거 최근 10거래일 `matched 0/mismatch 10`은 삭제하지 않았다. 새 marker 이후 current view만 분리했고 새 Phase 0 epoch는 휴장일이라 유효일 `0/10`이다.
- 기존 marker JSON/Markdown과 새 marker JSON을 `runtime-data/backups/paper-alignment/`에 보존했다. 이후 alignment는 실제 immutable JSON backup을 만들도록 가짜 `.sqlite3` 경로를 수정했다.
- trace가 과거 full-period 결과를 그대로 복사하던 문제를 수정해 새 marker가 증거 생성 이후이고 mismatch가 0이면 `clean_baseline_created_waiting_10_matched_days`로 판정한다. 관련 targeted unittest 13건을 통과했다.

## [2026-08-14] Phase 0 승인 전체 기간 조회 완결

- KST 23:28 장후, 첫 명시 승인 기본 10페이지 조회 1회는 150행/14거래일을 확보했지만 page cap으로 미완결됐다. 같은 승인 범위에서 재실행하지 않았다.
- KST 23:52 새 명시 승인으로 `--max-pages 30 --execute`를 정확히 1회 실행했다. 22페이지/329행/20거래일, distinct order key 329개로 pagination이 완결됐고 주문·취소는 0회다.
- 로컬 submission 320개는 모두 broker 활동에 연결됐으며 broker-only 활동 9행이 추가로 확인됐다. 계좌번호·주문번호·raw response는 저장하지 않았다.
- 전체 활동 position은 KIS snapshot과 일치했다. 로컬 paper만 `035420 +2`, `086520 +1`, `105560 +4`, `247540 -5` 차이여서 root cause를 `external_or_unlinked_broker_activity`로 확정했다.
- trace는 `cause_identified_clean_baseline_still_required`, `automatic_alignment_allowed=false`다. clean baseline과 새 local 기준선은 계좌 소유자의 별도 명시 승인 전 실행하지 않는다.
- 최근 10거래일 matched 0/mismatch 10은 과거 기준선의 누적이므로 유지한다. clean baseline 뒤 새 기준선에서 10개 유효 거래일을 다시 모두 정합시켜야 Phase 0을 통과한다.

## [2026-08-14] FULL CHECK 수집 보호와 수익성 재검수

- post-close에서 runtime/watchdog/dashboard/startup launcher, 26GB SQLite/날짜별 JSONL, Phase 0, 학습·label, challenger, rescue/avoid, 비용/horizon 근거를 다시 검수했다. 현재 통과한 수익 후보는 0개다.
- 8월 14일 raw JSONL은 market 10종목 공통 `15:01~15:29`, orderbook 공통 `15:01~15:24` 공백을 보였고 WebSocket reconnect 47/storm 19와 일치했다. decision ledger 3,608행의 lineage는 100%지만 coverage 92.5128%라 수집 성공으로 덮지 않는다.
- 같은 날 broker paper sync 일반 예외가 38회 발생했다. sync가 분봉 확정 경로의 동기 호출인 점을 고려해 일반 실패는 5/10/20/40/60분 지수 백오프, rate-limit은 120분 process pause로 보강했다. 주문 상태는 pending 보존하며 주문/취소·정렬은 수행하지 않았다.
- data-quality 리포트에 공통/종목별 raw 누락 범위를 추가하고 WebSocket 이벤트와 별도 증거로 분리했다. 비싼 raw minute grouping은 최근 요청 거래일로 제한해 동일 판정 기준 실행시간을 439초에서 126초로 줄였다.
- 비용/horizon 진단을 8월 14일까지 갱신했다. h60은 2배 비용 기준을 넘지만 신호·체결·보유 replay와 E1/E5 관문이 없어 `research_candidate_only`에도 못 미치는 연구 우선순위다. h15/LightGBM/buy-avoid/buy-rescue/hold-rescue는 모두 비용 후 절대 양수 후보가 아니다.
- Phase 0은 최근 10거래일 matched 0/mismatch 10과 네 종목 불일치를 유지한다. 최신 trace만 로컬에서 갱신했고 broker endpoint, 자동 align, clean baseline은 호출하지 않았다.
- targeted unittest 16건과 전체 unittest 553건을 통과했고, 저장소 구조 감사는 errors 0/warnings 2였다. 경고는 기존 대형 모듈 `app/services/dashboard.py`, `app/services/research.py`다.
- 보호 범위인 실전 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, active model/gate/threshold, NAS 백업은 변경하지 않았다.

## [2026-08-09] Phase 0 전체 기간 계좌 활동 probe

- alignment marker `2026-06-14 05:36 KST`부터 최신 KIS account snapshot `2026-08-07 16:56 KST`까지를 전체 조회 범위로 확정했다. 해당 범위의 로컬 mirrored submission은 320건, 20거래일이다.
- `scripts/probe_kis_paper_account_activity.py`를 추가해 KIS paper 일별 주문·체결을 read-only로 페이지 끝까지 조회하고, 완결성·외부/미연결 활동·position 재구성을 식별정보와 raw response 없이 판정하도록 했다.
- 계좌 소유자 요청에 따라 장외에서 첫 조회를 정확히 1회 시도했으나 즉시 `EGW00201`이 발생했다. 주문·취소 호출은 0회이며 `2026-08-10 00:48 KST`까지 cooldown을 기록하고 재시도하지 않았다.
- Phase 0 trace는 현재 `blocked_full_account_history_rate_limited`를 표시한다. cooldown 뒤 1회 완결 조회 전에는 clean baseline과 자동 align을 실행하지 않는다.
- targeted unittest 22건과 Python syntax를 통과했다.

## [2026-08-09] Phase 0 증거 범위 교정, E1/E5 snapshot 보호, 세션 연속성 계측

- Phase 0 trace가 보관된 mirrored status를 최신 KIS 전체 주문·체결 원장처럼 해석하던 문제를 고쳤다. 최신 bounded lookup은 3일·0행이고, 보관된 320 submission은 완전한 계좌 활동 원장이 아니다. 네 종목은 `current_account_vs_historical_mirrored_order_ledger_unresolved`이며 해소 상태는 `blocked_requires_full_account_history_or_clean_baseline`이다.
- 계좌 소유자 명시 승인으로 E1/E5 wrapper를 정확히 1회 실행했다. gate/label은 통과했지만 25GB snapshot이 180초 timeout으로 종료됐다. final snapshot 교체와 네트워크·주문 호출은 모두 0회이며 재실행하지 않았다.
- 대형 DB가 WSL 9P 경계를 건너 복사되는 경우 repo-local `runtime-data/research-snapshots/`를 기본으로 선택하고, timeout partial DB/journal/manifest를 실행 token 단위로 정리하도록 보강했다. WSL 배포판이 D드라이브에 있어 산출물 정책은 유지된다.
- KIS data-quality 리포트에 거래일별 decision ledger active/shadow lineage와 WebSocket reconnect/storm을 추가했다. 2026-08-07은 decision 3,803행, complete lineage 100%, feature closed coverage 97.5128%, reconnect 29/storm 0으로 수집 정상·연결 주의다.
- live runtime 상태와 watchdog 증거에 현재 RSS/peak RSS를 추가했다. 다음 장전/장중에 실제 실행 프로세스 값을 확인한다.
- 관련 targeted unittest 33건과 실제 25GB DB 리포트 재생성을 통과했다. 주문 정책, gate, threshold, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, 실전 주문·취소, NAS 백업은 변경하지 않았다.

## [2026-08-14] FULL CHECK 저장소 전용 skill 승격

- 반복 요청된 프로젝트 목표 정합성, 수집·source provenance, 판단 lineage, paper/KIS 정합성, 비용 후 수익성, 코드·테스트·문서 품질 전면 감사를 `.agents/skills/full-check/SKILL.md`로 고정했다.
- skill은 장 상태와 runtime부터 확인하고, 장중 보호 모드에서는 read-only로 제한하며, 장전/장후 세부 운영 절차는 기존 `daily-ops-check`를 함께 사용한다.
- 수익성 판정은 canonical 비용 버전, decision-episode portfolio replay, same-count random control, 비중복 기간, 최소 표본, 완전 lineage, 낙폭·비용 민감도를 요구한다. 손실 감소나 겹치는 신호 수익률 합은 수익 후보로 인정하지 않는다.
- 안전하고 원인이 확정된 결함은 수정·검증·문서화·commit/push까지 진행하되, 실전 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, active model/gate/threshold, clean baseline, NAS 백업은 승인 경계 밖으로 유지한다.

## [2026-08-09] 전체 수익성·근거 감사와 fail-closed 교정

- 휴장 상태에서 runtime/watchdog/dashboard/startup launcher, 2026-08-07 수집 품질, 학습/label refresh, Phase 0, 모델·rescue/avoid 원장을 read-only로 전수 점검했다. live runtime은 정상 정지이고 데이터 품질은 `ok`다.
- dashboard signal replay가 수수료·세금을 빼고 slippage 0.06%만 차감하던 문제를 공통 비용 `krx-common-stock-2026-v1` 왕복 0.29%로 고쳤다. 558건 합산 순수익은 `-150.3476%p`, 추정손익은 `-1,052,218원`이며 실제 계좌 수익률이 아님을 표시한다.
- LightGBM defensive shadow가 매일 새 artifact 하나만 선택해 최소 10거래일 조건을 구조적으로 채울 수 없던 문제를 고쳤다. 학습 완료 시각이 예측보다 앞선 완전 lineage 19개만 순방향 chain으로 결합하고, 누락·동일 결정 복수 lineage·동일 거래일 복수 artifact는 fail-closed로 차단한다.
- buy-avoid threshold 0.40은 baseline `-36.4241%`에서 policy `-34.3196%`로 손실을 `+2.1045%p` 줄였지만 절대수익·평균 기대값·일별 일관성 실패로 후보가 아니다. buy-rescue와 hold-rescue도 비용 후 음수이며 meta-policy primary candidate는 없다.
- 장후 label refresh에 buy-avoid, model overlay, hold-rescue, meta-policy 갱신을 포함해 학습만 최신이고 수익성 근거는 stale인 상태를 막았다. dashboard는 Phase 0 matched `0/10`일 때 로컬 누적손익을 수익 증거로 사용하지 않는다고 명시한다.
- 전체 unittest 534건, 수익성 targeted 38건, Python/bash 문법, dashboard 실제 재생성, 구조/Markdown 감사 errors=0을 통과했다. 주문 정책, gate, threshold, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, KIS 주문/취소, NAS 백업은 변경하지 않았다.

## [2026-08-06] 장후 운영 점검과 broker snapshot 메모리 가드

- live runtime은 15:30 KST에 정상 정지했고 watchdog, dashboard, Windows startup launcher는 정상이다. 2026-08-06 raw tick/orderbook JSONL은 09:00 이후 전 종목 1분 초과 공백 및 JSON 파싱 오류가 없었다.
- 장후 ML은 `ok`/`quick-live-train`(16:27 KST), label refresh는 `ok`(16:55 KST), KIS data quality는 `ok`다. active `baseline-h15-v1`, `keep_active`, promotion 없음은 유지한다.
- 당일 Phase 0 유효 기록이 이미 있어 KIS broker sync/reconciliation은 중복 호출하지 않았다. trace와 hold-rescue replay, buy-rescue overlay는 네트워크 없이 갱신했다. Phase 0은 matched 0일, mismatch 10일과 네 종목 snapshot divergence를 유지한다.
- `broker_paper_order_status_snapshots` 2,725,917건을 매 분 전부 Python으로 읽던 경로를 local order별 최신 1,819건 SQL 조회로 바꿨다. 상태 변화가 없는 polling 결과는 JSONL/SQLite에 다시 쓰지 않는다. 실제 `dev.db` 인덱스는 장후 12.7초에 적용됐고, 기존 raw JSONL과 과거 SQLite 행은 삭제하지 않았다.
- `tests.test_broker_paper_sync`, `tests.test_sqlite_store`, `tests.test_streaming_pipeline` 38건과 전체 unittest 533건, 구조/Markdown 감사 errors=0을 통과했다. 주문 정책, threshold, gate, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, KIS 네트워크 호출, 실제 주문/취소는 변경하지 않았다.

## [2026-08-02] 데이터 무결성 및 계좌 표시 보강

- 비정상 top-of-book 호가(bid 또는 ask 0 이하, crossed)를 raw 원장에는 보존하되 signal state, minute feature, offline research 입력에서 fail-closed로 제외했다. spread 기준값과 주문 정책은 바꾸지 않았다.
- P0 trace는 masked account number 없이 paper mode, product, fetch 시각, row-count shape를 함께 기록하도록 보강했다. 현재 근거는 local paper와 KIS order/fill net이 일치하고 KIS account snapshot만 다르다는 데까지이며, 외부 snapshot 원천 또는 수동 상태의 최종 원인 확정은 다음 거래일 재확인이 필요하다.
- feature JSONL은 SQLite primary key 정본에서 6,603,588 model input과 11,936,383 label을 전수 재생성·검증했다. 기존 54GB 보조본은 3.6GB canonical JSONL로 교체했고, 이전 디렉터리는 검증 뒤 제거했다. raw, order, fill, SQLite 정본은 변경하지 않았다.
- 오프라인 feature dataset 재구축은 SQLite가 있을 때 JSONL append를 생략하도록 바꿔 같은 중복 문제가 다시 누적되지 않게 했다.
- dashboard 모의계좌는 전체 정렬 원장의 현재 잔고/포지션과 선택 기간 주문·체결 활동을 분리해 표시한다. 계좌 현황이 날짜 필터에 따라 축소돼 보이던 혼선을 제거했다.
- 전체 unittest 531건과 구조/Markdown 감사 errors=0을 통과했다. 주문 정책, threshold, active model, 실전 주문과 취소, config, VERSION, ALLOW_LIVE_ORDERS는 변경하지 않았다. dashboard 검증 중 read-only 계좌 조회는 발생했지만 주문 호출은 없었다.

## [2026-08-02] 휴장 운영 감사와 원장 진단 갱신

- live runtime은 휴장 정상 정지, watchdog heartbeat fresh, dashboard server/API와 Windows startup launcher는 정상이다. Phase 1b 기본 preflight는 `ready/passed`이며 KIS 네트워크와 주문 호출은 각각 0회다.
- 2026-07-31 장후 ML은 `ok`/`quick-live-train`(16:24 KST), label refresh는 `ok`(16:54 KST), KIS data quality는 `ok`다. active `baseline-h15-v1`, `keep_active`, promotion 없음은 유지한다.
- P0 trace를 KIS 네트워크 호출 없이 갱신했다. local paper/KIS order-fill 순수량 `2/6/4/5`와 KIS snapshot `0/5/0/10`의 divergence는 그대로지만, 네 종목의 rejected close recent count는 모두 0건이다. 과거 lifetime 누적을 active retry로 오인하지 않으며 자동 align과 `SyncInitialCash`는 실행하지 않았다.
- hold-rescue paper-only replay는 161 eligible lot 중 37 lot 적용, `delta_cash_sum=-26,387원`, `diagnostic_only_no_hold_rescue_candidate`다. buy-rescue KIS live no-trade ledger는 52,417행 중 eligible 25,726행으로 확인했고, LightGBM 최선 6건 `-4.154%p`, linear-score 최선 229건 `-84.697%p`, 두 모델 동시 상승 35건 `-23.768%p`로 모두 후보가 아니다.
- buy-rescue 비교 리포트가 7월 12일 결과에 머물러 원장을 비어 있는 것으로 잘못 표시한 점을 수정했다. 실제 rescue가 0건인 threshold를 최선으로 선택하지 않도록 고쳤고, 장후 점검은 최신 overlay 리포트의 생성 시각과 ledger 행 수를 함께 확인한다.
- 전체 unittest `525 tests OK`, 구조 감사 errors=0을 확인했다. 주문 정책, threshold, gate, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, KIS 네트워크 호출, 실제 주문/취소는 변경하지 않았다.

## [2026-07-28] Phase 0 재시도 차단과 E1/E5 snapshot 보호

- runtime 원장을 read-only로 분석한 결과 035420, 086520, 105560, 247540은 실패한 KIS paper mirrored sell을 장중 매 분 재시도했다. 2026-07-27 최근 24시간 거절 건수는 각각 382, 379, 380, 380이며 누적 전체는 9,753, 7,830, 9,864, 3,901건이다.
- OnlinePipelineProcessor는 broker submission acknowledgement를 받지 못한 close를 rejected로 기록한 뒤 같은 symbol의 추가 close submission을 차단한다. runtime 재시작 시에도 마지막 sell 상태가 rejected이고 local position이 남아 있으면 차단을 복원한다. 명시적인 정합성 수리 전에는 재시도하지 않는다.
- mismatch trace는 lifetime rejected count와 24시간 recent count를 분리해, 과거 흔적만으로 active loop라고 단정하지 않도록 바꿨다.
- research snapshot은 D드라이브 복사 중 180초를 넘기면 final snapshot/manifest를 교체하지 않는다. partial 파일에서 quick_check 뒤 atomic replace하고, E1/E5 runner는 latest-completed-round 대신 sanitized snapshot_failed attempt만 남긴다.
- 주문 정책, threshold, gate, active model, app/risk, config, VERSION, ALLOW_LIVE_ORDERS, KIS 네트워크 호출, 실제 주문/취소는 변경하지 않았다.
- 관련 회귀 테스트 20건, 전체 unittest 525 tests OK, 작은 SQLite snapshot atomic smoke를 통과했다.

## [2026-07-23] Phase 0 10일 관측 종료와 장후 점검

- 장후 ML은 `ok`(16:18 KST, `quick-live-train`), label refresh는 `ok`(16:52 KST)였다. KIS live data quality도 `ok`이며 2026-07-23까지 거래일 58일을 관측했다.
- live runtime은 장후 정상 정지했고 watchdog, dashboard, Windows startup launcher는 정상이다.
- Phase 0은 유효 거래일 10일을 채웠지만 matched `0일`, mismatch `10일`이어서 완료 조건을 통과하지 못했다. 불일치 종목은 `035420`, `086520`, `105560`, `247540`이다.
- 당일 유효 정합 기록이 이미 있어 broker sync/reconciliation은 재호출하지 않았다. 오래된 mismatch trace만 로컬에서 갱신했으며, 네 종목 모두 local paper와 KIS order/fill 순수량은 맞고 KIS account snapshot 수량만 다른 `kis_account_snapshot_vs_order_fill_ledger_divergence`로 분류됐다.
- 자동 align, `SyncInitialCash`, 주문 정책, threshold, gate, active model, 실전 주문은 변경하지 않았다.
- hold-rescue paper-only replay는 `diagnostic_only_no_hold_rescue_candidate`다. buy-avoid와 buy-rescue도 기존 관측 결과만 유지했다.

## [2026-07-20] 월요일 수집 복구와 장후 점검

- 장전 readiness는 `ok`였다. runtime, watchdog, dashboard, KIS quote 자격정보, SQLite read-only smoke가 모두 통과했다.
- `serving_decision_ledger`는 08:30~15:19 KST에 3,812행을 추가했고, active prediction/artifact와 shadow prediction을 모두 포함한 complete lineage도 3,812행이었다. 2026-07-17 수집 공백은 해소됐지만 과거 공백 기록은 보존한다.
- live runtime은 장후 정상 정지했고 watchdog/dashboard/startup launcher는 정상이다. 다만 KIS WebSocket은 `no close frame`으로 29회 재연결됐으므로, 데이터 품질은 유지됐어도 연결 안정성 관찰을 계속한다.
- 장후 ML은 `ok`(16:24 KST, `quick-live-train`), label refresh는 `ok`(16:55 KST)였다. active 모델과 주문 정책, threshold, gate는 바꾸지 않았다.
- Phase 0은 `7/10`, matched `0일`, mismatch `7일`이다. mismatch 종목은 `035420`, `086520`, `105560`, `247540`이며 당일 유효 기록이 이미 있어 broker sync/reconciliation을 중복 호출하지 않았다.
- E1/E5 wrapper는 장후에 1회 실행했다. SQLite snapshot을 `/mnt/d/CodexData/.../research-snapshots`로 복사하는 단계가 WSL `p9_client_rpc` I/O 대기에 걸려 결과 파일 없이 중단됐다. 중복 실행은 하지 않았고, 주문/네트워크 호출은 없었다.

## [2026-07-18] KIS 수집 장애 완화 및 월요일 장전 준비

- 2026-07-17 KIS approval-key REST의 SSL EOF/timeout으로 listener가 종료되고 watchdog이 60초마다 재시작한 기록을 확인했다. 해당 거래일 `serving_decision_ledger`는 새 행이 없다.
- `app/brokers/kis_quote_ws.py`에서 approval-key 발급을 WebSocket connect와 같은 재시도 경로로 옮기고, 5초에서 최대 60초까지 지수형 대기를 적용했다.
- `scripts/wsl_ops.py` watchdog은 failed listener 재시작을 2분에서 최대 15분까지 지수형 대기한다. 정상 실행을 확인하면 실패 카운터를 초기화한다.
- 2026-07-18은 주말이라 KIS 네트워크를 호출하지 않았다. 2026-07-20 장전에는 수집 재개와 `serving_decision_ledger` 증가를 우선 확인한다.
- 주문 정책, active model, threshold, gate, `app/risk/`, config, VERSION, 실전 주문은 변경하지 않았다.
- 전체 unittest: `522 tests OK`; `git diff --check`와 Python syntax 검사를 통과했다.

## [2026-07-13] 저장소 구조와 현재 문서 정리

- 전체 구조를 실제 파일 기준으로 감사했다: app Python 97개, 테스트 89개, scripts 최상위 139개.
- 감사 전 추적 Markdown 208개의 명시적 local link 누락과 불균형 code fence는 각각 0건이었다.
- `logbook`, `STATUS`, 초기 sprint/workflow/cowork guide, 실전 전환 진행판 원문을 `docs/archive/`에 보존했다.
- archive와 HEAD 원문은 줄바꿈 정규화 기준으로 모두 일치한다.
- 현재판 6개 문서를 합계 약 1만 줄에서 406줄로 축약하고 문서별 소유권을 고정했다.
- `docs/Repository-Structure.md`에 실제 레이어, wrapper 규칙, D드라이브 위치, 구조 부채를 기록했다.
- `scripts/audit_repository_structure.py`와 회귀 테스트 3개를 추가했다.
- 전체 unittest `518 tests OK`, pytest `518 passed, 67 subtests passed`.
- cleanup helper로 87개, `94,171,757 bytes`를 정리하고 root `.pytest_cache`도 제거했다.
- 최종 감사 `errors=0`, 경고는 `research.py`와 `dashboard.py` 대형 모듈 2건뿐이다.
- 대형 모듈은 현재 계약 범위가 넓어 이번 작업에서 분해하지 않고 별도 테스트 리팩터링 대상으로 남겼다.
- 주문 정책, 모델, threshold, gate, Phase 상태, runtime DB, NAS 백업은 변경하지 않았다.

## [2026-07-12] review_ver_33 수익성 증거 정합성

- hold-rescue 기본비용을 구형 `0.13%`에서 현재 `0.29%`로 교정했다.
- E6 `cybos_historical`을 순수 Cybos가 아닌 pre-KIS 혼합 근사치로 명시했다.
- 구형 비용 `0.108%` walk-forward를 현행 수익성 증거에서 제외했다.
- 모든 challenger와 rescue/avoid 후보가 비용 후 수익 또는 재현성 기준을 통과하지 못했다.
- 주문 정책, threshold, active model, gate는 변경하지 않았다.
- 작업 리포트: `docs/cowork-reports/2026-07-12-rescue-avoid-profitability-review-work_ver_34.md`

## 아카이브

- 최신 요약: `docs/logbook_archive/logbook_20260712.md`
- 2026-07-12까지 전체 원문: `docs/archive/logbook-full-through-20260712.md`
- 최초 아카이브: `docs/logbook_archive/logbook_20260411.md`
