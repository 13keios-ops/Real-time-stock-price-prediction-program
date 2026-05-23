# 계좌 소유자/실전 운용 승인권자 결정 기록

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 관련 작업본: `work_ver_3`
- 기록일: 2026-05-14

## 결정 1: Slice 1 코드 작업 시작

- 결정값: 승인
- 허용 범위: `KisReadOnlyClient`, read-only wrapper 테스트, isolation 테스트
- 금지 유지:
  - 실전 주문 연결 금지
  - `ALLOW_LIVE_ORDERS` 변경 금지
  - `app/risk/` 변경 금지
  - gate 기준값 변경 금지
  - `VERSION` 변경 금지
- Codex 권장안: 승인
- 상태: 결정 완료
- 실행 결과:
  - `app/brokers/kis_readonly.py` 추가
  - `tests/test_live_readonly_guard.py`, `tests/test_live_client_isolation.py` 추가
  - targeted unittest와 전체 unittest 통과

## 결정 2: Phase 2 손실 한도와 슬리피지 budget

- 결정값:
  - Phase 2 보수 모드 첫 20거래일:
    - 1일 최대 손실: `min(운용 배정금 A의 1%, 30,000원)`
    - 종목별 최대 손실: `min(운용 배정금 A의 0.5%, 20,000원)`
  - Phase 2 기본 모드:
    - 1일 최대 손실: `min(운용 배정금 A의 2%, 50,000원)`
    - 종목별 최대 손실: `min(운용 배정금 A의 1%, 30,000원)`
  - 슬리피지 budget: Codex 권장안 채택
- Codex 슬리피지 권장안:
  - 일반 신규/청산 지정가 주문: warning 10 bps, hard budget 20 bps
  - 단, KRX 호가단위 때문에 실제 주문 가격 제한은 `max(1 tick, 10 bps)` warning, `max(2 ticks, 20 bps)` hard 기준으로 계산
  - realized adverse slippage가 hard budget을 넘으면 당일 해당 종목 신규 주문 차단 후보
  - 하루 중 realized adverse slippage hard violation이 2회 이상이면 당일 신규 주문 전체 차단 후보
  - 비상 청산은 일반 슬리피지 budget과 분리해 사고 리포트에 별도 기록
- 상태: 결정 완료

## 결정 3: 비상 청산 시장가 예외

- 결정값: Codex 권장안 채택
- 정책:
  - Phase 2 신규 진입은 지정가 only
  - 시장가는 기본 금지
  - 비상 청산 시장가는 청산 건별 수동 승인 후보
  - kill switch 발동 사유별 자동 fallback은 별도 검토
- 상태: 결정 완료

## 결정 4: VI 발동 중 open 주문 처리

- 결정값: Codex 권장안 채택
- 정책:
  - VI 발동 중 신규 주문 금지
  - 기존 open 주문은 조회 보류
  - 잔량 취소는 cancel-only guard 통과 후 허용 후보
  - KIS가 VI 중 미체결 주문을 어떤 상태로 반환하는지는 확인 필요
- 상태: 결정 완료

관련 문서/코드 경로: `docs/Production-Implementation-Blueprint.md`, `docs/Production-Architecture.md`, `docs/cowork-reports/README.md`
