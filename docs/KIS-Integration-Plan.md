# KIS Integration Plan

## 역할

이 문서는 한국투자 API 연동 기준을 정리하는 reference 문서다.

## 현재 구현 상태

- token 발급
- approval key 발급
- 현재가 REST
- 호가 REST
- WebSocket 구독 메시지 생성
- WebSocket frame 파싱
- reconnect 인자 지원

## 현재 남은 검증

- 실제 장중 수신 검증
- reconnect 상황에서의 운영 로그 확인
- 실전 키와 모의 키를 섞지 않는 운영 점검
