# External Benchmark Review

## 역할

이 문서는 외부 유사 구조와 비교해 현재 프로젝트의 빈칸을 찾기 위한 reference 문서다.

## 현재 판단

- `수집 -> feature -> 학습 -> 평가 -> paper 검증` 구조는 타당함
- 현재 가장 큰 남은 과제는 실시간 WebSocket 실수신 검증
- 그 다음은 richer model challenger 비교와 rolling retrain 강화

## 계속 유지할 교훈

- signal과 order를 분리
- portfolio와 reconciliation을 별도 계층으로 유지
- runtime report와 backtest report를 함께 봐야 함
