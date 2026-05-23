# Codex Work Ver 11-9

## 범위

P0 계열의 시스템 시계 오차 판정 helper를 추가했습니다. 외부 NTP, KIS API, runtime DB에는 접근하지 않는 순수 로직입니다.

## 변경 내용

- `app/services/system_clock.py`
  - `evaluate_clock_skew()` 추가.
  - local timestamp와 reference timestamp 차이를 계산합니다.
  - 기본 후보 한도는 `±2초`입니다.
  - naive timestamp는 UTC로 정규화합니다.
- `tests/test_system_clock.py`
  - ±2초 이내 허용.
  - 2초 초과 차단.
  - naive timestamp 정규화.
  - custom limit으로 더 좁게 잡는 경로를 검증합니다.
- 기준 문서 갱신
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/Production-Architecture.md`
  - `docs/Production-Implementation-Blueprint.md`

## 해석

이 helper는 “현재 PC 시간이 정확하다”를 직접 증명하지 않습니다. 신뢰 가능한 reference timestamp가 다른 레이어에서 들어왔을 때, 주문/취소 전 차단 또는 readiness 판단에 쓸 수 있는 판정 로직입니다.

## 검증

- `python -m py_compile app/services/system_clock.py tests/test_system_clock.py`
- `python -m unittest tests.test_system_clock`

## cowork에 확인받고 싶은 부분

1. 기본 후보 `±2초`가 Phase 1/2 기준으로 적절한지.
2. reference timestamp 원천을 KIS 응답 timestamp, OS NTP 상태, 또는 별도 time API 중 어디로 잡을지.
3. skew 초과 시 신규 submit만 막을지, cancel도 막을지. Codex 권장안은 submit은 차단, 보호성 cancel은 사람이 확인 가능한 별도 경로로 보류입니다.

## 안전 메모

- 외부 네트워크 호출 없음.
- KIS live/paper API 신규 호출 없음.
- 실전 계좌 접근 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.
