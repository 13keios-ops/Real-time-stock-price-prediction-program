# Codex 작업 리포트 work_ver_7-2: fixture 기반 live readiness dry-run

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-1.md`
- 새 cowork review 없음. 따라서 명명 규칙에 따라 `work_ver_7-2`로 기록한다.
- 작업 시각: 2026-05-16 02시대, `weekend`
- 시작 상태:
  - `get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`
  - `get_runtime_watchdog_status.sh`: watchdog running, `market_session_status=weekend`, `live_runtime_should_run=false`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| readiness fault runner | premarket report를 readiness record로 바꾸는 adapter만 있었다. | `build_fault_injection_dry_run_report()`와 `scripts/run_live_readiness_dry_run.sh`를 추가했다. | `app/services/live_phase_readiness.py`, `scripts/`, tests | fixture 의미가 느슨하면 readiness 통과를 과대평가할 수 있음 |
| missing fixture 처리 | premarket report만으로 일부 항목이 true가 될 여지가 있었다. | fault dry-run에서는 fixture가 없는 모든 항목을 `not_verified=false`로 둔다. | readiness report | 실제 운영 전에 fixture 작성이 필요해 통과가 더 보수적으로 막힘 |
| report 산출물 | `premarket-readiness` JSON만 있었다. | `runtime-data/reports/live-readiness/latest-readiness.json`도 생성한다. | runtime report, dashboard 후속 | dashboard 연결 전에는 수동 또는 파일로만 확인 |

## 3. 구현 세부

신규/갱신 파일:

- `app/services/live_phase_readiness.py`
- `scripts/run_live_readiness_dry_run.sh`
- `scripts/script_dispatch.sh`
- `tests/test_live_phase_readiness.py`
- `tests/test_live_readiness_dry_run_script.py`

Dry-run 정책:

- 실제 장애를 만들지 않는다.
- Codex CLI를 호출하지 않는다.
- DB에 insert하지 않는다.
- `--execute` 또는 `--apply`는 거부한다.
- fixture path와 report path는 저장소 내부만 허용한다.
- fixture 값이 `ok`, `passed`, `healthy`, `ready`, `true`일 때만 해당 readiness check를 통과로 본다.
- fixture가 없으면 `not_verified`로 남기고 readiness를 차단한다.

## 4. 실행 결과

- `./scripts/run_live_readiness_dry_run.sh`
  - report: `runtime-data/reports/live-readiness/latest-readiness.json`
  - `status=blocked`
  - 이유: 실제 fixture를 주지 않았기 때문에 `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `kill_switch`, `database` 모두 `not_verified`

이 결과는 실패가 아니라 안전 측 동작이다. 명시 fixture 또는 후속 실제 검증 runner가 없으면 readiness가 통과되지 않아야 한다.

## 5. 검증

- `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
  - 통과, 12개
- `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh scripts/run_codex_ops_job.sh`
  - 통과

## 6. 안전 확인

- 실제 장애 주입 없음
- Codex CLI 실제 호출 없음
- 운영 DB insert/apply 없음
- KIS live 주문 API 호출 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 7. 남은 위험과 다음 권장

🟢 다음 단계 권장: dashboard가 `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`와 `runtime-data/reports/live-readiness/latest-readiness.json`을 읽어 `상태 및 설정` 탭에 표시하게 한다. Codex 권장안은 DB insert 없이 JSON read-only 카드부터다.

🟢 다음 단계 권장: fixture 파일 표준 예시를 문서화한다. 단, 실제 운영 token/account/market 값을 예시에 쓰지 않는다.

🟢 다음 단계 권장: 이후 실제 fault injection은 네트워크/브로커 장애를 만들지 않고 mock/fake status file 기반으로 먼저 제한한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 없음. 이번 작업은 dry-run report와 테스트만 추가했다.

## 8. cowork 확인 질문

1. missing fixture를 전부 `not_verified=false`로 차단하는 정책이 충분히 보수적인지.
2. fixture ok status 후보(`ok`, `passed`, `healthy`, `ready`, boolean true)가 너무 넓거나 좁지 않은지.
3. 다음 순서를 dashboard read-only 카드로 가도 되는지. Codex 권장안은 dashboard 카드 먼저, DB insert는 그 다음이다.
