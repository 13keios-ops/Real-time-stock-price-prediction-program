# Codex work_ver_12-2: KIS fixture mapper verification

작성: Codex
기준 리뷰: `2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`
상태: 2026-05-19 장후 `post-close`, runtime DB read-only fixture export 기반

## 1. 작업 요약

review_ver_11의 P0 권장 항목 중 `snapshot_from_kis_daily_order_fill()`과 KIS 실제 응답 shape 검증을 진행했다. 새 KIS API 호출 없이 `runtime-data/dev.db`를 read-only로 열어 redaction fixture 후보를 갱신했고, 그 shape를 테스트에 고정했다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| KIS daily order/fill raw shape 검증 | HTTP client 정규화 테스트는 있었지만, runtime DB에서 추출한 실제 KIS paper status snapshot shape와 live execution snapshot 변환을 한 번에 잠그지는 않았다. | `scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings`로 redacted 후보를 갱신하고, `tests/test_kis_http_clients.py`에 실제 field shape 기반 정규화 테스트를 추가했다. | `tests/test_kis_http_clients.py`, `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json` | fixture는 2026-05-15 KIS paper row shape 기준이다. KIS가 필드명을 바꾸면 테스트가 그 차이를 잡지만, 새 shape fixture 갱신이 필요하다. |
| live execution snapshot 변환 | `snapshot_from_kis_daily_order_fill()`는 synthetic `KisDailyOrderFillRecord` 중심으로 검증됐다. | redacted runtime fixture 값을 정규화한 record가 `sell`/`filled` snapshot으로 변환되는 테스트를 추가했다. | `tests/test_live_execution_sync.py`, `app/services/live_execution_sync.py` | 테스트 helper 주문은 Phase 2 기본 `max_order_qty=1`과 충돌하므로 execution sync 테스트 목적에 맞게 `max_order_qty=10`을 명시했다. 운영 기본값은 바꾸지 않았다. |

## 3. 확인한 fixture shape

`broker_paper_order_status_snapshots` richest candidate 기준으로 아래 KIS 원 필드를 확인했다.

- `ord_dt`
- `ord_gno_brno`
- `odno`
- `orgn_odno`
- `pdno`
- `sll_buy_dvsn_cd`
- `sll_buy_dvsn_cd_name`
- `ord_qty`
- `tot_ccld_qty`
- `rmn_qty`
- `avg_prvs`
- `cncl_cfrm_qty`
- `rjct_qty`
- `cncl_yn`
- `excg_id_dvsn_cd`

redaction summary:

- status: `ok`
- redaction_ok: `true`
- KIS API 신규 호출: 없음

## 4. 검증

실행 완료:

```bash
python scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings
python -m unittest tests.test_kis_http_clients tests.test_live_execution_sync tests.test_live_order_manager
python -m py_compile tests/test_kis_http_clients.py tests/test_live_execution_sync.py
python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_live_order_manager tests.test_live_order_guard tests.test_kis_http_clients tests.test_live_execution_sync
git diff --check
```

결과:

- KIS fixture export: `status=ok`, `redaction_ok=true`.
- `tests.test_kis_http_clients`, `tests.test_live_execution_sync`, `tests.test_live_order_manager`: 38개 테스트 통과.
- 대상 테스트 파일 `py_compile` 통과.
- 오늘 변경 범위 전체 관련 묶음 59개 테스트 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.

## 5. 남은 후속

🟢 다음 단계 권장:

- 이 fixture 검증을 readiness dry-run의 `ws_recovery`/`account_snapshot`와 분리해 `kis_order_fill_mapper_fixture` 같은 check key 후보로 추가한다.
- 실제 live Phase 1 read-only 연결 후에는 live 계좌 조회 결과를 같은 redaction helper로 저장해 paper/live field shape 차이를 비교한다.

🔴 운영자 판단 필요:

- 현재 없음. 실전 계좌 fixture를 저장할지 여부는 Phase 1 read-only 연결 직전에 별도 승인 대상으로 남긴다.
