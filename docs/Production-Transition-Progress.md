# Production Transition Progress

이 문서는 실전 전환 단계와 blocker만 빠르게 확인하는 현재 진행판이다.
과거 상세 스냅샷은 `docs/archive/Production-Transition-Progress-through-20260712.md`에 보존한다.

## 1. 현재 결론

- 현재 기본 운용은 `paper`, 실전 주문은 비활성이다.
- 현재 통과한 수익 후보는 `0개`, 수익화 판정은 `no_profitable_candidate`다.
- active h15는 `baseline-h15-v1`, challenger action은 `keep_active`, promotion은 `false`다.
- Phase 0 현재 계좌 epoch는 `paper-2026-09-03`이고, 이전 계좌 baseline 때문에 `baseline_review_required`, `0/10`이다.
- 과거 Phase 1b bounded read-only 관측은 연결 이력으로 통과했지만 latest readiness가 stale하므로 현재 Phase 2 증거가 아니다.
- Phase 2 실제 주문 canary는 시작하지 않는다.

## 2. Phase 상태

### 설계 기준

- 상태: 완료
- 근거: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`

### Phase 0: paper + KIS 모의계좌

- 상태: 진행 중, `baseline_review_required`
- 현재 계좌 epoch: `paper-2026-09-03`, 활성 `2026-09-03`, 만료 `2026-12-03`
- 갱신 경고: 30일 전 `2026-11-03`, 긴급 7일 전 `2026-11-26`
- 새 자격정보 token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` orderability 통과
- 자연 broker cash-order 성공: 아직 미관찰
- 2026-08-15 clean baseline은 이전 계좌 기준이라 현재 계좌와 호환되지 않음
- 현재 epoch: `0/10`, matched 0일, mismatch 0일, remaining 10일
- 이전 계좌 epoch: `10/10`, matched 0일, mismatch 10일
- 이전 full-period sanitized activity: 22페이지/329행/20거래일, pagination complete
- 이전 계좌 root cause: `external_or_unlinked_broker_activity`; 이후 account rejection은 계좌 만료가 유력 root cause
- 해소 상태: `current_account_baseline_approval_required`
- 계좌 hard rejection circuit과 failure lineage는 유지하며 local paper/E7 원장은 계속 쌓는다.
- 유효일 조건: 현재 계좌와 호환되는 baseline 뒤 post-close, broker snapshot available, 실제 mirrored submission 존재
- 무거래일과 weekend/holiday는 분모를 늘리지 않는다.
- 완료 조건: 현재 계좌 epoch 유효 거래일 10개가 모두 matched
- 자동 align, `SyncInitialCash`, 강제 거래는 금지

### Phase 1a: KIS 모의투자 read-only

- 상태: 1차 리허설 통과
- token, account snapshot, system clock, dashboard/readiness 흐름 확인

### Phase 1b: 실전계좌 bounded read-only

