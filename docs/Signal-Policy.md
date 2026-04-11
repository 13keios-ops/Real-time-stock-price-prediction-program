# Signal Policy

## 역할

예측 확률을 어떤 기준으로 signal과 target position으로 바꿀지 정리하는 참고 문서다.

## 기본 원칙

- prediction과 order는 직접 연결하지 않는다.
- signal은 예측을 한 번 더 걸러낸 결과다.
- target position은 signal을 실제 보유 목표로 바꾼 결과다.

## 현재 추천 방향

- 15분 수평선 기준 signal을 우선 사용한다.
- 60분 신호는 보조 확인값으로 붙인다.
- 지나치게 약한 확률 차이는 signal로 채택하지 않는다.
- 장 시작 직후와 마감 직전에는 신규 진입을 제한한다.

## 검증 포인트

- signal 수가 너무 적지 않은가
- 특정 종목만 과도하게 signal을 내지 않는가
- backtest와 runtime에서 기준이 동일한가
- 거래비용 반영 후에도 의미가 남는가
