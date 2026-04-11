# Project Roadmap

## 역할

프로젝트를 어떤 단계로 진행할지 큰 순서를 설명하는 참고 문서다.

## 단계

1. 문서와 기준선 정리
2. KIS 연동과 raw 저장 구현
3. minute bar / feature / label 구현
4. baseline 학습과 backtest 구현
5. walk-forward와 runtime report 구현
6. 실제 KIS WebSocket 장중 검증
7. challenger 모델 비교
8. NLP 이벤트 확장

## 현재 위치

- 1단계부터 5단계까지는 기본 골격이 구현되어 있다.
- 6단계와 7단계가 다음 핵심 작업이다.

## 중기 목표

- 실제 장중 WebSocket 수신 검증
- 다중 모델 비교와 active model 선택 자동화
- reconciliation / replay 강화
- paper trading 보고 체계 보강
