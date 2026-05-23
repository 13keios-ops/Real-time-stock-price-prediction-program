# Codex work_ver_11-20: work_ver_11 전체 통합 handoff

작성: Codex
목적: cowork에 아직 전달되지 않은 `work_ver_11` 전체 흐름을 토큰 절약형으로 통합 전달
대상 리뷰 파일명 권장: `2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`

## 1. 통합 범위

이 파일은 아래 20개 파일을 cowork 전달용으로 압축한 통합본입니다.

- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-1.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-2.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-3.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-4.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-5.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-6.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-7.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-8.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-9.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-10.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-11.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-12.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-13.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-14.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-15.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-16.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-17.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-18.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-19.md`

관련 문서/코드 경로: `docs/cowork-reports/`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`

## 2. 운영자 결정 반영

`review_ver_10` 이후 계좌 소유자 또는 실전 운용 승인권자 결정과 Codex 권장안을 아래처럼 반영했습니다.

| 항목 | 반영 내용 | Codex 권장안 |
|---|---|---|
| Phase 2 부분 체결 잔량 | 자동 잔량 취소 없음. 잔량 유지, 같은 종목 신규 부모 주문 차단, 필요 시 cancel-only guard와 수동 승인 취소. | Phase 2에서는 유지 권장. 자동 잔량 취소는 Phase 3 전 fixture/alert 안정화 뒤 재검토. |
| `live_positions` 저장 시점 | 순수 계산 helper는 유지하되 실제 `live_positions` 정본 저장은 보류. | KIS 실제 응답 fixture, alert outbox, 장후 review, fill mismatch 0건 확인 뒤 관측용 snapshot부터 시작. |
| 외부 알림 채널 | 로컬 outbox 항상 기록, warning/critical은 텔레그램 outbox, critical 또는 중요 event type은 이메일 outbox도 생성. | 실제 sender는 아직 붙이지 말고 token/수신자 정보는 로컬 secret에서만 읽도록 별도 slice 권장. |
| Phase 2 부모 주문 금액 한도 | 기본값 `min(100,000원, 운용 배정금의 10%)`. 운용 배정금 미전달 시 100,000원. | 첫 canary 기준으로 보수적이며, 후속은 `order_policy` override로 조정 가능하게 유지. |
| 감사 원장 1차 anchor | 로컬 append-only hash chain + recovery export/NAS 포함 self-test로 시작. | 외부 timestamp/서명 anchor는 Phase 2/3 전 별도 결정으로 보류. |

관련 문서/코드 경로: `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-operator-decision.md`, `app/services/live_order_manager.py`, `app/services/live_alerting.py`, `app/services/live_position_accounting.py`, `app/services/live_audit.py`

## 3. 주요 변경 묶음

