# KIS 연결 장애 대응 Runbook

이 문서는 한국투자증권 Open API(KIS Developers) 연결 문제를 운영 중 어떻게 해석하고 조치할지 정리한다.
기준은 공식 KIS Developers 포털과 한국투자증권 공식 GitHub 샘플 저장소, 그리고 이 저장소에서 실제 관측한 로그다.

## 1. 공식 원천 확인 결과

확인일: 2026-06-12. 2026-06-13에 공개 HTML 기준으로 재확인했다.

- KIS Developers 포털 `https://apiportal.koreainvestment.com/intro`
  - 공식 진입점이다.
  - 포털은 API 문서, API 가이드 문서, FAQ/오류코드, 공식 GitHub 샘플 코드, 테스트베드를 제공한다.
  - 메인 공지 영역에 `[중요] 한국투자증권 Open API 신규 고객 초당 호출 제한 안내`가 노출된다.
  - 포털 상세 공지와 오류코드 본문은 웹 UI/로그인/동적 로딩 영향으로 CLI 텍스트 수집에서 완전 확인되지 않을 수 있다.
  - 2026-06-13 공개 HTML 재확인에서도 공지 제목 노출은 확인됐지만, 구체 초당/분당 수치는 공개 텍스트로 내려오지 않았다.
- KIS API 가이드 문서 `https://apiportal.koreainvestment.com/apiservice-apiservice`
  - OAuth 인증, 접근토큰 발급/폐기, 실시간 웹소켓 접속키 발급을 별도 항목으로 제공한다.
  - 국내주식 주문/계좌 항목에 주식일별주문체결조회, 주식잔고조회, 매수가능조회, 매도가능수량조회가 있다.
  - 국내주식 실시간시세 항목에 실시간 체결가, 실시간 호가, 실시간 체결통보, 장운영정보가 있다.
  - 국내주식 업종/기타 항목에 변동성완화장치(VI) 현황, 국내휴장일조회가 있다.
- 한국투자증권 공식 GitHub 샘플 저장소 `https://github.com/koreainvestment/open-trading-api`
  - 공식 README는 샘플 코드가 KIS Developers 연동 예시이며, REST와 WebSocket 예제를 제공한다고 설명한다.
  - 설정 항목에 앱키, 앱시크릿, HTS ID, 계좌번호, 모의/실전 키 분리를 명시한다.
  - 문제 해결 가이드에서 토큰 재발급은 1분당 1회라고 안내한다.
  - WebSocket `No close frame received`류 오류는 HTS ID 정확성 확인 대상으로 안내한다.
  - `EGW00201`은 초당 거래건수 초과이며, 모의투자 계좌는 REST API 호출 제한이 낮다고 안내한다.
  - 2026-06-13 재확인 기준 공식 GitHub README도 구체 수치 대신 모의투자 REST 제한이 낮다는 방향만 제공한다.

관련 문서/코드 경로: `docs/KIS-Integration-Plan.md`, `docs/Runtime-Configuration.md`, `app/brokers/kis_auth.py`, `app/brokers/kis_quote_rest.py`, `app/brokers/kis_quote_ws.py`

## 2. 현재 저장소에서 관측한 증상

2026-06-12 기준으로 반복 관측된 증상은 두 가지다.

- KIS 모의계좌 일별 주문/체결 조회에서 `EGW00201` 발생.
  - 최신 관측: `runtime-data/reports/broker-paper/latest-sync.json`
  - 상태: `status=rate_limited`
  - pending symbols: `005380`, `005930`, `035420`, `247540`, `373220`
  - open order count: `5`
  - 원인 해석: 모의투자 계좌의 REST 제한이 낮은데 장후 자동화와 수동 재시도가 같은 order-fill endpoint를 반복 호출했다.
- KIS WebSocket이 장전/장중에 `no close frame received or sent`로 끊긴 뒤 재연결.
  - 최신 관측: `runtime-data/logs/app/live-runtime.stderr.log`
  - 현재 구현은 reconnect를 수행하고 `storm=false`이면 live runtime을 유지한다.
  - 원인 해석: 네트워크/서버/HTS ID/웹소켓 접속키 상태 중 하나일 수 있다. 공식 GitHub는 HTS ID 확인을 문제 해결 후보로 둔다.

관련 문서/코드 경로: `runtime-data/reports/broker-paper/latest-sync.json`, `runtime-data/logs/app/live-runtime.stderr.log`, `app/services/broker_paper_sync.py`, `app/services/broker_paper.py`

