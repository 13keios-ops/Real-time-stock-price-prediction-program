# 저장소 심층리뷰 후속: Phase 1b readiness 연결 work_ver 30-4

## 1. 이번 작업 목적

Phase 1b 실전계좌 read-only 관측 wrapper는 이미 있었지만, 관측 결과가 기존 10개 check readiness에 직접 연결되지 않아 실제 live 관측과 오래된 paper fixture를 혼동할 여지가 있었다. 또한 generic readiness는 `market_status`와 kill switch OFF를 모든 phase의 필수값처럼 처리해, 주문이 없는 Phase 1b까지 잘못 차단할 수 있었다.

이번 작업은 이 두 경계를 바로잡고 대시보드에서 별도 Phase 1b 판정을 확인할 수 있게 하는 데 한정했다. 실제 주문·취소, active model, gate, 주문 정책은 바꾸지 않았다.

## 2. 구현 내용

1. `phase1b_live_readonly` 전용 readiness profile을 추가했다.
   - 필수: token refresh, WebSocket recovery, account snapshot, system clock, database, disk space, dashboard, storage migration state
   - 비차단: `market_status`, `kill_switch`
   - 이유: 두 항목은 주문 제출 전용 안전장치이며 Phase 1b는 주문 없는 조회 단계다.
2. Phase 1b 관측 JSON을 readiness fixture override로 변환했다.
   - live token, paper/live account shape comparison, live system clock만 whitelist한다.
   - raw response, 계좌번호, token, 자격정보 값은 포함하지 않는다.
3. `run_live_readiness_dry_run.sh`에 `--phase1b-observation-path`를 추가했다.
   - 관측값은 paper fixture의 token/account/system clock보다 우선한다.
   - 관측이 누락·차단되면 paper 성공값으로 fallback하지 않고 fail-closed로 차단한다.
   - 관측 JSON 안의 precomputed override는 신뢰하지 않고 `execution_started`와 sanitized artifact에서 매번 다시 계산한다. forged override 회귀 테스트도 추가했다.
   - Phase 1b 이외의 phase에 이 옵션을 주면 거부한다.
4. 대시보드 `상태 및 설정 > 실전 전환 readiness dry-run` 표에 Phase 1b status/pass/blocker와 token/account/clock/WS를 별도 표시한다.
5. README, AGENTS, Current Implementation, Execution Plan, Production Blueprint, Transition Progress, KIS runbook, daily ops skill을 같은 기준으로 갱신했다.

## 3. 실제 장외 dry-run 결과

- 결과 파일: `runtime-data/reports/live-readiness/phase1b/latest-readiness.json`
- phase: `phase1b_live_readonly`
- status: `blocked`
- 필수 blocker:
  - `token_refresh_not_verified_by_fault_dry_run`
  - `account_snapshot_not_verified_by_fault_dry_run`
  - `system_clock_not_verified_by_fault_dry_run`
  - stale WebSocket recovery로 인한 `ws_recovery_fault_dry_run_failed`
- 비차단:
  - `market_status_fault_dry_run_failed`
  - `kill_switch_fault_dry_run_failed`
- 통과:
  - database
  - disk space
  - dashboard
  - storage migration state
- 이번 dry-run은 기존 차단 attempt를 병합한 offline 판정이다. KIS 네트워크, 주문/취소, readiness DB 기록은 실행하지 않았다.

## 4. 검증

- 관련 테스트: `64 tests OK`
- 전체 unittest: `484 tests OK`
- 전체 pytest: `484 passed, 67 subtests passed`
- Python compileall: 통과
- bash parse: 통과
- dashboard build: 통과, `generated_at=2026-07-11T01:12:55.449995+09:00`
- `git diff --check`: 통과
- runtime: weekend, live runtime stopped, watchdog/dashboard running, watchdog heartbeat fresh

## 5. Codex 비판적 의견

이번 변경 전 구조는 안전해 보였지만 Phase 1b에서 두 종류의 오판 가능성이 있었다.

첫째, paper token/account/clock 성공 증거가 남아 있으면 실계좌 관측이 실패해도 readiness가 통과한 것처럼 보일 수 있었다. 이는 실제 자금 계좌 shape를 확인한다는 Phase 1b 목적과 충돌한다. 따라서 fallback 제거는 필수였다.

둘째, 주문이 없는 read-only 단계에 market status와 kill switch OFF를 필수로 요구하면 구조 준비와 live-submit 준비가 섞인다. 이번 profile 분리는 안전장치를 약화한 것이 아니라, 적용 시점을 명확히 한 것이다. Phase 2부터는 두 항목이 다시 필수다.

현재 `blocked`는 코드 실패 판정이 아니다. 실계좌 조회 자격정보와 실제 bounded 관측이 없고 WS 증거가 stale한 상태를 정직하게 표시한 것이다. 자격정보 없이 더 코드를 추가해도 Phase 1b 증거는 좋아지지 않는다.

## 6. 다음 진행 방향

1. 실전 KIS 조회 자격정보를 `--read-only-preparation`으로 로컬 비밀 저장소에 준비한다. paper mode와 `ALLOW_LIVE_ORDERS=false`는 유지한다.
2. 장외에 네트워크 없는 preflight를 재통과한 뒤 bounded `--execute`를 1회 실행한다.
3. 같은 판정 시점에 fresh WS recovery 증거를 만들고 Phase 1b 전용 readiness를 다시 생성한다.
4. 주문 함수 호출 0건과 paper/live account shape 비교를 확인한 뒤에만 Phase 1b 관측 시작 여부를 판정한다.
5. 다음 거래일 장후에는 4종목 paper/KIS mismatch를 HTTP 1회 제한 wrapper로 재확인한다.
6. 모델 연구는 사전등록대로 2026-07-20 장후 E1 재측정과 E5 역발상 관찰 전까지 동결한다.

## 7. 다음 cowork 리뷰 시점

지금은 새 질문보다 외부 증거 확보가 먼저다. 다음 cowork 리뷰는 아래 둘 중 하나가 발생했을 때 요청하는 것이 효율적이다.

- 실제 Phase 1b bounded read-only observation과 전용 readiness 재판정이 생성됐을 때
- 2026-07-20 장후 E1/E5 라운드 결과가 생성됐을 때

그 전에는 같은 blocker를 문서 표현만 바꿔 반복 리뷰할 필요가 없다.

## 8. 변경하지 않은 항목

- 실전 주문/취소
- `app/risk/`
- `config/`
- `VERSION`
- `ALLOW_LIVE_ORDERS`
- active model/gate/threshold
- 신규 모델 실험
- NAS 백업
