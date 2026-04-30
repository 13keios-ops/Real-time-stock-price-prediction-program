# 실시간 운영 계획

## 역할

실시간 수집과 장중 운용 시 어떤 순서와 점검 기준으로 프로그램을 돌릴지 정리하는 참고 문서다.

## 기본 흐름

- 인증 확인
- watchlist 확정
- 시세 수집 시작
- 원시 저장 확인
- minute bar 생성
- online prediction / signal 처리
- paper trading 기록
- 실행 리포트 생성

## 장중 점검 항목

- API 응답 실패 여부
- raw tick 누락 급증 여부
- minute bar 생성 지연 여부
- signal 발생 수 급감 여부
- position / equity 기록 이상 여부

## 장후 점검 항목

- reconciliation 실행
- replay 비교
- report 생성
- 다음 학습 후보 데이터 정리

## 운영 원칙

- 실시간 수집이 불안정하면 전략 튜닝보다 수집 안정화가 우선이다.
- 장중에는 변경을 줄이고, 장후에 구조 개선과 파라미터 조정을 검토한다.
