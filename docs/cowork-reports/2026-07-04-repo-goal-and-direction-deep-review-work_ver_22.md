# 2026-07-04 repo goal/direction review follow-up - work_ver_22

## 1. Codex 판단 요약

`review_ver_22`의 핵심 지적은 타당합니다. 2026-06-15 이후 cowork review gap 이 길었고, buy-avoid shadow 는 이미 10거래일 checkpoint 를 넘겼는데도 walk-forward/challenger 재검증과 stale 리포트 갱신이 늦었습니다.

다만 buy-avoid 의 숫자가 좋아 보인다는 사실은 active model 승격이나 주문 정책 변경 근거가 아닙니다. 이 작업에서는 checkpoint 를 닫고, 같은 기준으로 walk-forward, challenger, mismatch, readiness 를 다시 갱신했습니다. 결론은 보수적입니다.

- buy-avoid 는 손실 축소 후보로 유지합니다.
- active model 은 `baseline-h15-v1` 유지입니다.
- challenger recommendation 은 `keep_active`입니다.
- gate 는 계속 `needs_review`입니다.
- 주문 정책, gate, active model, KIS live shadow 확장은 변경하지 않았습니다.

## 2. review_ver_22 항목별 처리

| 리뷰 항목 | Codex 판단 | 조치 | 현재 결론 |
|---|---|---|---|
| 3주 review gap | 타당 | work_ver_22 로 후속 기록 | 다음 review 는 checkpoint 중심으로 요청 |
| buy-avoid 10거래일 충족 | 타당 | 최신 shadow 수치와 재검증 결과 정리 | 관측 후보 유지, 주문 반영 없음 |
| walk-forward stale | 타당 | `run_gate_walk_forward_backtest.sh` 실행 | gate `needs_review` 유지 |
| challenger stale 가능성 | 타당 | `python3 -m app --run-challengers --horizon-min 15` 실행 | `keep_active`, promotion 없음 |
| mismatch trace stale | 타당 | `trace_paper_kis_mismatch.py` 실행 | 5종목 mismatch 남음 |
| live-readiness stale | 타당 | KIS read-only probes + fixture dry-run 재생성 | KIS `KisApiError`로 blocked |
| social signal status | 타당 | plan 문서에 no-events 해석 추가 | 인프라만 준비, 실제 검증 전 |
| safety 파일 직접 확인 | 부분 수행 | git diff 기준 금지 파일 변경 없음 확인 예정 | `app/risk/`, `config/`, `VERSION` 변경 없음 |

## 3. 실행 결과

### 3.1 buy-avoid shadow

참조 파일: `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`

- 관측 구간: 2026-06-11~2026-07-03
- joined rows: `25,198`
- threshold `0.40` skip: `6,694`
- net delta: `+486.38%p`

해석: LightGBM 기반 하락 위험 필터가 baseline 매수 후보 중 손실성 구간을 줄이는 단서가 있습니다. 하지만 이 값은 사후 관측이며, walk-forward gate 가 통과하지 않았으므로 주문 정책에 반영하지 않습니다.

### 3.2 gate walk-forward 재검증

참조 파일: `runtime-data/reports/backtests/latest-walk-forward-h15.json`

- evaluation id: `walk-forward-h15-20260704201528027664`
- evaluated at: `2026-07-04T20:15:28+09:00`
- parameter profile: `gate_reference_v1`
- folds: `118`
- rows evaluated: `5,900,000`
- trades taken: `1,572,715`
- three-class accuracy: `0.416342`
- cumulative net return pct: `-170,736.13`

해석: 전체 3분류 정확도와 비용 차감 성과가 여전히 낮습니다. buy-avoid 후보는 살아 있지만, 현재 모델 체인 자체를 공격적으로 승격할 상태는 아닙니다.

### 3.3 challenger 재평가

참조 파일: `runtime-data/reports/challengers/latest-challengers-h15.json`

- run id: `challenger-h15-20260704203559674231`
- active model: `baseline-h15-v1`
- recommended action: `keep_active`
- recommended model: `baseline-h15-v1`
- promotion applied: `false`
- walk-forward gate status: `needs_review`
- gate reason: `Walk-forward overall accuracy is too low (0.4163).`

