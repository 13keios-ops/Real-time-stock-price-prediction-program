# Codex work_ver_13-2: KIS REST header clock 연결점

## 1. 작업 맥락

`work_ver_13-1` 이후 cowork 리뷰 없이 이어서 진행한 중간 작업이다. 남은 Phase 1 P0 중 reference clock은 운영자 원천 결정이 필요하지만, 코드로 안전하게 준비할 수 있는 KIS REST 응답 header 연결점을 먼저 만들었다. 작업 당시 live runtime은 `post-close`에서 stopped였고, runtime watchdog은 running/healthy였다.

KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.

## 1-1. work_ver_13-1 요약

토큰 절약을 위해 직전 중간 리포트의 핵심만 함께 둔다. `work_ver_13-1`에서는 NAS recovery export dry-run 명령을 완료했고, 실제 package는 만들지 않았다. 저장소가 약 56GB, `runtime-data`가 약 45GB라 실제 tar package 생성 또는 NAS 강제 백업은 별도 승인으로 남겼다. 같은 라운드에서 HTTP `Date` header parser와 readiness `system_clock` fixture 평가도 추가했다.

## 2. 변경 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| KIS REST response header 노출 | `_request_response()`와 `_post_response()`는 response header를 내부 pagination 등에서만 썼고, public method들은 payload 객체만 반환했다. | `KisRestQuoteClient.last_response_headers` read-only copy 속성을 추가했다. 마지막 성공 응답 header만 메모리에서 확인할 수 있고, 요청 시작 시 stale header를 먼저 비운다. 기존 public method 반환값은 바꾸지 않았다. | `app/brokers/kis_quote_rest.py`, KIS REST client 테스트 | caller가 header를 로그/파일에 저장하면 민감 header가 섞일 수 있으므로 현재는 read-only diagnostics 용도로만 문서화했다. |
| reference clock parser 연결 확인 | HTTP `Date` parser와 KIS REST client가 코드상 분리되어 있었다. | 테스트에서 KIS REST mock 응답의 `Date` header를 `last_response_headers`로 읽고 `reference_time_from_http_date_header()`로 파싱하는 경로를 잠갔다. 또한 `evaluate_clock_skew_from_http_date_header()` 순수 helper를 추가해 header에서 clock decision까지 한 번에 만들 수 있게 했다. | `app/services/system_clock.py`, `tests/test_kis_http_clients.py`, `tests/test_system_clock.py` | 실제 KIS가 `Date` header를 안정적으로 제공하는지는 아직 실응답 fixture로 확인 필요. |
| 기준 문서 동기화 | 기준 문서가 “KIS response header 연결 전”으로만 적혀 있었다. | KIS REST client header 노출은 완료, runtime submit guard/readiness 기본 연결은 후속이라고 경계를 갱신했다. | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 결정 템플릿 | Phase 1 진입 가능으로 오해하지 않게 P0 차단 조건은 유지했다. |

## 3. 현재 판단

- Codex 권장안은 그대로 유지한다. Phase 1 reference clock의 1차 후보는 KIS REST HTTP `Date` header 또는 KIS 응답 서버시각이고, OS/NTP는 보조 후보로 둔다.
- 이번 작업으로 “KIS REST 응답 header를 코드에서 읽을 수 있는가”와 “HTTP `Date` header를 clock decision으로 바꿀 수 있는가”는 테스트로 잠겼다.
- 아직 “실제 KIS 응답에 원하는 header가 항상 있는가”, “어떤 REST 조회를 reference clock sample로 삼을 것인가”, “runtime submit guard에서 이 값을 필수로 강제할 것인가”는 후속이다.

## 4. cowork 리뷰 요청

1. KIS REST client가 마지막 성공 응답 header를 read-only copy로 노출하는 방식이 레이어 경계를 과하게 흔들지 않는지 확인해 달라.
2. response header를 메모리에만 두고 파일/DB에는 저장하지 않는 현재 범위가 안전한지 확인해 달라.
3. Phase 1 전 실제 KIS paper 또는 read-only 조회 응답 fixture로 `Date` header 존재를 확인하는 단계를 P0로 남기는 판단이 적절한지 확인해 달라.

## 5. 검증

- `python -m unittest tests.test_kis_http_clients tests.test_system_clock` 통과, 18개.
- helper 추가 후 `python -m unittest tests.test_system_clock tests.test_kis_http_clients` 통과, 20개.
- stale header clear 보강 후 `python -m unittest tests.test_kis_http_clients tests.test_system_clock` 통과, 21개.
- `python -m unittest tests.test_kis_http_clients tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 56개.
- `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_phase_readiness.py` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- `git diff -- app/risk config VERSION` 결과는 비어 있었다.

## 6. 남은 위험

- 실제 KIS response header fixture가 아직 없다.
- `LiveOrderGuard`나 readiness runner가 `last_response_headers`를 자동으로 읽어 `system_clock` decision을 만드는 연결은 아직 없다.
- header에 민감한 값이 들어올 가능성을 완전히 배제하지 않았으므로, 이 값을 report/audit에 그대로 저장하는 작업은 별도 redaction 검토 전 금지한다.