| 묶음 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| Alert outbox | dashboard/report 안에서만 사고를 확인. 외부 알림 경로 없음. | 로컬/텔레그램/이메일 outbox 생성, state fingerprint 중복 억제, unknown/stuck grace hook, 저장 전 redaction. | `app/services/live_alerting.py`, `app/services/reporting.py`, `runtime-data/reports/alerts/` | 실제 sender가 없으므로 외부 알림은 아직 발송되지 않음. |
| Audit hash chain | 실전 주문 trace를 append-only로 검증하는 helper 없음. | `live_audit.py` hash chain 생성/검증, runtime report integrity 요약, 필수 trace field 검증. | `app/services/live_audit.py`, `app/storage/sqlite_store.py`, `app/services/reporting.py` | 비주문 audit event에는 별도 builder 또는 sentinel 정책 필요. |
| Recovery export self-test | 새 live-risk/alerts/ops 경로가 백업 archive에 들어가는지 잠금 없음. | tar export에서 디렉터리 재귀 우회 포함을 막고, 포함/제외 self-test 추가. | `scripts/wsl_ops.py`, `tests/test_wsl_ops.py` | 실제 NAS 공유 복구 drill은 아직 별도. |
| Phase 2 pre-submit | 부모 주문 수/금액 한도와 차단 context 노출 부족. | 1일 부모 주문 수, 같은 종목 pending, fill mismatch, 주문금액 한도를 broker 호출 전 차단하고 detail context 기록. | `app/services/live_order_manager.py`, `app/services/live_order_monitoring.py`, dashboard/report | 한도가 과하면 정상 재시도도 차단될 수 있음. Phase 2 의도상 안전 측 동작. |
| KIS fixture redaction | 실제 KIS 응답 sample 제공 전 민감정보 제거 절차가 수동. | redaction helper, unredacted finding audit, paper fixture candidate export script 추가. | `app/brokers/kis_response_redaction.py`, `scripts/export_kis_paper_fixture_candidates.py` | key 기반 redaction이므로 새 민감 key는 sample 수령 시 육안 검토 필요. |
| Live order guarded adapter | raw KIS client 위임 직전 이중 guard가 없음. | `KisLiveOrderAdapter`가 submit 직전 `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=true`, `profile_mode=live` 확인. cancel은 보호성 cancel-only 정책에 맞춰 enable flag와 분리. | `app/brokers/kis_live_order.py`, `tests/test_kis_live_order_adapter.py`, `tests/test_live_client_isolation.py` | streaming runtime에는 아직 연결하지 않음. |
| System clock | `±2초` 후보가 문서/순수 helper 수준. | readiness 필수 check key와 submit guard 선택 hook으로 연결. fixture 없으면 readiness 차단. | `app/services/system_clock.py`, `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py` | 기준 시각 원천은 아직 미연결. |
| Position accounting | unknown fill side가 조용히 무시될 수 있음. | invalid side count를 결과와 detail JSON에 남김. | `app/services/live_position_accounting.py` | 실제 `live_positions` 정본 저장은 아직 보류. |
| Intent/raw response validation | 잘못된 intent나 raw broker payload가 원장에 남을 수 있음. | 필수 trace field, side, qty, limit price를 DB write 전 검증하고 order/execution raw payload 저장 전 redaction. | `app/services/live_order_manager.py`, `app/services/live_execution_sync.py` | 임시 빈 trace field를 쓰는 후속 연결 코드는 실패함. 실전 원장 안전 측 동작. |
| Market data freshness | runtime running/WS connected와 주문 직전 데이터 신선도가 분리되지 않음. | 최신 체결 tick, 호가 tick, 1분봉, 예측 timestamp age를 순수 판정하고 submit guard hook으로 연결. | `app/services/market_data_freshness.py`, `app/services/live_order_guard.py` | runtime/report 최신 row를 실제 decision으로 조립하는 연결은 후속. |

관련 문서/코드 경로: `app/services/`, `app/brokers/`, `scripts/`, `tests/`, `docs/Production-Implementation-Blueprint.md`

## 4. 장중 이슈에서 반영한 안전 교훈

2026-05-18 장중 KIS WebSocket이 `no close frame received or sent`로 반복 재연결되는 현상을 확인했습니다. runtime은 paper 모드였고 데이터 수집은 계속됐지만, 실전 구조에서는 같은 문제가 주문 안전에 직접 영향을 줄 수 있습니다.

반영한 것:

- `runtime running` 또는 `WS connected` 자체를 주문 허용 근거로 쓰지 않는 방향을 명확히 했습니다.
- `app/services/market_data_freshness.py`로 최신 tick/bar/prediction 신선도 판정 helper를 추가했습니다.
- submit guard가 freshness decision을 선택적으로 받아 stale이면 broker 호출 전 차단할 수 있게 했습니다.

아직 남은 것:

- WebSocket keepalive 정책.
- 누적 reconnect와 연속 실패 reconnect metric 분리.
- reconnect storm dashboard/alert.
- runtime/report 최신 row를 freshness decision으로 조립해 실제 guard에 넘기는 연결.

Codex 권장안:

- Phase 2 submit 전에는 freshness check를 필수로 올립니다.
- 기본 후보는 체결/호가 tick 30초, 1분봉/예측 120초, future tolerance 2초입니다.
- Phase 2에서 `orderbook_tick`을 필수로 둘지 여부는 cowork가 특히 봐 주세요. Codex 기본 권장안은 필수입니다.

관련 문서/코드 경로: `runtime-data/logs/app/live-runtime.stderr.log`, `app/brokers/kis_quote_ws.py`, `app/services/market_data_freshness.py`, `app/services/live_order_guard.py`

## 5. 검증 요약

대표 검증:

- `python -m unittest discover -s tests -p "test_*.py"` 통과, 237개.
- `python -m unittest discover -s tests -p "test_*.py"` 통과, 242개.
- `python -m unittest tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_live_alerting tests.test_kis_response_redaction tests.test_live_position_accounting tests.test_live_audit tests.test_live_order_manager tests.test_live_order_guard tests.test_live_execution_sync tests.test_kis_live_order_adapter tests.test_live_client_isolation tests.test_live_readonly_guard tests.test_live_storage tests.test_reporting tests.test_dashboard` 통과, 119개.
- `python -m unittest tests.test_market_data_freshness tests.test_live_order_guard` 통과, 15개.
- `git diff --check` 통과. 기존 `docs/Current-Implementation.md`, `docs/logbook.md` CRLF/LF 경고만 확인.
- `git diff -- app/risk VERSION config` 출력 없음.

