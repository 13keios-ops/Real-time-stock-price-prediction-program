# Codex work_ver_12-1: WS reconnect metric + Phase 2 1주 제한

작성: Codex
기준 리뷰: `2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`
상태: 2026-05-19 장후 `post-close`, live runtime 정지 확인 후 코드 보강

## 1. 작업 요약

review_ver_11에서 Phase 1 전 P0/P1로 남긴 항목 중 두 가지를 먼저 코드로 좁게 반영했다.

- KIS WebSocket reconnect metric helper를 추가했다.
- Phase 2 기본 부모 주문 수량 제한을 `max_order_qty=1`로 추가했다.
- 실전 주문 활성 플래그, gate 기준값, `app/risk/`, `config/`, `VERSION`은 수정하지 않았다.
- KIS live/paper API 호출, 운영 DB schema apply, runtime restart는 하지 않았다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| KIS WebSocket reconnect metric | `KisWebSocketQuoteClient.listen()`은 누적 reconnect 횟수와 warning log만 갖고, 연속 reconnect storm 여부를 외부에서 읽기 어려웠다. | `KisWebSocketReconnectMetrics`와 snapshot을 추가해 누적 reconnect, 연속 reconnect, 안정 frame 수신 후 reset, storm 판정, optional `metrics_callback`을 제공한다. callback 예외는 warning으로 흡수해 관측 실패가 quote stream을 끊지 않게 했다. | `app/brokers/kis_quote_ws.py`, `tests/test_kis_ws_reconnect_metrics.py` | `listen()` 시그니처에 optional 인자가 늘었다. 기본값이 `None`이라 기존 호출은 유지된다. `max_reconnects`는 기존 누적 기준 그대로 둔다. |
| Phase 2 부모 주문 수량 제한 | Phase 2는 1일 1개 부모 주문서와 금액 한도는 막았지만, 저가 종목에서 2주 이상 주문되는 경우를 별도로 막지 않았다. | Phase 2 기본 `max_order_qty=1`을 두고, 부모 주문 수량이 1주를 넘으면 broker 호출 전 `phase2_order_qty_limit_exceeded`로 `blocked` 처리한다. | `app/services/live_order_manager.py`, `tests/test_live_order_manager.py`, `docs/Production-Implementation-Blueprint.md` | Phase 2에서 정상적인 2주 테스트 주문도 기본값으로는 막힌다. 후속 phase나 명시 테스트는 `order_policy.max_order_qty` 또는 `max_qty`로 조정 가능하다. |

## 3. 코드 기준 확인

- `app/brokers/kis_quote_ws.py`
  - `KisWebSocketReconnectSnapshot`
  - `KisWebSocketReconnectMetrics`
  - `stable_frame_reset_threshold`
  - `reconnect_storm_threshold`
  - `metrics_callback`
  - callback 예외 warning 흡수
- `app/services/live_order_manager.py`
  - `PHASE2_DEFAULT_MAX_ORDER_QTY = 1`
  - `LivePreSubmitPolicy.max_order_qty`
  - `phase2_order_qty_limit_exceeded`

## 4. 검증

실행 완료:

```bash
python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_live_order_manager tests.test_live_order_guard
python -m py_compile app/brokers/kis_quote_ws.py app/services/live_order_manager.py tests/test_kis_ws_reconnect_metrics.py tests/test_live_order_manager.py
git diff --check
```

결과:

- `tests.test_kis_ws_reconnect_metrics`, `tests.test_kis_ws_parser`, `tests.test_kis_ws_verification`, `tests.test_live_order_manager`, `tests.test_live_order_guard`: 39개 테스트 통과.
- 대상 파일 `py_compile` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.

## 5. 남은 후속

🟢 다음 단계 권장:

- KIS WebSocket reconnect snapshot을 readiness dry-run과 dashboard 카드에 read-only로 노출한다.
- `snapshot_from_kis_daily_order_fill()`이 실제 KIS 모의투자 raw fixture와 맞는지 redaction fixture로 검증한다.
- NAS recovery drill 결과 파일을 확인하고 `work_ver_12` 시리즈에 연결한다.
- reference clock 원천과 system clock 강제 기준을 readiness report에 연결한다.

🔴 운영자 판단 필요:

- 현재 없음. 기존 결정값은 유지한다.

## 6. cowork 검토 요청

이번 리뷰는 아래 두 점만 좁게 보면 충분하다.

1. WS reconnect metric이 Phase 1 전 P0 검증에 필요한 최소 관측값을 제공하는가.
2. Phase 2 기본 `max_order_qty=1`이 실전 canary 안전 기준으로 너무 과하거나 부족하지 않은가.
