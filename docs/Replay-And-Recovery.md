# Replay And Recovery

## 역할

재시작, 연결 끊김, 장후 재생산 검증을 어떻게 처리할지 정리하는 참고 문서다.

## 목적

- runtime 흐름이 중간에 끊겨도 상태를 복원할 수 있게 한다.
- 장후 replay로 runtime 결과를 다시 계산해 차이를 찾는다.

## recovery 기본 원칙

- 시작 시 최근 상태를 먼저 읽는다.
- 수집이 끊겼다면 gap 여부를 남긴다.
- 복구 직후 곧바로 주문하기보다 warm-up 이후 정상 모드로 전환한다.

## replay 기본 원칙

- raw 이벤트를 기준으로 분봉, feature, prediction을 다시 계산한다.
- runtime 결과와 replay 결과 차이를 리포트에 남긴다.
- 차이는 무시하지 않고 원인 분류 대상으로 본다.

## 현재 연결점

- runtime-data 아래 raw 기록과 report 경로를 함께 사용한다.
- reconciliation, portfolio, signal policy 문서와 같이 읽는 것이 좋다.
