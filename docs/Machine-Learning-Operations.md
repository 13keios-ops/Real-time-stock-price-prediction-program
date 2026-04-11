# Machine Learning Operations Plan

## 역할

머신러닝 학습, 평가, 재학습, 모델 교체 기준을 설명하는 참고 문서다.
현재 상태와 최신 수치는 `docs/logbook.md`와 `docs/Current-Implementation.md`를 기준으로 본다.

## 현재 추천 운영 방식

- 시작 모델은 `centroid baseline`으로 유지한다.
- 이후 challenger 모델을 추가해 같은 데이터셋으로 비교한다.
- 예측 수평선은 우선 `15분`, 이후 `60분`으로 확장한다.
- 모델 자체보다 `데이터 품질`, `라벨 정의`, `walk-forward 검증`을 먼저 고정한다.

## 데이터 기준

- 입력 데이터는 raw tick, orderbook, minute bar, feature, label 흐름으로 정리한다.
- 학습용 데이터는 SQLite canonical 저장본을 기준으로 만든다.
- synthetic 데이터는 로컬 파이프라인 검증용이고, 실전 기준 평가는 실제 수집 데이터로 다시 검증한다.

## 평가 기준

- 단일 accuracy만 보지 않는다.
- 아래 지표를 함께 본다.
  - label 분포
  - signal 발생 수
  - backtest 거래 수
  - 누적 순수익률
  - walk-forward 구간별 일관성
- 거래가 거의 발생하지 않는 모델은 accuracy가 높아도 운영 후보로 올리지 않는다.

## 모델 교체 기준

- champion은 현재 active model이다.
- challenger는 같은 데이터셋과 같은 검증 절차에서 비교한다.
- challenger가 아래를 만족할 때만 active 교체 후보로 본다.
  - walk-forward 결과가 champion보다 안정적일 것
  - 거래 수가 지나치게 줄지 않을 것
  - 신호 품질이 특정 구간에만 치우치지 않을 것

## 다음 확장 후보

- 다중 challenger 비교
- feature 중요도 기록
- drift 감지
- 재학습 주기 자동화
- paper trading 결과와 학습 결과 연결 리포트
