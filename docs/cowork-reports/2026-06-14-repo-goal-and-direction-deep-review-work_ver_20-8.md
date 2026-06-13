# Codex Work Ver 20-8 - Paper Cash Gap Dry-Run

- 작성 시각: 2026-06-14 05:25 KST
- 범위: Phase 0 paper/KIS `initial_cash_mismatch` 조치 전 영향 분석
- 상태: 실제 기준선 변경 없이 read-only dry-run 완료

## 1. cowork 리뷰 반영

cowork가 지적한 Cybos Step 0, 즉 `BaselineDirectionModel`을 Cybos bar row에서 실제 runtime baseline replay 로 볼 수 있는지 확인하는 항목은 이미 코드와 문서에 반영돼 있었다.

확인 결과:

- `BaselineDirectionModel`은 `return_1m_pct`, `bid_ask_imbalance`, `spread_bps`를 사용한다.
- Cybos bar row에는 `return_1m_pct`는 있지만 `bid_ask_imbalance`, `spread_bps`가 없다.
- 누락 feature 기본값 때문에 함수 호출은 가능하지만 runtime baseline 재현은 아니다.
- 따라서 현재 Cybos rescue 는 `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로만 해석한다.

관련 문서/코드 경로:
`app/models/baseline.py`,
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`tests/test_cybos_buy_avoid_proxy.py`,
`docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`

## 2. 추가 구현

추가 파일:

- `scripts/summarize_paper_cash_gap.py`
- `tests/test_paper_cash_gap_analysis.py`

목적:

- `-SyncInitialCash` 또는 `-AlignToBroker` 실행 전에 어떤 값이 바뀌는지 dry-run 으로 보여준다.
- 실제 `.env`, alignment marker, SQLite ledger 는 변경하지 않는다.
- `runtime-data/reports/reconciliation/latest-paper-cash-gap-analysis.json/.md`만 생성한다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

- 변경 전: `initial_cash_mismatch`를 보고 어떤 조치를 할지 판단하려면 수동으로 JSON을 대조해야 했다.
- 변경 후: raw cash, effective cash, local cash, env delta, snapshot gap 잔존 여부, hypothetical alignment baseline 을 한 리포트에서 본다.
- 영향 범위: reconciliation 분석 스크립트와 read-only report 생성.
- 회귀 위험: broker account snapshot 이 오래되면 dry-run 결론도 오래된다. 적용 직전 최신 계좌 snapshot 으로 다시 실행해야 한다.

관련 문서/코드 경로:
`scripts/summarize_paper_cash_gap.py`,
`tests/test_paper_cash_gap_analysis.py`,
`runtime-data/reports/reconciliation/latest-paper-cash-gap-analysis.json`

## 3. 실행 결과

실행:

```bash
python scripts/summarize_paper_cash_gap.py --as-json
```

결과 요약:

- `.env` PAPER_INITIAL_CASH: `8,748,211원`
- broker raw cash: `9,128,986원`
- broker effective cash: `9,098,995원`
- local cash / net liquidation: `8,536,028.660760004원`
- cash gap / total asset gap: `-562,966.3392399959원`
- positions match: `true`
- open order count: `153`

`SyncInitialCash` dry-run:

- target env initial cash: `9,128,986원`
- env delta: `+380,775원`
- current snapshot cash gap 을 닫는가: `false`
- 이유: `.env`의 시작 현금만 바꾸며 최신 portfolio snapshot, fills, broker order backlog 는 다시 쓰지 않는다.

`AlignToBroker` dry-run:

- hypothetical baseline cash/net liquidation: `9,098,995원`
- open positions: `0`
- env 변경: 없음
- 현재 view gap 을 닫을 수 있는가: `true`, 단 이후 fill 이 없다는 전제
- 주의: marker-only baseline 을 새로 쓰고 과거 paper row 를 현재 view 에서 cutoff 하므로 감사 메모가 필요하다.

관련 문서/코드 경로:
`runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`,
`runtime-data/reports/broker-paper/latest-sync.json`,
`runtime-data/reports/broker-paper/latest-alignment.json`

## 4. 판단

권장안:

1. 지금 `SyncInitialCash` 단독 실행은 하지 않는다.
2. `AlignToBroker`도 open order backlog 153건을 검토하기 전 자동 적용하지 않는다.
3. 다음 작업은 open order backlog 가 실제 미체결인지, 과거 final 상태를 local 이 open 으로 보는지, 조회 대상이 너무 넓은지 분리하는 것이다.
4. backlog 검토 뒤에도 포지션 mismatch 가 0이고 broker 계좌가 flat 이면, 당일 감사 메모를 남긴 뒤 marker-only alignment 를 별도 조치 후보로 본다.

관련 문서/코드 경로:
`docs/Production-Transition-Progress.md`,
`docs/Current-Implementation.md`

## 5. 검증

실행:

```bash
python -m py_compile scripts/summarize_paper_cash_gap.py tests/test_paper_cash_gap_analysis.py
python -m unittest tests.test_paper_cash_gap_analysis -q
python -m unittest tests.test_paper_cash_gap_analysis tests.test_paper_reconciliation tests.test_paper_alignment tests.test_wsl_ops -q
python -m unittest discover -s tests -p "test_*.py" -q
git diff --check
```

결과:

- py_compile 통과
- `tests.test_paper_cash_gap_analysis`: 3개 통과
- paper reconciliation/alignment/WSL ops 관련 테스트: 27개 통과
- 전체 테스트: 402개 통과
- `git diff --check`: 통과. CRLF/LF 경고만 확인.

관련 문서/코드 경로:
`tests/test_paper_cash_gap_analysis.py`