## 3. 운영 대응 기준

### 3.1. `EGW00201` order-fill rate limit

기본 판단:

- `EGW00201`이 뜨면 같은 KIS 일별 주문/체결 조회 endpoint를 즉시 반복 호출하지 않는다.
- 기본 helper, 장후 batch, 장중 종료 force sync 모두 한 실행에서 HTTP 1회만 시도하며 in-call retry는 하지 않는다.
- 이 저장소의 기본 cooldown은 2시간이다. 최초 제한 리포트부터 `cooldown_active=true`, `retry_after_seconds=7200`을 남긴다.
- cooldown 중에는 broker paper sync가 KIS order-fill 조회를 건너뛰고 `skipped_broker_call=true`, 남은 `retry_after_seconds`를 리포트에 남긴다.
- 실시간 수집기의 process pause도 `rate_limited` 결과에는 120분을 적용한다.
- timeout/게이트웨이 routing 같은 일반 예외는 5/10/20/40/60분 지수 백오프로 낮추고, 성공하면 초기화한다. 분봉 확정 경로를 반복 REST timeout으로 막지 않는 것이 우선이다.
- order-fill이 복구되지 않은 상태에서 `AlignToBroker`나 `SyncInitialCash`를 자동 적용하지 않는다.

권장 절차:

1. `runtime-data/reports/broker-paper/latest-sync.json`에서 `status`, `cooldown_active`, `retry_after_seconds`, `pending_symbols`를 확인한다.
2. `status=rate_limited`이면 같은 endpoint 호출을 멈춘다.
3. `python -m app --reconcile-paper-accounts`는 계좌 snapshot 기반 확인용으로 1회만 허용한다.
4. broker 계좌 포지션과 local 포지션 수량 mismatch가 있으면 자동 align을 보류한다.
5. cooldown 이후 장외에 `python -m app --sync-broker-paper-orders`를 1회 재시도한다.
6. 계속 `EGW00201`이면 다음 거래일 장후까지 보류하고, pending order 원장과 broker 계좌 화면을 사람 검토 대상으로 남긴다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

| 항목 | 내용 |
| --- | --- |
| 변경 전 | 장후 batch는 한 실행에서 최대 5회, 기본 helper는 최대 4회까지 같은 order-fill endpoint를 재시도할 수 있었다. |
| 변경 후 | 모든 운영 경로를 HTTP 1회로 제한하고, 최초 `EGW00201`부터 service/runtime 2시간 cooldown을 함께 적용한다. 일반 장중 실패는 최대 60분 지수 백오프로 수집 경로를 보호한다. |
| 영향 범위 | `app/services/broker_paper.py`, `app/services/broker_paper_sync.py`, `app/services/streaming.py`, 관련 테스트와 장후 reconciliation 절차. |
| 회귀 위험 | 체결 복구가 최대 2시간 늦어질 수 있다. 대신 rate limit 연쇄와 잘못된 자동 align 위험을 줄인다. |

관련 문서/코드 경로: `app/services/broker_paper_sync.py`, `tests/test_broker_paper_sync.py`, `.agents/skills/daily-ops-check/SKILL.md`

### 3.1.1. order-fill 연결 진단

`runtime-data/reports/broker-paper/latest-sync.json`은 계좌번호, 주문번호, 원문 응답을 노출하지 않고 아래 건수만 남긴다.

| 필드 | 의미 | 운영 해석 |
| --- | --- | --- |
| `order_fill_lookback_days` | KIS 주문/체결 조회 기간 | 예상한 날짜 범위인지 확인한다. |
| `broker_rows_returned` | KIS가 반환한 주문/체결 행 수 | 조회 자체가 비어 있는지 판단한다. |
| `broker_rows_linked_to_submissions` | 로컬 broker 제출 원장과 연결된 KIS 행 수 | 현재 감사 원장으로 설명되는 범위다. |
| `broker_rows_unlinked_to_submissions` | 로컬 제출 원장과 연결되지 않은 KIS 행 수 | 수동/외부 주문 또는 로컬 제출 기록 누락 후보다. |
| `exact_matched_orders` | 주문일+지점번호+주문번호로 정확히 연결된 로컬 주문 수 | 정상 연결의 우선 근거다. |
| `fallback_matched_orders` | 주문일 없이 지점번호+주문번호로 연결된 로컬 주문 수 | 날짜 경계 또는 lookback 범위 차이를 추가 확인한다. |
| `ambiguous_fallback_key_count` | 보조 매칭 키가 둘 이상 겹친 수 | 자동 align을 금지하고 원장을 검토한다. |

