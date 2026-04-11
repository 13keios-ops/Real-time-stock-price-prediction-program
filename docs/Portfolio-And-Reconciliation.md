# Portfolio And Reconciliation

## 역할

신호를 바로 주문으로 보내지 않고 목표 포지션을 거치는 구조와, 런타임 결과를 비교 검증하는 절차를 정리하는 참고 문서다.

## 포트폴리오 계층

- signal은 방향성 제안이다.
- target position은 실제 보유 목표다.
- order는 target position을 맞추기 위한 실행 수단이다.

## reconciliation 목적

- prediction, signal, target, order, fill, position 사이의 연결이 맞는지 확인한다.
- backtest, replay, runtime, broker 상태 차이를 추적한다.

## 현재 권장 체크

- 주문 수와 체결 수 차이
- 포지션 수량 불일치
- cash / equity 계산 차이
- replay 결과와 runtime 결과 차이
- 일자별 누락 이벤트 존재 여부

## 운영 원칙

- 하루가 끝나면 최소 한 번 reconciliation을 남긴다.
- 차이가 생기면 원인 분류를 먼저 한다.
  - 데이터 누락
  - 계산 규칙 차이
  - 주문 상태 처리 차이
  - 시간대 처리 차이
