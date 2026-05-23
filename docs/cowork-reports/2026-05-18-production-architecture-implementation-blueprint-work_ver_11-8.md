# Codex Work Ver 11-8

## 범위

P1-D alert false alarm 완화 보강입니다. 실제 외부 텔레그램/이메일 sender는 연결하지 않았고, outbox 생성 전 순수 helper 동작만 추가했습니다.

## 변경 내용

- `app/services/live_alerting.py`
  - `live_order_attention` payload에 `max_attention_age_minutes`와 `attention_grace_minutes`가 함께 있으면 grace window 안의 attention alert를 만들지 않습니다.
  - 조건: `max_attention_age_minutes < attention_grace_minutes`
  - 기본값은 0분이라 기존 report/outbox 동작은 그대로 유지됩니다.
- `tests/test_live_alerting.py`
  - grace window 안의 `unknown/stuck` attention이 alert로 올라가지 않는지 확인.
  - grace 이후에는 `live_order_attention` critical alert가 생성되는지 확인.
- `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`
  - alert fingerprint dedupe와 attention grace hook 구현 상태를 반영했습니다.

## 해석

이 grace hook은 확정 사고 억제용이 아닙니다. `live_fill_mismatch`, kill switch, DB/disk 장애 같은 사고는 그대로 즉시 alert 후보입니다. 대상은 막 생긴 `unknown/stuck` 주문 상태가 짧은 조회 지연 뒤 정상화되는 경우의 false alarm 완화입니다.

## 검증

- `python -m py_compile app/services/live_alerting.py tests/test_live_alerting.py`
- `python -m unittest tests.test_live_alerting`

## cowork에 확인받고 싶은 부분

1. Phase 2에서 `unknown/stuck` attention grace를 기본 몇 분으로 둘지. Codex 권장 후보는 1분입니다.
2. grace 적용 대상을 `unknown/stuck` 신규 attention으로만 제한하는 것이 적절한지.
3. fill mismatch, kill switch, DB/disk 장애를 grace 예외로 두는 정책이 충분히 보수적인지.

## 안전 메모

- 실제 외부 sender 연결 없음.
- KIS live/paper API 신규 호출 없음.
- 실전 계좌 접근 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.