판정 순서는 다음과 같다.

1. `broker_rows_unlinked_to_submissions > 0`이면 외부/수동 주문 또는 로컬 제출 이력 누락 가능성을 먼저 확인한다.
2. `fallback_matched_orders > 0` 또는 `ambiguous_fallback_key_count > 0`이면 날짜 포함 정확 매칭이 깨진 원인을 확인한다.
3. 위 세 값이 모두 0이고 로컬 수량과 KIS order-fill 순수량도 같지만 계좌 수량만 다르면 `kis_account_snapshot_vs_order_fill_ledger_divergence`를 유지한다.
4. 어떤 경우에도 이 진단만으로 `AlignToBroker`나 `SyncInitialCash`를 자동 실행하지 않는다.

장후 자동화는 먼저 `latest-paper-account-history.json`에서 오늘 유효 기록 존재 여부를 확인한다. 이미 있으면 같은 endpoint를 중복 호출하지 않고, 실제 거래일 장후인데 기록이 없을 때만 통합 recheck를 한 번 실행한다. 주말/휴장일 차단 시도는 `latest-paper-kis-mismatch-recheck-attempt.json`에만 남고 10거래일 분모에는 들어가지 않는다.

### 3.1.2. Phase 0 전체 기간 계좌 활동 probe

Phase 0 snapshot divergence는 최근 3일 조회를 반복하지 않고 아래 dry-run으로 범위와 cooldown을 먼저 확인한다.

```bash
python3 scripts/probe_kis_paper_account_activity.py
```

계좌 소유자의 해당 작업 명시 승인, 장외, live runtime 정지를 모두 확인했을 때만 `--execute`를 붙여 1회 실행한다.

- 조회 범위는 latest alignment marker부터 latest account snapshot까지다.
- 페이지 끝을 확인하지 못하면 `blocked_incomplete_pagination`으로 남기며 정합 근거로 쓰지 않는다. 기본 page cap에 도달하면 같은 작업에서 재실행하지 않고, 다음 실행은 계좌 소유자의 새 명시 승인 뒤 예상 행 수를 덮는 충분한 `--max-pages`를 지정해 정확히 1회 수행한다.
- 보고서에는 계좌번호, 주문번호, raw response를 남기지 않는다.
- 로컬 submission에 없는 broker 활동, 로컬 원장 divergence, account snapshot과 전체 활동 divergence를 분리한다.
- `EGW00201`이면 2시간 cooldown 동안 어떤 dry-run도 네트워크 실행으로 승격하지 않는다.
- 완료 결과는 `latest-paper-account-activity.json`, 제한/차단 시도는 `latest-paper-account-activity-attempt.json`에 분리한다.
- 어떤 결과도 자동 align, `SyncInitialCash`, 주문 정책 변경을 허용하지 않는다.

2026-08-14 새 승인 조회 범위는 `2026-06-14~2026-08-14`다. `--max-pages 30` 실행은 22페이지/329행/20거래일에서 `pagination_complete=true`였고 로컬 submission 320개와 broker-only 활동 9행을 확인했다. 전체 활동 position은 KIS snapshot과 일치하고 local paper만 divergence여서 `external_or_unlinked_broker_activity`로 확정했다. 2026-08-15 별도 승인으로 KIS snapshot 기준 marker-only clean baseline을 생성했고 mismatch/cash/total asset gap 0을 확인했다. 과거 10일 이력은 보존하며 새 기준선 이후 10개 유효 거래일을 다시 누적한다.

### 3.1.3. broker paper 주문 계좌 hard rejection

2026-08-28 `order_rejected=832`를 risk event와 local order/decision lineage로 다시 분해했다.

