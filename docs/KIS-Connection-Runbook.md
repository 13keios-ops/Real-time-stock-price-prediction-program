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
- 이 저장소의 기본 cooldown은 2026-06-12부터 2시간이다.
- cooldown 중에는 broker paper sync가 KIS order-fill 조회를 건너뛰고 `cooldown_active=true`, `skipped_broker_call=true`, `retry_after_seconds`를 리포트에 남긴다.
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
| 변경 전 | order-fill rate limit 후 기본 cooldown이 30분이라 같은 장후 세션 안에서 다시 KIS 제한을 맞을 수 있었다. |
| 변경 후 | 기본 cooldown을 2시간으로 늘려 모의투자 REST 제한이 낮은 상황에서 같은 endpoint 반복 호출을 줄인다. |
| 영향 범위 | `app/services/broker_paper_sync.py`, `tests/test_broker_paper_sync.py`, 장후 paper/KIS reconciliation 운영 절차. |
| 회귀 위험 | 체결 복구가 최대 2시간 늦어질 수 있다. 대신 rate limit 연쇄와 잘못된 자동 align 위험을 줄인다. |

관련 문서/코드 경로: `app/services/broker_paper_sync.py`, `tests/test_broker_paper_sync.py`, `.agents/skills/daily-ops-check/SKILL.md`

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
4. missing_*_credentials이면 .env 존재 여부와 필수 키 shape만 확인하고 값은 출력하지 않는다.

관련 문서/코드 경로: app/services/kis_probe_errors.py, app/services/kis_token_probe.py, app/services/kis_account_probe.py, app/services/system_clock_probe.py, runtime-data/reports/live-readiness/

### 3.3. WebSocket `No close frame received`

기본 판단:

- 단발 reconnect는 장애가 아니라 관측 이벤트로 본다.
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
