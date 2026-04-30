# 주문 생명주기

## 역할

모의주문과 향후 실주문 확장에 필요한 주문 상태 전이 기준을 정리하는 참고 문서다.

## 상태 흐름

- `created`
- `queued`
- `sent`
- `acknowledged`
- `partially_filled`
- `filled`
- `cancelled`
- `rejected`
- `recovery_pending`

## 기본 원칙

- 주문은 상태 전이와 이벤트 로그를 함께 남긴다.
- 재시작 이후에도 같은 주문을 추적할 수 있어야 한다.
- 중복 주문 방지를 위해 idempotency key 또는 유사한 식별 기준을 둔다.

## 현재 구현 기준

- 현재는 paper trading 중심으로 주문/체결/포지션 흐름을 기록한다.
- 실전 주문은 기본 비활성화 상태를 유지한다.
- 실계좌 확장은 이 상태 흐름을 그대로 따라가야 한다.

## 확인 포인트

- partial fill 지원
- reject 사유 기록
- recovery 시 재조정 규칙
- signal과 order 간 연결 식별자 유지
