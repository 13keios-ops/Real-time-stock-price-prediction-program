# Codex Work Ver 20-9 - Broker Paper Backlog Fix And Step 0 Interpretation Lock

- 작성 시각: 2026-06-14 05:45 KST
- 범위: cowork Step 0 리뷰 반영, Phase 0 paper/KIS open order backlog 해소, cash gap no-action 판정 갱신
- 상태: 코드/문서 보강, 전체 회귀 검증, dashboard build 완료.

## 1. cowork 리뷰 반영 판단

cowork 리뷰의 핵심 지적은 맞다.

- Cybos buy-avoid proxy 의 `baseline`은 실제 runtime baseline 모델이 아니다.
- 기존 12/12 fold 개선 결과는 `LightGBM이 runtime baseline의 나쁜 매수를 막았다`가 아니라 `LightGBM이 자기 proxy 매수 후보 중 하락 위험이 높은 row 를 자체 필터링했더니 손실이 줄었다`로만 해석해야 한다.
- `BaselineDirectionModel`이 Cybos bar row 에서 runtime baseline replay 로 인정 가능한지 확인하는 Step 0 없이 Step 1 실험으로 넘어가면 안 된다.

Step 0은 이미 코드와 문서로 확인돼 있었다.

- `BaselineDirectionModel`은 `return_1m_pct`, `bid_ask_imbalance`, `spread_bps`를 사용한다.
- Cybos bar row 는 `return_1m_pct`는 갖지만 live orderbook 피처인 `bid_ask_imbalance`, `spread_bps`를 갖지 않는다.
- 함수 호출 자체는 누락 피처 기본값 때문에 가능하지만 runtime baseline 재현은 아니다.
- 따라서 Cybos rescue 1차 실험은 `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로만 해석한다.

반영:

- `docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`에 self-filter 해석 제한을 추가했다.
- `docs/Execution-Plan.md`와 `docs/Production-Transition-Progress.md`에도 같은 해석 제한을 반영했다.

관련 문서/코드 경로:
`app/models/baseline.py`,
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`

## 2. broker paper backlog 원인

2026-06-14 장외 점검에서 기존 153건 open order backlog 의 원인을 확인했다.

- KIS order-fill 조회가 정상 응답해도 오래된 주문은 KIS lookback 에서 사라질 수 있다.
- 기존 sync normal path 는 broker row 가 없으면 이전 final/applied fill 상태를 충분히 보존하지 못하고 `pending_lookup`처럼 다시 볼 수 있었다.
- 그 결과 이미 적용된 체결이 있거나 과거 주문일 잔량인 row 가 active open count 를 부풀렸다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

- 변경 전: KIS lookback 에서 사라진 주문이 이미 full fill 로 적용됐거나 과거 주문일 잔량으로 남아도 다음 sync 에서 open backlog 로 되살아날 수 있었다.
- 변경 후: 이전 final 상태와 applied fill 수량을 보존하고, 정상 조회 뒤에도 남은 과거 주문일 잔량은 `expired` 또는 `expired_partial` final 상태로 닫는다.
- 영향 범위: `app/services/broker_paper_sync.py` normal sync 해석, broker-paper 관련 테스트, read-only backlog 분석 리포트.
- 회귀 위험: 당일 open 주문을 잘못 final 처리하면 안 되므로 주문일이 동기화일보다 이전인지 확인하고, KIS rate-limit 조회 실패 경로에서는 기존 pending 보존 원칙을 유지한다.

관련 문서/코드 경로:
`app/services/broker_paper_sync.py`,
`tests/test_broker_paper_sync.py`

## 3. 추가 구현

추가/변경:

- `app/services/broker_paper_sync.py`
  - broker row 가 없을 때 이전 snapshot 의 `filled/cancelled/rejected/expired` final 상태를 보존한다.
  - 이전 `applied_fill_qty`가 주문 수량 이상이면 `filled`로 유지한다.
  - 과거 주문일 잔량은 정상 조회 뒤 `expired` 또는 `expired_partial`로 닫는다.
