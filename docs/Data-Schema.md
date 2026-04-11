# Data Schema

## 역할

이 문서는 SQLite와 논리 스키마 기준을 정리하는 reference 문서다.

## 현재 저장 범위

- raw: market ticks, orderbook ticks
- curated: minute bars
- feature: inputs, labels
- serving: predictions, trade signals, target positions
- paper: orders, order events, fills, positions, portfolio snapshots
- ops: risk events, reconciliation runs, replay runs
- ml: training runs, model evaluations

## 현재 코드 기준

실제 로컬 저장 구현은 `app/storage/sqlite_store.py`와 `app/storage/runtime_writer.py`가 맡는다.

## 다음 보강

- SQLite와 migration SQL의 차이를 더 줄이기
- 필요 시 evaluation 전용 요약 테이블 추가
