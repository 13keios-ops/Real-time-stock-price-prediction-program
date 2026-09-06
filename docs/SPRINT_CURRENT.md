# 현재 스프린트

현재 운영 수치는 `docs/STATUS.md`가 소유한다. 이 문서의 수치는 스프린트 기준선이며 작업 범위와 동결 조건을 설명한다.

## 이름

Phase 1 수익성 증거 원장 축적과 E7 미래 검증

## 기간

- 시작: `2026-07-13`
- E1/E5 완결: `2026-08-15`
- E7 독립 미래 구간 시작: `2026-08-31 09:15 KST`
- 후속 checkpoint: `10/20/30/60거래일`

일주일은 최종 승격 기간이 아니라 첫 조기 진단 구간이다.

## 목표

1. 정규장 raw부터 실제 판단까지 완전한 decision lineage를 축적한다.
2. Phase 0 clean baseline 이후 10개 유효 거래일의 paper/KIS 정합성을 검증한다.
3. 탐색적으로 양수인 LightGBM buy-rescue를 독립 미래 구간의 실제 portfolio와 random control로 검증한다.
4. 실패 결과를 threshold로 구제하지 않고 h60 또는 entry/exit 분리 가설로 이동할 기준을 고정한다.
5. active model, gate, 주문 정책은 검증 통과 전까지 동결한다.

## 현재 기준선

- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 현재 통과한 수익 후보: `0개`
- 수익화 판정: `no_profitable_candidate`
- 자동 승격: 없음
- Phase 0 과거 계좌 epoch: 유효일 `10/10`, matched 0일, mismatch 10일
- Phase 0 현재 계좌 epoch: `paper-2026-09-03`; 2026-09-06 승인 clean baseline은 호환되며 상태 `no_history`, 유효일 `0/10`
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: bounded live read-only 관측 1회 통과 이력은 있으나 latest readiness는 stale
- Phase 2/3: 미시작
- 2026-09-04 decision ledger: 3,800행, complete lineage 3,800행, ratio 1.0
- 2026-08-31/09-01 broker account rejection은 만료된 이전 paper 계좌에서 발생한 이력이다. 새 계좌에서 같은 경로의 자연 submission 36건이 성공해 이전 계좌 무효 root cause가 사실상 확인됐다.
- 새 paper 계좌는 2026-09-03 활성, 2026-12-03 만료다. 30일/7일 전 갱신 경고를 적용한다.
- 새 계좌 자연 cash-order는 성공 36건, invalid tick 4건, network timeout 1건이다. 2026-09-04 current account snapshot/reconciliation은 정상 조회됐지만 이전 계좌 baseline과 미동기화 체결 때문에 mismatch 5건이었다. 2026-09-05 order-fill sync는 3페이지/38행, submission 38/38 exact-linked, open 0/final 38/pending 0으로 완결되고 `068270` 매도 2주를 반영했다.
- 2026-09-06 승인 marker-only clean baseline과 직후 reconciliation은 current epoch compatible, mismatch/cash/total asset gap `0`, `aligned_waiting_first_submission`이다. 휴장일은 유효일 분모에 넣지 않는다.
- 2026-09-04 data quality: market/orderbook `3,811/4,049` symbol-minute, feature `3,800`행/`97.44%`, reconnect `28`, storm `0`, unexpected common gap 없음, assessment `ATTENTION/주의`
- 2026-09-04 E7 day 5: `valid_collecting`, future trading days `5`, 실행 가능 모집단 episode `3,119`, official policy episode/symbol `0/0`, invalid mark `0`, official status `collecting_future_sample`
- 이전 계좌 KIS support snapshot은 역사 증거로만 보존하며 현재 계좌 결론에는 사용하지 않는다.
- E7 탐색 기준선과 threshold 0.55는 동결하며 future evidence와 섞지 않는다.

## 활성 체크리스트

