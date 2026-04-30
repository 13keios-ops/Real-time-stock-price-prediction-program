# 모의투자 검증 계획

## 역할

예측 결과를 모의주문으로 검증하는 절차와 평가 기준을 정리하는 참고 문서다.

## 목적

- 모델 예측과 실제 주문 정책을 분리해서 검증한다.
- accuracy가 아니라 실제 signal 품질과 포지션 성과를 함께 본다.

## 흐름

- prediction 생성
- signal filter 적용
- target position 계산
- paper order 생성
- fill / position / equity 기록
- runtime report와 backtest 결과 비교

## 검증 기준

- 거래 수가 충분한가
- 특정 시간대에만 편중되지 않는가
- backtest와 runtime 방향성이 크게 어긋나지 않는가
- 비용과 슬리피지 가정이 달라도 결과가 무너지지 않는가

## 현재 원칙

- 자동주문은 paper 계좌만 허용한다.
- live 키는 조회 중심으로 유지한다.
- 실전 전환 전에는 reconciliation과 replay 검증이 먼저 필요하다.