- 상태: 과거 제한 관측 1회 통과, 현재 evidence stale
- 과거 범위: live token 1회, paper/live account 각 1페이지, live clock quote 1회
- `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, 주문 메서드 미노출 유지
- latest readiness 생성 시각: 2026-07-11, 현재 승격 근거로 사용 불가
- 의미: 과거 조회 연결 성공 이력
- 의미하지 않는 것: 현재 readiness, 수익성 통과, 주문 허용, Phase 2 승인

### Phase 2: 실전 1종목 소액 canary

- 상태: 미시작
- blocker: Phase 0, 검증된 양수 수익 후보, fresh Phase 1b readiness, real WS recovery, fresh market status, 유효 kill switch OFF

### Phase 3: 다종목 일일 한도

- 상태: 미시작
- 조건: Phase 2 최소 20~60거래일 운영 안정성 증거

## 3. 데이터와 판단 원장

- 최신 거래일: `2026-09-02`
- raw market/orderbook symbol-minute: `3,815/4,060`
- raw market session coverage: `97.57%`; feature closed coverage: `97.54%`
- decision ledger: `3,804`행, complete lineage `3,804/3,804`, ratio `1.0`
- WebSocket: reconnect `28`, storm `0`, 사유는 모두 `no close frame received or sent`
- `15:20~15:29 KST` 공통 market gap은 forced-flat 뒤 예상 종가 동시호가 구간
- 판정: 수집과 판단 계보는 정상 범위, 연결 안정성은 `watch`

## 4. 모델과 수익성

- active h15: `baseline-h15-v1`
- top challenger: 3분류 정확도 `19.53%`, buy hit `20.96%`, 거래 `1,474건`, 누적 진단 순수익 `-363.07%`
- buy-avoid threshold 0.40: 손실 완화 진단은 양수지만 절대 portfolio가 음수라 기각
- hold-rescue threshold 0.40: 적용 37/eligible 161 lot, delta `-26,387원`
- buy-rescue: current overlay는 진단 전용이며 Cybos proxy도 buy-rescue 주문 반영을 권하지 않는다.
- E7은 미래 거래일 `3/10`, episode `0/100`, symbol `0/5`로 최소 표본 축적 중이다.
- 공식 evaluator/manifest는 일치하고 invalid mark는 0이다. 현행·2배 비용, random control 1,000회와 비중복 구간은 최소 표본 전까지 대기한다.
- 위 조건을 통과하기 전에는 active model, gate, threshold 설정, 주문 정책을 바꾸지 않는다.

## 5. 현재 P0/P1

### P0

현재 발견된 즉시 실전 위험 P0 결함은 없다. 실전 주문은 비활성이고 live runtime은 휴장 정지 상태다.

### P1

1. 현재 paper 계좌와 호환되는 Phase 0 clean baseline 미승인, 유효 거래일 `0/10`
2. 검증된 절대 양수 수익 후보 없음
3. Phase 1b latest readiness stale
4. real WebSocket recovery evidence 없음
5. reconnect 28회의 연결 안정성 추적 필요

## 6. 다음 순서

1. 계좌 소유자 승인 뒤 현재 paper 계좌 snapshot 기준 Phase 0 clean baseline을 생성한다.
2. 다음 거래일부터 coverage 95% 이상, lineage 100%, storm 0과 reconnect 추이를 함께 확인한다.
3. 호환 baseline 뒤 자연 broker submission이 있는 실제 유효일만 Phase 0에 누적한다.
4. E7 미래 표본이 최소 기준을 채우면 decision-episode portfolio/random-control을 실행한다.
5. E7 고정 평가 3회 실패 시 threshold 탐색 없이 h60 또는 entry/exit 분리 가설로 이동한다.
6. 모델 수익성과 Phase 0이 모두 통과한 뒤 fresh Phase 1b/readiness/WS recovery를 갱신한다.

## 7. 동결 범위

Phase 0 current epoch 10거래일 정합과 E7 미래 검증 전에는 threshold/EV, 종목별·h60 주문 정책, active model/gate, rescue/avoid 주문 반영, 실전 주문/취소를 바꾸지 않는다.

운영 장애, 데이터 누락, lineage 저장 오류, 관측 리포트 수정은 동결 대상이 아니다.

## 8. 운영자 작업

현재 필요한 수동 결정은 새 paper 계좌 snapshot 기준 Phase 0 clean baseline 생성 승인 여부다.
무거래일을 Phase 0 유효일로 만들기 위한 강제 주문은 하지 않는다. market status, kill switch OFF, NAS 백업은 해당 단계에서만 별도 요청한다.

## 9. 종료 체크

- 실제 상태 파일을 확인했는가
- 현재 수익 후보 유무를 명시했는가
- Phase 통과와 단순 구현 완료를 구분했는가
- 주문 정책과 안전 flag를 건드리지 않았는가
- `docs/STATUS.md`, `docs/SPRINT_CURRENT.md`, `docs/logbook.md`를 동기화했는가
