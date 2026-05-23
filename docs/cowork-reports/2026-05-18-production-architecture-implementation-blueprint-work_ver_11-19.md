# Codex work_ver_11-19: market data freshness submit guard hook

## 목적

2026-05-18 장중 KIS WebSocket 반복 재연결을 확인한 뒤, 실전 구조가 같은 문제를 반복하지 않도록 `runtime running` 또는 `WS connected`와 별개인 주문 직전 데이터 신선도 hook을 추가했다.

## 변경

- `app/services/market_data_freshness.py`
  - 최신 체결 tick, 호가 tick, 1분봉, 예측 timestamp의 age를 계산한다.
  - 누락, stale, future timestamp를 차단 사유로 반환한다.
- `app/services/live_order_guard.py`
  - `assert_can_submit()`에 선택적 `market_data_freshness_decision`과 `require_market_data_freshness_check`를 추가했다.
  - freshness decision이 차단이면 broker 호출 전 submit을 차단한다.
- `tests/test_market_data_freshness.py`
  - fresh, stale prediction, missing required input, future timestamp case를 잠갔다.
- `tests/test_live_order_guard.py`
  - stale freshness decision 차단과 필수 freshness check 누락 차단을 추가했다.
- `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`
  - 현재 구현 상태와 검증 결과를 반영했다.

## 검증

- `python -m unittest tests.test_market_data_freshness tests.test_live_order_guard`
  - 15개 통과.
- `git diff --check`
  - 통과. 기존 `docs/Current-Implementation.md`, `docs/logbook.md` CRLF 경고만 확인.

## 범위 밖

- runtime/report/dashboard 최신 row를 실제 freshness decision으로 조립하는 연결은 아직 하지 않았다.
- WebSocket keepalive 정책, cumulative/consecutive reconnect metric 분리, reconnect storm alert는 후속이다.
- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 자동 commit/push 없음.

## cowork 검토 질문

1. `trade_tick`, `orderbook_tick`, `minute_bar`, `prediction` 네 종류를 submit 전 필수 freshness 입력으로 보는 기본 방향이 충분히 보수적인가?
2. Phase 2에서는 `orderbook_tick`을 필수로 둘지, 초기에는 `require_orderbook=False`로 시작할 여지가 있는가?
3. default max age 후보 `trade/orderbook 30초`, `bar/prediction 120초`, future tolerance `2초`가 Phase 2 canary 기준으로 너무 느슨하거나 과한가?
