# 외부 벤치마크 검토

## 역할

이 문서는 외부 유사 구조와 비교해 현재 프로젝트의 빈칸을 찾기 위한 참고 문서다.

## 현재 판단

- `수집 -> 특징 생성 -> 학습 -> 평가 -> 모의 검증` 구조는 타당하다.
- 현재 가장 큰 남은 과제는 실시간 WebSocket 실수신 검증이다.
- 그 다음은 더 강한 challenger 모델 비교와 rolling retrain 강화다.

## 계속 유지할 교훈

- signal과 order를 분리한다.
- portfolio와 reconciliation을 별도 계층으로 유지한다.
- runtime report와 backtest report를 함께 봐야 한다.
