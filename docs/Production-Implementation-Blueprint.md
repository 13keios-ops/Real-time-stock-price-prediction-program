# 실전 전환 구현 청사진

## 1. 목적과 범위

이 문서는 `docs/Production-Architecture.md`를 코드 작업 가능한 수준으로 쪼갠 구현 청사진이다. 초기 작성 시점은 문서 단계였지만, 2026-05-14 계좌 소유자 또는 실전 운용 승인권자 승인 후 Slice 1 read-only wrapper, Slice 2a/2b live storage 원장, Slice 3 market status 순수 로직 구현을 시작했다. 2026-05-16에는 Slice 5 live order manager의 1차 골격을 추가했고, 2026-05-17에는 Slice 5-3 성격의 `live_fills` delta 멱등 기록, Phase 2 pre-submit 정책, live fill 정합성 및 `unknown`/`stuck` 미해결 주문 dashboard/runtime report read-only 노출, Phase 2 부모 주문 한도 dashboard 카운터, live fill mismatch 신규 intent 차단, `live_fills` 기반 순수 position accounting helper, 로컬/텔레그램/이메일 alert outbox를 추가했다. 2026-05-18에는 system clock submit hook과 market data freshness submit hook을 추가했다. 2026-05-19에는 KIS WebSocket reconnect metric helper, Phase 2 기본 `max_order_qty=1` pre-submit 제한, redacted KIS paper daily order/fill runtime fixture shape 테스트를 추가했다. 2026-05-20에는 KIS WebSocket reconnect snapshot에 `observed_at`, `last_reconnect_at`, `last_stable_at`, `storm_active_since`, JSON 직렬화 helper를 추가했고, system clock reference로 HTTP `Date` header를 파싱/판정하는 helper, readiness `system_clock` fixture/CLI wrapper 평가, KIS REST 마지막 성공 응답 header 노출 지점을 추가했으며 KIS paper 현재가 read-only 조회에서 실제 `date` header를 확인했다. 2026-05-21에는 HTTP `Date` header가 timezone을 포함하지 않거나 알 수 없는 timezone이면 안전 측으로 invalid 처리하도록 잠그고, `run_live_readiness_dry_run.sh`가 외부 sanitized `system_clock` check JSON을 `--system-clock-check-path`로 받아 fixture보다 우선 병합할 수 있게 했다. 이어 `app/services/system_clock_probe.py`와 `scripts/probe_kis_clock_reference.sh`를 추가해 read-only 현재가 조회 1회에서 sanitized `system_clock` check JSON을 생성하는 wrapper를 구현했고, KIS paper probe 1회에서 `system_clock=true`, skew 약 0.167초를 확인했다. 2026-05-22에는 readiness 증거 freshness 가드, account snapshot shape drift 차단, Phase 2/3 synthetic WS recovery 거부를 readiness와 live submit guard 양쪽에 추가했고, manual market status runbook과 source enum을 추가했다. 2026-05-23에는 WS evidence enum 단일 소스화, key별 freshness 기준, manual market status symbol hash helper, HTTP Date 초 단위 정밀도 표기, dashboard WS recovery evidence 상세 표시, paper/live HTTP Date reference 비교 helper, account snapshot value type drift 차단을 추가했다. 설정값, gate 기준값, 실전 주문 활성 플래그는 바꾸지 않는다. 목표는 Phase 1 read-only부터 Phase 2 소액 실전 canary까지 필요한 모듈, 상태 전이, SQLite 초안, 테스트 잠금, 구현 순서를 명확히 하는 것이다.

이 문서에서 `제안 신규`는 각 절 작성 시점에 아직 존재하지 않는 목표 코드/테이블을 뜻한다. 2026-05-14 이후 일부 slice는 구현 완료 상태로 바뀌었으므로 최신 상태는 각 slice 구현 상태와 `docs/logbook.md`를 함께 본다. `확인 필요`는 구현 전 실제 KIS 응답, 계좌 소유자 또는 실전 운용 승인권자 정책, 또는 기존 코드 세부 확인이 필요한 항목이다. 실전 계좌번호, KIS app key, app secret, token은 본문에 적지 않는다.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Current-Implementation.md`, `app/storage/contracts.py`, `app/storage/sqlite_store.py`, `app/storage/runtime_writer.py`

## 2. 구현 순서

실전 전환 구현은 아래 순서로 쪼갠다. P0는 Phase 1 read-only 전에 필요하고, P1은 Phase 2 주문 전, P2는 Phase 3 확장 전에 필요하다.

| 우선순위 | 작업 단위 | 완료 조건 |
|---|---|---|
| P0-A | live read-only 구조적 차단 | 실전 profile로 계좌/체결 조회만 가능하고 주문/취소 메서드는 노출되지 않는다. |
| P0-B | live enable guard | live order manager와 KIS live order adapter 호출 직전에 `TRADING_MODE=live`와 `ALLOW_LIVE_ORDERS=true`를 다시 검증한다. wrapper 골격과 테스트는 구현됐고, streaming runtime 연결은 후속이다. |
| P0-C | market status snapshot | 초기 순수 판정 로직은 구현됐다. runtime/guard 연결 전까지는 fixture 기반 테스트 범위로 본다. |
| P0-D | phase/fault-injection 리포트 | Phase 1 token refresh, WS drop, stale account alert, market status snapshot, system clock skew를 강제 테스트로 통과/실패 기록한다. token refresh probe, account snapshot probe, synthetic WS recovery probe, manual market status snapshot probe, system clock helper/probe, local fixture snapshot은 구현됐고, 실제 market status snapshot 증적과 kill switch 상태 파일은 후속이다. |
| P0-E | storage 2a: 주문/상태 원장 | `market_status_snapshots`, `live_orders`, `live_order_events`와 write 메서드는 구현됐다. 운영 DB 적용은 dry-run으로 먼저 검증한다. |
| P1-A | live order manager | 1차 골격은 구현됐다. idempotency key, 상태머신, guard 호출, broker 주입형 제출/취소, 재시작 복구를 제공한다. market status, system clock, market data freshness를 submit guard 입력으로 받을 수 있다. Phase 2 기본 `max_order_qty=1` pre-submit 제한은 구현됐다. runtime/streaming/KIS live adapter 연결은 후속이다. |
| P1-B | live execution sync | 1차 mapper, `live_orders` 상태/수량 반영, `live_fills` delta 멱등 기록, `live_orders.filled_qty`와 fill 합계 정합성 검사, mismatch 신규 intent 차단은 구현됐다. redacted KIS paper runtime fixture shape 기반 HTTP 정규화와 snapshot 변환 테스트를 추가했다. 실제 KIS 조회 호출과 포지션/포트폴리오 적용은 후속이다. |
| P1-C | live audit append-only | hash chain 생성/검증 helper와 runtime report integrity 요약은 구현됐다. prediction/signal/gate/order/fill 전체 자동 연결, 운영 승인 이벤트 연결, 외부 anchor는 후속이다. |
| P1-D | dashboard/report/alert cards | readiness dry-run, WS recovery evidence 상세, live fill 정합성과 `unknown`/`stuck` 미해결 주문 dashboard/runtime report read-only 노출, Phase 2 부모 주문 한도 dashboard/runtime report 카운터, live fill mismatch/미해결 주문 status alert, 로컬/텔레그램/이메일 outbox, 동일 상태 fingerprint 중복 outbox 억제, `unknown/stuck` attention grace hook은 구현됐다. enable 상태, market status, T+2, slippage, approvals, 실제 외부 발송기, raw minute lag 연속 조건 기반 alert hysteresis는 후속이다. |
| P1-E | storage 2b: 체결/포지션/감사 원장 | `live_fills`, `live_positions`, `live_portfolio_snapshots`, audit/approval/readiness 테이블과 writer는 구현됐다. 운영 DB 적용은 dry-run으로 먼저 검증한다. |
| P2-A | 노출/손실/슬리피지 gate 구현 | 계좌 소유자 또는 실전 운용 승인권자 기준값 확정 뒤 `app/risk/` 변경 승인을 받아 구현한다. |
| P2-B | NAS recovery self-test | 재난 복구용 전체 백업과 실전 전환 검증용 sanitized recovery export를 분리한다. live-risk/alerts/approvals/ops/registry-backups 경로가 sanitized recovery export에 들어가고, `.env`/KIS token cache/runtime logs/key 파일이 제외되는지 self-test로 검증한다. 기존 NAS 전체 백업은 별도 이중 보관 체계로 유지한다. |

Phase 1 진입 전 P0 진행 상황은 아래처럼 따로 본다.

| P0 항목 | 상태 | 기준 work/review | Phase 1 진입 판단 |
|---|---|---|---|
| WS keepalive/reconnect metric | 완료. 누적/연속 reconnect, 안정 frame reset, storm, timestamp, JSON 직렬화 helper, dashboard readiness 상세 노출까지 구현 | `work_ver_12-1`, `review_ver_12`, `work_ver_13`, `work_ver_16` | 실제 KIS WS 복구 관측 evidence는 Phase 1 read-only에서 별도 수집 |
| KIS 실제 응답 fixture 검증 | 완료. redacted KIS paper fixture shape로 HTTP 정규화와 snapshot 변환 테스트 추가 | `work_ver_12-2`, `review_ver_12` | Phase 1 read-only 진입 후 live shape 비교 필요 |
| NAS recovery drill | 부분 완료. sanitized export 포함/제외 self-test 통과, export dry-run 명령 완료. 기존 NAS 전체 백업은 재난 복구용 이중 보관으로 유지한다. | `work_ver_12-3`, `review_ver_12`, `work_ver_13-1` | Phase 1용 sanitized drill 표본 확인은 별도 승인 필요 |
| reference clock 원천 | 후보 구현 완료. `system_clock`은 HTTP `Date` header를 reference timestamp로 파싱하고 곧바로 skew decision으로 바꿀 수 있으며, readiness fixture/CLI wrapper에서 skew를 평가할 수 있다. KIS REST client와 read-only wrapper는 마지막 성공 응답 header를 read-only 진단용 copy로 노출한다. live order manager는 HTTP `Date` 기반 clock decision을 필수 submit guard 입력으로 받아 통과/차단할 수 있다. 2026-05-20 KIS paper 현재가 read-only 조회 1회에서 실제 response header에 `date`가 있음을 확인했다. raw header를 저장하지 않고 sanitized readiness check result를 만드는 helper가 있다. 2026-05-21에는 timezone 없는 HTTP `Date`와 알 수 없는 timezone을 invalid로 차단하고, readiness dry-run이 `--system-clock-check-path`로 받은 sanitized check를 fixture보다 우선 병합할 수 있게 했다. `app/services/system_clock_probe.py`와 `scripts/probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 sanitized check JSON을 생성하고, `--compare-paper-live`로 paper/live reference delta를 비교할 수 있다. KIS paper probe 1회에서 `system_clock=true`, skew 약 0.167초를 확인했다. | `review_ver_12`, `work_ver_13-1`, `work_ver_13-2`, `work_ver_13-3`, `work_ver_13-4`, `work_ver_13-5`, `work_ver_13-6`, `review_ver_13`, `work_ver_14`, `work_ver_14-1`, `work_ver_16` | live account header shape와 paper/live 비교 실행 증적 확보 전에는 Phase 1 진입 차단 |

관련 문서/코드 경로: `docs/Production-Architecture.md`, `app/config/settings.py`, `app/brokers/kis_quote_rest.py`, `app/services/broker_paper_sync.py`, `app/services/dashboard.py`

## 3. 변경 제안 목록

아래 표는 구현 전 변경 단위와 회귀 위험을 고정한다.

