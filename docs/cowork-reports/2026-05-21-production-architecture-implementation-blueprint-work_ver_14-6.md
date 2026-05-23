# Codex work_ver_14-6: work_ver_14 시리즈 통합 전달본

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
통합 대상: `work_ver_14`, `work_ver_14-1`, `work_ver_14-2`, `work_ver_14-3`, `work_ver_14-4`, `work_ver_14-5`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 한 줄 결론

review_ver_13 이후 Phase 1 readiness의 로컬 증적 경로를 대부분 코드로 닫았다. 현재 실제 readiness는 `blocked`이며 남은 blocker는 `market_status` 실제 snapshot 증적 부재와 kill switch 상태 파일 missing 두 가지다.

이 통합본 하나만 cowork에 전달하면 된다.

## 2. 14 시리즈에서 닫은 것

| 버전 | 핵심 작업 | 현재 상태 |
|---|---|---|
| `work_ver_14` | HTTP `Date` header parser 강건화, `run_live_readiness_dry_run.sh --system-clock-check-path` 연결 | 완료 |
| `work_ver_14-1` | read-only 현재가 조회 1회로 sanitized `system_clock` check 생성 wrapper 구현 | KIS paper probe 1회 성공, `system_clock=true`, skew 약 0.167초 |
| `work_ver_14-2` | local readiness fixture snapshot wrapper 구현 | 로컬 증거가 있는 check만 fixture에 병합 |
| `work_ver_14-3` | KIS auth-only token refresh probe 구현 | KIS paper token refresh 1회 성공, token 원문 미저장 |
| `work_ver_14-4` | KIS account snapshot read-only probe, synthetic WS recovery probe 구현 | paper account snapshot 1회 성공, synthetic WS recovery 통과 |
| `work_ver_14-5` | repo-local manual market status snapshot probe 구현 | 코드 경로 완료. 실제 market status snapshot은 아직 없음 |

## 3. 현재 readiness 결과

최신 `runtime-data/reports/live-readiness/latest-readiness.json` 기준:

| check | 결과 | 해석 |
|---|---|---|
| `token_refresh` | true | paper auth-only refresh 성공. token 원문 저장 없음 |
| `ws_recovery` | true | synthetic/offline fault injection 성공. 실제 KIS WebSocket 관측은 아님 |
| `account_snapshot` | true | paper 계좌 snapshot read-only 조회 성공. 계좌번호/raw response 저장 없음 |
| `market_status` | false | 실제 snapshot 증적 없음. 자동 통과 금지 |
| `system_clock` | true | KIS REST HTTP `Date` 기반 skew 약 0.167초 |
| `kill_switch` | false | `kill-switch.json` missing. fail-closed로 정상 차단 |
| `database` | true | premarket SQLite read-only smoke 통과 |
| `disk_space` | true | 여유 공간 기준 통과 |
| `dashboard` | true | dashboard running 상태 확인 |
| `storage_migration_state` | true | planned 상태 확인 |

전체 상태: `blocked`

blocking reasons:

- `market_status_not_verified_by_fault_dry_run`
- `kill_switch_fault_dry_run_failed`

## 4. 보안/안전 경계

- KIS app key, app secret, token, 계좌번호는 리포트와 fixture에 저장하지 않는다.
- `account_snapshot` check는 row count와 주요 금액 필드 존재 여부만 저장한다.
- `token_refresh` check는 token type, expiry, seconds_to_expiry 같은 sanitized metadata만 저장한다.
- `ws_recovery` check는 실제 WebSocket을 열지 않고 `KisWebSocketReconnectMetrics` 상태 전이만 검증한다.
- `market_status` check는 repo 내부 수동 snapshot이 있을 때만 생성된다. KIS/거래소 자동 원천은 아직 붙이지 않았다.
- `kill_switch` missing은 fail-closed로 신규 submit 차단이다. 자동으로 OFF 파일을 만들지 않았다.

