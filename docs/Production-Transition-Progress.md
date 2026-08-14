# Production Transition Progress

이 문서는 실전 전환 단계와 blocker만 빠르게 확인하는 현재 진행판이다.
과거 상세 스냅샷은 `docs/archive/Production-Transition-Progress-through-20260712.md`에 보존한다.

## 1. 현재 결론

- 현재 기본 운용은 `paper`다.
- Phase 1b의 주문 없는 live 계좌 조회 준비는 통과했다.
- 현재 수익 후보는 `0개`다.
- Phase 2 실제 주문 canary는 시작하지 않는다.
- 2026-08-09 E1/E5 명시 실행도 snapshot timeout으로 안전 종료됐다. 주문·네트워크 호출은 0회이며 유효 연구 결과는 아직 없다.
- 2026-08-07 수집은 raw/feature coverage 97.5%, decision lineage 100%로 정상이다. WebSocket reconnect 29회는 별도 주의다.

## 2. Phase 상태

### 설계 기준

- 상태: 완료
- 근거: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`

### Phase 0: paper + KIS 모의계좌

- 상태: 진행 중
- 과거 기준선 최근 10거래일 누적: `10/10`, matched/mismatch `0일/10일` 미통과 이력 보존
- 새 기준선: 2026-08-15 00:20 KST clean baseline 생성, 즉시 mismatch/cash/total asset gap 0
- 새 기준선 유효 거래일: `0/10`
- 과거 mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 최신 KIS bounded 주문·체결 조회는 3일 범위에서 0행이다. 보관된 320건은 전체 계좌 활동이 아니라 과거 mirrored submission 증거다.
- full-period probe 범위: `2026-06-14~2026-08-14`, 로컬 mirrored submission 320건/20거래일
- 2026-08-14 새 명시 승인 30페이지 조회: 22페이지/329행/20거래일, pagination 완결, local submission 320개 연결, broker-only 9행, 주문·취소 0회
- 현재 root cause scope: `external_or_unlinked_broker_activity`
- 해소 상태: `clean_baseline_created_waiting_10_matched_days`
- clean baseline: 계좌 소유자 승인으로 완료. `SyncInitialCash`, 주문, 취소 없음
- 완료 전 조건: 새 기준선 이후 10개 유효 거래일 모두 matched; 자동 align 금지
- 완료 조건: 미러링 기간 전체 sanitized 계좌 활동 또는 계좌 소유자 승인 clean baseline 뒤 새 local baseline으로 divergence를 해소하고, 이후 10개 유효 거래일이 모두 정합

### Phase 1a: KIS 모의투자 read-only

- 상태: 1차 리허설 통과
- token, account snapshot, system clock, dashboard/readiness 흐름 확인

### Phase 1b: 실전계좌 bounded read-only

- 상태: 제한 관측 1회와 전용 readiness 통과
- live token 1회, paper/live account 각 1페이지, live clock quote 1회로 제한
- system clock skew: `0.533151초`, 허용 2초 이내
- `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, 주문 메서드 미노출 유지
- 의미: 실전계좌 조회 연결 준비 통과
- 의미하지 않는 것: 수익성 통과, 주문 허용, Phase 2 승인

### Phase 2: 실전 1종목 소액 canary

- 상태: 미시작
- blocker: Phase 0, 양수 수익 후보, real WS recovery, fresh market status, 유효 kill switch OFF

### Phase 3: 다종목 일일 한도

- 상태: 미시작
- 조건: Phase 2 최소 20~60거래일 운영 안정성 증거

## 3. 데이터와 판단 원장

- 2026-08-07 raw market/orderbook: 804,435/641,766행
- raw market/orderbook symbol-minute: 3,815/4,059
- minute bar/feature: 3,803/3,803
- closed-minute feature coverage: 97.5128%
- decision ledger: 3,803행, complete lineage 3,803행, ratio 1.0
- shadow lineage: 7,606/7,606
- WebSocket: reconnect 29, storm 0. no-close-frame 28, no-frame timeout 1
- 판정: 수집과 판단 계보는 정상, 연결 안정성은 주의
- 다음 거래일부터 live runtime 현재/peak RSS를 status/watchdog 증거에 포함한다.

## 4. 모델과 수익성

- active h15: `baseline-h15-v1`
- challenger action: `keep_active`
- promotion applied: `false`
- 현재 통과한 수익 후보: `0개`
- active baseline 평가는 31건의 작은 표본이고 3분류 정확도 `0.267826`이므로 겹치는 거래 수익률 합 `+20.458524%p`를 수익 후보로 쓰지 않는다.
- LightGBM challenger는 5건 합산 `-5.218279%p`다.
- buy-avoid, buy-rescue, hold-rescue는 모두 현행 비용 후 절대 수익성이 음수다.
- 유효 E1/E5 결과 전 threshold/EV 반복 탐색을 하지 않는다.
- 이후 연구도 실현 p75 미래변동을 entry 필터로 쓰지 않는다. entry 시점 정보만 사용하는 저빈도 비용여유 후보, h60 별도 트랙, entry/exit 분리 가설을 같은 portfolio replay·random control·비중복 구간으로 비교한다.

## 5. 현재 P0

1. Phase 0 clean baseline 이후 새 기준선의 10개 유효 거래일 모두 정합
2. WebSocket reconnect 47/storm 19와 15:01~15:29 공통 market 공백 재발 여부, real recovery evidence
3. E1/E5 유효 결과 확보. 다음 명시 실행부터 대형 DB snapshot은 repo-local D드라이브 물리 저장소와 token별 partial 정리를 사용
4. 비용 후 양수 entry 후보와 독립 exit 후보를 동일 portfolio replay에서 검증
5. 당일 fresh market status와 유효 kill switch OFF
6. 26GB 운영 DB의 보존·집계 비용 관리

## 6. 동결 범위

E1/E5 유효 결과와 Phase 0 해소 경로가 정해지기 전에는 threshold/EV, 종목별·h60 주문 정책, active model/gate, rescue/avoid 주문 반영을 바꾸지 않는다.

운영 장애, 데이터 누락, lineage 저장 오류, snapshot 원자성, 관측 리포트 수정은 동결 대상이 아니다.

## 7. 운영자 작업

현재 즉시 필요한 수동 작업은 없다.
Phase 0 clean baseline은 승인·실행 완료됐다. E1/E5 재실행, 자격정보, market status, kill switch OFF, NAS 백업은 해당 단계에서만 별도 요청한다.

## 8. 종료 체크

- 실제 상태 파일을 확인했는가
- 현재 수익 후보 유무를 명시했는가
- Phase 통과와 단순 구현 완료를 구분했는가
- 주문 정책과 안전 flag를 건드리지 않았는가
- `docs/STATUS.md`, `docs/SPRINT_CURRENT.md`, `docs/logbook.md`를 동기화했는가