| 제안 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| 제안 신규 `app/brokers/kis_readonly.py` | `KisRestQuoteClient`가 조회와 주문 메서드를 함께 가진다. | 실전 Phase 1은 조회 전용 client만 사용하고 주문/취소 메서드를 노출하지 않는다. | `app/brokers/`, `app/services/kis_account.py`, 테스트 | 기존 계좌 조회 코드가 client 타입을 강하게 가정하면 수정 필요. |
| 초기 구현 `app/services/live_order_guard.py`, `app/services/market_data_freshness.py`, `app/brokers/kis_live_order.py` | `ALLOW_LIVE_ORDERS`는 설정 일관성만 검증됐고, WebSocket 연결 상태와 최신 데이터 신선도는 주문 직전 guard 입력으로 분리되지 않았다. | live 주문/취소 호출 직전에 trading mode, enable flag, phase, kill switch를 검증하고, KIS client 위임 직전 enable/profile을 다시 확인한다. 선택적으로 market status, system clock, market data freshness decision을 받아 stale tick/bar/prediction이면 broker 호출 전 차단한다. | `app/services/`, `app/brokers/kis_quote_rest.py` 호출부 | guard가 paper mirroring까지 막지 않도록 mode 분리가 필요. runtime/report 최신 row를 freshness decision으로 연결하는 작업은 후속이다. |
| 초기 구현 `app/services/market_status.py` | 시간 규칙과 유니버스 제외 원칙이 문서/설정에 흩어져 있다. | 외부 API 없이 `MarketStatusSnapshot`을 입력으로 받아 종목별 차단 사유를 계산한다. 신호/게이트/주문 매니저 연결은 후속 Slice다. | `app/services/market_status.py`, `app/collectors/`, `app/services/streaming.py`, SQLite | 데이터 원천 stale이면 정상 주문도 차단될 수 있다. runtime 연결 전에는 테스트 fixture와 수동 snapshot에 한정된다. |
| 초기 구현 `app/services/system_clock.py`, `app/brokers/kis_quote_rest.py`, `app/brokers/kis_readonly.py`, `app/services/system_clock_probe.py`, `scripts/probe_kis_clock_reference.sh`, `app/services/live_order_manager.py`, `app/services/live_phase_readiness.py` | 시스템 시계 오차 허용 범위가 문서 후보로만 있었다. | local timestamp와 reference timestamp 차이가 기본 후보 `±2초` 안인지 순수 판정한다. HTTP `Date` header에서 reference timestamp를 파싱하고 clock skew decision으로 바꾸는 순수 helper를 제공하며, timezone 없는 header와 알 수 없는 timezone은 invalid로 차단한다. readiness fixture와 `run_live_readiness_dry_run.sh` wrapper에서 skew를 평가할 수 있고, wrapper는 `--system-clock-check-path`로 받은 sanitized check JSON을 fixture보다 우선 병합할 수 있다. KIS REST client와 read-only wrapper는 마지막 성공 응답 header를 read-only 진단용 copy로 노출한다. `probe_kis_system_clock_check()`와 `probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 raw header 원문 없이 readiness check result를 만든다. `probe_kis_clock_reference.sh --compare-paper-live`는 paper/live HTTP `Date` reference delta를 raw header 없이 비교한다. KIS paper probe 1회에서 `system_clock=true`, skew 약 0.167초를 확인했다. `LiveOrderGuard.assert_can_submit()`과 `LiveOrderManager.submit_intent()`는 clock decision을 필수 submit guard 입력으로 받을 수 있고, HTTP `Date` 기반 decision 통과/차단 테스트가 있다. | readiness, 주문 guard 후보 | live account header shape 확인, paper/live 비교 실행 증적, 기본 강제 여부는 후속 결정 필요. |
| 초기 구현 `app/services/live_order_manager.py` | paper 주문 생성과 broker paper sync가 분리되어 있다. | live 주문 intent, idempotency, 상태 전이, 재시작 복구를 한 서비스가 관리한다. intent 생성 전 필수 trace field, side, qty, limit price를 검증한다. Phase 2 기본 정책으로 1거래일 1개 부모 주문, 부모 주문 수량 `max_order_qty=1`, 같은 종목 pending 차단, live fill mismatch 신규 intent 차단을 `blocked` 감사 이벤트로 남긴다. 차단 detail에는 부모 주문 현재 수/한도, 주문 수량 현재값/한도 등 pre-submit context를 남긴다. 주문 manager와 execution sync가 저장하는 broker raw response/output은 KIS redaction helper로 가린다. 현재는 broker interface 주입형이며 실제 KIS live adapter 연결은 하지 않는다. | `app/services/streaming.py`, `app/storage/`, KIS adapter | idempotency/Phase 2 구조 제한이 과하면 정상 재주문도 막힐 수 있다. 상태 전이와 실제 KIS 응답 매핑은 live execution sync에서 추가 검증이 필요하다. |
| 초기 구현 `app/services/live_execution_sync.py` | 실전 체결 동기화 원장이 없다. | KIS live 주문/체결 조회 record를 live 주문 상태와 delta fill로 해석하고, `live_orders` status/filled/remaining/avg_fill, `live_order_events`, `live_fills` delta 기록까지 반영한다. 포지션/포트폴리오/세금 정산 적용은 후속이다. | `app/services/`, `app/storage/` | 체결 delta 계산 오류가 포지션을 왜곡할 수 있다. 실제 KIS 응답 필드 차이는 추가 fixture가 필요하다. |
| 초기 구현 `app/services/live_audit.py` | prediction/signal/order 연결이 흩어져 있다. | live 의사결정 감사 event를 append-only hash chain으로 생성/검증한다. `prediction_id`, `signal_id`, `gate_decision_id`, `rule_version`, `model_version`, `data_snapshot_id`, `previous_hash` 같은 필수 trace field가 비어 있으면 event build를 거부한다. 현재는 RuntimeWriter/SQLite 기반 helper와 runtime report read-only 검증이며, 주문 경로 전체 자동 연결과 외부 anchor는 후속이다. | `app/storage/`, `runtime-data/ops/`, `app/services/reporting.py` | audit 저장 실패 시 주문 차단 정책을 정해야 한다. |
| 초기 구현 `app/services/live_alerting.py` | dashboard와 runtime report 안에서만 사고를 확인한다. | live fill mismatch와 unknown/stuck 주문을 로컬/텔레그램/이메일 outbox로 routing한다. 같은 event type/trading day/state fingerprint의 동일 alert는 같은 날짜 outbox에 중복 기록하지 않는다. unknown/stuck payload는 선택적 `attention_grace_minutes` 안이면 alert 생성을 미룰 수 있다. outbox JSONL의 `detail_json`은 저장 직전에 KIS redaction helper로 계좌/토큰/app secret 계열 key를 가린다. 실제 발송기는 후속이며 비밀값은 문서/저장소에 쓰지 않는다. | `app/services/reporting.py`, `runtime-data/reports/alerts/`, dashboard, 운영 스크립트 | outbox만 있는 동안에는 실제 외부 알림이 발송되지 않는다. message/title 같은 자유 텍스트 redaction, raw minute lag 연속 조건 hysteresis, escalation sender는 별도 slice가 필요하다. |
| 초기 구현 `app/brokers/kis_response_redaction.py` | KIS 실제 응답 fixture를 받을 때 비밀값 제거 절차가 수동이다. | JSON payload에서 token, app key/secret, 계좌번호, 계좌상품코드, 고객 식별값을 redaction하고 주문번호/종목코드/수량/가격 필드는 유지한다. | `tests/test_kis_response_redaction.py`, `tests/test_kis_http_clients.py` | key 기반 redaction이므로 새로운 민감 필드명은 fixture 반영 전 사람이 한 번 검토해야 한다. |
| 초기 구현 `app/services/live_phase_readiness.py`, `app/services/ws_recovery_evidence.py`, `app/services/kis_token_probe.py`, `app/services/kis_account_probe.py`, `app/services/kis_ws_recovery_probe.py`, `app/services/market_status_probe.py`, `app/services/live_readiness_fixture.py`, `scripts/probe_kis_token_refresh.sh`, `scripts/probe_kis_account_snapshot.sh`, `scripts/probe_kis_ws_recovery.sh`, `scripts/probe_market_status_snapshot.sh`, `scripts/build_live_readiness_fixture_snapshot.sh`, `app/services/dashboard.py` | phase 통과 조건이 문서에만 있었다. | phase approval hash와 readiness run record를 생성한다. token refresh probe는 KIS auth-only refresh 결과를 token 원문 없이 sanitized check로 저장한다. account snapshot probe는 KIS 계좌 snapshot 조회 결과를 계좌번호 없이 sanitized check로 저장하며 필수 shape 누락과 값 타입 drift를 차단한다. synthetic WS recovery probe는 실제 WebSocket을 열지 않고 reconnect metric 상태 전이를 fault injection으로 검증한다. 실제 WS evidence type은 `app/services/ws_recovery_evidence.py`에서 단일 정의한다. manual market status snapshot probe는 repo 내부 snapshot을 순수 판정 로직으로 평가해 sanitized check를 만들고, `source`를 `manual_operator_snapshot`, `manual_krx_snapshot`, `manual_kis_snapshot`으로 제한한다. `symbol_set_hash`는 sorted symbol list의 SHA-256 prefix로 검증한다. local fixture snapshot은 premarket report, token refresh check, account snapshot check, synthetic WS recovery check, market status check, system clock check, kill switch 상태를 읽어 로컬로 증명 가능한 항목만 fixture로 묶는다. market status check 파일이 없으면 자동 통과시키지 않는다. timestamp가 있는 핵심 증거는 key별 freshness 기준을 넘으면 stale로 차단한다. 현재 기준은 `system_clock/ws_recovery=30분`, `account_snapshot/market_status=1시간`, `token_refresh=4시간`이다. Phase 2/3 readiness와 live submit guard는 synthetic WS recovery를 실전 제출 증거로 인정하지 않는다. dashboard live readiness 카드는 WS recovery evidence type/실제 증거 여부/freshness/stable frame/reconnect storm을 표시한다. | `app/storage/`, `runtime-data/reports/live-readiness/`, dashboard | 자동 평가 기준이 과하면 phase 전환이 과도하게 막힌다. synthetic WS check는 네트워크 복구 증거가 아니므로 Phase 1 관측 전에는 submit guard 기준으로 쓰지 않는다. manual market status snapshot은 데이터 원천 결정을 대신하지 못하므로 KIS/거래소 자동 원천은 별도 slice로 남긴다. 증거 없는 항목을 통과시키면 false positive가 생기므로 absent/not_verified 유지가 기본이다. |
| 초기 구현 `app/services/codex_ops.py`, `scripts/run_codex_ops_job.sh` | Codex CLI 운영 자동화가 설계 문구에만 있었다. | job manifest, 장 상태별 권한 모델, action allow/deny, backup/cleanup 정책, premarket-readiness dry-run report wrapper를 구현한다. 실제 Codex CLI 호출은 아직 하지 않는다. | `runtime-data/reports/codex/ops/`, `.tmp-tests/codex-ops/`, scripts | manifest가 과하면 운영 보조가 막히고, 느슨하면 장중 보호 규칙을 우회할 수 있다. |
| 제안 신규 `app/services/live_kill_switch.py` | kill switch 상태 파일 형식과 관리 주체가 문서화되지 않았다. | `runtime-data/reports/live-risk/kill-switch.json` 후보 파일을 atomic write로 관리하고 guard가 같은 schema를 읽는다. | `app/services/live_order_guard.py`, `runtime-data/reports/live-risk/`, dashboard | 파일 stale 또는 손상 시 신규 주문을 과도하게 차단할 수 있다. |

관련 문서/코드 경로: `app/brokers/kis_quote_rest.py`, `app/services/broker_paper.py`, `app/services/streaming.py`, `app/storage/runtime_writer.py`

## 4. Phase 1 read-only 설계

Phase 1의 기본 후보는 `KisReadOnlyClient`다. 이 client는 live profile을 받을 수 있지만 주문/취소 메서드를 아예 제공하지 않는다. 계좌 조회, 주문/체결 조회, 현재가/호가 조회처럼 읽기 작업만 허용한다.

제안 인터페이스:

```text
class KisReadOnlyClient:
    get_current_price(symbol, market_code="J")
    get_orderbook(symbol, market_code="J")
    get_intraday_minute_chart(symbol, ...)
    get_account_balance(...)
    get_daily_order_fills(...)
