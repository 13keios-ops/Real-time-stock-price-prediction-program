# Architecture

## 역할

이 문서는 전체 시스템의 큰 흐름을 설명하는 reference 문서다.

## 현재 구조

1. `brokers`
   - KIS 인증, REST 조회, WebSocket 연결
2. `collectors`
   - 외부 응답을 내부 이벤트 형식으로 변환
3. `storage`
   - JSONL과 SQLite에 raw, curated, serving 데이터를 기록
4. `features`와 `labels`
   - minute bar, feature snapshot, 라벨 생성
5. `models`
   - baseline, centroid, registry, loader
6. `services`
   - research, streaming, reporting, orchestration
7. `paper_trading`, `portfolio`, `risk`
   - 신호, 포지션, 리스크 게이트, paper 상태 관리

## 기본 데이터 흐름

`KIS -> raw ticks/orderbook -> minute bars -> features/labels -> training/backtest -> online prediction -> signal -> target -> paper order/fill -> report`

## 현재 판단

- 구조 방향은 맞다
- 이제는 설계 추가보다 실제 실시간 검증과 모델 확장이 중요하다
