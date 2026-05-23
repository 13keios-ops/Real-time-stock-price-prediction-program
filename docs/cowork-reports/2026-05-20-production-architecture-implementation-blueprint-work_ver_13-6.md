# Codex work_ver_13-6: sanitized system_clock readiness check helper

## 1. 작업 맥락

`work_ver_13-5` 이후 cowork 리뷰 없이 이어서 진행한 하위 작업이다. KIS paper REST 응답에서 실제 HTTP `Date` header가 있음을 확인했으므로, 다음 위험인 “header 원문을 readiness report나 audit에 저장하지 않으면서 system clock check로 쓰는 방법”을 순수 helper로 좁혔다.

KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.

## 1-1. work_ver_13-5 요약

토큰 절약을 위해 직전 확인의 핵심을 함께 둔다. 기존 runtime report에는 KIS REST response header/date 증거가 없었다. 이후 실전 주문과 무관한 KIS paper 현재가 read-only 조회 1회를 실행했고, response header key에 `date`가 있음을 확인했다. parser source는 `kis_rest_http_date`였고, 계좌번호/token/app key/secret은 출력하거나 문서에 저장하지 않았다.

## 2. 변경 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| header 기반 readiness check 생성 | runtime caller가 KIS header를 받은 뒤 raw header를 fixture에 넣거나 자체 포맷을 만들어야 했다. | `app/services/live_phase_readiness.py`에 `build_system_clock_check_from_http_date_headers()`를 추가했다. HTTP `Date` header와 local time을 받아 `system_clock` check result를 만들고, details에는 source, skew, local/reference time, blocking reasons만 담는다. raw header 원문은 저장하지 않는다. | readiness runner, future runtime caller | helper는 네트워크를 호출하지 않는다. 실제 KIS 조회 직후 어떤 caller가 호출할지는 후속이다. |
| readiness report 연동 테스트 | fixture dict 기반 system_clock 테스트는 있었지만, sanitized check result를 report에 넣는 경로는 별도 검증이 없었다. | `tests/test_live_phase_readiness.py`에 sanitized check result가 `build_fault_injection_dry_run_report()`에 들어가 readiness를 통과하고, raw HTTP date 문자열이 check JSON에 남지 않는 테스트를 추가했다. | readiness tests | raw header를 아예 저장하지 않는 정책 때문에, 사후 감사에는 parsed reference time만 남는다. |

## 3. 현재 상태

- 실제 KIS paper quote REST response header의 `date` 존재: 확인 완료.
- KIS REST client 마지막 성공 header read-only 노출: 구현 완료.
- HTTP `Date` parser/decision helper: 구현 완료.
- live order manager submit guard decision 주입 테스트: 구현 완료.
- readiness CLI wrapper HTTP `Date` fixture 테스트: 구현 완료.
- raw header 원문 없는 sanitized readiness check helper: 구현 완료.
- 실제 runtime caller/readiness runner의 KIS 조회/decision 자동 주입: 후속.

## 4. cowork 리뷰 요청

1. raw header 원문을 저장하지 않고 parsed reference time/skew만 남기는 helper 방향이 감사성과 보안성 사이에서 적절한지 확인해 달라.
2. 사후 감사에 raw HTTP `Date` 문자열까지 필요하다고 보는지, 아니면 parsed reference time이면 충분한지 봐 달라.
3. 다음 slice를 runtime caller/readiness runner 연결로 진행해도 될지, live account read-only header 확인을 먼저 해야 할지 의견 부탁한다.

## 5. 검증

- `python -m unittest tests.test_live_phase_readiness tests.test_system_clock tests.test_live_readiness_dry_run_script` 통과, 31개.
- `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 89개.
- `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- `git diff -- app/risk config VERSION` 결과는 비어 있었다.

## 6. 남은 위험

- 실제 runtime에서 helper를 호출하는 연결은 아직 없다.
- live account read-only API response header는 아직 확인하지 않았다.
- raw header를 저장하지 않으므로, header 원문 자체를 증거로 보관해야 한다면 별도 redaction/retention 정책이 필요하다.
