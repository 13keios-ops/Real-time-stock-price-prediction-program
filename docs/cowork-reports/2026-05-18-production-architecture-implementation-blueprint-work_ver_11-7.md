# Codex Work Ver 11-7

## 범위

P0-B live enable guard의 두 번째 방어선 보강입니다. 실제 runtime 주문 경로에 연결하지 않고, KIS client 위임 직전의 순수 wrapper와 정적 격리 테스트만 추가했습니다.

## 변경 내용

- `app/brokers/kis_live_order.py`
  - `KisLiveOrderAdapter` 추가.
  - 이미 생성된 KIS client를 감싸고, `submit_cash_order` 위임 직전에 아래 조건을 다시 확인합니다.
    - `TRADING_MODE=live`
    - `ALLOW_LIVE_ORDERS=true`
    - `profile_mode=live`
  - `cancel_order` 위임 직전에는 보호성 cancel-only 정책과 맞추기 위해 `TRADING_MODE=live`, `profile_mode=live`만 확인합니다.
  - import 또는 wrapper 생성만으로 KIS 네트워크를 호출하지 않습니다.
- `tests/test_kis_live_order_adapter.py`
  - submit/cancel 정상 위임.
  - `ALLOW_LIVE_ORDERS=false` 차단.
  - `profile_mode=paper` 차단.
  - `describe()`가 guarded adapter임을 표시하는지 검증.
- `tests/test_live_client_isolation.py`
  - `submit_cash_order`/`cancel_order` surface가 허용된 경계 안에만 있는지 정적으로 검사합니다.
  - 현재 허용 경계:
    - `app/brokers/kis_quote_rest.py`
    - `app/brokers/kis_live_order.py`
    - `app/services/broker_paper.py`
    - `app/services/live_order_manager.py`
- `README.md`, `docs/Current-Implementation.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`
  - 새 live order guarded adapter와 정적 surface lock 상태를 반영했습니다.

## 해석

이 변경은 “실전 주문이 가능해졌다”가 아닙니다. 반대로, live 주문 경로를 나중에 연결할 때 raw KIS client를 직접 쓰지 않고 guarded adapter를 끼우기 위한 사전 안전장치입니다.

## 검증

- `python -m py_compile app/brokers/kis_live_order.py tests/test_kis_live_order_adapter.py tests/test_live_client_isolation.py`
- `python -m unittest tests.test_kis_live_order_adapter tests.test_live_client_isolation tests.test_live_readonly_guard`

## cowork에 확인받고 싶은 부분

1. KIS live order adapter를 `app/brokers/`에 두는 레이어 배치가 적절한지.
2. `ALLOW_LIVE_ORDERS=false`여도 보호성 cancel은 adapter에서 허용하는 현재 분리가 적절한지.
3. 정적 surface allowlist가 너무 빡빡해서 향후 합법적 adapter 추가를 방해하지 않는지.

## 안전 메모

- KIS live/paper API 신규 호출 없음.
- 실전 계좌 접근 없음.
- 운영 DB schema apply 없음.
- streaming runtime 연결 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.
