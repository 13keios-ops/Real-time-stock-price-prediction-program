# Machine Learning Operations Plan

## 역할

머신러닝 학습, 평가, 재학습, 모델 교체 기준을 설명하는 참고 문서다.
현재 상태와 최신 수치는 `docs/logbook.md`와 `docs/Current-Implementation.md`를 기준으로 본다.

## 현재 추천 운영 방식

- 운영용 메인 모델은 `LightGBM` 으로 간다.
- `baseline`, `centroid`, `linear-score` 는 보조 모델과 비교 기준으로 유지한다.
- 장중에는 `추론` 중심으로 돌리고, 장후에는 `재학습` 중심으로 돌린다.
- 학습창은 `최근 60거래일 + 오늘 데이터` 를 기본으로 쓴다.
- 예측 수평선은 우선 `15분`, 이후 `60분`으로 확장한다.
- 모델 자체보다 `데이터 품질`, `라벨 정의`, `walk-forward 검증`을 먼저 고정한다.

## 데이터 기준

- 입력 데이터는 raw tick, orderbook, minute bar, feature, label 흐름으로 정리한다.
- 학습용 데이터는 SQLite canonical 저장본을 기준으로 만든다.
- synthetic 데이터는 로컬 파이프라인 검증용이고, 실전 기준 평가는 실제 수집 데이터로 다시 검증한다.
- 학습 입력은 아래처럼 나눈다.
  - 느린 특징: 최근 60거래일의 추세, 변동성, 거래대금, 이동평균 이격, 고점/저점 거리
  - 빠른 특징: 장중 1분 수익률, 호가 불균형, 스프레드, VWAP 이격, 장중 누적 거래량 비율
  - 이벤트 특징: 뉴스, 공시, 검색량, 반응 지표
- 장중 late row는 미래 라벨이 아직 안 생기면 즉시 학습에 넣지 않고, 라벨이 닫힌 뒤 다음 재학습 회차에서 반영한다.

## 데이터 보관 기준

- `최근 60거래일 + 오늘 데이터` 는 운영용 학습창 기준이다.
- 이보다 오래된 데이터는 버리지 않는 것을 기본으로 한다.
- 추천 보관 계층은 아래와 같다.
  - hot: 최근 60거래일 + 오늘 데이터
    - active 학습, 장중 추론 보조, 장후 재학습
  - warm: 최근 6개월~12개월
    - challenger 비교, walk-forward 확장, drift 점검, 구간 비교
  - cold: 그 이전 데이터
    - 재현, 회귀 검증, 구조 변경 전후 비교, 장애 분석
- 저장 공간이 허용되면 raw 데이터와 가공 데이터 모두 보관하고, 학습에만 rolling window 를 적용한다.
- 즉, `학습창은 롤링`, `데이터 저장은 보존`이 기본 원칙이다.

## 모델 선정 사유

### 메인 모델: LightGBM

- 표 형태 수치 특징에 강하다.
- 학습 속도가 빠르다.
- 비교적 적은 데이터에서도 안정적으로 시작할 수 있다.
- 비선형 관계를 잘 잡는다.
- 특징 중요도와 기여도를 보기 쉽다.
- 장후 재학습 자동화에 운영 비용이 낮다.

### 보조 모델: baseline / centroid / linear-score

- `baseline`
  - 규칙 기반 기준선으로 쓰기 쉽다.
  - 파이프라인이 깨졌는지 빠르게 확인하기 좋다.
- `centroid`
  - 간단하고 해석이 쉽다.
  - 데이터가 적은 초기 단계에서 안정적인 비교 기준이 된다.
- `linear-score`
  - 특징 가중치 기반의 얕은 모델이라 디버깅이 쉽다.
  - LightGBM 과 규칙 모델 사이의 중간 기준선으로 적합하다.

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
  - 장후 재학습 기준에서 `review_required` 없이 통과할 것

## 일중/일후 운영 기준

- 장중
  - 실시간 수집
  - 특징 생성
  - 현재 active model 추론
  - signal / paper trading / report 기록
- 장후
  - 오늘 데이터까지 포함해 feature / label 갱신
  - 최근 60거래일 + 오늘 데이터로 재학습
  - backtest
  - walk-forward
  - challenger 비교
  - 통과 모델만 다음 세션 후보로 반영

## 추천 확장 순서

1. 15분용 / 60분용 모델 분리
2. feature importance 기록
3. drift 감지
4. 텍스트 이벤트 특징 추가 강화
5. 필요 시 더 복잡한 시계열 딥러닝 검토

## 다음 확장 후보

- LightGBM 15분 학습 파이프라인 구현 완료
- LightGBM 승격 기준 고도화
- LightGBM 전용 walk-forward 비교
- 다중 challenger 비교
- feature 중요도 기록
- drift 감지
- 재학습 주기 자동화
- paper trading 결과와 학습 결과 연결 리포트

## 현재 구현 메모

- `python -m app --train-lightgbm --horizon-min 15` 로 LightGBM artifact를 만들 수 있다.
- 이 학습은 현재 기본값으로 active model을 자동 교체하지 않는다.
- active model은 `python -m app --set-active-builtin --builtin-model baseline --horizon-min 15` 같은 명시적 명령이나 challenger promotion으로만 바뀐다.
- 따라서 현재 운영 posture는 `baseline active + latest LightGBM challenger` 이다.