- 830건: KIS 응답 `모의투자 주문이 불가한 계좌`
- 2건: `EGW00201` 초당 거래건수 초과
- 830건은 signal/gate/allocator 이전 차단이 아니라 `BrokerPaperMirror -> KisRestQuoteClient.submit_cash_order` 실제 호출 뒤 발생했다.
- 대표 표본은 모두 paper profile, 국내주식 product shape, 지정가 `ORD_DVSN=00`, 양수 수량/가격, KRX였다.
- 저장소의 paper 매수/매도 TR ID `VTTC0012U/VTTC0011U`와 `CANO`, `ACNT_PRDT_CD`, `PDNO`, `ORD_DVSN`, `ORD_QTY`, `ORD_UNPR`, `EXCG_ID_DVSN_CD`, `SLL_TYPE`, `CNDT_PRIC` 구성은 공식 국내주식 `order_cash` 예제와 일치한다.
- 공식 근거: `https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py`, `https://github.com/koreainvestment/open-trading-api/blob/main/README.md`

따라서 현재 증거로는 repository 주문 요청 구현 오류를 root cause로 볼 수 없다. KIS 서버가 현재 설정된 paper 계좌를 국내주식 주문 불가로 판정한 사실까지 확정되며, 세부 원인은 paper app 자격정보와 모의계좌 연결 상태, 계좌의 모의투자 활성/주문 가능 상태 중 하나로 남는다. 계좌번호, app key/secret, token을 로그나 문서에 남기지 말고 계좌 소유자가 KIS/HTS에서 이 두 항목만 확인한다.

운영 보호는 다음과 같다.

1. 정확한 계좌 hard rejection이 한 번 발생하면 해당 runtime process에서 broker paper 제출 circuit을 30분 연다.
2. circuit 동안 같은 계좌의 broker network call은 하지 않지만 local paper 판단, E7 수집, order rejection lineage는 계속 기록한다.
3. `EGW00201`, auth, invalid request, 종목별 거절, network, unknown 오류는 account circuit을 열지 않는다.
4. 30분 만료 뒤 주문 후보 1건만 probe하고, 성공하면 circuit을 해제한다. 같은 hard rejection이면 다시 30분 연다.
5. runtime 재시작 뒤 circuit은 초기화되므로 첫 후보 1건은 다시 probe한다.
6. 성공 acknowledgement가 없으면 broker submission 행을 만들지 않는다. 해당 거래일은 기존 Phase 0 no-submission day 규칙대로 유효일이 아니다.
7. 성공 submission이 실제로 생성되기 전에는 다음 정상 거래 준비를 통과로 표시하지 않는다.

실패 evidence는 원문 예외 대신 분류, sanitized code/message, `network_attempted`, circuit 상태와 stable lineage ID를 JSON으로 남긴다. 계좌값과 자격정보 값은 기록하지 않는다.

### 3.2. read-only probe 실패 분류

기본 판단:

- token_refresh, account_snapshot, system_clock probe는 실패할 때 원문 응답 본문을 저장하지 않고 sanitized error category만 남긴다.
- 현재 분류 후보는 missing_quote_credentials, missing_account_credentials, rate_limited, token_invalid_or_expired, network_error, http_error, kis_business_error, client_error이다.
- EGW00201은 rate_limited로 분류하고, EGW00121/EGW00123은 token_invalid_or_expired로 분류한다.
- 계좌번호, app key, app secret, token, raw response body는 리포트 본문에 쓰지 않는다.

운영 확인:

1. runtime-data/reports/live-readiness/token-refresh-check.json, account-snapshot-check.json, system-clock-check.json의 details.error_category를 먼저 본다.
2. rate_limited이면 즉시 반복 호출하지 않고 cooldown 후 장외에 다시 확인한다.
3. token_refresh와 account_snapshot이 ok이고 system_clock만 rate_limited이면 Phase readiness blocker는 system_clock read-only quote 호출량 문제로 좁힌다.
4. system_clock quote probe가 `EGW00201`이면 즉시 같은 현재가 endpoint를 반복 호출하지 않는다. 대신 장외에 계좌 snapshot read-only 조회 1회로 HTTP Date를 재사용한다.
5. 계좌 snapshot과 system_clock을 함께 갱신할 때는 아래 명령을 사용한다. 이 명령은 주문/취소가 아니라 `get_account_balance` 조회 1회만 수행하고, 계좌번호와 raw header는 저장하지 않는다.

```bash
./scripts/probe_kis_account_snapshot.sh --mode paper --output-path runtime-data/reports/live-readiness/account-snapshot-check.json --system-clock-output-path runtime-data/reports/live-readiness/system-clock-check.json
```

6. missing_*_credentials이면 .env 존재 여부와 필수 키 shape만 확인하고 값은 출력하지 않는다.