```

금지 인터페이스:

```text
submit_cash_order(...)
cancel_order(...)
```

현재 코드 기준으로 `KisRestQuoteClient`에는 조회 메서드 `get_current_price`, `get_orderbook`, `get_intraday_minute_chart`, `get_account_balance`, `get_daily_order_fills`가 있고, 주문/취소 메서드 `submit_cash_order`, `cancel_order`가 같은 class에 함께 있다. Slice 1은 이 class의 동작을 바꾸기보다 composition wrapper로 조회 메서드만 노출한다. 실제 코드 위치는 `app/brokers/kis_quote_rest.py`의 조회 메서드 영역과 주문/취소 메서드 영역이다.

composition 가능성은 현재 `KisRestQuoteClient.__init__`가 `KisAuthProfile`, `KisTokenManager`, timeout을 인자로 받는 구조라는 점을 기준으로 한 설계 후보이며, Slice 1 시작 시 실제 초기화 side effect와 session 보유 여부를 다시 확인한다. composition이 불가능하면 Slice 1은 상속이 아니라 factory 차단 또는 adapter protocol로 재설계한다.

read-only wrapper 공개 메서드 후보:

```text
get_current_price(symbol: str, market_code: str = "J")
get_orderbook(symbol: str, market_code: str = "J")
get_intraday_minute_chart(
    symbol: str,
    *,
    input_hour: str = "153000",
    market_code: str = "J",
    include_past_data: bool = True,
)
get_account_balance(*, inqr_dvsn: str = "02", max_pages: int = 10)
get_daily_order_fills(
    *,
    start_date: str,
    end_date: str,
    symbol: str = "",
    order_no: str = "",
    side_filter: str = "00",
    filled_filter: str = "00",
    order_filter_3: str = "00",
    order_filter_1: str = "",
    exchange_code: str = "KRX",
    max_pages: int = 10,
)
```

직접 `KisRestQuoteClient(`를 생성하는 경로는 2026-07-10 기준 아래 두 경계로 축소했다. 조회 전용 흐름은 원본 클라이언트를 직접 생성하지 않는다.

| 경로 | mode 원천 | 호출 메서드 카테고리 | Phase 1 처리 |
|---|---|---|---|
| `app/brokers/kis_readonly.py` | 명시적 `paper/live` | 조회 메서드만 공개하는 내부 delegate | 조회 전용 client를 만드는 유일한 경계 |
| `app/services/broker_paper.py` | `get_kis_profile(settings, "paper")` | paper 주문/조회 | KIS 모의계좌 mirroring 전용 예외 |

`app/collectors/historical.py`, `app/services/runtime.py`, `app/services/collector.py`, `app/services/kis_account.py`, `app/__main__.py`의 현재가·호가·과거분봉·계좌 조회는 모두 `get_kis_readonly_client`를 사용한다.

allowlist 정책:

- direct constructor allowlist는 `app/brokers/kis_readonly.py`와 paper mirroring 경계만 허용한다.
- paper mirroring용 `app/services/broker_paper.py`는 paper profile 전용 예외로 남긴다.
- 새 조회 전용 경로는 `tests/test_live_client_isolation.py`에서 read-only factory 사용과 direct constructor 부재를 함께 확인한다.
- 문자열 기반 static check는 의도적 dynamic import, subclass, `getattr` 우회까지 자동 차단하지 않으며, 그런 우회는 코드 리뷰와 보안 리뷰에서 잡는다.

Phase 1 구현 원칙:

- `get_kis_profile(settings, "live")`는 가능하지만 이를 바로 주문 가능 client에 넣지 않는다.
- Phase 1 서비스는 반드시 `KisReadOnlyClient` 또는 같은 책임의 wrapper를 통해서만 live profile을 사용한다.
- `ALLOW_LIVE_ORDERS=false`는 두 번째 방어선이다. 1차 방어선은 주문 메서드가 없는 구조다.
- tests에서 `hasattr(readonly_client, "submit_cash_order") == False`를 확인한다. Codex 권장안은 hard fail 메서드가 아니라 메서드 미노출이다.
- `get_kis_readonly_client`는 paper/live 조회에 공통 사용하고, `get_kis_live_readonly_client`는 live 전용 호출만 허용한다.
- paper/live 계좌 shape 비교는 `scripts/compare_kis_account_snapshot_checks.sh`가 별도 저장된 sanitized check 두 개만 읽어 수행한다.
- `scripts/run_phase1b_readonly_observation.sh` 기본 실행은 네트워크 0회 사전검사다. `--execute`를 명시한 경우에만 live token refresh 1회, paper/live account snapshot 각 최대 1페이지, live current-price 기반 clock check 1회를 순차 실행하며 앞 단계 실패 시 뒤 호출을 중단하고 `pre-open`/`regular-session`은 네트워크 시작 전에 차단한다. system clock은 token/account 단계의 소요시간이 skew에 섞이지 않도록 quote 직전 UTC 시각을 사용한다.
- 실행 결과는 `runtime-data/reports/live-readiness/phase1b/`에 preflight/attempt/observation을 서로 다른 파일로 저장하고 raw response, 계좌 식별자, 자격정보 값을 넣지 않는다.
- fault injection은 실제 장애가 우연히 발생하기를 기다리지 않고 token refresh, WS drop, stale account snapshot을 강제로 만든다.

Slice 1 acceptance criteria:

| 기준 | 테스트/확인 후보 | 통과 조건 |
|---|---|---|
| 주문 메서드 미노출 | `tests/test_live_readonly_guard.py::test_readonly_client_does_not_expose_order_methods` | `submit_cash_order`, `cancel_order` attribute가 없다. |
| 시그니처 동등성 | `tests/test_live_readonly_guard.py::test_readonly_method_signatures_match_delegate` | `inspect.signature` 기준으로 공개 조회 메서드가 delegate 메서드와 호환된다. |
| 조회 메서드 위임 | `tests/test_live_readonly_guard.py::test_readonly_client_delegates_quote_and_account_reads` | 공개 조회 메서드가 내부 client의 같은 메서드를 호출하고 반환값을 변형하지 않는다. |
| live 전용 factory | `tests/test_live_readonly_guard.py::test_live_readonly_factory_uses_live_profile_only` | factory가 `get_kis_profile(settings, "live")`만 사용한다. |
| factory negative | `tests/test_live_readonly_guard.py::test_live_readonly_factory_rejects_non_live_mode` | paper 또는 알 수 없는 mode를 받는 API가 생기면 명시적으로 실패한다. |
| import-time 부작용 없음 | `tests/test_live_readonly_guard.py::test_import_does_not_trigger_network` | `app.brokers.kis_readonly` import만으로 token 발급, hashkey 발급, REST 호출이 발생하지 않는다. |
| paper mirroring 불변 | `tests/test_live_client_isolation.py::test_paper_mirroring_still_uses_paper_profile` | `app/services/broker_paper.py`의 paper profile 생성 경로를 readonly wrapper로 바꾸지 않는다. |
| 우회 경로 잠금 | `tests/test_live_client_isolation.py::test_live_readonly_paths_do_not_bypass_wrapper` | direct `KisRestQuoteClient(` 생성은 read-only factory와 paper mirroring 경계만 허용한다. |
| 조회 흐름 고정 | `tests/test_live_client_isolation.py::test_query_only_kis_paths_use_readonly_factory` | 조회 전용 5개 경로가 read-only factory를 사용한다. |
| 비밀값 노출 없음 | 코드 리뷰 체크 | test fixture와 assert message에 app key, app secret, token, 계좌번호를 쓰지 않는다. |

Slice 1 테스트 fixture 원칙:

- 실제 KIS 네트워크를 호출하지 않는다.
- `KisRestQuoteClient` 내부 delegate는 fake object 또는 `unittest.mock.Mock`으로 대체한다.
- `KisAuthProfile` fixture는 비어 있거나 dummy 값을 쓰되, 실제 계좌번호와 토큰은 쓰지 않는다.
- allowlist static check는 문자열 검색 기반으로 시작하되, Windows/WSL 경로 차이에 흔들리지 않도록 repository root 기준 상대 경로만 비교한다.
- Slice 1 검증 명령 후보: `python -m unittest tests.test_live_readonly_guard tests.test_live_client_isolation tests.test_kis_http_clients tests.test_settings`

관련 문서/코드 경로: `app/brokers/kis_auth.py`, `app/brokers/kis_quote_rest.py`, `app/services/kis_account.py`, `tests/test_kis_http_clients.py`, `tests/test_settings.py`

## 5. Live order 상태머신

실전 주문은 paper 상태를 그대로 복사하지 않고 live 전용 상태머신을 둔다.

| 상태 | 의미 | 진입 조건 | 허용 전이 | 기본 동작 |
|---|---|---|---|---|
| `intent_created` | 주문 의도 생성 | signal/gate 통과 뒤 주문 intent 저장 | `blocked`, `submit_pending` | 아직 브로커 전송 전이므로 실패 시 안전 |
| `blocked` | 주문 차단 | enable/market/risk/idempotency/order type fail | 없음 | 신규 주문 없음, audit 기록 |
| `submit_pending` | 브로커 제출 직전 | idempotency key 확보, 최종 guard 통과 | `submitted`, `unknown` | 제출 중 예외면 `unknown` 후보 |
| `submitted` | REST 제출 응답 수신 | KIS 주문 응답에 broker order id 존재 | `accepted`, `open`, `rejected`, `unknown` | 즉시 조회 예약 |
| `accepted` | 브로커 접수 확인 | 주문 조회에서 접수 확인 | `open`, `partially_filled`, `filled`, `cancel_requested`, `rejected`, `unknown` | 신규 같은 종목 주문 차단 |
| `open` | 미체결 잔량 있음 | remaining_qty > 0 | `partially_filled`, `filled`, `cancel_requested`, `stuck`, `unknown` | Phase 2 동일 종목 신규 주문 차단 |
| `partially_filled` | 일부 체결 | filled_qty > 0 and remaining_qty > 0 | `filled`, `cancel_requested`, `cancelled_partial`, `stuck`, `unknown` | delta fill만 반영, 잔량 정책 적용 |
| `filled` | 전량 체결 | filled_qty >= order_qty | 없음 | 포지션/회계 반영 |
| `cancel_requested` | 취소 요청 제출 | cancel-only guard 통과 | `cancelled`, `cancelled_partial`, `filled`, `unknown` | 재조회 필수 |
| `cancelled` | 미체결 취소 완료 | cancel confirmed and filled_qty == 0 | 없음 | 신규 허용 여부는 gate가 다시 판단 |
| `cancelled_partial` | 일부 체결 후 잔량 취소 | cancel confirmed and filled_qty > 0 | 없음 | 체결분만 포지션 반영 |
| `expired` | 장 종료 또는 주문 유효기간 만료 | 브로커 조회에서 미체결 주문 만료 확인 | 없음 | 사람 취소와 구분해 audit 기록 |
| `rejected` | 브로커 거절 | reject_qty 또는 KIS reject 응답 | 없음 | 재주문 금지, 원인 audit |
| `stuck` | 장시간 open/unknown | age threshold 초과 | `cancel_requested`, `unknown`, `filled` | 신규 주문 차단, 사람 호출 |
| `unknown` | 제출/취소/조회 결과 불명 | timeout, DB lock, network split | `accepted`, `open`, `filled`, `cancelled`, `expired`, `rejected`, `stuck` | 신규 주문 차단, 조회 우선 |

정정 정책:

- KIS 주문 정정 API는 확인 필요지만, Phase 2에서는 정정(modify)을 금지한다.
- 가격/수량 변경은 `cancel_requested` -> `cancelled` 또는 `cancelled_partial` 확인 뒤 새 주문 intent로만 처리한다.
- Phase 3에서 정정을 허용하려면 `modify_requested`, `modified` 상태와 `parent_order_id` 기반 chain을 별도 slice로 추가한다.

전이 금지:

- `filled`, `cancelled`, `cancelled_partial`, `expired`, `rejected`에서 다시 open 상태로 되돌리지 않는다.
- `unknown` 상태에서 idempotency key가 같은 신규 주문을 만들지 않는다.
- `kill switch` 상태에서 신규 위험 증가 주문으로 전이하지 않는다.
- Phase 2에서 같은 거래일 같은 종목에 `open`, `partially_filled`, `unknown`, `stuck`이 있으면 새 부모 주문을 만들지 않는다.
- VI 발동 중 KIS가 미체결 주문을 어떤 상태로 반환하는지는 확인 필요이며, 확인 전 기본 동작은 신규 차단과 조회 보류다.

관련 문서/코드 경로: `app/services/broker_paper_sync.py`, `app/storage/contracts.py`, `docs/Order-Lifecycle.md`

## 6. Idempotency와 재시작 복구

idempotency key는 같은 신호가 재시작 뒤 중복 주문으로 이어지는 것을 막는 키다. 초안은 아래 필드를 정규화해 만든다.

```text
sha256(
  trading_day,
  phase,
  symbol,
  side,
  order_type,
  qty,
  limit_price_tick,
  prediction_id,
  signal_id,
  target_id,
  model_version,
  rule_version,
  gate_decision_id
)
```

규칙:

- `idempotency_key`는 `live_orders`에서 unique여야 한다.
- 같은 key가 이미 `intent_created`, `submit_pending`, `submitted`, `accepted`, `open`, `partially_filled`, `unknown`, `stuck`이면 새 주문을 차단한다.
- 같은 key가 `blocked`이면 차단 사유가 바뀌지 않는 한 새 주문을 만들지 않는다.
- 같은 key가 final 상태여도 같은 거래일 재주문은 계좌 소유자 또는 실전 운용 승인권자 승인 없이는 금지한다. 이 정책은 Phase 2 기준이며 Phase 3에서 완화 여부 확인 필요다.
- 재시작 시 `live_orders`에서 open 계열 상태를 먼저 조회하고 KIS live 주문/체결 조회로 복구한 뒤에만 새 신호 처리를 시작한다. `app/services/live_order_manager.py`는 open 계열 주문을 `unknown`으로 잠그는 1차 복구 메서드를 갖지만, 현재 `app/services/streaming.py` 재시작 흐름에는 아직 연결되지 않았다.
- `blocked`는 terminal이다. 같은 idempotency key로는 retry하지 않으며, 차단 사유 해제 뒤 재시도하려면 새 `prediction_id` 또는 `signal_id`를 가진 새 intent가 필요하다.
- Phase 2 기본 pre-submit 정책은 1거래일 1개 부모 주문서, 부모 주문 수량 기본 `max_order_qty=1`, 같은 종목 pending 차단, live fill mismatch 신규 intent 차단이다. 이 제한은 `app/services/live_order_manager.py`에서 `intent_created -> blocked` 전이와 `pre_submit_policy_blocked` event로 기록한다. 2026-05-17 보강으로 `phase2_canary`도 같은 기본 정책 대상에 포함하고, 차단 detail에 부모 주문 현재 수/한도와 mismatch 수 같은 `pre_submit_policy_context`를 남긴다. 2026-05-19 보강으로 수량 초과 차단은 `phase2_order_qty_limit_exceeded` 사유와 `{current, limit}` context를 남긴다.
- Phase 2에서 부분 체결 잔량이 있으면 같은 종목 신규 부모 주문은 차단한다. 잔량 취소는 cancel-only guard와 사람 승인 절차로 분리한다.

관련 문서/코드 경로: `app/services/streaming.py`, `app/services/broker_paper_sync.py`, `app/storage/sqlite_store.py`

## 7. Market status와 주문 타입 정책

`market_status_snapshot`은 주문 전 필터와 감사 로그가 같은 시장 상태를 참조하게 만드는 snapshot이다.

필수 상태:

- 거래일, 장 상태, 휴장/거래시간 변경.
- 종목별 거래정지, 관리종목, 투자유의.
- 상한가/하한가 또는 가격제한 근접 상태.
- VI(변동성완화장치) 발동/해제, 동적/정적 구분은 데이터 원천 확인 필요.
- 시초가/종가 동시호가, 시간외 단일가 구간.
- 권리락, 배당락, 액면분할, 유상증자 같은 corporate action.

주문 타입 정책 초안:

| 상황 | 기본 주문 타입 | 정책 |
|---|---|---|
| Phase 1 | 없음 | 주문 자체 금지 |
| Phase 2 신규 진입 | 지정가 | 시장가 금지 |
| Phase 2 잔량 취소 | 취소 | cancel-only guard 필요 |
| Phase 2 비상 청산 | 확인 필요 | 시장가 후보이나 계좌 소유자 또는 실전 운용 승인권자 승인 필요 |
| VI/동시호가 | 없음 | 신규 주문 금지 후보 |
| Phase 3 신규 진입 | 지정가 기본 | 시장가 허용 여부는 계좌 소유자 또는 실전 운용 승인권자 결정 |

데이터 원천 후보는 KIS REST, 한국거래소 OpenAPI, 계좌 소유자 또는 실전 운용 승인권자 수동 calendar다. 구현 전에는 실제 API 응답 필드와 사용 가능 시간, 호출 제한을 확인해야 한다.

Kill switch 상태 파일 초안:

- 제안 신규 파일 후보: `runtime-data/reports/live-risk/kill-switch.json`
- 제안 신규 관리 책임: `app/services/live_kill_switch.py`
- 제안 신규 관리 명령 후보: `scripts/live_kill_switch.py` 또는 기존 `python -m app` 하위 명령. 실제 배치는 구현 전 결정한다.
- 파일 쓰기는 임시 파일에 기록한 뒤 atomic replace로 교체한다.
- 파일을 읽을 수 없거나 JSON schema가 깨졌거나 `stale_after`가 지난 경우 기본값은 신규 주문 차단이다.
- kill switch ON 상태에서도 cancel-only guard를 통과한 취소 요청은 허용 후보로 둔다.

제안 schema:

```json
{
  "enabled": true,
  "reason": "manual_or_limit_or_health",
  "actor": "account_owner_or_system",
  "created_at": "ISO-8601",
  "stale_after": "ISO-8601",
  "scope": "all|symbol",
  "symbol": "",
  "allow_cancel_only": true,
  "event_hash": "sha256"
}
```

관련 문서/코드 경로: `docs/Market-Schedule-Rules.md`, `docs/Universe-Freeze-Policy.md`, `docs/Market-Data-Policy.md`, `config/market_calendar.toml`, `app/brokers/kis_quote_rest.py`

## 8. SQLite와 dataclass 초안

기존 패턴은 `app/storage/contracts.py` dataclass, `RuntimeWriter`, `SQLiteRuntimeStore` 테이블/쓰기 메서드다. 실전 전환도 같은 패턴을 따른다.

구현 anchor:

- `app/storage/contracts.py`: 기존 `RecordMixin` dataclass 패턴을 따라 live dataclass를 추가한다.
- `app/storage/sqlite_store.py`: `SQLiteRuntimeStore._initialize_schema()`에 live 테이블과 index를 추가하고, `_run_write_query()` / `_run_write_many()` 패턴으로 insert/upsert 메서드를 둔다.
- `app/storage/runtime_writer.py`: `write_live_order`, `write_live_order_event`, `write_live_fill`, `write_live_position`, `write_live_portfolio_snapshot`, `write_live_audit_event`, `write_live_phase_approval` 후보를 추가한다.
- JSONL 경로는 기존 관례에 맞춰 `live`, `ops`, `broker` namespace 후보로 나누되, 실제 경로는 구현 전 한 번 더 확인한다.

핵심 규약:

- `RecordMixin.to_record()`는 dataclass 필드를 dict로 바꾸고 `datetime`은 ISO-8601 문자열로 직렬화한다.
- SQLite schema는 `SQLiteRuntimeStore._initialize_schema()`의 `CREATE TABLE IF NOT EXISTS` 목록에 추가한다.
- 기존 테이블/컬럼 삭제나 타입 변경은 하지 않는다. 새 테이블과 새 index 추가를 기본으로 한다.
- 기존 운영 DB에 적용할 때는 live runtime/dashboard/runtime watchdog 정지, SQLite native backup, schema 초기화, table/index 및 sample insert/read/delete smoke check, 재기동 순서로 dry-run한다.
- SQLite는 컬럼 변경/삭제가 제한적이므로 Slice 2a에서 core 필드를 충분히 확정하고, 이후 추가 필드는 새 컬럼 추가만 허용한다.

제안 신규 dataclass:

- `MarketStatusSnapshot`
- `LiveOrder`
- `LiveOrderEvent`
- `LiveFill`
- `LivePosition`
- `LivePortfolioSnapshot`
- `LiveAuditEvent`
- `LivePhaseApproval`
- `LiveReadinessRun`

Slice 2a dataclass 필드 초안:

```text
MarketStatusSnapshot(
    snapshot_id: str,
    trading_day: str,
    created_at: datetime,
    source: str,
    symbol_set_hash: str,
    status_json: dict[str, object],
    stale_after: datetime,
)

LiveOrder(
    order_id: str,
    idempotency_key: str,
    trading_day: str,
    phase: str,
    symbol: str,
    side: str,
    qty: int,
    filled_qty: int,
    remaining_qty: int,
    order_type: str,
    limit_price: float,
    avg_fill_price: float,
    status: str,
    prediction_id: str,
    signal_id: str,
    target_id: str,
    gate_decision_id: str,
    market_status_snapshot_id: str,
    model_version: str,
    rule_version: str,
    broker_order_no: str,
    broker_branch_no: str,
    reject_reason: str | None,
    cancel_reason: str | None,
    parent_order_id: str | None,
    created_at: datetime,
    submitted_at: datetime | None,
    last_synced_at: datetime | None,
    detail_json: dict[str, object],
)

LiveOrderEvent(
    order_event_id: str,
    order_id: str,
    event_time: datetime,
    from_status: str,
    to_status: str,
    event_type: str,
    actor: str,
    detail_json: dict[str, object],
)
```

Slice 2a의 `broker_order_no`, `broker_branch_no`는 브로커 응답 전에도 빈 문자열을 넣어 `NOT NULL`을 유지한다. `reject_reason`, `cancel_reason`, `parent_order_id`는 사유/부모 주문이 없는 정상 상태와 아직 정보가 없는 상태를 구분하기 위해 nullable로 둔다. 시간 필드는 기존 `RecordMixin.to_record()` 직렬화 규칙을 따른다.

Slice 2a 최소 JSON 규약:

- `market_status_snapshots.status_json`: `symbols`, `market_session`, `source_generated_at` 키를 포함한다.
- `live_orders.detail_json`: `order_policy`, `blocking_reasons`, `raw_broker_response` 키를 포함한다. 브로커 전송 전이면 `raw_broker_response`는 빈 dict 후보.
- `live_order_events.detail_json`: `reason`, `source`, `raw_broker_response` 키를 포함한다.

표준 actor 값 후보:

- `system`
- `account_owner`
- `recovery`
- `kill_switch`
- `test`

`codex` actor는 운영 감사 원장에 섞이지 않도록 2026-05-15 `review_ver_4` 반영 때 제거했다. 테스트 fixture나 migration 진단은 `test` 또는 `system` actor를 쓴다.

Slice 2a acceptance criteria:

| 기준 | 테스트/확인 후보 | 통과 조건 |
|---|---|---|
| dataclass 직렬화 | storage 단위 테스트 | `MarketStatusSnapshot`, `LiveOrder`, `LiveOrderEvent`의 `to_record()`가 datetime을 ISO-8601 문자열로 바꾼다. |
| dataclass-schema 정합성 | `test_live_order_dataclass_matches_schema` 후보 | dataclass 필드가 SQL insert 대상 컬럼과 일치하고, NOT NULL 컬럼을 빠짐없이 채운다. |
| schema 추가 | schema smoke query | 새 테이블 3개와 관련 index가 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`로 생성된다. |
| 기존 paper 불변 | `tests/test_broker_paper_sync.py`, `tests/test_paper_reconciliation.py` | 기존 paper 주문/체결/포지션 write 경로가 깨지지 않는다. |
| unique idempotency | storage 단위 테스트 | 같은 `idempotency_key`의 `live_orders` 중복 insert가 실패한다. |
| JSON 최소 키 | storage 단위 테스트 | `status_json`, `detail_json`에 최소 키가 없으면 fixture 생성 또는 writer가 실패한다. |
| actor 표준값 | storage 단위 테스트 | `live_order_events.actor`가 표준 actor 값 후보 밖이면 실패한다. |
| open order 조회 준비 | storage 단위 테스트 | status/symbol/trading_day index로 open 계열 주문을 조회할 수 있다. |
| migration dry-run | 수동 검증 절차 또는 스크립트 후보 | backup 뒤 schema 초기화와 smoke query가 기존 DB를 파괴하지 않는다. |

Migration dry-run 자동화 후보:

- 제안 신규 스크립트 후보: `scripts/run_storage_migration_dry_run.sh`
- 기본 순서: live runtime/dashboard 정지 확인 -> DB backup -> schema 초기화 -> smoke query -> backup 보존 확인 -> 재기동은 사람이 별도 수행.
- 이 스크립트는 Slice 2a 구현 범위에 반드시 포함하지 않아도 되지만, 운영 DB 적용 전에는 필요하다.

Slice 2a smoke query 후보:

```sql
SELECT name FROM sqlite_master
WHERE type = 'table'
  AND name IN ('market_status_snapshots', 'live_orders', 'live_order_events');
```

```sql
SELECT order_id, status, symbol, trading_day
FROM live_orders
WHERE status IN ('intent_created', 'submit_pending', 'submitted', 'accepted', 'open', 'partially_filled', 'unknown', 'stuck')
ORDER BY created_at ASC;
```

```sql
SELECT snapshot_id, trading_day, symbol_set_hash, stale_after
FROM market_status_snapshots
ORDER BY created_at DESC
LIMIT 1;
```

제안 신규 테이블:

```sql
CREATE TABLE IF NOT EXISTS market_status_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    trading_day TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol_set_hash TEXT NOT NULL,
    status_json TEXT NOT NULL,
    stale_after TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_orders (
    order_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    trading_day TEXT NOT NULL,
    phase TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    filled_qty INTEGER NOT NULL,
    remaining_qty INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    limit_price REAL NOT NULL,
    avg_fill_price REAL NOT NULL,
    status TEXT NOT NULL,
    prediction_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    gate_decision_id TEXT NOT NULL,
    market_status_snapshot_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    broker_order_no TEXT NOT NULL,
    broker_branch_no TEXT NOT NULL,
    reject_reason TEXT,
    cancel_reason TEXT,
    parent_order_id TEXT,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    last_synced_at TEXT,
    detail_json TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_order_events (
    order_event_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    broker_order_no TEXT NOT NULL,
    broker_branch_no TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    event_time TEXT NOT NULL,
    side TEXT NOT NULL,
    fill_qty INTEGER NOT NULL,
    fill_price REAL NOT NULL,
    commission REAL NOT NULL,
    tax REAL NOT NULL,
    fee REAL NOT NULL,
    settlement_day TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_positions (
    symbol TEXT PRIMARY KEY,
    opened_at TEXT,
    updated_at TEXT NOT NULL,
    qty INTEGER NOT NULL,
    avg_price REAL NOT NULL,
    last_price REAL NOT NULL,
    market_value REAL NOT NULL,
    cost_basis REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    unsettled_cash_delta REAL NOT NULL,
    orderable_qty INTEGER NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    event_time TEXT NOT NULL,
    cash_balance REAL NOT NULL,
    orderable_cash REAL NOT NULL,
    unsettled_cash REAL NOT NULL,
    gross_market_value REAL NOT NULL,
    net_liquidation_value REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    source TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS ops_live_audit_events (
    audit_event_id TEXT PRIMARY KEY,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    chain_id TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_phase_approvals (
    approval_id TEXT PRIMARY KEY,
    event_time TEXT NOT NULL,
    phase TEXT NOT NULL,
    approver TEXT NOT NULL,
    approval_type TEXT NOT NULL,
    valid_for_trading_day TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    event_hash TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS live_readiness_runs (
    run_id TEXT PRIMARY KEY,
    event_time TEXT NOT NULL,
    phase TEXT NOT NULL,
    check_type TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT NOT NULL,
    report_path TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
```

권장 index:

- `idx_market_status_day_hash(trading_day, symbol_set_hash)`
- `idx_live_orders_status_symbol_day(status, symbol, trading_day)`
- `idx_live_orders_broker(broker_branch_no, broker_order_no)`
- `idx_live_orders_parent(parent_order_id)`
- `idx_live_order_events_order_time(order_id, event_time)`
- `idx_live_fills_order_time(order_id, event_time)`
- `idx_live_readiness_runs_day_phase(trading_day, phase)`
- `idx_ops_live_audit_order_time(order_id, event_time)`
- `idx_ops_live_audit_hash(event_hash)`

관련 문서/코드 경로: `app/storage/contracts.py`, `app/storage/sqlite_store.py`, `app/storage/runtime_writer.py`

## 9. Service interface 초안

제안 신규 `app/services/live_order_guard.py`:

```text
LiveOrderGuard.assert_readonly(settings, phase)
LiveOrderGuard.assert_can_submit(settings, phase, profile_mode, kill_switch_state)
LiveOrderGuard.assert_can_cancel(settings, phase, profile_mode, kill_switch_state)
```

초기 구현 `app/services/live_order_manager.py`:

```text
LiveOrderManager.create_intent(request)
LiveOrderManager.submit_intent(order_id, settings, profile_mode, kill_switch_state, market_status_decision, phase_approved, broker)
LiveOrderManager.request_cancel(order_id, reason)
LiveOrderManager.recover_open_orders()
LiveOrderManager.mark_unknown(order_id, reason)
```

2026-05-17 기준 구현은 `LiveOrderGuard`를 첫 caller로 사용하고, 실제 브로커는 `submit_cash_order`/`cancel_order` protocol을 만족하는 객체를 외부에서 주입받는다. 따라서 이 slice 자체가 KIS live client를 생성하거나 실전 주문 endpoint를 직접 선택하지 않는다. `submit_pending` 이후 broker 응답이 곧바로 `accepted` 또는 `open`을 암시하면 내부 이벤트는 `submitted`를 먼저 기록한 뒤 다음 상태로 전이한다. Phase 2 기본 pre-submit 정책은 1거래일 1개 부모 주문서, 부모 주문 수량 기본 `max_order_qty=1`, 같은 종목 pending 차단, live fill mismatch 신규 intent 차단이며, 위반 시 broker 호출 없이 `blocked`로 기록한다. `phase2`, `phase2_canary`, `phase2_conservative`는 같은 기본 pre-submit 정책을 쓴다. `order_policy.max_order_qty` 또는 legacy alias `max_qty`를 명시하면 테스트/후속 phase에서 정책값을 조정할 수 있다.

초기 구현 `app/services/live_execution_sync.py`:

```text
snapshot_from_kis_daily_order_fill(record)
derive_live_order_status(snapshot)
build_live_order_sync_decision(snapshot, previous_applied_fill_qty)
LiveExecutionSync.apply_order_snapshot(order_id, snapshot, previous_applied_fill_qty)
LiveExecutionSync.apply_order_snapshot_and_fill_delta(order_id, snapshot, settlement_day)
LiveExecutionSync.validate_live_order_fill_qty(order_id)
LiveExecutionSync.scan_live_order_fill_consistency(trading_day)
LiveExecutionSync.build_live_order_fill_consistency_summary(trading_day)
```

2026-05-17 기준 구현은 실제 KIS REST 호출을 만들지 않는다. 기존 `KisDailyOrderFillRecord` 형태 또는 같은 attribute/key를 가진 입력을 받아 `accepted`, `open`, `partially_filled`, `filled`, `cancelled`, `cancelled_partial`, `expired`, `rejected`, `unknown` 상태와 delta fill 수량을 계산한다. `LiveExecutionSync.apply_order_snapshot()`은 `live_orders` 상태/수량과 `live_order_events`만 반영한다. unmatched snapshot은 `unknown`으로만 전이하고 수량은 갱신하지 않는다. `LiveExecutionSync.apply_order_snapshot_and_fill_delta()`는 기존 `live_fills` 합계와 브로커 누적 체결수량을 비교해 미기록 delta만 deterministic `fill_id`로 기록하며, order/fill/event에 저장하는 raw broker output은 redaction한다. `scan_live_order_fill_consistency()`와 `build_live_order_fill_consistency_summary()`는 거래일 단위 mismatch를 찾고 요약하는 read-only helper다. `app/services/live_order_monitoring.py`는 거래일 단위 `unknown`/`stuck` 미해결 주문 수, 열린 주문 수, 최장 경과 시간, Phase 2 부모 주문 한도 사용량을 read-only로 요약한다. `app/services/live_position_accounting.py`는 기록된 `live_fills`에서 long-only 평균단가 포지션을 순수 계산하고, buy/sell로 해석되지 않는 fill side는 `invalid_side_count`로 기록한다. `app/services/live_alerting.py`는 live fill mismatch와 live order attention을 로컬/텔레그램/이메일 outbox record로 routing하고, outbox 저장 직전 `detail_json`을 redaction한다. `app/services/dashboard.py`는 order/fill summary와 Phase 2 부모 주문 한도를 `실 운용계좌` 탭과 status alert에 read-only로 표시하고, `app/services/reporting.py`는 runtime report JSON/Markdown에 같은 지표와 alert outbox summary를 기록한다. 자동 포지션 저장, 포트폴리오, 세금/수수료 정산, 계좌 snapshot reconciliation, 실제 텔레그램/이메일 발송은 후속 slice다.

초기 구현 `app/services/live_alerting.py`:

```text
route_live_alert(alert)
build_live_monitoring_alerts(created_at, live_fill_consistency, live_order_attention)
LiveAlertOutbox.write_alert(alert)
render_telegram_alert(alert)
render_email_alert(alert)
```

현재 alerting은 `delivery_mode=outbox_only`다. `warning`과 `critical`은 텔레그램 outbox 대상이고, `critical` 또는 중요한 event type은 이메일 outbox 대상이다. 같은 event type/trading day/state fingerprint의 alert는 같은 날짜 outbox에 중복 append하지 않는다. `unknown/stuck` attention payload가 `max_attention_age_minutes`와 `attention_grace_minutes`를 함께 제공하면 grace window 안에서는 alert를 만들지 않는다. 실제 텔레그램 bot token, 이메일 API key/SMTP password, 수신 주소는 저장소에 기록하지 않으며, sender는 outbox를 읽는 별도 후속 모듈로 둔다.

제안 신규 `app/services/market_status.py`:

```text
MarketStatusService.build_snapshot(trading_day, symbols)
MarketStatusService.assess_symbol(snapshot, symbol, event_time)
MarketStatusService.is_stale(snapshot, now)
```

초기 구현 `app/services/live_audit.py`:

```text
LiveAuditLog.append(...)
LiveAuditLog.latest_hash(trading_day)
LiveAuditLog.verify(trading_day)
build_live_audit_event(...)
compute_live_audit_hash(...)
verify_live_audit_chain(records)
```

현재 구현은 `ops_live_audit_events`와 `runtime-data/ops/YYYY-MM-DD/live_audit_events.jsonl`에 같은 event를 남긴다. 첫 이벤트의 `previous_hash`는 `GENESIS_HASH`이고, 이후 이벤트는 직전 event hash를 참조한다. event hash는 `audit_event_id`를 제외한 event payload와 `detail_json`의 canonical JSON으로 계산한다. `build_live_audit_event()`는 `prediction_id`, `signal_id`, `gate_decision_id`, `rule_version`, `model_version`, `data_snapshot_id`, `previous_hash` 등 필수 trace field가 비어 있으면 event 생성을 거부한다. runtime report는 거래일 기준 audit chain을 read-only로 검증해 `Live Audit Integrity` 절에 `checked_count`, `issue_count`, `latest_hash`를 표시한다. 아직 모든 live order manager/guard/execution sync event를 audit chain에 자동 append하지 않았고, 외부 anchor와 보관 기간은 계좌 소유자 또는 실전 운용 승인권자 결정이 필요하다.

제안 신규 `app/services/live_kill_switch.py`:

```text
LiveKillSwitch.read_state(now)
LiveKillSwitch.write_state(enabled, reason, actor, scope, symbol)
LiveKillSwitch.assert_not_stale(state, now)
LiveKillSwitch.allow_cancel_only(state)
```

관련 문서/코드 경로: `app/services/`, `app/storage/runtime_writer.py`, `app/brokers/kis_quote_rest.py`

## 10. Dashboard와 report 초안

추가 카드:

- `실전 read-only guard`: Phase, live profile 준비 여부, 주문 메서드 차단 self-check.
- `live enable guard`: `TRADING_MODE`, `ALLOW_LIVE_ORDERS`, kill switch, phase approval.
- `market status`: 거래정지/VI/상하한가/corporate action stale 여부.
- `live order lifecycle`: 상태별 주문 수, oldest open age, unknown/stuck 수, Phase 2 부모 주문 한도 사용량. 2026-05-17 현재 `unknown`/`stuck` read-only summary, Phase 2 부모 주문 dashboard 카운터, dashboard/runtime report 노출은 구현됐고, 상태별 전체 분포와 자동 stuck 전이는 후속이다.
- `T+2/orderable cash`: 내부 현금, 브로커 예수금, 주문가능금액, 미정산 금액.
- `phase readiness`: fault injection 결과, 누적 paper-vs-broker, paper-vs-live metric.
- `audit integrity`: latest audit hash, chain verify status, approval record status.

제안 신규 리포트 경로:

- `runtime-data/reports/live-readiness/latest-readiness.json` (Slice 1 fault injection, Slice 8 dashboard)
- `runtime-data/reports/live-orders/latest-order-state.json` (Slice 5 order manager, Slice 8 dashboard)
- `runtime-data/reports/live-risk/latest-risk-state.json` (Slice 4 guard/kill switch, Slice 8 dashboard)
- runtime report `Live Audit Integrity` 절 (Slice 7 audit, Slice 8 report). 별도 `runtime-data/reports/live-audit/latest-audit-integrity.json` 파일은 아직 구현하지 않았다.
- `runtime-data/reports/live-approvals/latest-approval.json` (Slice 4 phase approval 후보, Slice 8 dashboard)
- `runtime-data/reports/alerts/{local,telegram,email}/alerts-YYYY-MM-DD.jsonl` (Slice 8 report alert outbox, 실제 외부 발송기는 후속)

위 경로 중 `runtime-data/reports/alerts/`, `runtime-data/reports/live-risk/`, `runtime-data/reports/live-approvals/`, `runtime-data/ops/`, `runtime-data/ml/registry-backups/`는 2026-05-17 `tests/test_wsl_ops.py`의 sanitized recovery export self-test로 포함 여부를 잠갔다. root `.env`, `runtime-data/cache/kis`, `runtime-data/logs`, key 파일 제외도 같은 테스트가 확인한다. 재난 복구용 NAS 전체 백업은 별도 이중 보관 체계이며, cowork 전달/Phase readiness 증거로 직접 쓰지 않는다.

관련 문서/코드 경로: `app/services/dashboard.py`, `runtime-data/reports/dashboard/latest-dashboard.json`, `scripts/run_weekly_nas_backup.sh`, `scripts/script_dispatch.sh`

## 11. 테스트 초안

P0 테스트:

- `tests/test_live_readonly_guard.py`
  - live read-only client에 `submit_cash_order`, `cancel_order`가 없음을 확인.
  - 공개 조회 메서드 signature가 delegate 메서드와 호환되는지 확인.
  - factory가 non-live mode를 거부하는지 확인.
  - module import만으로 token/REST/network 호출이 발생하지 않는지 확인.
  - `ALLOW_LIVE_ORDERS=false`에서 live 주문 client 생성 실패.
  - paper mirroring은 기존처럼 paper profile에서만 동작.
- `tests/test_live_client_isolation.py`
  - 기존 `KisRestQuoteClient(` 직접 생성 경로를 allowlist로 고정하고 새 Phase 1 live read-only 경로가 wrapper를 우회하지 않음을 확인.
  - Phase 1 factory가 `live`만 허용하고 paper mirroring 경로를 readonly wrapper로 대체하지 않음을 확인.
- `tests/test_live_order_guard.py`
  - `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=true`는 기존 설정 오류 유지.
  - `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=false`는 read-only 조회만 허용.
  - kill switch on이면 신규 submit fail, cancel-only 후보는 별도 허용.
  - kill switch 파일 missing/broken/stale이면 신규 submit fail.
  - phase 이름 오타 또는 미등록 phase는 `phase_unknown`으로 차단.
- `tests/test_market_status.py`
  - 거래정지/VI/stale/corporate action snapshot이면 신규 주문 차단 decision.
  - 정상 snapshot이면 gate 입력으로 snapshot id가 전달.
- `tests/test_system_clock.py`
  - 기본 후보 `±2초` 이내 허용, 초과 차단.
  - naive timestamp를 UTC로 정규화.
  - custom limit으로 더 좁게 잡을 수 있는지 확인.
- `tests/test_live_phase_readiness.py`
  - phase approval hash 안정성, active approval 조회, readiness blocked/ok record 생성을 검증.
  - token refresh fault injection, WS drop fault injection, stale account alert 실행 자체는 후속 runner에서 추가한다.

P1 테스트:

- `tests/test_live_order_manager.py`
  - 주문 intent 생성과 idempotency 재사용.
  - Phase 2에서 1거래일 1개 부모 주문서 제한, `phase2_canary` 기본 정책 적용, 같은 종목 pending 차단, 차단 context 기록.
  - `LiveOrderGuard` 통과 뒤 `submit_pending`/`submitted`/`accepted`/`open` 전이.
  - guard 차단 시 broker 호출 없이 `blocked` 기록.
  - broker 제출 예외 시 `unknown` 기록.
  - kill switch ON 상태에서도 cancel-only 경로가 `cancel_requested`로 이동.
  - 재시작 복구에서 open 계열 주문을 `unknown`으로 잠그고 broker reconcile을 요구.
- `tests/test_live_order_lifecycle.py` 후보
  - 부분 체결 뒤 같은 종목 부모 주문 차단.
  - Phase 2에서 정정 상태가 금지되고 cancel + new submit만 허용.
  - 장 종료 만료는 `expired`로 기록되어 `cancelled`와 구분.
- `tests/test_live_execution_sync.py`
  - KIS daily order/fill record를 live broker snapshot으로 정규화.
  - KIS daily order/fill 대체 필드명과 연속 조회(`tr_cont=M`) fixture를 `tests/test_kis_http_clients.py`에서 검증.
  - `open`, `partially_filled`, `filled`, `cancelled`, `cancelled_partial`, `expired`, `rejected`, `accepted`, `unknown` 상태 해석.
  - delta fill은 이전 적용 수량 이후의 증가분만 반영하고 음수 delta를 만들지 않음.
  - `LiveExecutionSync.apply_order_snapshot()`이 `live_orders` 상태/수량과 `live_order_events`를 반영.
  - `LiveExecutionSync.apply_order_snapshot_and_fill_delta()`가 같은 snapshot 반복 적용 시 `live_fills`를 중복 insert하지 않음.
  - unmatched snapshot은 `unknown` 전이만 수행하고 수량/체결 원장을 갱신하지 않음.
  - `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)` 정합성을 검출.
- `tests/test_live_execution_sync.py` 후속 후보
  - T+2/orderable cash mismatch가 신규 매수 차단으로 연결.
- `tests/test_live_alerting.py`
  - warning은 로컬/텔레그램 outbox 대상, critical 또는 중요한 event type은 로컬/텔레그램/이메일 outbox 대상임을 확인.
  - live fill mismatch와 live order attention이 critical alert로 변환되는지 확인.
  - outbox 기록이 `delivery_mode=outbox_only`이고 비밀값 없이 생성되는지 확인.
  - 동일 state fingerprint alert가 같은 날짜 outbox에 중복 append되지 않는지 확인.
  - `unknown/stuck` attention이 grace window 안이면 alert를 만들지 않고, grace 이후에는 alert를 만드는지 확인.
- `tests/test_kis_response_redaction.py`
  - KIS 실제 응답 sample을 fixture로 옮기기 전 token, app key/secret, 계좌번호, 계좌상품코드, 고객 식별값을 제거하고 주문번호/종목코드/수량/가격 필드는 유지하는지 확인.
- `tests/test_live_audit.py`
  - append-only hash chain 생성/검증.
  - payload 수정 시 검증 실패.

P2 테스트:

- `tests/test_dashboard.py`
- `tests/test_reporting.py`
  - live cards가 missing/stale/ok 상태를 보여주고, dashboard가 Phase 2 부모 주문 한도를 표시하며, runtime report가 alert outbox summary와 JSONL outbox를 생성한다.
- `tests/test_wsl_ops.py`
  - live report/audit/approval/risk/registry backup 경로가 sanitized recovery export에 포함되고, `.env`, KIS token cache, runtime logs, key 파일이 제외되는지 확인.

관련 문서/코드 경로: `tests/`, `tests/test_settings.py`, `tests/test_kis_http_clients.py`, `tests/test_broker_paper_sync.py`, `tests/test_dashboard.py`, `tests/test_reporting.py`, `tests/test_live_alerting.py`

## 12. 구현 PR slice

코드 작업은 한 번에 실전 주문까지 연결하지 않는다. 아래 순서로 작은 PR 또는 작업 단위로 자른다.

| Slice | 파일 범위 | 목표 | 검증 |
|---|---|---|---|
| 1 | `app/brokers/`, `tests/test_live_readonly_guard.py`, `tests/test_live_client_isolation.py` | read-only client와 live 주문 메서드 구조적 차단 | 관련 단위 테스트, static isolation 검사, `git diff --check` |
| 2a | `app/storage/`, storage tests | `market_status_snapshots`, `live_orders`, `live_order_events` 추가 | storage 단위 테스트, schema smoke query |
| 2b | `app/storage/`, storage tests | `live_fills`, `live_positions`, `live_portfolio_snapshots`, audit/approval/readiness 테이블 추가 | storage 단위 테스트, migration dry-run, 완료 |
| 3 | `app/services/market_status.py`, tests | market status snapshot과 blocking decision | market status 테스트, 완료 |
| 4 | `app/services/live_order_guard.py`, `app/services/live_kill_switch.py`, tests | enable/phase/kill switch/order type guard | guard 테스트, 완료 |
| 5 | `app/services/live_order_manager.py`, tests | intent, idempotency, state transition, recovery shell, Phase 2 pre-submit 정책 | lifecycle 테스트, 1일 1부모주문/기본 1주 수량 제한/같은 종목 pending/live fill mismatch 차단 완료 |
| 6 | `app/services/live_execution_sync.py`, tests | KIS 조회 기반 상태/체결 반영 | 상태/수량 반영과 `live_fills` delta 멱등 기록 완료. KIS live 조회 연결/포지션 반영은 후속 |
| 7 | `app/services/live_audit.py`, tests | audit append-only/hash chain | hash chain 생성/검증, 필수 trace field 빈 값 거부, runtime report integrity 요약 완료. 주문 경로 전체 자동 연결과 외부 anchor는 후속 |
| 8 | `app/services/dashboard.py`, `app/services/reporting.py`, `app/services/live_alerting.py`, report tests | live 상태 카드, readiness report, alert outbox | dashboard/report/alert 테스트, dry-run 카드, live fill 정합성과 `unknown`/`stuck` 미해결 주문 및 Phase 2 부모 주문 한도 read-only 노출, 로컬/텔레그램/이메일 outbox 완료 |
| 9 | `scripts/`, recovery tests | NAS sanitized export self-test와 readiness wrapper | bash parse, sanitized recovery export 포함/제외 테스트 완료. 재난 복구용 NAS 전체 백업은 별도 운영 체계 |
| 10 | `app/services/codex_ops.py`, `scripts/run_codex_ops_job.sh`, `scripts/run_live_readiness_dry_run.sh`, tests | Codex CLI 운영 job manifest, 장 상태별 권한 모델, premarket-readiness dry-run report, fixture 기반 10개 check readiness dry-run report | codex ops/readiness wrapper 테스트, 완료 |

`app/risk/` 변경이 필요한 Slice는 계좌 소유자 또는 실전 운용 승인권자 승인 전까지 별도 보류한다. gate 기준값은 문서 또는 테스트 fixture 안에서도 임의 확정하지 않는다.

관련 문서/코드 경로: `app/brokers/`, `app/services/`, `app/storage/`, `tests/`, `scripts/`

## 13. 첫 코드 작업 체크리스트

Slice 1은 2026-05-14에 `app/brokers/kis_readonly.py`, `tests/test_live_readonly_guard.py`, `tests/test_live_client_isolation.py`로 구현했다. 이 단계는 실전 주문을 절대 연결하지 않고 read-only 구조와 테스트만 만든다.

Slice 2a는 2026-05-14에 `app/storage/contracts.py`, `app/storage/sqlite_store.py`, `app/storage/runtime_writer.py`, `tests/test_live_storage.py`로 구현했다. 2026-05-15에는 `scripts/run_storage_migration_dry_run.sh`와 `tests/test_storage_migration_dry_run_script.py`를 추가해 실 DB 사본 또는 빈 임시 DB에서 필수 live table/index 초기화 여부를 확인할 수 있게 했다.

Slice 2b는 2026-05-15에 `LiveFill`, `LivePosition`, `LivePortfolioSnapshot`, `LiveAuditEvent`, `LivePhaseApproval`, `LiveReadinessRun` dataclass, SQLite table/index, RuntimeWriter 메서드, storage/migration smoke 테스트로 구현했다. 2026-05-16에는 `create_readiness_run_from_premarket_report()`와 `build_fault_injection_dry_run_report()`를 추가해 Codex ops premarket report와 fixture 기반 fault dry-run 결과를 보수적인 readiness record로 변환할 수 있게 했다. 아직 live execution sync, order manager, dashboard에는 연결하지 않았다.

Slice 3은 2026-05-15에 `app/services/market_status.py`, `tests/test_market_status.py`로 구현했다. 현재 범위는 외부 API 연결 없이 `MarketStatusSnapshot` 기반의 순수 차단 판정까지이며, `LiveOrderGuard.assert_can_submit()`은 `MarketStatusDecision`을 입력으로 받아 차단 사유를 반영한다. streaming과 실제 market status snapshot 생성 연결은 후속 작업이다.

System clock skew helper는 2026-05-18에 `app/services/system_clock.py`, `tests/test_system_clock.py`로 구현했다. 현재 범위는 local timestamp와 reference timestamp의 차이를 기본 후보 `±2초`로 판정하는 순수 helper다. 2026-05-20에는 HTTP `Date` header parser/decision helper와 KIS REST 마지막 성공 응답 header read-only 노출 지점을 추가했고, 2026-05-21에는 timezone 없는 header와 알 수 없는 timezone을 invalid로 차단하는 테스트를 추가했다. `app/brokers/kis_readonly.py`는 주문/취소 메서드 없이 마지막 read response header copy를 노출하고, `app/services/system_clock_probe.py`와 `scripts/probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 raw header 원문 없이 sanitized check JSON을 생성한다. `scripts/probe_kis_clock_reference.sh --compare-paper-live`는 paper/live HTTP `Date` reference delta를 sanitized JSON으로 만든다. KIS paper probe 1회에서 `system_clock=true`, skew 약 0.167초를 확인했다. `scripts/run_live_readiness_dry_run.sh`에는 `system_clock` fixture check로 연결되어 fixture가 없으면 readiness를 통과시키지 않으며, `--system-clock-check-path`로 받은 sanitized check JSON을 fixture보다 우선 병합할 수 있다. `app/services/live_order_guard.py`와 `app/services/live_order_manager.py`에는 선택적 submit guard hook을 연결해, caller가 clock decision을 주거나 check를 필수로 요구할 때 submit을 차단할 수 있다. live account header shape 확인, paper/live 비교 실행 증적, 기본 강제 정책은 후속 작업이다.

Slice 4는 2026-05-15에 `app/services/live_kill_switch.py`, `app/services/live_order_guard.py`, `tests/test_live_kill_switch.py`, `tests/test_live_order_guard.py`로 구현했다. 2026-05-18에는 KIS client 위임 직전 submit enable/profile을 재검증하고 cancel은 live/profile만 확인하는 `app/brokers/kis_live_order.py`, `tests/test_kis_live_order_adapter.py`와 주문 함수 등장 위치를 허용 경계로 제한하는 정적 테스트를 추가했다. 현재 범위는 streaming runtime 연결 전 순수 가드와 wrapper다.

Slice 5/6/7/8의 추가 골격은 2026-05-16~17에 `app/services/live_order_manager.py`, `app/services/live_execution_sync.py`, `app/services/live_order_monitoring.py`, `app/services/live_position_accounting.py`, `app/services/live_alerting.py`, `app/services/live_audit.py`, `tests/test_live_order_manager.py`, `tests/test_live_execution_sync.py`, `tests/test_live_alerting.py`, `tests/test_live_audit.py`로 구현했다. 현재 범위는 broker protocol 주입형 주문 manager, intent 필수 입력 검증, 주문 manager raw broker response redaction, guard 차단 시 `blocked` 감사 기록, broker 예외 시 `unknown`, 재시작 open 계열 `unknown` 복구, Phase 2 1거래일 1개 부모 주문서 제한, 부모 주문 수량 기본 `max_order_qty=1`, `phase2_canary` 기본 정책 적용, 같은 종목 pending 차단, Phase 2 부모 주문 금액 한도 `min(100,000원, 운용 배정금의 10%)`, pre-submit 차단 context 기록, live fill mismatch 신규 intent 차단, KIS daily order/fill record 기반 상태/수량 반영, execution sync raw broker output redaction, `live_fills` delta 멱등 기록과 정합성 검사, `unknown`/`stuck` 미해결 주문 및 Phase 2 부모 주문 한도 read-only 요약, `live_fills` 기반 long-only position 순수 계산과 invalid fill side 카운트, 로컬/텔레그램/이메일 alert outbox와 `detail_json` redaction, audit hash chain 생성/검증, 필수 trace field 빈 값 거부, runtime report integrity 요약까지다. 실제 KIS live adapter 연결, streaming 연결, 자동 포지션 저장, 포트폴리오/세금 정산 반영, 실제 텔레그램/이메일 발송, 모든 주문 decision의 audit chain 자동 append는 후속이다.

KIS WebSocket reconnect metric은 2026-05-19에 `app/brokers/kis_quote_ws.py`와 `tests/test_kis_ws_reconnect_metrics.py`로 추가했다. 현재 범위는 누적 reconnect, 연속 reconnect, 안정 frame 수신 후 연속 reconnect reset, reconnect storm 판정, `observed_at`, `last_reconnect_at`, `last_stable_at`, `storm_active_since`, JSON 직렬화 helper, optional `metrics_callback`, callback 예외 warning 흡수, reconnect warning log의 consecutive/storm 표시까지다. `metrics_callback`은 동기 호출이므로 DB/file/network I/O를 직접 하지 않고 in-memory update 또는 별도 worker queue에 넘기는 방식으로 써야 한다. `max_reconnects`는 기존 누적 reconnect 기준을 유지한다. Dashboard readiness 카드는 WS recovery evidence type/실제 증거 여부/freshness/stable frame/reconnect storm을 표시한다. keepalive 정책 변경과 실제 장중 reconnect fault injection은 후속이다.

KIS 모의투자 응답 fixture export는 2026-05-17에 `scripts/export_kis_paper_fixture_candidates.py`, `tests/test_kis_paper_fixture_export_script.py`로 추가했다. 이 스크립트는 `runtime-data/dev.db`를 SQLite read-only URI로 열고, broker paper 주문 제출/상태 snapshot의 최신 후보와 가장 풍부한 `detail_json` 후보를 redaction 후 `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json`에 저장한다. 2026-05-18에는 `find_unredacted_sensitive_paths()` 기반 `redaction_ok`/`redaction_findings` 요약을 추가해, 민감 key가 redaction 뒤에도 남아 있으면 summary status가 `needs_review`가 되도록 했다. `--fail-on-redaction-findings`를 주면 findings 발생 시 non-zero exit로 사용할 수 있다. KIS API를 새로 호출하지 않는다.

2026-05-19에는 `scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings`로 redacted runtime fixture 후보를 갱신했다. 확인된 `broker_paper_order_status_snapshots`의 richest candidate는 KIS 원 필드 `ord_dt`, `ord_gno_brno`, `odno`, `pdno`, `sll_buy_dvsn_cd`, `ord_qty`, `tot_ccld_qty`, `rmn_qty`, `avg_prvs`, `cncl_yn` 등을 포함했고 redaction status는 `ok`였다. 이 shape를 `tests/test_kis_http_clients.py`에 고정해 `KisRestQuoteClient.get_daily_order_fills()` 정규화를 잠갔고, 정규화된 record가 `snapshot_from_kis_daily_order_fill()`에서 `sell`/`filled` snapshot으로 변환되는지를 `tests/test_live_execution_sync.py`에 추가했다. 이 테스트는 KIS API를 호출하지 않는다.

운영 DB 적용 wrapper 보강은 2026-05-15에 `scripts/apply_storage_migration.sh`, `tests/test_storage_migration_apply_script.py`로 구현했다. 이 wrapper는 기본 plan 모드에서는 DB를 바꾸지 않고, `--apply`가 있을 때만 적용한다. 기본 `runtime-data/dev.db`에는 서비스 상태 확인을 건너뛸 수 없고, 적용 전 live runtime/dashboard/runtime watchdog 정지 확인, SQLite native backup, schema 초기화, table/index 및 sample insert/read/delete smoke check, 실패 시 SQLite native restore 절차를 수행한다.

다음 코딩 세션의 권장 순서는 Slice 2b 원장의 운영 DB 적용 전 dry-run/plan 검증과 readiness DB 저장 절차의 운영 적용 검증이다. `app/services/live_phase_readiness.py`의 approval/readiness record 생성, premarket report adapter, fixture 기반 10개 check fault dry-run report, timestamped evidence freshness 가드, Phase 2/3 synthetic WS recovery 차단, `app/services/codex_ops.py`의 job manifest/권한 모델, `scripts/run_codex_ops_job.sh --job-type premarket-readiness`, `scripts/run_live_readiness_dry_run.sh`, dashboard read-only 카드는 구현됐다. `database` check는 `scripts/run_codex_ops_job.sh`에서 SQLite read-only smoke(`SELECT 1`, `sqlite_master`, `schema_version`, `journal_mode`)로 확인하고, `storage_migration_state`는 migration plan/apply 상태로 분리한다. `account_snapshot` check는 계좌번호/raw response 없이 필수 shape와 값 타입 drift를 차단한다. `system_clock` check는 네트워크 시각 보정이 아니라 fixture/dry-run 결과로만 통과시키며, `scripts/probe_kis_clock_reference.sh --compare-paper-live`는 paper/live reference delta를 별도 sanitized 진단 JSON으로 만든다. HTTP `Date` header는 초 단위 정밀도라 표시 skew가 0.002초여도 실제 의미는 대략 1초 이내 여부다. `run_live_readiness_dry_run.sh`의 기본 실행은 JSON only이며, SQLite 저장은 `--record --database-path <repo 내부 경로>`가 함께 있을 때만 수행한다. 실제 Codex CLI 호출과 실제 장애 주입은 후속이다. 실제 운영 DB 적용은 `scripts/run_storage_migration_dry_run.sh`와 `scripts/apply_storage_migration.sh`를 함께 통과한 뒤 수행한다.

Slice 1 상세 절차:

1. `app/brokers/kis_readonly.py`를 추가한다.
2. `KisReadOnlyClient`는 내부에 `KisRestQuoteClient`를 composition으로 가진다.
3. 공개 메서드는 기존 조회 메서드 중 `get_current_price`, `get_orderbook`, `get_intraday_minute_chart`, `get_account_balance`, `get_daily_order_fills`만 둔다.
4. `submit_cash_order`, `cancel_order`는 클래스에 만들지 않는다.
5. `get_kis_live_readonly_client(settings)` factory를 둔다. Phase 1용 factory는 `live`만 허용한다.
6. `tests/test_live_readonly_guard.py`와 `tests/test_live_client_isolation.py`를 추가한다.
7. 테스트는 live read-only client가 주문 제출/취소를 못 한다는 점, 새 Phase 1 live read-only 경로가 allowlist 밖에서 직접 `KisRestQuoteClient(`를 만들지 않는다는 점, 기존 paper mirroring 경로가 깨지지 않는다는 점을 함께 본다.
8. 검증은 `python -m unittest tests.test_live_readonly_guard tests.test_live_client_isolation tests.test_kis_http_clients tests.test_settings`와 `git diff --check`를 기본으로 한다.

Slice 2a 상세 절차:

1. `app/storage/contracts.py`에 `MarketStatusSnapshot`, `LiveOrder`, `LiveOrderEvent` dataclass 초안을 추가한다.
2. `app/storage/sqlite_store.py`에 `market_status_snapshots`, `live_orders`, `live_order_events` 테이블과 관련 index를 추가한다.
3. `app/storage/runtime_writer.py`에 `write_market_status_snapshot`, `write_live_order`, `write_live_order_event` 후보를 추가한다.
4. 기존 paper write 메서드 이름과 JSONL 경로를 바꾸지 않는다.
5. 운영 DB 적용 전 live runtime/dashboard 정지, backup, schema 초기화, smoke query, 재기동 순서로 dry-run한다.
6. 검증은 storage 단위 테스트와 기존 `tests/test_broker_paper_sync.py`, `tests/test_paper_reconciliation.py`를 함께 본다.

Slice 2b 상세 절차:

1. `app/storage/contracts.py`에 `LiveFill`, `LivePosition`, `LivePortfolioSnapshot`, `LiveAuditEvent`, `LivePhaseApproval`, `LiveReadinessRun` dataclass 초안을 추가한다.
2. `app/storage/sqlite_store.py`에 `live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs` 테이블과 관련 index를 추가한다.
3. `app/storage/runtime_writer.py`에 체결/포지션/감사/승인/readiness write 메서드를 추가한다.
4. schema 변경은 새 테이블, 새 index, 새 컬럼 추가까지만 허용하고 기존 컬럼 변경/삭제는 하지 않는다.
5. 검증은 storage 단위 테스트, audit hash fixture, migration dry-run을 함께 본다.

Slice 3 상세 절차:

1. `app/services/market_status.py`를 추가했다.
2. 첫 구현은 외부 API 없이 fixture 또는 계좌 소유자/실전 운용 승인권자 수동 snapshot을 입력으로 받아 decision을 만드는 순수 로직으로 시작했다.
3. KIS REST 또는 한국거래소 OpenAPI 연동은 데이터 원천 확정 뒤 별도 slice로 분리한다.
4. stale snapshot, VI, 거래정지, 상하한가, 기업행위 fixture를 테스트했다.

Slice 4 상세 절차:

1. `app/services/live_order_guard.py`를 추가했다.
2. read-only, submit, cancel-only guard를 분리했다.
3. paper mirroring에는 이 guard를 적용하지 않았다. paper는 기존 `BrokerPaperMirror.enabled` 조건을 유지한다.
4. `app/services/live_kill_switch.py`를 추가해 kill switch 파일을 읽고 atomic write로 저장한다.
5. kill switch 상태 파일 기본 후보는 `runtime-data/reports/live-risk/kill-switch.json`이다.
6. missing/broken/stale 상태는 신규 submit 차단, cancel-only 허용 후보로 처리한다.
7. `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=true`, live profile, phase approval, limit order, kill switch off, market status allowed를 submit 전제 조건으로 잠갔다.

코드 작업 시작 전 확인:

- `VERSION`을 바꾸지 않는다.
- `ALLOW_LIVE_ORDERS` 값을 바꾸지 않는다.
- KIS live 주문 API를 호출하지 않는다.
- `app/risk/` 변경은 계좌 소유자 또는 실전 운용 승인권자 승인 전 보류한다.
- root `.env`나 비밀값을 읽어 문서/테스트 fixture에 쓰지 않는다.

Slice 1 go/no-go 기준:

- Go: `KisRestQuoteClient.__init__`가 profile/token manager를 받는 composition 가능한 구조임을 코드로 재확인했다.
- Go: read-only wrapper는 조회 메서드만 노출하고 주문/취소 메서드를 만들지 않는 방향으로 구현한다.
- Go: 테스트는 fake profile, fake token manager, mock delegate만 사용한다.
- Go: Slice 1 테스트 실행 중 실제 KIS 네트워크 호출, token 발급, hashkey 발급은 0건이어야 한다.
- No-go: 구현 중 live 주문/취소 호출부를 수정해야 한다면 Slice 1을 중단하고 별도 설계로 분리한다.
- No-go: paper mirroring 동작을 바꿔야 한다면 Slice 1을 중단한다.
- No-go: `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION` 변경이 필요해지면 계좌 소유자 또는 실전 운용 승인권자 승인 전까지 보류한다.
- Stop line: Slice 1은 read-only wrapper와 isolation 테스트까지만 포함하고, dashboard/report/streaming 연결은 후속 slice로 남긴다.
- PR 크기 후보: 새 파일 1개와 테스트 2개 중심으로 유지하고, 대략 400줄을 넘거나 기존 runtime 흐름 수정이 필요하면 분할을 검토한다.
- No-go 발동 절차: 작업 중단 -> 변경 이유를 `docs/cowork-reports/*-operator-decision.md` 또는 다음 `work_ver_*`에 기록 -> 계좌 소유자/실전 운용 승인권자 승인 전 코드 범위 확대 금지.
- Rollback 기준: Slice 1은 신규 파일 중심이어야 하므로 revert가 쉬워야 한다. rollback 뒤에는 read-only wrapper import를 추가한 파일이 남지 않았는지 확인한다.

관련 문서/코드 경로: `app/brokers/kis_quote_rest.py`, `app/services/broker_paper.py`, `app/storage/contracts.py`, `app/storage/sqlite_store.py`, `app/storage/runtime_writer.py`, `tests/test_kis_http_clients.py`, `tests/test_settings.py`

## 14. 남은 계좌 소유자/실전 운용 승인권자 결정

✅ 결정 완료(P0): Phase 1 read-only 구조적 차단 방식.

- Codex 권장안: 별도 read-only client를 기본으로 하고 주문/취소 메서드는 아예 노출하지 않는다.
- 결정값: Slice 1 구현 시작 승인. hard fail 메서드 없이 미노출 방식으로 진행.
- 기록: `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision.md`

✅ 결정 완료(P0): VI 발동 중 open 주문 처리.

- Codex 권장안: Phase 2에서는 신규 주문 금지, 기존 open 주문은 조회 보류, 잔량 취소는 cancel-only guard 통과 후 허용 후보로 둔다.
- 결정값: Codex 권장안 채택.
- 확인 필요: KIS가 VI 중 미체결 주문을 어떤 상태로 반환하는지.

✅ 결정 완료(P0): Phase 2 주문 타입.

- Codex 권장안: 신규 진입은 지정가 only, 시장가는 기본 금지. 비상 청산 시장가는 청산 건별 수동 승인 후보로 두고, kill switch 발동 시에만 자동 fallback을 검토한다.
- 결정값: Codex 권장안 채택. kill switch 발동 사유별 자동 fallback은 별도 검토.

✅ 결정 완료(P1): Phase 2 1일 1주문 해석.

- Codex 권장안: Phase 2의 `1일 1주문`은 1거래일 1개 부모 주문서로 해석하고, 같은 종목 pending/open/partial/unknown/stuck 주문이 있으면 새 부모 주문을 차단한다.
- 결정값: Codex 권장안 채택. 2026-05-17 기준 `app/services/live_order_manager.py`에 pre-submit `blocked` 정책으로 구현했다.

✅ 결정 완료(P1): Phase 2 부모 주문 금액 한도.

- Codex 권장안: Phase 2 첫 20거래일과 기본 Phase 2에서는 부모 주문 1건의 금액 한도를 `min(100,000원, 운용 배정금의 10%)`로 둔다. 운용 배정금이 아직 전달되지 않는 경로에서는 100,000원을 기본 한도로 쓴다.
- 결정값: Codex 권장안 채택. 2026-05-17 기준 `app/services/live_order_manager.py`는 `order_policy.max_order_notional`, `allocation_amount` 또는 `phase2_allocation_amount`, `max_order_allocation_pct` 또는 `max_order_allocation_ratio`로 후속 조정할 수 있게 구현했다.
- 구현값: 한도를 넘는 부모 주문 intent는 broker 호출 전에 `phase2_order_notional_limit_exceeded` 사유로 `blocked` 처리한다.

✅ 결정 완료(P1): Phase 2 부모 주문 수량 한도.

- Codex 권장안: Phase 2 기본 canary에서는 부모 주문 수량을 `max_order_qty=1`로 둔다. 2주 이상 주문은 명시 override가 있을 때만 허용한다.
- 결정값: review_ver_11/12 권장안 채택. 2026-05-19 기준 `app/services/live_order_manager.py`에 `PHASE2_DEFAULT_MAX_ORDER_QTY=1`로 구현했다.
- 구현값: 한도를 넘는 부모 주문 intent는 broker 호출 전에 `phase2_order_qty_limit_exceeded` 사유로 `blocked` 처리하고 `{current, limit}` context를 남긴다. `order_policy.max_order_qty` 또는 legacy alias `max_qty`로 후속 phase에서 조정할 수 있다.

✅ 결정 완료(P0): 일일 손실 한도, 슬리피지 budget, 비상 청산 슬리피지 예외.

- 결정값: Phase 2 보수 모드 첫 20거래일은 1일 최대 손실 `min(운용 배정금 A의 1%, 30,000원)`, 종목별 최대 손실 `min(A의 0.5%, 20,000원)`.
- 결정값: Phase 2 기본 모드는 1일 최대 손실 `min(A의 2%, 50,000원)`, 종목별 최대 손실 `min(A의 1%, 30,000원)`.
- 결정값: 일반 신규/청산 지정가 주문 슬리피지는 warning 10 bps, hard budget 20 bps. 단, KRX 호가단위를 반영해 실제 주문 가격 제한은 `max(1 tick, 10 bps)` warning, `max(2 ticks, 20 bps)` hard 기준으로 계산.
- 결정값: 비상 청산은 일반 슬리피지 budget과 분리해 사고 리포트에 별도 기록.

✅ 결정 완료(P1): Phase 2 부분 체결 잔량 자동 취소.

- Codex 권장안: Phase 2에서는 자동 잔량 취소를 하지 않고 잔량 유지, 같은 종목 신규 부모 주문 차단, 필요 시 cancel-only guard와 수동 승인 취소로 처리한다.
- 결정값: Codex 권장안 채택. 장마감 전 자동 잔량 취소는 KIS cancel fixture와 alert/review 안정화 뒤 Phase 3 전 후보로 둔다.

✅ 결정 완료(P1): `live_positions` 실제 저장 시점.

- Codex 권장안: `live_fills` 기반 순수 계산 helper는 유지하되, `live_positions` 자동 저장은 KIS 실제 응답 fixture, alert outbox, 장후 review 경로가 안정되고 live order/fill mismatch가 0임을 확인한 뒤 시작한다.
- 결정값: Codex 권장안 채택. 첫 저장은 관측용 snapshot으로만 쓰고 리스크 게이트나 주문 수량 산정의 정본 입력으로 쓰지 않는다.

✅ 결정 완료(P1): dashboard 외 사고 알림 채널.

- Codex 권장안: 텔레그램을 기본 장중 메시지 채널로 쓰고, 중요한 이슈는 이메일도 함께 보낸다. 로컬 outbox는 항상 남긴다.
- 결정값: Codex 권장안 기반으로 텔레그램 + 중요 이슈 이메일을 채택했다. 현재 구현은 로컬/텔레그램/이메일 outbox까지이며 실제 발송기와 비밀값 주입은 후속이다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: market status 데이터 원천.

- Codex 권장안: Slice 3은 fixture와 수동 calendar 기반 순수 로직으로 시작하고, KIS REST 또는 한국거래소 OpenAPI 연동은 별도 slice로 분리한다.
- 판단 필요: Phase 1/2에서 자동 market status 원천을 어디까지 요구할지.

✅ 결정 완료(P1): audit chain 1차 anchor 방식.

- Codex 권장안: live 주문 관련 audit은 append-only hash chain으로 남기고, sanitized recovery export 포함/제외 self-test를 Phase 2 전 필수로 유지한다. 1차 anchor는 로컬 hash chain과 sanitized export self-test로 시작한다. 재난 복구용 NAS 전체 백업은 별도 이중 보관으로 유지하고, 외부 timestamp/서명 anchor는 Phase 2/3 전 별도 후보로 미룬다.
- 결정값: Codex 권장안 채택. 장기 보관 기간과 실제 NAS 공유 복구 drill 주기는 후속 운영 정책으로 남긴다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요(P0): reference clock 원천.

- Codex 권장안: Phase 1은 KIS REST 응답의 HTTP `Date` 헤더 또는 KIS 응답 서버시각처럼 broker 응답에서 얻는 시각을 1차 reference로 쓰고, 사용할 수 없을 때만 OS/NTP 확인을 보조 reference로 둔다. 수동 시각 확인은 긴급 fallback으로만 둔다.
- 이유: 주문/조회 경로와 같은 외부 시스템 기준을 쓰면 KIS timestamp 거부와 stale 판정 위험을 가장 직접적으로 줄일 수 있다.
- 현재 상태: `app/services/system_clock.py`는 local timestamp와 reference timestamp를 비교하고 HTTP `Date` 헤더를 reference timestamp/clock decision으로 바꾸는 순수 helper를 제공한다. `app/services/live_phase_readiness.py`와 `scripts/run_live_readiness_dry_run.sh`는 fixture 또는 check-path 기반 `system_clock` skew 평가를 할 수 있다. `app/brokers/kis_quote_rest.py`와 `app/brokers/kis_readonly.py`는 마지막 성공 응답 header를 read-only 진단용 copy로 노출한다. `app/services/system_clock_probe.py`와 `scripts/probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 raw header 원문 없이 sanitized check JSON을 생성하고, `--compare-paper-live`로 paper/live reference delta를 비교할 수 있다. `app/services/live_order_manager.py`는 HTTP `Date` 기반 decision을 필수 submit guard 입력으로 받아 broker 호출 전 통과/차단할 수 있다. 2026-05-20 KIS paper 현재가 read-only 조회 1회에서 header keys에 `date`가 포함됐고, 2026-05-21 paper probe wrapper 실행에서 `system_clock=true`, skew 약 0.167초를 확인했다. live account header shape 확인, paper/live 비교 실행 증적, runtime submit caller/readiness 자동 호출 정책은 아직 없다.

🔴 계좌 소유자/실전 운용 승인권자 실행 필요(P0): sanitized NAS recovery drill 표본 확인.

- Codex 권장안: 기존 NAS 전체 백업은 재난 복구용 이중 보관으로 유지한다. Phase 1 read-only 진입 전에는 별도 `recovery-drills/phase1-readonly` 폴더에 sanitized recovery export 표본을 만들고 제외 정책과 복구 가능성을 확인한다.
- 현재 상태: sanitized recovery export 포함/제외 self-test와 저장소 내부 dry-run 명령은 통과했다. Windows/NAS 기존 전체 백업은 확인됐지만, cowork 전달/Phase readiness 증거로 쓰지 않는다.

🟢 다음 단계 권장: Slice 2b 원장을 운영 DB에 적용하기 전, dry-run과 apply wrapper plan을 먼저 확인한다. `scripts/run_codex_ops_job.sh --job-type premarket-readiness`, `scripts/run_live_readiness_dry_run.sh`, premarket report adapter, dashboard read-only 카드는 구현됐다. readiness DB insert는 기본 동작에서 분리했고, `--record --database-path <repo 내부 경로>`를 함께 줄 때만 수행된다. 현재 readiness dry-run은 `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `system_clock`, `kill_switch`, `database`, `disk_space`, `dashboard`, `storage_migration_state` 10개 check가 모두 fixture로 통과되어야 `ok`가 된다. timestamp가 있는 핵심 증거는 key별 freshness 기준을 넘으면 `stale_evidence`로 차단하고, Phase 2/3에서는 실제 KIS WS 관측 evidence type 없이는 readiness와 submit guard가 통과하지 않는다. `system_clock`, `disk_space`, `dashboard`, `storage_migration_state`는 현재 `checks_json`에만 저장하며, SQL 컬럼 승격은 별도 schema migration 결정으로 남긴다. 다음 권장안은 운영 DB 적용 후에도 `--record` 실행을 장전 명시 절차 안에서만 호출하도록 runbook에 묶는 것이다.

🟢 다음 단계 권장: `LiveExecutionSync`를 실제 KIS live 조회 adapter에 연결하기 전, fixture를 더 늘려 KIS 응답 필드 차이를 검증한다. 포지션/포트폴리오 반영은 `live_fills` 정합성 검사가 안정된 뒤 별도 slice로 진행한다.

🟢 다음 단계 권장: KIS paper fixture 후보를 cowork 또는 테스트 fixture로 옮기기 전, `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json`의 `redaction_ok=true`와 `redaction_findings=[]`를 먼저 확인한다. 주문번호와 종목코드는 mapper 검증을 위해 보존하므로, 외부 공유 전에는 계좌 소유자/실전 운용 승인권자가 한 번 더 확인한다.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `AGENTS.md`, `README.md`
