# Experiment Tracking

## 역할

이 문서는 실험 기록과 비교 기준을 정리하는 reference 문서다.

## 현재 기록 대상

- training run
- model evaluation
- validation-tail backtest
- walk-forward backtest
- active model registry

## 기록 위치

- SQLite: `ml_training_runs`, `ml_model_evaluations`
- 파일: `runtime-data/ml/`, `runtime-data/reports/backtests/`

## 다음 보강

- 실험 메모와 파라미터를 더 구조화
- challenger 비교 결과 포맷 추가