2026-07-05 실제 확인:

- 위 계좌 snapshot 파생 방식으로 `account_snapshot=ok`, `system_clock=ok`를 같은 read-only 계좌 조회 1회에서 생성했다.
- `system_clock` 세부값은 `source=kis_rest_http_date_account_snapshot`, `probe=kis_readonly_account_snapshot`, `derived_from=account_snapshot`, `skew_seconds=0.029246`이다.
- 이 방식으로 readiness dry-run의 `system_clock_fault_dry_run_failed` blocker는 제거됐고, 남은 blocker는 `ws_recovery` stale, `market_status`, `kill_switch`다.

관련 문서/코드 경로: app/services/kis_probe_errors.py, app/services/kis_token_probe.py, app/services/kis_account_probe.py, app/services/system_clock_probe.py, scripts/probe_kis_account_snapshot.py, runtime-data/reports/live-readiness/

### 3.2-1. read-only probe 3종 원인 분리 기준

2026-07-07 기준으로 `token_refresh`, `account_snapshot`, `system_clock` probe는 각각 다른 실패면을 본다. 세 항목을 모두 `KisApiError` 하나로 묶으면 Phase 1a blocker를 잘못 판단할 수 있으므로 아래처럼 분리한다.

| probe | 접근 범위 | 실패 세부 필드 | 1차 분류 | 판정 기준 |
| --- | --- | --- | --- | --- |
| `token_refresh` | auth-only | `details.error_category`, `http_status`, `kis_error_codes`, `force_refresh` | 자격증명/토큰/KIS 인증 서버 | `missing_quote_credentials`면 로컬 설정 문제, `token_invalid_or_expired`면 토큰 갱신 문제, `network_error/http_error/rate_limited`면 KIS 또는 네트워크/호출량 문제로 본다. |
| `account_snapshot` | read-only `get_account_balance` | `details.error_category`, `shape_status`, `position_row_count`, `summary_row_count`, 값 타입 존재 여부 | 자격증명/계좌 shape/KIS 모의계좌 서버 | `missing_account_credentials`면 로컬 계좌 설정 문제, `shape_status != ok`면 응답 shape drift 또는 파서 문제, `rate_limited/network_error/http_error`면 KIS/네트워크 문제로 본다. |
| `system_clock` | read-only HTTP `Date` | `details.source`, `probe`, `skew_seconds`, `blocking_reasons`, `error_category` | 시스템 시계/quote rate limit/대체 증거 | `kis_readonly_current_price`가 `rate_limited`이면 현재가 endpoint 호출량 문제다. 이때 같은 quote 호출을 반복하지 않고 account snapshot 응답의 HTTP `Date`를 재사용한다. |

코드 문제 / 자격증명 문제 / KIS 서버 문제 분류:

- 코드 문제: `shape_status=missing_required_attributes` 또는 `invalid_value_types`, `client_error`, 파서가 기대 필드를 못 찾는 경우. 조치 순서는 저장된 sanitized shape와 parser test 확인이다.
- 자격증명 문제: `missing_quote_credentials`, `missing_account_credentials`, `token_invalid_or_expired`. 값은 출력하지 않고 root `.env` 존재와 필수 key shape만 확인한다.
- KIS 서버/네트워크/호출량 문제: `rate_limited`, `network_error`, `http_error`, 반복되는 `kis_business_error`. 같은 endpoint 반복 호출을 멈추고 cooldown 뒤 장외 1회만 재시도한다.

2026-07-07 실제 증거:

- `runtime-data/reports/live-readiness/token-refresh-check.json`: `status=ok`, `access=auth-only`, `force_refresh=false`, `seconds_to_expiry=30441.289`.
- `runtime-data/reports/live-readiness/account-snapshot-check.json`: `status=ok`, `shape_status=ok`, `position_row_count=4`, `summary_row_count=1`.
- `runtime-data/reports/live-readiness/system-clock-check.json`: `status=ok`, `source=kis_rest_http_date_account_snapshot`, `probe=kis_readonly_account_snapshot`, `skew_seconds=0.075518`.
- `runtime-data/reports/live-readiness/latest-readiness.json`: `token_refresh=true`, `account_snapshot=true`, `system_clock=true`다. 현재 Phase 1 readiness blocker는 이 3종이 아니라 `ws_recovery` stale, `market_status`, `kill_switch`다.

account_snapshot probe와 paper/KIS mismatch 연관성:

