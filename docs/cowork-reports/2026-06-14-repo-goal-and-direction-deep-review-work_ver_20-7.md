# Codex Work Ver 20-7 - Paper/KIS Mismatch Recheck

- 작성 시각: 2026-06-14 05:15 KST
- 범위: Phase 0 paper/KIS 정합성 blocker 최신화
- 상태: 포지션 mismatch 는 해소. initial cash mismatch 와 open order backlog 는 남음.

## 1. 실행

실행:

```bash
python scripts/trace_paper_kis_mismatch.py --limit-per-table 20
./scripts/verify_paper_dual_account_match.sh -AsJson
python scripts/trace_paper_kis_mismatch.py --limit-per-table 20
```

주의:

- 실전 주문/취소 없음.
- `-SyncInitialCash`, `-AlignToBroker`는 실행하지 않음.
- NAS 백업 없음.

관련 문서/코드 경로:
`scripts/trace_paper_kis_mismatch.py`,
`scripts/verify_paper_dual_account_match.sh`

## 2. 결과

최신 mismatch trace:

- generated_at: `2026-06-14T05:07:15+09:00`
- assessment: `ok`
- summary: `no mismatched symbols`
- mismatch_count: `0`

최신 dual account match:

- checked_at: `2026-06-14 05:07:02 +0900`
- status: `initial_cash_mismatch`
- positions_match: `true`
- position mismatch count: `0`
- cash_gap: `-562,966.3392399959원`
- total_asset_gap: `-562,966.3392399959원`
- broker effective cash: `9,098,995원`
- local net liquidation: `8,536,028.660760004원`
- `.env` PAPER_INITIAL_CASH: `8,748,211원`
- 2026-06-09 marker-only alignment baseline snapshot: `9,301,757원`

최신 broker sync:

- status: `ok`
- synced_at: `2026-06-14T05:06:42+09:00`
- total_submissions: `173`
- matched_orders: `20`
- updated_orders: `140`
- applied_fill_events: `5`
- applied_fill_qty: `10`
- open_order_count: `153`
- pending symbols: `005380`, `005930`, `035420`, `068270`, `086520`, `105560`, `247540`, `373220`

추가 확인:

- 2026-06-14 broker sync 는 2026-06-12 15:07~15:08 close sell 5건을 새 fill 로 반영했다.
- 이 fill 반영 후 local position 은 0이 됐다.
- 따라서 남은 gap 은 포지션 수량 문제가 아니라 initial cash / cash ledger 문제다.

관련 문서/코드 경로:
`runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`,
`runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`,
`runtime-data/reports/broker-paper/latest-sync.json`

## 3. 해석

변경 전:

- 4종목 local-only position mismatch 가 Phase 0 blocker 로 보였다.

변경 후:

- 최신 계좌 snapshot 기준 포지션 mismatch 는 닫혔다.
- 남은 blocker 는 초기 현금 기준 불일치와 과거 open order backlog 다.

영향 범위:

- paper/KIS reconciliation 해석
- dashboard 계좌 카드
- 모델 성과 해석에서 paper 손익 신뢰도

회귀 위험:

- initial cash gap 을 바로 `-SyncInitialCash`로 덮으면 체결/수수료/세금/현금 기준 차이를 놓칠 수 있다.
- open order backlog 를 단순 삭제하면 주문 lifecycle 감사 추적이 끊길 수 있다.

관련 문서/코드 경로:
`docs/Production-Transition-Progress.md`

## 4. 권장안

권장안:

1. 지금은 `-SyncInitialCash` 또는 `-AlignToBroker`를 자동 적용하지 않는다.
2. initial cash gap 이 로컬 기준금액 문제인지, 체결/수수료/세금 반영 차이인지 계속 분해한다.
3. open order backlog 는 broker 실제 상태와 local 상태를 구분해 정리 기준을 만든다.
4. 포지션 mismatch 가 닫혔으므로 marker-only alignment 는 하지 않는다.
5. 다음 장외 작업은 initial cash sync 적용 전/후 영향을 dry-run 으로 계산하는 것이다.

관련 문서/코드 경로:
`runtime-data/reports/reconciliation/latest-paper-account-sync.json`,
`runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
