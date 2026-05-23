# Codex work_ver_13-5: 실제 KIS paper HTTP Date header 확인

## 1. 작업 맥락

`work_ver_13-4` 이후 cowork 리뷰 없이 이어서 진행한 하위 작업이다. 기존 runtime report에 KIS REST response header 증거가 남아 있는지 먼저 read-only로 확인했고, 기존 산출물에는 header/date 증거가 없었다. 이후 실전 주문과 무관한 KIS paper 현재가 read-only 조회 1회를 실행해 HTTP `Date` header 존재 여부만 확인했다.

실전 계좌 주문, live order submit/cancel, runtime restart, 운영 DB schema apply는 하지 않았다. 출력에는 계좌번호, token, app key/secret을 남기지 않았고, header key 목록과 `Date` parsing 결과만 확인했다.

## 2. 확인 결과

| 항목 | 결과 |
|---|---|
| 조회 종류 | KIS REST 현재가 read-only 조회 |
| mode | `paper` |
| symbol | `005930` |
| response header key | `date` 포함 |
| parsed source | `kis_rest_http_date` |
| 비밀값 출력 | 없음 |

확인된 header key 목록에는 `connection`, `content-length`, `content-type`, `date`, `gt_uid`, `tr_cont`, `tr_id`, `x-content-type-options`, `x-oracle-dms-ecid`, `x-oracle-dms-rid`, `x-xss-protection`가 있었다. 값은 `date` reference time만 확인했고, header 전체 원문은 문서에 저장하지 않았다.

## 3. 현재 의미

- KIS paper quote REST 응답에서 HTTP `Date` reference clock 후보가 실제로 존재함을 확인했다.
- 아직 KIS live account read-only 응답, order/fill 조회 응답, 장애/점검 응답에서 항상 `Date`가 제공되는지는 확인하지 않았다.
- Phase 1 진입 전 남은 작업은 runtime caller/readiness runner가 fresh read-only 조회 직후 `last_response_headers`에서 clock decision을 만들고, 이 decision을 readiness report와 submit guard에 주입하도록 연결하는 것이다.

## 4. cowork 리뷰 요청

1. Phase 1 reference clock 1차 후보를 KIS REST HTTP `Date`로 두는 판단이 이번 paper quote 확인으로 충분히 강화됐는지 봐 달라.
2. Phase 1 전 live account read-only 응답에서도 `date` header를 한 번 더 확인해야 하는지, paper quote 확인으로 충분한지 의견 부탁한다.
3. header 전체 원문을 저장하지 않고 header key와 parsed reference time만 문서화하는 방식이 보안상 충분한지 확인해 달라.

## 5. 검증

- KIS REST 현재가 read-only 조회 1회 성공. `paper` mode, symbol `005930`, response header에 `date` 존재.
- `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 88개.
- `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- `git diff -- app/risk config VERSION` 결과는 비어 있었다.

## 6. 남은 위험

- 실제 live account read-only API 응답 header는 아직 확인하지 않았다.
- runtime readiness/check path가 KIS 조회를 직접 실행하도록 연결되지는 않았다.
- token refresh가 필요한 경우 token cache는 갱신될 수 있으므로, 실제 운영 전에는 이 check를 장외/장전 readiness 절차에 명시해야 한다.
