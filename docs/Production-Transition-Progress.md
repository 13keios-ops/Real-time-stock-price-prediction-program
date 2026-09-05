# Production Transition Progress

이 문서는 실전 전환 단계와 blocker만 빠르게 확인하는 진행판이다. 최신 운영 수치와 incident는 `docs/STATUS.md`만 기준으로 한다.
과거 상세 스냅샷은 `docs/archive/Production-Transition-Progress-through-20260712.md`에 보존한다.

## 1. 현재 결론

- 현재 기본 운용은 `paper`, 실전 주문은 비활성이다.
- 현재 통과한 수익 후보는 `0개`, 수익화 판정은 `no_profitable_candidate`다.
- active h15는 `baseline-h15-v1`, challenger action은 `keep_active`, promotion은 `false`다.
- Phase 0 현재 계좌 epoch는 `paper-2026-09-03`이고, 2026-09-06 승인 clean baseline과 호환된다. 현재 `no_history`, `0/10`이다.
- 과거 Phase 1b bounded read-only 관측은 연결 이력으로 통과했지만 latest readiness가 stale하므로 현재 Phase 2 증거가 아니다.
- Phase 2 실제 주문 canary는 시작하지 않는다.

## 2. Phase 상태

### 설계 기준

- 상태: 완료
- 근거: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`

### Phase 0: paper + KIS 모의계좌

- 상태: 진행 중, `no_history`
- 현재 계좌 epoch: `paper-2026-09-03`, 활성 `2026-09-03`, 만료 `2026-12-03`
- 갱신 경고: 30일 전 `2026-11-03`, 긴급 7일 전 `2026-11-26`
- 새 자격정보 token refresh, 새 계좌 snapshot, `VTTC8908R/ORD_DVSN=00` orderability 통과
- 자연 broker cash-order: 2026-09-03 KIS submission 성공 36건; 이전 계좌 account-orderability blocker 종료
- 실패: invalid tick 4건은 `broker_invalid_request/invalid_price_tick`, network timeout 1건은 `broker_network_error`
- order-fill sync: 2026-09-05 장외 1회에서 3페이지/38행, submission 38/38 exact-linked, open 0/final 38/pending 0으로 완결
- 2026-09-06 승인 marker-only clean baseline 생성, 직후 mismatch/effective cash/total asset gap 0
- 현재 epoch: `0/10`, matched 0일, mismatch 0일, remaining 10일
- 이전 계좌 epoch: `10/10`, matched 0일, mismatch 10일
- 이전 full-period sanitized activity: 22페이지/329행/20거래일, pagination complete
- 이전 계좌 root cause: `external_or_unlinked_broker_activity`; 이후 account rejection은 계좌 만료가 유력 root cause
- 해소 상태: `baseline_complete_waiting_valid_days`
- 계좌 hard rejection circuit과 failure lineage는 유지하며 local paper/E7 원장은 계속 쌓는다.
- 유효일 조건: 현재 계좌와 호환되는 baseline 뒤 post-close, broker snapshot available, 실제 mirrored submission 존재
- 무거래일과 weekend/holiday는 분모를 늘리지 않는다.
- 완료 조건: 현재 계좌 epoch 유효 거래일 10개가 모두 matched
- 추가 자동 align, `SyncInitialCash`, 강제 거래는 금지
- 현재 local/new-broker position과 effective cash·total asset은 일치한다. 과거 원장과 이전 계좌 epoch는 삭제·reset하지 않는다.

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

## 3. 데이터·모델 증거 gate

최신 수집, lineage, WebSocket incident, 모델·E7 수치는 `docs/STATUS.md`가 소유한다. Phase 전환에는 완전한 lineage, 유효한 공식 evaluator/manifest, 최소 미래 표본, 비용 후 양수 수익 후보가 모두 필요하다. 이 조건을 통과하기 전에는 active model, gate, threshold, 주문 정책을 바꾸지 않는다.

## 4. 현재 P0/P1

### P0

2026-09-03 NOW-P0는 KRX invalid tick 전송과 storm/common-gap 심각도 누락이었다. 호가단위 정규화, failure reason, 재구독·첫 frame 증적, `CRITICAL/실패` 우선순위를 구현했다. 실전 주문은 비활성이며 다음 거래일 자연 paper 경로에서 재발 여부를 확인한다.

### P1

1. current account snapshot/reconciliation이 남아 local/new-broker position·cash 차이와 Phase 0 baseline 검토 보류, `0/10`
2. 검증된 절대 양수 수익 후보 없음
3. Phase 1b latest readiness stale
4. real WebSocket recovery evidence 없음
5. reconnect 36/storm 7의 다음 거래일 복구 증적과 공통 gap 재발 추적 필요

## 5. 다음 순서

1. current account snapshot과 reconciliation을 장외에서 1회 수행해 local/new-broker position·cash 차이를 설명한다.
2. 결과 보고 뒤 계좌 소유자의 별도 승인으로만 current account baseline을 검토한다.
3. 다음 거래일부터 tick rejection 재발 여부, coverage 95% 이상, lineage 100%, storm 0과 subscription/first-frame 복구 증적을 확인한다.
4. E7 미래 표본이 최소 기준을 채우면 decision-episode portfolio/random-control을 실행한다.
5. E7 고정 평가 3회 실패 시 threshold 탐색 없이 h60 또는 entry/exit 분리 가설로 이동한다.
6. 모델 수익성과 Phase 0이 모두 통과한 뒤 fresh Phase 1b/readiness/real WS recovery를 갱신한다.

## 6. 동결 범위

Phase 0 current epoch 10거래일 정합과 E7 미래 검증 전에는 threshold/EV, 종목별·h60 주문 정책, active model/gate, rescue/avoid 주문 반영, 실전 주문/취소를 바꾸지 않는다.

운영 장애, 데이터 누락, lineage 저장 오류, 관측 리포트 수정은 동결 대상이 아니다.

## 7. 운영자 작업

현재는 baseline 승인 단계가 아니다. current account snapshot/reconciliation 결과를 먼저 확인한 뒤 baseline 승인 여부를 별도로 결정한다.
무거래일을 Phase 0 유효일로 만들기 위한 강제 주문은 하지 않는다. market status, kill switch OFF, NAS 백업은 해당 단계에서만 별도 요청한다.

## 8. 종료 체크

- 실제 상태 파일을 확인했는가
- 현재 수익 후보 유무를 명시했는가
- Phase 통과와 단순 구현 완료를 구분했는가
- 주문 정책과 안전 flag를 건드리지 않았는가
- `docs/STATUS.md`, `docs/SPRINT_CURRENT.md`, `docs/logbook.md`를 동기화했는가
