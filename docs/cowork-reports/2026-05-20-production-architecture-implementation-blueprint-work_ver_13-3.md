# Codex work_ver_13-3: HTTP Date clock decision submit guard 연결 테스트

## 1. 작업 맥락

`work_ver_13-2` 이후 cowork 리뷰 없이 이어서 진행한 하위 작업이다. `work_ver_13-2`에서 KIS REST 마지막 성공 응답 header와 HTTP `Date` 기반 clock decision helper를 준비했으므로, 이번에는 그 decision이 live order manager submit guard까지 실제로 이어지는지 테스트로 잠갔다.

작업 시작 전 live runtime은 `post-close`에서 stopped였고, runtime watchdog은 running/healthy였다. KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.

## 2. 변경 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| HTTP `Date` decision의 submit guard 연결 증거 | `system_clock` helper와 `LiveOrderManager.submit_intent()`의 `clock_skew_decision` hook은 따로 검증됐다. | `tests/test_live_order_manager.py`에 HTTP `Date` header에서 만든 clock decision이 `require_clock_skew_check=True` submit을 통과시키는 테스트와, stale header decision이 broker 호출 전 `blocked`로 차단되는 테스트를 추가했다. | `tests/test_live_order_manager.py`, live order manager submit guard | 테스트 보강만으로 runtime 자동 연결이 된 것은 아니다. runtime caller가 decision을 만들어 주입하는 작업은 후속이다. |
| 기준 문서 경계 정리 | reference clock은 “runtime 연결 전”으로만 적혀 있었다. | 기준 문서에 “live order manager는 HTTP `Date` 기반 decision을 필수 submit guard 입력으로 받을 수 있음”과 “runtime caller/readiness가 자동 생성해 주입하는 연결은 후속”을 분리해 적었다. | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 결정 템플릿 | Phase 1 진입 가능으로 오해하지 않도록 P0 차단 조건은 유지했다. |

## 3. 현재 상태

- KIS REST response header를 읽는 연결점: 구현 완료.
- HTTP `Date` header에서 clock skew decision을 만드는 helper: 구현 완료.
- readiness fixture에서 `system_clock`을 평가하는 경로: 구현 완료.
- live order manager submit guard가 HTTP `Date` 기반 decision을 필수 입력으로 받아 통과/차단하는 테스트: 구현 완료.
- 실제 KIS response header fixture 확인: 미완료.
- runtime submit caller/readiness runner가 KIS header에서 decision을 자동 생성해 주입하는 작업: 미완료.

## 4. cowork 리뷰 요청

1. HTTP `Date` 기반 decision을 live order manager에 “주입형”으로 유지하고, runtime 자동 연결은 다음 slice로 미루는 판단이 보수적인지 확인해 달라.
2. Phase 1 전 남은 P0를 “실제 KIS response header fixture 확인”과 “runtime caller/readiness decision 자동 주입”으로 좁힌 것이 맞는지 확인해 달라.
3. `require_clock_skew_check=True`를 Phase 2 submit 직전부터 기본으로 올리는 기존 권장 순서를 유지해도 되는지 봐 달라.

## 5. 검증

- `python -m unittest tests.test_live_order_manager tests.test_system_clock tests.test_kis_http_clients` 통과, 41개.
- `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 87개.
- `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- `git diff -- app/risk config VERSION` 결과는 비어 있었다.

## 6. 남은 위험

- 실제 KIS 응답에서 HTTP `Date` header가 항상 제공되는지 아직 확인하지 않았다.
- header를 report/audit에 저장하는 기능은 없다. 저장이 필요해지면 redaction 정책을 먼저 정해야 한다.
- runtime caller가 오래된 header를 decision으로 쓰지 않도록, 실제 연결 slice에서는 fresh read-only 조회 직후 decision을 만들고 생성 시각을 함께 기록해야 한다.
