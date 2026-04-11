# Local Activity Logging

## 역할

이 문서는 로컬 활동 기록 구조를 정리하는 reference 문서다.

## 주요 기록 위치

- `runtime-data/logs/`
- `runtime-data/reports/runtime/`
- `runtime-data/reports/backtests/`
- `runtime-data/ml/`
- `runtime-data/autopush/`

## 원칙

- 사람이 바로 읽는 요약은 Markdown
- 프로그램 연계와 재처리는 JSON
- watcher와 app 로그는 분리
