# Production Transition Progress

이 문서는 실전 전환 단계와 blocker만 빠르게 확인하는 현재 진행판이다.
과거 상세 스냅샷은 `docs/archive/Production-Transition-Progress-through-20260712.md`에 보존한다.

## 1. 현재 결론

- 현재 기본 운용은 `paper`다.
- Phase 1b의 주문 없는 live 계좌 조회 준비는 통과했다.
- 현재 수익 후보는 `0개`다.
- Phase 2 실제 주문 canary는 시작하지 않는다.
- 다음 핵심 판정은 2026-07-20 장후 E1/E5다.

## 2. Phase 상태

### 설계 기준

- 상태: 완료
- 근거: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`

### Phase 0: paper + KIS 모의계좌

- 상태: 진행 중
- 최근 10거래일 누적: `6/10`
- matched/mismatch: `0일/6일`
- mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 원인 범위: local paper와 KIS order/fill 원장은 맞지만 KIS account snapshot이 다름
- 자동 align과 `SyncInitialCash`: 보류
- 완료 조건: 10개 유효 장후 거래일 모두 정합하고 현재 divergence 해소

### Phase 1a: KIS 모의투자 read-only

- 상태: 1차 리허설 통과
- token, account snapshot, system clock, dashboard/readiness 흐름 확인
- market status와 kill switch는 조회 전용 단계에서 비차단
- 증거가 stale하면 필요 시 다시 생성

### Phase 1b: 실전계좌 bounded read-only

- 상태: 제한 관측 1회와 전용 readiness 통과
- live token 1회, paper/live account 각 1페이지, live clock quote 1회로 제한
- system clock skew: `0.533151초`, 허용 `2초` 이내
- `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, 주문 메서드 미노출 유지
- 의미: 실전계좌 조회 연결 준비 통과
- 의미하지 않는 것: 수익성 통과, 주문 허용, Phase 2 승인

### Phase 2: 실전 1종목 소액 canary

- 상태: 미시작
- blocker: Phase 0, 양수 수익 후보, real WS recovery, fresh market status, 유효 kill switch OFF

### Phase 3: 다종목 일일 한도

- 상태: 미시작
- 조건: Phase 2 최소 20~60거래일 운영 안정성 증거

## 3. 모델과 수익성

- active h15: `baseline-h15-v1`
- challenger action: `keep_active`
- promotion applied: `false`
- 현재 통과한 수익 후보: `0개`
- LightGBM holdout 3분류 정확도: `0.346248`
- LightGBM 기본 방향 거래: 53건, 평균 `-0.348534%`, 누적 `-18.472324%p`
- 최신 walk-forward: 정확도 `0.414466`, 다수 클래스 기준 미달, 구형 비용 `0.108%` 증거

### Rescue/Avoid

- buy-avoid `0.40`: `-38.1734% -> -36.3645%`, random-control 역선별로 기각
- buy-rescue: Cybos proxy 비용 후 음수, KIS live no-trade ledger는 아직 0행
- hold-rescue `0.40`: 37건 적용, `-26,387원`, 후보 아님

세 항목 모두 관측/진단용이며 실제 주문과 모델 승격에 반영하지 않는다.

## 4. 현재 P0

1. 2026-07-20 장전 KIS approval-key 재시도와 complete lineage decision ledger 수집 정상화 확인 (2026-07-17 수집 공백 별도 기록)
2. 매 거래일 장후 Phase 0 정합성 유효 기록 누적
3. 2026-07-20 장후 E1/E5 사전등록 라운드 1회 실행
4. 신호 재현 시 h15 저빈도와 h60을 동일 portfolio replay로 비교
5. 실패 시 threshold 탐색을 중지하고 새 feature/source/horizon 가설 사전등록

## 5. 동결 범위

2026-07-20 판정 전에는 threshold/EV, 종목별·h60 주문 정책, active model/gate, rescue/avoid 주문 반영을 바꾸지 않는다.

운영 장애, 데이터 누락, lineage 저장 오류 수정은 동결 대상이 아니다.

## 6. 운영자 작업

현재 필요한 수동 작업은 없다.
자격정보 입력, market status 승인, kill switch OFF, NAS 백업은 해당 단계에서 명시적으로 필요할 때만 요청한다.

## 7. 종료 체크

- 실제 상태 파일을 확인했는가
- 현재 수익 후보 유무를 명시했는가
- Phase 통과와 단순 구현 완료를 구분했는가
- 주문 정책과 안전 flag를 건드리지 않았는가
- `docs/STATUS.md`, `docs/SPRINT_CURRENT.md`, `docs/logbook.md`를 동기화했는가
