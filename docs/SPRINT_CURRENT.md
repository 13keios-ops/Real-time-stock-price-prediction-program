# 현재 스프린트

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
- Phase 0 과거 epoch: 유효일 `10/10`, matched 0일, mismatch 10일
- Phase 0 현재 epoch: 2026-08-15 clean baseline 뒤 `0/10`, matched 0일, mismatch 0일
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: bounded live read-only 관측 1회 통과 이력은 있으나 latest readiness는 stale
- Phase 2/3: 미시작
- 2026-08-28 decision ledger: 3,802행, complete lineage 3,802행, ratio 1.0
- 2026-08-28 data quality: raw market session coverage 97.5959%, feature closed coverage 97.4872%, reconnect 28, storm 0, assessment `watch`
- 2026-08-28 challenger: LightGBM 거래 1건, net `-0.757017%`; active 유지
- E7 탐색 기준선: LightGBM threshold 0.55, 76행/9거래일, 신호행 합 `+13.073707%p`; portfolio 수익 증거 아님

## 활성 체크리스트

- [x] 정규장 `serving_decision_ledger`와 prediction artifact lineage 축적
- [x] baseline 판단, gate, allocator, 현금·보유·pending, 주문·체결 결과 연결
- [x] 비정상 호가 fail-closed와 broker 상태 snapshot 중복 적재 차단
- [x] data-quality에 coverage, complete lineage, reconnect/storm, 공통 gap 보고
- [x] `15:20~15:29 KST` 예상 종가 동시호가 market gap을 unexpected gap과 분리
- [x] reconnect가 있어도 storm 0·coverage 95% 이상·lineage 100%이면 수집과 연결 주의를 분리
- [x] Phase 0 full-period account activity 22페이지/329행과 pagination 완결 확보
- [x] broker-only 9행을 확인하고 2026-08-15 clean baseline 생성
- [x] Phase 0 history를 clean baseline 이전/이후 epoch로 분리
- [ ] 현재 Phase 0 epoch의 유효 거래일 10개를 모두 matched로 확인
- [x] E1 후보 0/3, E5 second interval 미재현으로 기존 가설 기각
- [x] hold-rescue 기본값을 15분/2.0%/15:20으로 통일하고 no-op threshold 선택 차단
- [x] buy-avoid의 절대 portfolio 손실을 근거로 기각 유지
- [x] E7 LightGBM buy-rescue 미래 검증을 threshold 0.55와 고정 기준으로 사전등록
- [ ] 2026-08-31 이후 E7 최소 10거래일/100 episode/5종목 확보
- [ ] E7 decision-episode portfolio replay와 층화 same-count random control 1,000회 실행
- [ ] E7 2배 비용, 일별 일관성, 집중도, 최대 낙폭, 비중복 두 번째 구간 판정
- [ ] fresh Phase 1b read-only readiness와 실제 WebSocket recovery evidence 확보

## E7 통과 기준

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
