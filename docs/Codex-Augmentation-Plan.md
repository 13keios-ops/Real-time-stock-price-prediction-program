# Codex Augmentation Plan

## 역할

이 문서는 Codex를 개발 보조와 운영 점검에 어떻게 붙일지 정리하는 reference 문서다.

## 현재 기준

- Codex는 코드 보조, 문서 점검, 로그 리뷰, 개선 제안에 사용
- 프로그램 내부 기능보다 외부 보조 루프 성격이 더 강함
- 로컬 활동 기록은 `runtime-data/` 아래에 남김
- Codex가 확인할 주요 산출물
  - runtime report
  - backtest report
  - walk-forward report
  - watcher state와 app log

## 현재 보류

- 프로그램 내부에 OpenAI 호출을 상시 내장하는 구조는 아직 보류
- 자동 전략 변경이나 실전 주문 연동은 금지