## 5. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| system clock | 문서 후보와 순수 helper 중심 | KIS REST HTTP `Date` 기반 sanitized check 생성 wrapper까지 연결 | `app/services/system_clock_probe.py`, `scripts/probe_kis_clock_reference.sh`, readiness dry-run | HTTP Date 초 단위 정밀도와 KIS header shape 의존. skew 초과 시 안전 차단 |
| token refresh | credential 준비 여부와 실제 refresh 성공이 분리되지 않음 | auth-only refresh 증적을 token 원문 없이 저장 | `app/services/kis_token_probe.py`, `scripts/probe_kis_token_refresh.sh` | KIS auth 장애 시 readiness blocked |
| account snapshot | account snapshot freshness 증거 없음 | read-only 계좌 snapshot sanitized check 생성 | `app/services/kis_account_probe.py`, `scripts/probe_kis_account_snapshot.sh` | live 계좌 shape는 아직 미확인. Phase 1 승인 뒤 확인 필요 |
| WS recovery | reconnect metric은 있었지만 readiness 증거 없음 | synthetic reconnect/drop/stable 상태 전이 check 생성 | `app/services/kis_ws_recovery_probe.py`, `scripts/probe_kis_ws_recovery.sh` | 실제 KIS WS 복구 증거가 아니므로 submit guard 기준으로 쓰면 안 됨 |
| market status | 실제 증거가 없으면 `not_verified` | repo-local manual snapshot이 있을 때만 check 생성 | `app/services/market_status_probe.py`, `scripts/probe_market_status_snapshot.sh` | 수동 snapshot 품질/신선도 의존. 자동 원천은 별도 slice 필요 |
| fixture snapshot | 일부 check만 병합 | token/account/synthetic WS/market/system/kill switch/premarket check 병합 | `app/services/live_readiness_fixture.py`, `scripts/build_live_readiness_fixture_snapshot.py` | 증거 없는 check는 계속 blocked. 의도된 안전 동작 |

## 6. 검증

최종 검증:

- `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager`
  - 통과, 119개.
- `python -m py_compile ...`
  - 통과.
- `bash -n scripts/probe_market_status_snapshot.sh scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과.
- `git diff --check`
  - 통과. CRLF/LF warning만 있고 whitespace error 없음.
- `git diff -- app/risk config VERSION`
  - 출력 없음.

## 7. Cowork 리뷰 요청

이제 cowork 리뷰가 필요한 지점이다. 코드 골격보다 정책 판단이 남았다.

질문:

1. Phase 1 readiness에서 `market_status`를 수동 snapshot으로 시작해도 되는가?
2. 자동 market status 원천은 KIS REST, 한국거래소, 수동 snapshot 중 어떤 순서로 붙이는 게 안전한가?
3. kill switch missing fail-closed를 Phase 1 직전까지 유지하고, 직전 승인 때만 OFF 파일을 생성하는 판단이 맞는가?
4. synthetic `ws_recovery`를 Phase 1 readiness check로는 허용하되 Phase 2 submit guard 기준으로 쓰지 않는 경계가 충분한가?
5. live account read-only probe는 Phase 1 승인 뒤 1회 실행으로 충분한가, 아니면 cowork 리뷰 전 shape 검증이 먼저 필요한가?

## 8. Codex 권장안

🟢 권장안:

- cowork에는 이 통합본 1개만 전달한다.
- Phase 1 전 market status는 수동 snapshot으로 시작한다.
- KIS/거래소 자동 market status 원천은 Phase 1 read-only 이후 별도 slice로 붙인다.
- kill switch `OFF` 파일은 지금 만들지 않는다. readiness 통과 직전 계좌 소유자 또는 실전 운용 승인권자 승인 후 `scripts/set_live_kill_switch.sh --disable --apply --confirm-disable`로 생성한다.
- synthetic WS recovery는 readiness의 로컬 단위 증거로만 쓰고, 실제 WS baseline은 Phase 1 read-only 첫 5~10거래일 동안 dashboard/readiness에 노출해 관측한다.

🔴 운영자 판단 필요:

- 실제 거래일 market status snapshot을 수동으로 만들지, 자동 원천 구현을 먼저 할지.
- Phase 1 직전 kill switch `OFF` 상태 파일을 생성할지.
- live account read-only probe를 언제 허용할지.

## 9. 주의

- 실전 주문 없음.
- live order submit/cancel 없음.
- 운영 DB schema apply 없음.
- runtime restart 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 자동 commit/push 없음.
