# buy-avoid validation verification — work_ver_30

- 작성 시각: 2026-07-07 KST
- 작성자: Codex
- 대응 리뷰: `docs/cowork-reports/2026-07-07-buy-avoid-validation-verification-review_ver_29.md`
- 작업 범위: review_ver_29 §5 운영자 승인 반영, Phase 1 readiness fail-closed 준비
- 금지선: 실전 주문/취소, live submit 경로 연결, app/risk/, config/, VERSION, ALLOW_LIVE_ORDERS, gate 기준값, active model 변경 없음

## 1. Codex 판단

cowork review_ver_29의 핵심 판단은 타당합니다. KIS read-only 3종은 단일 야간 시점 기준 blocker가 아니고, 남은 blocker는 `ws_recovery` freshness, `market_status`, `kill_switch`입니다. 다만 `market_status`와 `kill_switch`는 readiness 통과를 위해 바로 열어서는 안 됩니다. 따라서 이번 작업은 “통과”가 아니라 “규격 준비 + fail-closed 유지”로 처리했습니다.

review_ver_29의 미세 지적도 반영합니다. 이번 work report에서는 변경 파일과 보관 파일을 구분합니다. cowork review 원본은 보관 대상으로 git에 포함할 수 있지만 Codex가 내용을 수정하지 않습니다.

## 2. 적용한 작업

### market_status

- `scripts/prepare_market_status_snapshot_template.py`와 `.sh` wrapper를 추가했습니다.
- helper는 `config/watchlist.txt` 기준 10종목 snapshot 템플릿을 만들고 `symbol_set_hash`를 자동 계산합니다.
- 템플릿은 모든 종목을 `tradable=null`, `operator_checked=false`로 둡니다.
- 실제 생성 경로: `runtime-data/reports/live-readiness/market-status-snapshot.json`.
- probe 결과: `status=failed`, `allowed_count=0`, 10종목 모두 `tradable_unknown`.

해석: 사람 확인 전에는 Phase 1 readiness가 통과하지 않는 것이 정상입니다.

### kill_switch

- `scripts/set_live_kill_switch.sh --enable --reason phase1_readiness_preparation_fail_closed --actor account_owner --stale-after-minutes 1440 --apply`를 실행했습니다.
- 실제 상태 파일: `runtime-data/reports/live-risk/kill-switch.json`.
- 상태: `enabled=true`, `submit_blocking_reason=kill_switch_enabled`.

해석: 상태 파일은 생겼지만 OFF가 아니라 ON이므로 submit 차단이 유지됩니다.

### 장전 재확인 절차

`.agents/skills/daily-ops-check/SKILL.md`에 다음 장전 절차를 추가했습니다.

- `ws_recovery` synthetic evidence 재생성.
- `token_refresh`, `account_snapshot`, `system_clock` 장전 시간대 read-only 재확인.
- `market_status` snapshot probe 실행.
- kill switch status 확인.
- fixture snapshot rebuild와 readiness dry-run 실행.

현재 야간 증거는 장전 증거를 대체하지 않는다고 명시했습니다.

## 3. 현재 readiness 결과

현재 시점 read-only/offline 증거를 다시 만들었습니다.

| check | 현재 결과 | 해석 |
| --- | --- | --- |
| `ws_recovery` | ok | synthetic/offline evidence, 다음 장전 재생성 필요 |
| `token_refresh` | ok | cached token check ok |
| `account_snapshot` | ok | `shape_status=ok`, position rows 4 |
| `system_clock` | ok | account snapshot HTTP Date 기준 skew 약 0.373초 |
| `market_status` | failed | fail-closed template 이므로 10종목 `tradable_unknown` |
| `kill_switch` | failed | 명시적으로 ON 상태라 submit 차단 유지 |

`runtime-data/reports/live-readiness/latest-readiness.json` 결과는 `status=blocked`입니다.
Blocking reasons 는 아래 2개입니다.

- `market_status_fault_dry_run_failed`
- `kill_switch_fault_dry_run_failed`

## 4. 변경 파일과 보관 파일

내용 변경 파일:

- `scripts/prepare_market_status_snapshot_template.py`
- `scripts/prepare_market_status_snapshot_template.sh`
- `scripts/script_dispatch.sh`
- `tests/test_prepare_market_status_snapshot_template.py`
- `.agents/skills/daily-ops-check/SKILL.md`
- `docs/Manual-Market-Status-Runbook.md`
- `docs/Current-Implementation.md`
- `docs/Execution-Plan.md`
- `docs/Production-Transition-Progress.md`
- `docs/logbook.md`

보관 파일:

- `docs/cowork-reports/2026-07-07-buy-avoid-validation-verification-review_ver_29.md`
- `docs/cowork-reports/2026-07-07-buy-avoid-validation-verification-work_ver_30.md`

## 5. 검증

- `bash -n scripts/prepare_market_status_snapshot_template.sh scripts/script_dispatch.sh` 통과.
- `python3 -m unittest tests.test_prepare_market_status_snapshot_template tests.test_market_status_probe tests.test_live_kill_switch tests.test_live_kill_switch_cli_script tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_ws_recovery_probe tests.test_kis_token_probe tests.test_kis_account_probe tests.test_kis_clock_reference_probe -q` 통과, 58개 테스트.
- 실제 fixture dry-run: `status=blocked`, blocker 2개가 의도대로 남음.

## 6. Codex 의견과 다음 방향

이 단계에서 readiness를 억지로 통과시키면 위험합니다. 지금 맞는 방향은 `market_status`와 `kill_switch`의 파일 형태와 절차를 먼저 안정화하고, 다음 장전 시간대에 증거를 다시 만든 뒤에도 차단이 의도대로 작동하는지 보는 것입니다.

다음 장전에서 운영자가 직접 확인한 market status가 들어오고, kill switch OFF에 대한 별도 명시 승인이 있을 때만 readiness 통과 후보가 됩니다. 그 전까지는 `market_status`와 `kill_switch`가 blocker로 남는 것이 정상입니다.

다음 cowork 리뷰가 필요한 시점:

- 다음 장전 후 `ws_recovery`/probe 3종 재확인 결과가 나오고,
- 운영자가 market status 실제 값과 kill switch OFF를 별도 승인했거나,
- readiness가 여전히 예기치 않은 blocker로 막힐 때.

07-18 이후 첫 거래일 장후 E1/E5 재측정 전까지 신규 실험, E2/E3 threshold/EV tuning, 종목별 주문 정책, h60 정책, active model/gate 변경은 계속 하지 않습니다.