주의:

- 최신 `market_data_freshness` 추가 이후 전체 discover는 다시 돌리지 않았고, 관련 좁은 테스트 15개와 `git diff --check`를 확인했습니다.
- 장중 보호 모드에서는 full test나 runtime DB write 가능성이 있는 명령을 피했습니다.

관련 문서/코드 경로: `tests/`, `.tmp-tests/`, `docs/logbook.md`

## 6. 안전 확인

- KIS 실제 운용 계좌 주문 없음.
- KIS live 주문/취소/조회 호출 없음.
- KIS paper API 신규 호출은 fixture export 작업에서 하지 않았습니다. export는 기존 `runtime-data/dev.db` read-only 조회 기반입니다.
- 운영 DB schema apply 없음.
- 실전 주문 활성 flag 변경 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 실제 텔레그램/이메일 발송 없음.
- 토큰, app key/secret, 계좌번호, 개인정보 본문 기록 없음.
- 자동 commit/push 없음.

관련 문서/코드 경로: `AGENTS.md`, `docs/Current-Implementation.md`, `docs/Versioning.md`

## 7. cowork가 우선 봐야 할 질문

1. Phase 2 잔량 자동 취소 금지와 같은 종목 pending 차단 정책이 실전 canary 첫 20거래일 기준으로 충분히 안전한가?
2. Phase 2 부모 주문 금액 한도 `min(100,000원, 운용 배정금의 10%)`가 너무 크거나 작은가?
3. `KisLiveOrderAdapter`에서 submit은 `ALLOW_LIVE_ORDERS=true`를 요구하고, 보호성 cancel은 enable flag와 분리한 정책이 적절한가?
4. 운영 원장에는 redacted payload만 저장하고 원본 broker response를 저장하지 않는 정책이 과하게 보수적인가?
5. audit event에서 `symbol`, `order_id`, `prediction_id`, `signal_id`, `gate_decision_id`, `rule_version`, `model_version`, `data_snapshot_id`를 필수로 강제하는 것이 맞는가?
6. `system_clock`은 Phase 1 readiness에서는 fixture/dry-run evidence로, Phase 2 submit에서는 필수 guard로 올리는 순서가 맞는가?
7. market data freshness 기본 후보 `trade/orderbook 30초`, `bar/prediction 120초`, future tolerance `2초`가 Phase 2 canary에 적절한가?
8. Phase 2에서 `orderbook_tick`을 필수 freshness 입력으로 둘지, 초기에는 선택 입력으로 둘 여지가 있는가?
9. unknown/stuck attention grace 기본값을 1분으로 두고, fill mismatch/kill switch/DB/disk 장애에는 grace를 적용하지 않는 방향이 적절한가?
10. 실제 NAS 공유 복구 drill은 Phase 1 read-only 전 필수인지, Phase 2 주문 전 필수인지 봐 주세요.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `app/services/live_order_guard.py`, `app/services/live_order_manager.py`

## 8. Codex 권장안

🟢 다음 단계 권장:

- cowork 리뷰는 이 통합본 하나만 보고 `review_ver_11`로 남겨도 됩니다. 세부 확인이 필요한 경우에만 개별 `work_ver_11-*` 파일을 열면 됩니다.
- Phase 1은 read-only 구조 차단, readiness evidence, recovery export self-test, alert outbox까지만 통과 기준으로 둡니다.
- Phase 2 submit 전에는 `system_clock`과 `market_data_freshness`를 필수 guard로 올립니다.
- 운영 원장에는 redacted payload만 남기고, 원본 KIS 응답은 git 추적 밖 암호화 저장소를 쓸지 별도 결정 전까지 저장하지 않습니다.
- 실제 텔레그램/이메일 sender는 outbox 안정화와 redaction 검토 후 별도 slice에서 붙입니다.

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요:

- Phase 2 주문 금액 한도 최종값.
- system clock 허용치 `±2초` 유지 여부.
- audit 외부 anchor 방식과 보관 기간.
- 원본 broker response 별도 보관 여부.
- 실제 NAS 복구 drill 시작 시점.

관련 문서/코드 경로: `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-20.md`
