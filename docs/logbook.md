# 작업 기록

## 역할

이 파일은 중요한 변경, 원인, 검증 이력을 유지한다. 최신 운영 상태와 blocker는 `docs/STATUS.md`, 현재 작업 범위는 `docs/SPRINT_CURRENT.md`가 소유한다.
긴 과거 기록은 `docs/logbook_archive/`와 `docs/archive/`에 보관한다.

## 최근 운영 스냅샷 (2026-09-04)

- 기준 시각: 2026-09-05 16:36 KST
- 장 상태: weekend; 최신 운영 거래일 `2026-09-04`는 post-close 완료
- live runtime: 2026-09-04 15:30 KST 정상 종료 후 정지
- weekend 기준 watchdog/dashboard는 stale·정지, `live_runtime_should_run=false`; startup launcher 정상
- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 2026-09-04 post-close ML은 `status=ok`, 18:14 KST `quick-live-train`; label refresh는 `status=ok`, 19:13 KST 완료했고 모델 승격은 없다.
- 현재 통과한 수익 후보: `0개`
- 수익화 판정: `no_profitable_candidate`
- 현재 paper account epoch는 `paper-2026-09-03`, 활성일 `2026-09-03`, 만료일 `2026-12-03`이다. 갱신 준비는 `2026-11-03`, 긴급 경고는 `2026-11-26`부터다.
- 새 자격정보 token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` read-only orderability가 통과했다. 2026-09-03 자연 cash-order submission 36건이 성공해 이전 account rejection은 만료·무효 상태였던 이전 계좌가 주원인으로 사실상 확인됐다.
- 지정가 4건은 KRX 일반주권 500원 호가단위 위반, 1건은 network timeout으로 분리했다. 2026-09-05 order-fill sync는 3페이지/38행을 완결했고 `068270` 매도 체결 2주를 반영했다.
- 2026-09-06 승인 marker-only clean baseline은 현재 계좌와 호환된다. 직후 reconciliation은 mismatch/effective cash/total asset gap `0`, Phase 0은 `no_history`, `0/10`이며 휴장일은 유효일로 세지 않는다.
- Phase 0 prior epoch의 `10/10`, matched 0일, mismatch 10일과 네 종목 불일치 이력은 보존한다.
- Phase 1b: bounded read-only 관측 1회 통과 이력은 있으나 latest readiness는 stale. 반복 자동화 preflight는 네트워크·주문 호출 0회다.
- runtime 원장: 2026-09-04 decision ledger `3,800/3,800`, complete lineage 100%, market/orderbook `3,811/4,049` symbol-minute, feature `3,800`행/closed coverage `97.44%`다.
- WebSocket: reconnect 28, storm 0, 예상 밖 공통 gap 없음이다. 28회 모두 재구독 완료와 첫 프레임 복구가 확인돼 `ATTENTION/주의`다.
- 수익성: top challenger는 3분류 정확도 `19.61%`, buy hit `18.35%`, 누적 진단 순수익 `-400.65%`, 거래 `1,477건`이다. buy-avoid는 절대 portfolio 손실, buy-rescue는 진단 전용, hold-rescue threshold 0.40은 `-26,887원`이어서 후보가 아니다.
- 비용 구조: 현행 왕복 0.29%, 2배 민감도 0.58%. active model/gate/threshold/주문 정책은 동결한다.
- E7 evaluator `portfolio-replay-v2-minute-mtm`과 manifest `1d61b288...e0dd3fa`는 일치한다.
- E7은 2026-09-04 기준 future trading days `5`, 실행 가능 모집단 episode `3,119`, official policy episode/symbol `0/0`, invalid mark `0`, evidence health `valid_collecting`, 공식 상태 `collecting_future_sample`이다. 수익성 실패가 아니라 표본 축적 단계다.

상세 현재값은 `docs/STATUS.md`, Phase 상태는 `docs/Production-Transition-Progress.md`를 기준으로 한다.

## 최근 작업 체크포인트 (이력)

- [x] 2026-08-28 raw→feature→decision ledger와 complete lineage 100% 확인
- [x] 종가 동시호가 예상 gap과 unexpected common gap 분리
- [x] reconnect storm과 정규장 예상 밖 전 종목 공통 gap을 `CRITICAL/실패`로 우선 판정
- [x] Phase 0 baseline과 paper account epoch 분리
- [x] broker 실패 taxonomy, account hard-rejection circuit, stable failure lineage 추가
- [x] 이전 paper 계좌 만료를 account rejection의 유력 root cause로 교정
- [x] 새 paper APP 자격정보, account snapshot, `VTTC8908R/ORD_DVSN=00` orderability 확인
- [x] 만료일과 30일/7일 전 갱신 경고를 lifecycle report/dashboard/daily ops에 연결
- [x] 이전 KIS support snapshot을 superseded 역사 증거로 분리
- [x] 다음 정상 거래의 자연 broker submission 36건 성공 확인
- [x] KRX common-stock 지정가 호가단위 정규화와 `invalid_price_tick` taxonomy 추가
- [x] WebSocket 재구독 완료·첫 프레임 복구 증적 추가
- [x] 2026-09-05 장외 order-fill sync 1회로 38 submission 상태 완결
- [x] current account snapshot/reconciliation과 후속 order-fill sync로 local/new-broker position·cash 차이의 기준선 세대 원인 설명
- [x] 계좌 소유자 승인으로 현재 계좌용 Phase 0 marker-only clean baseline 생성 및 gap 0 검증
- [ ] 현재 계좌 Phase 0 유효 거래일 10개 모두 matched 확인
- [x] hold-rescue canonical 15분/2.0%/15:20 기준 통일과 no-op threshold 선택 차단
- [x] buy-avoid/hold-rescue 절대 손익 음수 판정 유지
- [x] E7 LightGBM buy-rescue threshold 0.55 미래 검증 사전등록
- [x] replay v1 보존, minute MTM v2, immutable E7 manifest와 혼합 차단 검증
- [x] E7 daily read-only artifact writer와 sample/drift/mark/idempotency 검증
- [ ] 2026-08-31 이후 E7 최소 10거래일/100 episode/5종목 확보
- [ ] E7 portfolio replay, random control 1,000회, 2배 비용, 비중복 두 구간 판정
- [ ] 2026-09-04 real WebSocket recovery evidence를 fresh Phase 1b readiness에 연결

현재 상세 작업 범위는 `docs/SPRINT_CURRENT.md`를 따른다.

## 최신 검증

- KRX 호가단위·broker mirror·WebSocket·data-quality targeted unittest: `55 tests OK`
- demo pipeline root runtime 격리 회귀 테스트: `3 tests OK`
- 전체 unittest: `627 tests OK` in 33.770s, 테스트 쓰기는 `.tmp-tests/` 격리
- repository structure audit: errors 0/warnings 2. 기존 대형 모듈 `app/services/dashboard.py`, `app/services/research.py`
- 2026-09-04 저장 증거 재검산: market/orderbook `3,811/4,049` symbol-minute, feature closed coverage `97.44%`, decision lineage `3,800/3,800`·100%
- 2026-09-04 WebSocket: reconnect 28, storm 0, 정규장 예상 밖 공통 gap 없음, 재구독 완료와 복구 후 첫 프레임 각각 28건
- 새 paper 계좌 자연 cash-order submission 36건 성공 확인. 지정가 실패 4건은 KRX common-stock 호가단위 오류, 별도 1건은 network timeout
- 2026-09-05 order-fill sync는 1.0초 paper 페이지 간격으로 3페이지/38행을 완결했고 submission 38/38 exact-linked, open 0/final 38/pending 0, 체결 event 1건·2주 적용을 확인
- Phase 0 current epoch: compatible clean baseline, `no_history`, 유효일 `0/10`; 이전 계좌 epoch의 10/10 mismatch 이력은 보존

## [2026-09-06] 현재 paper 계좌 Phase 0 clean baseline

- 휴장일·live runtime 정지·`live_runtime_should_run=false`와 current epoch `paper-2026-09-03`을 확인한 뒤, 계좌 소유자 승인 범위로 `python3 -m app --align-local-paper-to-broker`를 정확히 1회 실행했다.
- KIS paper account snapshot 기준 marker-only baseline은 `aligned_to_broker_marker`, position 2종목이며 immutable JSON backup을 보존했다. `SyncInitialCash`, order-fill 재조회, 주문·취소, 실전 계좌 호출은 실행하지 않았다.
- 직후 account reconciliation 1회는 `aligned_waiting_first_submission`, position mismatch `0`, effective cash gap `0원`, total asset gap `0원`, raw cash gap `-1,850원`이다. current view는 `005930` 1주와 `035420` 2주다.
- lifecycle은 baseline `compatible`, blocking reason 없음이다. Phase 0 history는 `no_history`, `0/10`, remaining 10이며 휴장일인 2026-09-06은 분모에 포함하지 않는다.
- 실행 전 alignment/reconciliation/history 회귀 테스트 14건이 통과했다. 기존 원장과 이전 계좌 epoch의 10일 mismatch 이력은 삭제하거나 재작성하지 않았다.

## [2026-09-05] 로드맵 1단계 증거 정렬

- 2026-09-04 current account snapshot/reconciliation이 이미 정상 조회됐음을 확인했다. latest 비교는 mismatch 5건과 cash gap `-4,382,557.78원`이었고, 이전 계좌 2026-08-15 baseline 포지션과 당시 미동기화 `068270` 매도 체결이 함께 원인이었다.
- 2026-09-05 order-fill sync의 최신 status/fill을 DB read-only로 재검산해 `068270` 매도 2주가 exact-linked·filled·applied 상태임을 확인했다. 새 계좌 baseline 생성, account 재조회, 주문·취소는 실행하지 않았다.
- 2026-09-04 E7은 evaluator/manifest 일치, 미래 거래일 5일, 실행 가능 모집단 episode 3,119, official episode 0이다. grouped episode 첫 판단의 entry score를 사용하는 사전등록 의미와 일치하므로 threshold나 evaluator를 변경하지 않는다.
- 같은 날 WebSocket reconnect 28회는 storm 0이고 재구독·첫 프레임 복구가 모두 확인됐다. 실제 복구 증거는 확보됐지만 Phase 1b readiness 연결은 여전히 stale/synthetic이라 Phase 2 진입 증거로 쓰지 않는다.
- 새 package, plugin, MCP, application code는 추가하지 않았다. 현재 단계는 기존 저장소 기능과 artifact로 충분해 Hypothesis·OpenTelemetry·vectorbt 도입은 원래 로드맵의 후속 조건까지 보류한다.

## [2026-09-05] 저장소 관리 규칙 마이그레이션

- `MIGRATE_EXISTING_REPO_v1.txt`와 `ref_AGENTS_v4.md`를 기준으로 기존 구조와 이력을 보존한 채 관리 문서를 정리했다.
- root `AGENTS.md`를 저장소 고유 미션, 장중 보호, 거래·비밀값 안전, D드라이브 산출물, 실제 검증 명령 중심으로 줄였다. 필수 Read First는 5개로 제한하고 cowork, KIS, 복구, 구현 문서는 관련될 때만 읽도록 바꿨다.
- 현재 운영 수치의 단일 기준은 `docs/STATUS.md`, 스프린트 범위는 `docs/SPRINT_CURRENT.md`, 구현 계약은 `docs/Current-Implementation.md`, 변경 이력은 `docs/logbook.md`로 명확히 나눴다. 기존 문서와 역사 기록은 삭제하거나 이름을 바꾸지 않았다.
- KIS order-fill의 `논리 동기화 1회`와 `연속조회 페이지별 HTTP 요청`을 구분하고, paper 응답 완료 기준 최소 1.0초 간격과 `EGW00201` 2시간 cooldown을 README·구현 문서·runbook에 맞췄다.
- 2026-09-05 실환경 order-fill 결과는 3페이지/38행, submission 38/38 exact-linked, open 0/final 38/pending 0, 체결 event 1건·2주 적용이다. account snapshot/reconciliation과 baseline 생성은 수행하지 않았다.
- 검증은 전체 unittest 627건, repository audit errors 0/warnings 2, `python -m app --help`, 문서 경로 확인, `git diff --check`를 통과했다. application code, 전략, 설정, DB, runtime-data, `VERSION`, 주문·취소, NAS 백업은 변경하지 않았다.

## [2026-09-04] 2026-09-03 장후 호가단위·WebSocket P0 개선

- 2026-09-03 지정가 거절 4건을 재검산했다. 모두 일반주권 `005930`, `ORD_DVSN=00`이며 20만~50만원 구간의 KRX 500원 호가단위를 벗어난 `252750/253250/253750` 가격이었다. 매수는 유효 tick으로 내림, 매도는 올림 정규화하고 risk evidence와 실제 KIS request가 같은 정규화 가격을 기록하도록 했다.
- KIS business error에서 sanitized `rt_cd/msg_cd/msg1`을 보존하고 `invalid_price_tick` reason을 `broker_invalid_request` 아래에 추가했다. 계좌번호, 앱 키, 시크릿, 토큰, raw response는 기록하지 않는다.
- 새 paper 계좌의 자연 KIS cash-order submission 36건 성공을 canonical 사실로 반영했다. 이전 `broker_account_not_orderable` blocker는 만료된 이전 계좌 상태로 사실상 종결하되 같은 taxonomy가 재발하면 새 incident로 다시 조사한다.
- WebSocket reconnect 36/storm 7과 전 종목 공통 gap `15:01~15:08`은 `UPSTREAM_KIS_OR_NETWORK_DISCONNECT`로 분류했다. KIS와 로컬 네트워크 중 어느 쪽인지는 저장 증거만으로 단정하지 않았다. 기존 5/10/20/40/60초 bounded reconnect와 전체 재구독으로 같은 process가 복구했으므로 retry 정책은 바꾸지 않고 재구독 완료와 복구 후 첫 프레임 로그만 추가했다.
- coverage 95% 이상·lineage 100%라도 `storm_count>0` 또는 정규장 예상 밖 공통 gap이 있으면 daily data-quality 최종 심각도를 `CRITICAL/실패`로 우선하도록 고쳤다. 단순 reconnect이며 storm 0인 경우는 계속 `ATTENTION/주의`로 분리한다.
- 초기 전체 테스트 1회에서 기존 demo pipeline 테스트가 root runtime 경로를 사용해 고정 demo ID를 upsert할 수 있는 경로가 실행됐다. 이후 테스트를 임시 디렉터리와 임시 SQLite로 완전히 격리했다. root DB read-only 확인에서는 해당 prediction·signal·paper order가 각 1행 존재하지만 기존 행인지 이번 실행이 다시 쓴 행인지는 구분할 수 없어 임의 정리·재생성은 하지 않았다.
- E7 threshold/model/manifest, signal/gate/allocator, `app/risk/`, `config/`, `VERSION`, Phase 0 baseline, 실전 주문 flag는 변경하지 않았다. 이번 작업 중 KIS 네트워크와 주문·취소 호출은 모두 0회다.
- targeted 55건, pipeline 3건, 전체 619건과 repository structure audit errors 0/warnings 2를 통과했다.

## [2026-09-03] 새 paper 계좌 lifecycle 및 장전 자동화 복구

- 이전 paper 계좌 만료와 새 자격정보·계좌 교체를 반영해 현재 epoch를 `paper-2026-09-03`, 활성일 `2026-09-03`, 만료일 `2026-12-03`으로 기록했다. 갱신 준비는 `2026-11-03`, 긴급 경고는 `2026-11-26`부터며 만료일부터 fail-closed한다.
- 네트워크 0회 lifecycle report와 dashboard 카드·경고를 추가하고, Phase 0 history/reconciliation이 현재 계좌 활성일보다 오래된 2026-08-15 baseline을 재사용하지 않도록 `baseline_review_required`, `0/10`으로 분리했다.
- 새 paper 자격정보 token refresh, account snapshot, `VTTC8908R/ORD_DVSN=00` orderability는 통과했다. 이전 `broker_account_not_orderable`은 만료된 계좌가 유력 root cause지만 새 계좌의 자연 cash-order 성공은 아직 관찰되지 않았다.
- 07:56 KST 장전 Phase 1b preflight를 수동 1회 보완했다. `status=ready`, `passed=true`, 차단 사유 없음, KIS network/order call은 각각 0회였다.
- 자동화 프롬프트는 07:20~07:40이었지만 실제 schedule이 08:25로 남아 있어 오늘 예약 실행이 누락됐다. 실제 schedule만 07:25/20:25 KST로 고치고 저장된 automation TOML을 재검수했다.
- 08:00 KST watchdog가 live runtime을 `paper`/pre-open으로 정상 시작했다. 운영 DB·runtime·dashboard는 재시작하거나 갱신하지 않았고 관련 43개 단위 테스트는 `.tmp-tests/`에서 통과했다.
- 전략, E7 threshold/model/manifest, signal/gate/allocator, `app/risk/`, 실전 주문 flag, Phase 0 baseline, VERSION, 주문·취소는 변경하지 않았다.

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

## 아카이브

- 최신 요약: `docs/logbook_archive/logbook_20260814.md`
- 2026-07-12까지 전체 원문: `docs/archive/logbook-full-through-20260712.md`
- 최초 아카이브: `docs/logbook_archive/logbook_20260411.md`
