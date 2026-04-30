# 구현 청사진

## 역할

이 문서는 구현 단계를 설명하는 참고 문서다.

## 현재 구현 완료 축

- config 로더
- KIS 인증 / REST / WebSocket parser
- SQLite 실행 저장소
- 분봉, 특징, 라벨 생성
- centroid baseline 학습
- 검증 꼬리구간 백테스트
- 워크포워드 백테스트
- 실행 리포트

## 현재 남은 큰 축

1. 실제 KIS WebSocket 장중 수신 검증 안정화
2. 다중 모델 challenger 구조 고도화
3. 뉴스, 공시, 반응 데이터 파이프라인 본 구현
4. 대시보드와 운영 UI 지속 개선
