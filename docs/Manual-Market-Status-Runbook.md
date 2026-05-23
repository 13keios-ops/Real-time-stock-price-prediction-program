# Manual Market Status Runbook

이 문서는 Phase 1 전까지 자동 market status 원천이 붙기 전, repo-local 수동 snapshot으로 `market_status` readiness 증거를 만드는 최소 절차다.

## 1. 목적과 경계

- 목적: 장전 readiness에서 watchlist 종목이 거래 가능 상태인지 수동 증거로 확인한다.
- 범위: repo 내부 JSON snapshot 파일을 읽어 `market_status` check JSON을 만든다.
- 제외: KRX/KIS 자동 조회, 외부 웹 scraping, 실전 주문, 계좌 조회.
- 실패 기본값: snapshot이 없거나 stale이거나 source enum이 맞지 않으면 readiness를 통과시키지 않는다.

관련 문서/코드 경로: `app/services/market_status_probe.py`, `scripts/probe_market_status_snapshot.sh`, `runtime-data/reports/live-readiness/`

## 2. Source Enum

수동 snapshot의 `source`는 아래 값 중 하나만 허용한다.

| source | 의미 | 사용 조건 |
|---|---|---|
| `manual_operator_snapshot` | 운영자가 직접 확인해 만든 snapshot | 자동 원천 전 임시 기본값 |
| `manual_krx_snapshot` | 한국거래소(KRX) 화면/자료를 사람이 확인해 만든 snapshot | KRX 공식 자동 API가 붙기 전 |
| `manual_kis_snapshot` | KIS 조회 화면/응답을 사람이 확인해 만든 snapshot | KRX 확인이 어렵고 KIS 상태만 임시 확인할 때 |

자유 문자열은 허용하지 않는다. `app/services/market_status_probe.py`가 enum 밖 source를 `failed`로 차단한다.

관련 문서/코드 경로: `app/services/market_status_probe.py`, `tests/test_market_status_probe.py`

## 3. Snapshot 양식

기본 위치 후보는 `runtime-data/reports/live-readiness/market-status-snapshot.json`이다.

```json
{
  "snapshot_id": "market-status-YYYYMMDD-001",
  "trading_day": "YYYY-MM-DD",
  "created_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "source": "manual_operator_snapshot",
  "symbol_set_hash": "symbols-sha256-<16hex>",
  "stale_after": "YYYY-MM-DDTHH:MM:SS+09:00",
  "status_json": {
    "market_session": "regular",
    "source_generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
    "symbols": {
      "005930": {
        "tradable": true,
        "vi_active": false,
        "halted": false,
        "managed": false,
        "caution": false,
        "limit_up": false,
        "limit_down": false
      }
    }
  }
}
```

`symbol_set_hash`는 snapshot의 `status_json.symbols` key를 정렬한 뒤 줄바꿈으로 이어 SHA-256 digest 앞 16자를 붙인 값이다. 예시는 `symbols-sha256-<16hex>` 형식이다. `scripts/probe_market_status_snapshot.sh --snapshot-path <path> --print-symbol-set-hash`로 현재 snapshot의 기대 hash를 출력할 수 있고, 값이 맞지 않으면 `app/services/market_status_probe.py`가 readiness 증거로 인정하지 않는다.

관련 문서/코드 경로: `runtime-data/reports/live-readiness/market-status-snapshot.json`, `app/storage/contracts.py`

## 4. 장전 절차

1. watchlist 대상 종목을 확인한다.
2. 각 종목의 거래정지, 관리/투자유의, VI 여부, 상한가/하한가, 정규장 거래 가능 여부를 확인한다.
3. snapshot의 `created_at`, `source_generated_at`, `stale_after`에 timezone을 포함한다.
4. `stale_after`는 장전 readiness 실행 시점 이후로 두되, 다음 거래일로 넘어가게 길게 두지 않는다.
5. snapshot 파일을 repo 내부 `runtime-data/reports/live-readiness/` 아래에 둔다.
6. `scripts/probe_market_status_snapshot.sh --snapshot-path <path> --print-symbol-set-hash`로 기대 `symbol_set_hash`를 확인해 snapshot에 반영한다.
7. `scripts/probe_market_status_snapshot.sh`로 check JSON을 만든다.
8. check가 failed면 Phase 1 readiness를 통과시키지 않는다.

관련 문서/코드 경로: `scripts/probe_market_status_snapshot.sh`, `scripts/build_live_readiness_fixture_snapshot.sh`, `scripts/run_live_readiness_dry_run.sh`

## 5. Stale 회복 절차

readiness에서 `market_status`가 `stale_evidence` 또는 `not_verified`로 막히면 아래 순서로 회복한다.

1. 수동 snapshot의 `trading_day`, `created_at`, `source_generated_at`, `stale_after`가 현재 거래일과 장전 실행 시점에 맞는지 확인한다.
2. `status_json.symbols` 대상 종목이 현재 watchlist와 일치하는지 확인한다.
3. `--print-symbol-set-hash`로 `symbol_set_hash`를 다시 계산한다.
4. `scripts/probe_market_status_snapshot.sh`로 `market-status-check.json`을 다시 만든다.
5. `scripts/build_live_readiness_fixture_snapshot.sh`와 `scripts/run_live_readiness_dry_run.sh`를 다시 실행한다.

관련 문서/코드 경로: `scripts/probe_market_status_snapshot.sh`, `scripts/build_live_readiness_fixture_snapshot.sh`, `scripts/run_live_readiness_dry_run.sh`

## 6. 권장안

🟢 다음 단계 권장: Phase 1 전 임시 기본 source는 `manual_operator_snapshot`으로 둔다.

🟢 다음 단계 권장: 자동 원천 우선순위는 KRX 공식 원천 확인 후 `KRX -> KIS -> 수동 snapshot` 후보로 검토한다. KRX 공식 API 가용성은 확인 필요다.

🔴 운영자 판단 필요: 매 거래일 장전 수동 snapshot을 누가 언제까지 만들지 정해야 한다. 권장안은 Phase 1 동안만 계좌 소유자 또는 위임 운영자가 장전 readiness 전에 생성하는 것이다.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`
