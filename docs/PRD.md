# Product Requirements Document

## 역할

이 프로젝트가 무엇을 만들고 어떤 범위까지를 현재 목표로 삼는지 설명하는 참고 문서다.

## 제품 목표

- 국내 주식 실시간 데이터를 수집한다.
- 장중 데이터로 feature를 만들고 방향 예측을 수행한다.
- 예측을 paper trading에 연결해 품질을 검증한다.
- 결과를 runtime report와 backtest report로 정리한다.

## 현재 범위

- 로컬 연구용 프로그램
- 실시간 수집과 재현 가능한 연구 흐름
- paper trading 중심 검증
- live 주문은 기본 비활성화

## 포함 범위

- KIS 연동
- SQLite / JSONL 저장
- minute bar / feature / label
- baseline 모델 학습
- backtest / walk-forward
- runtime report

## 제외 범위

- 자동 실전 매매 기본 활성화
- 대규모 분산 인프라
- 무제한 종목 동시 처리
- 고빈도 초단타 최적화
