# Implementation Blueprint

## 역할

이 문서는 구현 단계를 설명하는 reference 문서다.

## 현재 구현 완료 축

- config 로더
- KIS auth / REST / WS parser
- SQLite runtime store
- minute bar, feature, label 생성
- centroid baseline 학습
- validation-tail backtest
- walk-forward backtest
- runtime report

## 현재 남은 큰 축

1. 실제 KIS WebSocket 장중 수신 검증
2. multi-model challenger 구조
3. 뉴스, 공시, 반응 데이터 파이프라인 본 구현
4. 대시보드 또는 운영 UI