- `scripts/summarize_broker_order_backlog.py`
  - 현재 view 기준 broker open order backlog 를 read-only 로 분석한다.
  - 최신 alignment marker 이후 제출 주문, 최신 broker status snapshot, projection reason 을 함께 본다.
- `scripts/summarize_paper_cash_gap.py`
  - 이미 position/effective cash/total asset/open order 가 정합하면 권고를 `keep_current_alignment`와 `no_cash_gap_action_required`로 낮춘다.

관련 문서/코드 경로:
`scripts/summarize_broker_order_backlog.py`,
`scripts/summarize_paper_cash_gap.py`

## 4. 실제 실행 결과

실행:

```bash
python -m app --sync-broker-paper-orders
./scripts/verify_paper_dual_account_match.sh -AlignToBroker -AsJson
python scripts/summarize_broker_order_backlog.py --as-json
python scripts/summarize_paper_cash_gap.py --as-json
python -m app --build-dashboard
```

결과:

- broker paper sync 실행 출력 기준 기존 backlog 는 `open_order_count=0`, `final_order_count=173`, `pending_symbols=[]`까지 닫혔다.
- 이후 `-SyncInitialCash` 없이 marker-only `-AlignToBroker`를 적용했다.
- 최신 dual account match 는 `status=matched_waiting_first_submission`이다.
- effective cash gap 과 total asset gap 은 `0원`이다.
- broker raw cash 와 effective cash 의 차이 `29,991원`은 `raw_cash_gap`으로 분리한다.
- 최신 backlog analysis 는 marker 이후 현재 view 기준 `submission_rows=0`, `current_open_order_count=0`, `projected_open_order_count=0`, 권고 `backlog_cleared_no_action`이다.
- 최신 cash gap analysis 는 권고 `keep_current_alignment`, 다음 조치 `no_cash_gap_action_required`다.

관련 문서/코드 경로:
`runtime-data/reports/broker-paper/latest-sync.json`,
`runtime-data/reports/broker-paper/latest-open-order-backlog-analysis.json`,
`runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`,
`runtime-data/reports/reconciliation/latest-paper-cash-gap-analysis.json`

## 5. 검증

실행:

```bash
python -m py_compile app/services/broker_paper_sync.py scripts/summarize_broker_order_backlog.py scripts/summarize_paper_cash_gap.py tests/test_broker_paper_sync.py tests/test_broker_order_backlog_analysis.py tests/test_paper_cash_gap_analysis.py
python -m unittest tests.test_broker_paper_sync tests.test_broker_order_backlog_analysis tests.test_paper_cash_gap_analysis -q
python -m unittest tests.test_broker_paper_sync tests.test_broker_order_backlog_analysis tests.test_paper_cash_gap_analysis tests.test_paper_reconciliation tests.test_paper_alignment tests.test_wsl_ops -q
python -m unittest discover -s tests -p "test_*.py" -q
python -m app --build-dashboard
git diff --check
```

결과:

- py_compile 통과.
- broker/cash-gap 관련 단위 테스트 19개 통과.
- broker/paper reconciliation 관련 테스트 43개 통과.
- 전체 테스트 410개 통과.
- dashboard build 통과. 최신 dashboard snapshot 생성 시각은 `2026-06-14T05:50:20+09:00`이다.
- `git diff --check` 통과. CRLF/LF 경고만 확인.

관련 문서/코드 경로:
`tests/test_broker_paper_sync.py`,
`tests/test_broker_order_backlog_analysis.py`,
`tests/test_paper_cash_gap_analysis.py`

## 6. 다음 권장안

- 월요일 장전에는 새 주문 전 상태를 read-only 로 확인한다.
- 월요일 장후에는 신규 broker submission 이후에도 stale open 주문이 다시 active open 으로 재발하지 않는지 확인한다.
- `SyncInitialCash`와 추가 `AlignToBroker`는 현재 필요하지 않다.
- Cybos 연구는 buy-rescue 확장이 아니라 KIS live buy-avoid shadow 10거래일 누적 관측을 우선한다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`