- [x] 정규장 `serving_decision_ledger`와 prediction artifact lineage 축적
- [x] baseline 판단, gate, allocator, 현금·보유·pending, 주문·체결 결과 연결
- [x] 비정상 호가 fail-closed와 broker 상태 snapshot 중복 적재 차단
- [x] data-quality에 coverage, complete lineage, reconnect/storm, 공통 gap 보고
- [x] `15:20~15:29 KST` 예상 종가 동시호가 market gap을 unexpected gap과 분리
- [x] reconnect가 있어도 storm 0·coverage 95% 이상·lineage 100%이면 수집과 연결 주의를 분리
- [x] 이전 계좌 Phase 0 full-period account activity 22페이지/329행과 pagination 완결 확보
- [x] 이전 계좌 broker-only 9행을 확인하고 2026-08-15 clean baseline 생성
- [x] Phase 0 history를 baseline 및 paper account epoch로 분리
- [x] broker failure taxonomy, 30분 account hard-rejection circuit, decision→attempt→failure lineage 추가
- [x] 이전 paper 계좌 만료를 account rejection의 유력 root cause로 교정
- [x] 새 paper APP 자격정보, account snapshot, `VTTC8908R/ORD_DVSN=00` orderability 확인
- [x] 새 계좌 활성일/만료일과 30일/7일 전 갱신 경고를 lifecycle report와 dashboard에 연결
- [x] 이전 KIS support snapshot을 superseded 역사 증거로 분리
- [x] 새 계좌의 자연 KIS cash-order submission 36건 성공으로 이전 account-orderability blocker 종료
- [x] KRX common-stock 지정가 호가단위 정규화와 `invalid_price_tick` taxonomy 추가
- [x] WebSocket 재구독/첫 프레임 복구 증적과 storm/common-gap 우선 `CRITICAL/실패` 판정 추가
- [x] cooldown 종료 후 장외 order-fill sync 1회로 38 submission 상태 완결
- [x] broker paper 누적 체결 평균가를 local fill 대금 기준 delta 체결가로 변환
- [x] broker paper order/fill/position accounting을 local order 단위 SQLite transaction과 메모리 rollback으로 원자화
- [x] live manager의 `limit` 주문을 KIS `ORD_DVSN=00` 계약으로 변환하고 local idempotency key를 broker request에서 분리
- [x] live cancel에 local order 미체결 잔량을 KIS `order_qty`로 전달
- [x] live submit의 market-data freshness 판정과 필수검사 flag를 guard까지 전달
- [x] restart inflight live order를 완결된 broker history와 exact identity로만 복구하고 불확실하면 `UNKNOWN` 유지
- [x] current account snapshot/reconciliation 1회와 후속 order-fill sync로 local/new-broker position·cash 차이의 기준선 세대 원인 설명
- [x] 계좌 소유자 승인으로 현재 계좌용 Phase 0 marker-only clean baseline 생성 및 gap 0 검증
- [ ] 현재 계좌 Phase 0 epoch의 유효 거래일 10개를 모두 matched로 확인
- [x] E1 후보 0/3, E5 second interval 미재현으로 기존 가설 기각
- [x] hold-rescue 기본값을 15분/2.0%/15:20으로 통일하고 no-op threshold 선택 차단
- [x] buy-avoid의 절대 portfolio 손실을 근거로 기각 유지
- [x] E7 LightGBM buy-rescue 미래 검증을 threshold 0.55와 고정 기준으로 사전등록
- [x] 기존 replay v1 보존, minute MTM v2와 immutable E7 manifest/compatibility guard 검증
- [x] E7 current-day post-close read-only daily artifact writer와 sample/drift/mark/idempotency 검증
- [ ] 2026-08-31 이후 E7 최소 10거래일/100 episode/5종목 확보
- [ ] E7 decision-episode portfolio replay와 층화 same-count random control 1,000회 실행
- [ ] E7 2배 비용, 일별 일관성, 집중도, 최대 낙폭, 비중복 두 번째 구간 판정
- [ ] 2026-09-04 실제 WebSocket recovery evidence를 fresh Phase 1b readiness artifact에 연결

## E7 통과 기준

- 공식 비교 16개 결과가 모두 `portfolio-replay-v2-minute-mtm`과 동일 manifest/구간/비용/제약을 사용
- 현행 비용 0.29%와 2배 비용 0.58%에서 portfolio return과 평균 거래 기대값이 모두 양수
- random control 상위 5% 초과
- 비음수 거래일 비율 2/3 이상
- 한 종목 또는 한 거래일의 총이익 기여가 50% 이하
- lineage 100%, 10거래일, 100 episode, 5종목 이상
- 서로 겹치지 않는 미래 평가구간 두 개에서 재현

최소 표본 미달은 `observe_more`, 기준 실패는 `rejected`, 두 구간 통과만 `research_candidate`다.

## 동결 범위

Phase 0 현재 epoch 10거래일 정합과 E7 미래 검증 전에는 신규 threshold/EV tuning, 종목별·h60 주문 정책, active model/gate 변경, rescue/avoid 주문 반영, 실전 주문/취소를 하지 않는다.

운영 장애, 데이터 lineage 누락, 관측 리포트 오류를 고치는 작업은 동결 대상이 아니다.

## 다음 분기

- E7 두 구간 통과: 운영자/cowork 검토 뒤에도 바로 승격하지 않고 paper canary 설계만 검토한다.
- E7 표본 부족: 기준을 바꾸지 않고 관측을 연장한다.
- E7 세 번 고정 평가 실패: threshold 탐색을 중단하고 h60 또는 entry/exit 분리 가설을 새로 사전등록한다.
- 어느 분기든 실현 미래 변동폭을 entry 필터로 사용하지 않는다.

## 과거 스프린트

스프린트 01 원문은 `docs/archive/SPRINT_CURRENT-sprint-01-legacy.md`에 보존한다.