- 현재 `account_snapshot` probe는 KIS 계좌 snapshot API가 호출되고 필수 필드 shape가 정상인지 확인한다. 즉 API 연결과 응답 형식은 정상이다.
- 2026-07-06 `paper/KIS mismatch`의 root cause는 `kis_account_snapshot_vs_order_fill_ledger_divergence`다. 이는 account snapshot API가 실패했다는 뜻이 아니라, 같은 KIS 모의계좌에서 계좌 snapshot 수량과 order/fill 원장 순수량이 서로 다르게 보인다는 뜻이다.
- 따라서 현재 증거상 `account_snapshot` probe 실패와 mismatch는 같은 실패가 아니다. 다만 둘 다 KIS 모의계좌 계좌/잔고 원천을 보므로, 다음 장후에도 mismatch가 지속되면 `account_snapshot shape ok + order/fill net 일치 + account qty divergence`를 한 묶음으로 남겨 KIS 모의계좌 snapshot 원천 차이 또는 외부/수동 체결 가능성을 운영 검토 대상으로 둔다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

| 항목 | 내용 |
| --- | --- |
| 변경 전 | read-only probe 실패가 모두 `KisApiError`처럼 보이면 token/account/system_clock 중 어느 계층이 문제인지 문서만으로 구분하기 어려웠다. |
| 변경 후 | probe별 접근 범위, error_category, 코드/자격증명/KIS서버 분류, account_snapshot과 mismatch의 관계를 분리해서 해석한다. |
| 영향 범위 | 문서 판정 기준, Phase 1a readiness 운영 해석, cowork review handoff. 코드 실행 경로는 바꾸지 않는다. |
| 회귀 위험 | 없음. 다만 문서 기준과 실제 `kis_probe_errors.py`의 category 목록이 달라지면 함께 갱신해야 한다. |

관련 문서/코드 경로: `app/services/kis_probe_errors.py`, `app/services/kis_token_probe.py`, `app/services/kis_account_probe.py`, `app/services/system_clock_probe.py`, `runtime-data/reports/live-readiness/token-refresh-check.json`, `runtime-data/reports/live-readiness/account-snapshot-check.json`, `runtime-data/reports/live-readiness/system-clock-check.json`, `runtime-data/reports/live-readiness/latest-readiness.json`, `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`
### 3.3. Phase 1b 실전계좌 read-only 관측

먼저 네트워크 없는 사전검사만 실행한다.

```bash
./scripts/run_phase1b_readonly_observation.sh
```

통과 조건은 `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, paper/live 조회 자격정보 존재, 주문 메서드 미노출이다. 자격정보 값과 계좌 식별자는 출력하지 않는다.

사전검사가 통과하고 계좌 소유자 또는 실전 운용 승인권자가 해당 작업을 승인한 경우에만 아래를 1회 실행한다.

```bash
./scripts/run_phase1b_readonly_observation.sh --execute
```

허용 호출은 live token refresh 1회, paper/live account snapshot 각 최대 1페이지, live current price 기반 system clock 1회다. 앞 단계가 실패하면 뒤 단계는 `not_run`으로 남기고 중단한다. `pre-open`과 `regular-session`이면 `protected_market_session`으로 네트워크 시작 전에 차단한다. system clock은 token/account 단계 시작 시각이 아니라 quote 직전 UTC 시각을 사용한다. 주문/취소 호출은 0건이어야 한다.

산출물은 `runtime-data/reports/live-readiness/phase1b/` 아래에 둔다. preflight 차단, 실행 시도 차단, 실제 관측 성공/실패를 서로 다른 latest 파일로 저장해 마지막 유효 증거를 덮지 않는다. 자동화는 별도 승인 없이 `--execute`를 붙이지 않는다.

관측 결과와 공통 운영 fixture를 합친 Phase 1b 전용 readiness는 아래처럼 만든다. 실제 실행 성공 파일이 아직 없으면 차단된 `latest-phase1b-readonly-attempt.json`을 넣어 blocker를 정직하게 보존할 수 있다.

```bash
./scripts/run_live_readiness_dry_run.sh \
  --phase phase1b_live_readonly \
  --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json \
  --phase1b-observation-path runtime-data/reports/live-readiness/phase1b/latest-phase1b-readonly-observation.json \
  --report-path runtime-data/reports/live-readiness/phase1b/latest-readiness.json