해석: fresh centroid, LightGBM, linear-score 후보 모두 active 교체 근거가 아닙니다. 특히 표본이 작은 후보의 수익률은 과대 해석하지 않습니다.

### 3.4 paper/KIS mismatch trace

참조 파일: `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`

- generated at: `2026-07-04T20:18:46+09:00`
- broker sync: `status=ok`
- open order count: `0`
- final order count: `269`
- mismatch count: `5`
- symbols: `005380`, `035420`, `086520`, `105560`, `247540`

해석: open order backlog 는 없습니다. 다만 position mismatch 가 남아 있으므로 paper 손익과 모델 성과를 확정값처럼 해석하면 안 됩니다. 다음 장후 broker sync 이후에도 계속 남으면 reconciliation 우선순위를 올립니다.

### 3.5 live-readiness 재생성

참조 파일: `runtime-data/reports/live-readiness/latest-readiness.json`

- phase: `phase1a_paper_readonly`
- generated at: `2026-07-04T20:31:34+09:00`
- status: `blocked`
- 통과: synthetic `ws_recovery`, database, disk_space, dashboard, storage_migration_state
- 실패/차단: `token_refresh`, `account_snapshot`, `system_clock` KIS read-only probe `KisApiError`
- 비차단 미확인: `market_status`, `kill_switch`

해석: readiness stale 문제는 해결했지만, KIS read-only 쪽은 아직 막혀 있습니다. 이 문제를 닫기 전에는 Phase 1a 를 통과로 볼 수 없습니다.

### 3.6 social signal shadow

참조 파일: `runtime-data/reports/research/latest-social-signal-shadow-h15.json`

- status: `no_events_file`
- event count: `0`
- matched: `0`

해석: SNS/공개 영향력 이벤트는 아직 실제 검증이 아닙니다. 공식 API, 공개 feed, 수동 export 로 `runtime-data/social/signals/social_events.jsonl`이 생긴 뒤에야 성능을 말할 수 있습니다.

## 4. Codex 의견

이번 리뷰는 방향을 바꾸는 리뷰가 아니라, 이미 찬 checkpoint 를 정리하고 과대 해석을 막는 리뷰였습니다. 가장 중요한 결론은 아래입니다.

1. buy-avoid 는 버릴 후보가 아닙니다.
2. 그러나 현재 시스템을 수익 모델로 승격할 근거도 아닙니다.
3. Cybos/KIS 비교와 live shadow 는 defensive meta-filter 방향을 지지하지만, 공격적 매수/보유 rescue 는 아직 증거가 약합니다.
4. 현재 우선순위는 새 모델을 늘리는 것보다 KIS read-only probe 실패와 paper/KIS mismatch 를 먼저 닫는 것입니다.

## 5. 다음 진행 방향

- KIS `KisApiError` 원인을 token/account/system_clock probe 별로 분리합니다.
- 다음 장후 broker sync 뒤에도 5종목 mismatch 가 남는지 확인합니다.
- buy-avoid 는 30거래일, 60거래일 checkpoint 에서 같은 기준으로 다시 판정합니다.
- social signal 은 이벤트 파일이 생기기 전까지 성공/실패로 판단하지 않습니다.
- 다음 cowork 리뷰는 아래 중 하나가 생길 때 요청하는 것이 좋습니다.
  - KIS read-only probes 가 다시 통과하거나, 실패 원인이 코드/설정으로 특정됨.
  - paper/KIS mismatch 5종목이 해소되거나 구조적 원인이 밝혀짐.
  - buy-avoid 30거래일 checkpoint 가 참.
  - social event 표본이 최소 20건 이상 쌓임.

## 6. 안전 확인

- 실전 주문/취소 없음.
- `app/risk/` 변경 없음.
- `config/` 변경 없음.
- `VERSION` 변경 없음.
- `ALLOW_LIVE_ORDERS` 변경 없음.
- gate 기준값 변경 없음.
- NAS 백업 실행 없음.
