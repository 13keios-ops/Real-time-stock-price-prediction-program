# buy-avoid validation verification — work_ver_29

- 작성 시각: 2026-07-07 KST
- 작성자: Codex
- 대응 리뷰: `docs/cowork-reports/2026-07-06-buy-avoid-validation-verification-review_ver_28.md`
- 작업 범위: review_ver_28의 P0 §4·§5, P1 §3 보완 2건
- 금지선: 신규 실험, E2/E3 threshold/EV tuning, 종목별 주문 정책, h60 주문 정책, active model/gate 변경 없음

## 1. Codex 판단

cowork 지적은 타당합니다. 07-05 작업에서 실제로 KIS probe 분류 helper와 account snapshot 기반 system_clock 우회는 구현돼 있었지만, `KisApiError` 3종 실패를 코드/자격증명/KIS서버 문제로 어떻게 구분하는지와 account_snapshot probe가 paper/KIS mismatch root cause와 같은 문제인지가 한 문서에서 닫혀 있지 않았습니다.

이번 라운드 결론은 다음과 같습니다.

- 현재 `token_refresh`, `account_snapshot`, `system_clock`은 모두 ok 입니다.
- 따라서 Phase 1 readiness blocker는 KIS read-only 3종이 아니라 `ws_recovery` stale, `market_status`, `kill_switch`입니다.
- `account_snapshot` probe는 KIS 계좌 snapshot API 호출과 shape 검증이 정상인지 보는 체크입니다.
- paper/KIS mismatch는 account snapshot API 실패가 아니라 KIS 계좌 snapshot 수량과 KIS order/fill 원장 순수량이 서로 다른 현상입니다. 즉 관련은 있지만 같은 실패는 아닙니다.

## 2. P0 — KIS read-only probe 3종 원인 분리

실행한 read-only 확인:

```bash
./scripts/probe_kis_token_refresh.sh --mode paper --use-cache
./scripts/probe_kis_account_snapshot.sh --mode paper --output-path runtime-data/reports/live-readiness/account-snapshot-check.json --system-clock-output-path runtime-data/reports/live-readiness/system-clock-check.json
./scripts/build_live_readiness_fixture_snapshot.sh
./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json
```

결과:

| 항목 | 결과 | 해석 |
| --- | --- | --- |
| token_refresh | ok, auth-only, `seconds_to_expiry=30441.289` | 자격증명/토큰 문제 재현 안 됨 |
| account_snapshot | ok, `shape_status=ok`, `position_row_count=4`, `summary_row_count=1` | 계좌 snapshot API와 parser shape는 정상 |
| system_clock | ok, `source=kis_rest_http_date_account_snapshot`, `skew_seconds=0.075518` | quote endpoint를 추가 호출하지 않고 account 응답 Date로 확인 |
| readiness | blocked | blocker는 `ws_recovery` stale, `market_status`, `kill_switch` |

문서 반영:

- `docs/KIS-Connection-Runbook.md`에 probe별 error_category, 코드/자격증명/KIS서버 분류표를 추가했습니다.
- account_snapshot probe와 mismatch root cause 관계를 명시했습니다.

## 3. P1 — PreRegistration 보완

`docs/Model-Research-PreRegistration.md` 보완:

- OB-1 `spread_bps`: 1차 라운드 다중 비교 수 `k=12`로 고정.
- OB-2 `bid_ask_imbalance`: 1차 라운드 다중 비교 수 `k=24`로 고정.
- 사전등록 밖에서 발견한 조합은 `exploratory_only`로만 표시하고 주문 정책 후보로 올리지 않음.
- h60 random-control 기준: `abs(z_score) >= 2.5`, empirical percentile 5% 밖.
- h60 최소 표본: `days_usable >= 10`, `symbols >= 5`, `virtual_trades >= 100`.

## 4. 변경 파일

- `docs/KIS-Connection-Runbook.md`
- `docs/Model-Research-PreRegistration.md`
- `docs/Production-Transition-Progress.md`
- `docs/logbook.md`
- `docs/cowork-reports/2026-07-06-buy-avoid-validation-verification-review_ver_28.md`
- `docs/cowork-reports/2026-07-07-buy-avoid-validation-verification-work_ver_29.md`

## 5. 검증

- `token_refresh`, `account_snapshot`, `system_clock` read-only probe 재확인 완료.
- fixture 명시 readiness dry-run 완료.
- `git diff --check` 통과.
- `python3 -m unittest tests.test_kis_token_probe tests.test_kis_account_probe tests.test_kis_clock_reference_probe -q`: 22개 테스트 통과.
- 전체 pytest는 코드 변경이 없고 문서/운영 판정 보완 중심이므로 실행하지 않았습니다.

## 6. 남은 방향

- 2026-07-18 이후 첫 거래일 장후 전까지는 신규 실험을 늘리지 않습니다.
- 다음 cowork 리뷰는 07-18 이후 E1/E5 라운드 결과가 나오거나, Phase 1 readiness의 `market_status`/`kill_switch`/실제 WS evidence 중 하나를 코드로 닫는 작업을 시작할 때 요청하는 것이 적절합니다.
- 현재 즉시 추가로 할 일은 `market_status` 수동 snapshot과 kill switch 상태 파일을 Phase 1 readiness 규격으로 준비하는 것입니다. 단, 이 작업은 live submit 정책과 연결될 수 있으므로 별도 지시나 장전 readiness 흐름에서 처리하는 편이 안전합니다.
