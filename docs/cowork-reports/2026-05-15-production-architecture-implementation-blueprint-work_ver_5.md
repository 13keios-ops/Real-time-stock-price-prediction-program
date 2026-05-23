# production architecture implementation blueprint work_ver_5

작성자: Codex
기준 리뷰: `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_4.md`
작성일: 2026-05-15

## 1. 시작 전 확인

- 장 상태 확인: `./scripts/get_live_runtime_status.sh` 기준 `session_status=post-close`, live runtime `stopped`.
- watchdog 확인: `./scripts/get_runtime_watchdog_status.sh` 기준 `market_session_status=post-close`, `live_runtime_should_run=false`.
- 최신 cowork 리뷰 확인: `review_ver_4`.
- 작업 경계: KIS live 주문 호출 없음, `ALLOW_LIVE_ORDERS` 변경 없음, `app/risk/` 변경 없음, `VERSION` 변경 없음.

## 2. 이번 반영 범위

`review_ver_4`의 결론인 "Slice 4 live_order_guard 진입 권장"을 기준으로 작업했습니다. 운영 경로 연결은 하지 않고, 주문 직전 가드와 kill switch 상태 파일의 순수 로직 및 테스트까지만 구현했습니다.

반영 항목:

- `codex` actor 제거, `test` actor 추가.
- `LiveOrder` 필수 문자열 빈 값 거부.
- `LiveKillSwitch` fail-closed read/write 구현.
- `LiveOrderGuard` read-only / submit / cancel-only 분리.
- market status flag truthy normalization 보강.
- 기준 문서와 logbook 갱신.

## 3. 변경 파일

- `app/storage/contracts.py`
  - `LIVE_ORDER_EVENT_ACTORS`에서 `codex` 제거, `test` 추가.
  - `LiveOrder.__post_init__`에서 필수 문자열 빈 값을 거부.
- `tests/test_live_storage.py`
  - `codex` actor 거부, `test` actor 허용, 필수 문자열 빈 값 거부 테스트 추가.
- `app/services/live_kill_switch.py`
  - `runtime-data/reports/live-risk/kill-switch.json` 후보 파일을 읽고 쓰는 service 추가.
  - missing/broken/stale 상태는 fail-closed로 신규 submit 차단.
  - cancel-only는 보호성 동작 후보로 허용.
  - write는 임시 파일 후 `os.replace`로 atomic replace.
- `tests/test_live_kill_switch.py`
  - missing, broken, stale, enabled, 정상 round-trip, `codex` actor 거부 검증.
- `app/services/live_order_guard.py`
  - `assert_readonly`, `assert_can_submit`, `assert_can_cancel` 추가.
  - submit 조건: live trading mode, live profile, `ALLOW_LIVE_ORDERS=true`, phase approval, 지정가 주문, kill switch 정상/off, market status allowed.
  - cancel 조건: live mode/profile과 phase 값만 확인하고 kill switch ON/missing/stale 상태에서도 cancel-only 후보를 허용.
- `tests/test_live_order_guard.py`
  - read-only 허용, submit 차단/허용, kill switch 차단, cancel-only 허용, market status 차단 검증.
- `app/services/market_status.py`, `tests/test_market_status.py`
  - `vi_active=1` 같은 truthy flag도 차단되도록 보강.
- `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`, `docs/cowork-reports/README.md`
  - Slice 4 구현 상태와 다음 권장 순서 반영.

## 4. 안전 경계

- 이번 구현은 브로커 주문 함수에 연결하지 않았습니다.
- `app/brokers/kis_quote_rest.py`의 주문 함수는 수정하지 않았습니다.
- KIS live 주문, 취소, hashkey, token 발급 호출 없음.
- `ALLOW_LIVE_ORDERS` 값 변경 없음.
- `app/risk/` 변경 없음.
- gate 기준값 변경 없음.
- `VERSION` 변경 없음.
- 자동 commit/push 없음.

## 5. Codex 판단

Slice 4는 실전 주문을 실제로 보내기 전 가장 중요한 마지막 차단점을 순수 로직으로 잠근 단계입니다. 아직 주문 경로에 연결하지 않았으므로 live 주문 안전을 완성한 것은 아니지만, 다음 구현에서 order manager가 반드시 호출해야 할 단일 guard 표면이 생겼습니다.

권장 다음 순서:

1. 운영 DB 적용 wrapper 보강: live runtime/dashboard 정지, backup, schema 적용, smoke query, rollback 절차.
2. Slice 2b live fill/position/audit schema.
3. Slice 5 live order manager에서 `LiveOrderGuard.assert_can_submit()`와 `assert_can_cancel()`을 호출하도록 연결.

## 6. cowork에게 묻는 리뷰 질문

1. `LiveOrderGuard.assert_can_cancel()`이 `ALLOW_LIVE_ORDERS=false`에서도 cancel-only 후보를 허용하는 정책이 Phase 2 안전 관점에서 맞는가?
2. kill switch missing/broken/stale 상태에서 cancel-only를 허용하는 현재 fail-closed 설계가 충분히 보수적인가?
3. `LiveKillSwitch.write_state()`의 기본 stale 기간 1일이 적절한가, 아니면 장중 운용 전용으로 더 짧게 둬야 하는가?
4. `LiveOrder` 필수 문자열 빈 값 거부 대상에 `broker_order_no`, `broker_branch_no`를 제외한 판단이 맞는가? 현재는 브로커 응답 전 빈 문자열을 허용하기 위해 제외했습니다.
5. 다음 작업을 운영 DB 적용 wrapper로 먼저 가는 판단이 맞는가, 아니면 `phase approval` 저장 구조를 Slice 4-2로 먼저 잠가야 하는가?

## 7. 현재 남은 위험

- `LiveOrderGuard`는 아직 실제 broker submit/cancel 호출 경로에 연결되지 않았습니다.
- phase approval 저장소와 approval hash/audit chain은 아직 없습니다.
- kill switch 파일을 운영자가 안전하게 ON/OFF하는 CLI는 아직 없습니다.
- 운영 DB 실제 적용 wrapper와 rollback 자동화는 아직 없습니다.
- live fill/position/audit schema는 Slice 2b로 남아 있습니다.

## 8. 검증 결과

- `python -m unittest tests.test_live_kill_switch tests.test_live_order_guard tests.test_live_storage tests.test_market_status`: 통과, 24개.
- `python -m unittest tests.test_live_kill_switch tests.test_live_order_guard tests.test_live_storage tests.test_market_status tests.test_storage_migration_dry_run_script`: 통과, 26개.
- `bash -n scripts/run_storage_migration_dry_run.sh scripts/script_dispatch.sh`: 통과.
- `python -m unittest discover -s tests -p "test_*.py"`: 통과, 146개.
- `git diff --check`: 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됨.
- `git diff -- app/risk VERSION config`: 출력 없음.