```

이 옵션은 live token/account/system clock 값을 paper fixture보다 우선하며 실패 시 paper 값으로 fallback하지 않는다. 관측 JSON의 precomputed override는 신뢰하지 않고 `execution_started`와 sanitized artifact에서 다시 계산한다. `market_status`와 kill switch OFF는 Phase 1b read-only에서는 비차단이고 Phase 2 live-submit readiness부터 필수다. WebSocket recovery와 database/disk/dashboard/storage migration은 Phase 1b에서도 필수다.

권장 운영 명령은 개별 명령 대신 아래 cycle이다.

```bash
# 외부 KIS 네트워크 0회 사전 판정
./scripts/run_phase1b_readiness_cycle.sh

# 자격정보 준비 후 장외 bounded 관측과 dashboard 갱신
./scripts/run_phase1b_readiness_cycle.sh --execute --refresh-dashboard
```

cycle은 protected session에서 시작 전에 차단한다. 기본 결과는 `latest-cycle-preflight.json`과 `latest-readiness-preflight.json`, 실행 요청은 `latest-cycle-execute.json`, 실행 미시작 readiness는 `latest-readiness-attempt.json`, bounded 관측이 시작된 readiness만 `latest-readiness.json`에 남긴다. 실제 네트워크 시도 수는 `network_calls_executed=0..4`로 기록하고 0회는 관측 시작으로 인정하지 않는다. 따라서 단순 preflight나 local client 생성 실패가 마지막 실제 관측 증거를 덮지 않는다.

### 3.4. WebSocket `No close frame received`

기본 판단:

- 단발 reconnect는 장애가 아니라 관측 이벤트로 본다.
- approval-key REST 발급 실패도 연결 수립 실패로 취급한다. listener는 5초에서 최대 60초까지 지수형 대기 후 재시도한다.
- listener가 종료된 경우 watchdog은 2분에서 최대 15분까지 지수형 대기 후 재시작한다. 이는 listener 내부 재연결과 별도 보호막이며, 정상 실행을 확인하면 실패 카운터를 초기화한다.
- 2026-07-17 approval-key SSL EOF/timeout은 KIS 또는 네트워크 계열 후보로 기록했다. 원인을 자격증명이나 코드 결함으로 단정하지 않으며, 다음 장전 수집 재개 여부로 확인한다.
- `storm=false`이고 watchdog heartbeat가 정상이라면 runtime을 즉시 재시작하지 않는다.
- 짧은 시간 안에 반복되어 `storm=true`가 되거나 stable frame이 사라지면 신규 신호/주문 판단은 보수적으로 차단하는 방향으로 연결해야 한다.

운영 확인:

1. `runtime-data/logs/app/live-runtime.stderr.log`에서 reconnect 간격과 `storm` 여부를 본다.
2. `./scripts/get_runtime_watchdog_status.sh`에서 `errors=[]`, `heartbeat_stale=false`인지 확인한다.
3. HTS ID 설정은 공식 GitHub의 WebSocket 문제 해결 후보이므로 `.env` 값 존재 여부만 확인하고, 본문/리포트에 값을 쓰지 않는다.
4. WebSocket 끊김이 장중 데이터 공백으로 이어졌는지는 `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`에서 최신 거래일 coverage로 판단한다.

관련 문서/코드 경로: `app/brokers/kis_quote_ws.py`, `runtime-data/logs/app/live-runtime.stderr.log`, `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`

## 4. 해결/보류 기준

정상:

- broker paper sync가 `status=ok`.
- `open_order_count=0`.
- paper/KIS reconciliation이 `status=ok` 또는 운영상 설명 가능한 `aligned_waiting_first_submission`.
- WebSocket reconnect가 있어도 `storm=false`이고 데이터 품질 최신 거래일 coverage가 정상.

주의:

- `EGW00201`로 `cooldown_active=true`.
- pending symbols가 남아 있으나 order-fill endpoint cooldown 때문에 아직 복구 불가.
- WebSocket reconnect가 반복되지만 `storm=false`.

실패:

- `EGW00201`이 cooldown 이후에도 반복되어 1거래일 이상 order-fill 감사가 복구되지 않음.
- broker 계좌와 local 장부의 수량 mismatch가 있는데 자동 align을 적용하려는 상황.
- WebSocket reconnect storm 또는 데이터 coverage 공백이 발생.

관련 문서/코드 경로: `runtime-data/reports/broker-paper/latest-sync.json`, `runtime-data/reports/reconciliation/latest-paper-account-sync.json`, `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`

## 5. 남은 확인 필요

- 포털 공지 `[중요] 한국투자증권 Open API 신규 고객 초당 호출 제한 안내`의 상세 수치와 적용 대상은 로그인/동적 UI에서 별도 확인 필요.
- KIS 모의투자 일별 주문/체결 조회의 공식 초당/분당/일별 제한 수치는 포털 상세 문서 또는 KIS 지원 채널 확인 필요.
- WebSocket `No close frame received`가 현재 HTS ID 문제인지, KIS 서버 측 정상 reconnect 패턴인지, WSL2 네트워크 환경 문제인지는 추가 관측 필요.
- 실전 계좌 read-only Phase 1에서는 모의투자 REST 제한과 다르게 동작할 수 있으므로 별도 호출량 budget을 잡아야 한다.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Transition-Progress.md`, `runtime-data/logs/app/live-runtime.stderr.log`

