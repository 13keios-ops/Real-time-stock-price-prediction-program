# Codex work_ver_13-4: HTTP Date readiness wrapper 검증

## 1. 작업 맥락

`work_ver_13-3` 이후 cowork 리뷰 없이 이어서 진행한 하위 작업이다. HTTP `Date` 기반 clock decision이 submit guard에 주입될 수 있음을 확인한 뒤, 같은 형태의 `system_clock` fixture가 실제 readiness dry-run CLI wrapper까지 통과하는지 테스트로 잠갔다.

KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.

## 2. 변경 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| readiness CLI wrapper의 HTTP `Date` fixture 검증 | `app/services/live_phase_readiness.py` 단위 테스트는 있었지만, `scripts/run_live_readiness_dry_run.sh` wrapper 수준에서 HTTP `Date` fixture shape를 직접 검증하지 않았다. | `tests/test_live_readiness_dry_run_script.py`에 `system_clock` fixture가 `{local_time, http_date, reference_source}` 형태일 때 CLI wrapper output의 `fixture_checks`가 `ok`, `source=kis_rest_http_date`, `skew_seconds=1.0`으로 나오는 테스트를 추가했다. | `scripts/run_live_readiness_dry_run.sh`, `scripts/script_dispatch.sh`, `app/services/live_phase_readiness.py` | 테스트 보강이다. 실제 KIS response header를 자동 수집하는 기능은 아직 없다. |

## 3. 현재 상태

- HTTP `Date` header parser/decision helper: 구현 완료.
- KIS REST 마지막 성공 응답 header read-only 노출: 구현 완료.
- live order manager submit guard 주입 테스트: 구현 완료.
- readiness dry-run CLI wrapper HTTP `Date` fixture 검증: 구현 완료.
- 실제 KIS response header fixture 확인: 미완료.
- runtime caller/readiness runner가 KIS read-only 조회를 실행한 직후 decision을 자동 생성해 주입하는 작업: 미완료.

## 4. cowork 리뷰 요청

1. Phase 1 readiness 증거를 “fixture 기반 dry-run”으로 유지하되, 실제 KIS response header fixture 확인 전까지 통과시키지 않는 판단이 적절한지 확인해 달라.
2. readiness wrapper가 HTTP `Date` raw string을 report에 남기지 않고 parsed reference time/skew 중심으로 남기는 현재 방향이 안전한지 확인해 달라.
3. 다음 slice를 실제 KIS read-only/paper 응답 header fixture 확보로 잡는 것이 맞는지 봐 달라.

## 5. 검증

- `python -m unittest tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness tests.test_system_clock` 통과, 30개.
- `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 88개.
- `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- `git diff -- app/risk config VERSION` 결과는 비어 있었다.

## 6. 남은 위험

- 실제 KIS response header가 mock과 다를 수 있다.
- 현재 wrapper는 fixture를 평가할 뿐, KIS read-only call을 직접 실행하지 않는다.
- Phase 1 전에는 실제 KIS response header fixture와 redaction 검토가 필요하다.