## 6. KIS paper 매수가능조회 진단

계좌 소유자가 확인한 현재 사실은 paper API 자격정보가 해당 국내주식 모의계좌에 연결돼 있고 만료일이 `2027-04-10`이라는 점이다.
`모의투자 주문이 불가한 계좌`가 재발해도 미연결/만료로 단정하지 않고 orderability/entitlement 상태를 분리한다.

공식 국내주식 매수가능조회 계약:

- endpoint: `/uapi/domestic-stock/v1/trading/inquire-psbl-order`
- paper TR ID: `VTTC8908R`
- query: `CANO`, `ACNT_PRDT_CD`, `PDNO`, `ORD_UNPR`, `ORD_DVSN`, `CMA_EVLU_AMT_ICLD_YN`, `OVRS_ICLD_YN`
- 구현: `KisReadonlyClient.get_orderability()`와 `scripts/probe_kis_paper_orderability.py`

기본 실행은 dry-run이며 network/order/cancel call이 모두 0이다. `--execute`는 계좌 소유자의 해당 작업 명시 승인, 장외, live runtime 정지 조건에서 read-only endpoint를 정확히 1회 호출하고 주문/취소는 0회다.
결과는 `orderability_ok`, `orderability_zero`, `account_not_orderable`, `auth_error`, `invalid_request`, `rate_limited`, `network_error`, `unknown_error`로 나눈다.
보고서에는 exact 현금 대신 positive/zero/unavailable만 남기고 full CANO, app key/secret, token, raw response를 저장하지 않는다.
`account_not_orderable`이면 KIS 계좌 측 orderability/entitlement 근거가 강해지고, 정상/positive인데 cash order만 실패하면 endpoint 간 정책 차이를 KIS 지원에 문의한다. 어느 경우에도 실제 주문을 반복하지 않는다.

2026-09-01 계좌 소유자 승인으로 같은 `005930`과 최신 확정 분봉 가격을 사용해 `ORD_DVSN=01`, 실제 지정가 주문과 같은 `ORD_DVSN=00`을 각각 read-only 1회 확인했다. 두 조회 모두 transport/business success, `rt_cd=0`, `orderability_ok`, value presence `positive`였고 주문/취소 호출은 0회다. 따라서 `ORDER_TYPE_DIFFERENCE_NOT_CAUSAL`로 판정하며, 계좌 미연결·만료·주문구분 차이보다 KIS paper cash-order endpoint별 entitlement 또는 정책 문제를 우선 의심한다. 이는 KIS 서버 결함 확정이 아니다.

2026-08-31 `broker_account_not_orderable` 871건은 실제 network attempt 11건과 circuit 차단 860건, 2026-09-01 811건은 실제 attempt 12건과 circuit 차단 799건이다. 두 날 모두 failure lineage는 100%이고 성공 submission은 0건이다. 지원 문의용 sanitized 증적은 `runtime-data/reports/broker-paper/kis-support-paper-orderability-evidence.md`에 둔다.

KIS 회신 또는 새로운 증거 전에는 orderability `--execute`, 다른 symbol/order type probe, 강제 cash order/cancel을 반복하지 않는다. account hard-rejection circuit도 완화하지 않고, 기존 정책에서 자연 발생한 broker submission만 관찰한다. Phase 0은 성공 submission이 확인되기 전까지 `0/10`, `waiting_first_submission`으로 유지한다.
