# Codex 작업 리포트 work_ver_3: review_ver_2 반영 + Slice 1/2a 구현 통합본

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_3`
- 기준 리뷰: `2026-05-14-production-architecture-implementation-blueprint-review_ver_2.md`
- 다음 cowork 리뷰 권장 파일명: `2026-05-14-production-architecture-implementation-blueprint-review_ver_3.md`
- 참고: `work_ver_3-1`, `work_ver_3-2`는 version 3이 cowork에게 아직 전달되지 않은 상태에서 남긴 내부 하위 작업 기록이다. cowork에게는 이 통합본 하나를 우선 전달하면 된다.

## 요약

`review_ver_2` 이후 Codex는 먼저 문서 보강을 했고, 계좌 소유자 또는 실전 운용 승인권자 승인 뒤 Slice 1과 Slice 2a를 구현했다.

이번 통합본의 핵심은 두 가지다.

- Slice 1: 실전 계좌 read-only 구조적 차단을 위한 `KisReadOnlyClient` 구현.
- Slice 2a: live 주문 전용 초기 원장 `market_status_snapshots`, `live_orders`, `live_order_events` 구현.

실전 주문 전송 경로는 만들지 않았다.

## 반영한 review_ver_2 항목

### Slice 1 acceptance criteria 보강

- read-only wrapper 공개 조회 메서드의 `inspect.signature` 동등성 테스트를 추가했다.
- factory가 non-live mode를 거부하는 negative test를 추가했다.
- module import만으로 token 발급, hashkey 발급, REST 호출이 발생하지 않는지 확인하는 import-time 부작용 테스트를 추가했다.
- Slice 1 테스트 실행 중 실제 KIS 네트워크 호출, token 발급, hashkey 발급은 0건이어야 한다는 기준을 문서화했다.

### `KisRestQuoteClient(` allowlist 분석

기존 직접 생성 경로를 allowlist로 관리한다.

| 경로 | mode 원천 | 호출 메서드 카테고리 | Phase 1 처리 |
|---|---|---|---|
| `app/collectors/historical.py` | `get_active_kis_profile(settings)` | 조회: `get_intraday_minute_chart` | live profile 가능 경로이므로 read-only wrapper 전환 후보 |
| `app/services/runtime.py` | `get_active_kis_profile(settings)` | 조회: `get_current_price`, `get_orderbook` | live profile 가능 경로이므로 read-only wrapper 전환 후보 |
| `app/services/collector.py` | `get_active_kis_profile(settings)` | 조회: `get_current_price`, `get_orderbook` | live profile 가능 경로이므로 read-only wrapper 전환 후보 |
| `app/services/kis_account.py` | `get_kis_profile(settings, resolved_mode)` | 조회: `get_account_balance` | live read-only 계좌 조회 후보 |
| `app/services/broker_paper.py` | `get_kis_profile(settings, "paper")` | paper 주문/조회: `submit_cash_order`, `get_account_balance`, `get_daily_order_fills` | paper mirroring 전용 예외로 유지 |
| `app/__main__.py` | `get_active_kis_profile(settings)` | 조회: `get_current_price`, `get_orderbook` | CLI 조회 경로. live profile이면 read-only wrapper 전환 후보 |

allowlist는 영구 예외가 아니라 Phase 1~2 전환 중 임시 통제 목록이다. grep false positive는 allowlist reason으로 관리하고, dynamic import/subclass/getattr 같은 이론적 우회는 코드 리뷰로 잡는 한계가 있다.

### Slice 2a schema 보강

- `reject_reason`, `cancel_reason`, `parent_order_id`는 nullable로 뒀다.
- `broker_order_no`, `broker_branch_no`는 브로커 응답 전 빈 문자열로 `NOT NULL`을 유지한다.
- `status_json`, `live_orders.detail_json`, `live_order_events.detail_json` 최소 JSON key 규약을 추가했다.
- `live_order_events.actor` 표준 값 후보를 추가했다.
- dataclass-schema 정합성, JSON 최소 key, actor 표준값, unique idempotency를 테스트로 잠갔다.

## Slice 1 구현 결과

추가 파일:

- `app/brokers/kis_readonly.py`
- `tests/test_live_readonly_guard.py`
- `tests/test_live_client_isolation.py`

`KisReadOnlyClient`는 `KisRestQuoteClient`를 composition으로 감싸고 조회 메서드만 노출한다.

허용 메서드:

- `get_current_price`
- `get_orderbook`
- `get_intraday_minute_chart`
- `get_account_balance`
- `get_daily_order_fills`

노출하지 않는 메서드:

- `submit_cash_order`
- `cancel_order`

`get_kis_live_readonly_client(settings, mode="live")` factory는 `live`만 허용하고, `paper` 등 다른 mode는 `ValueError`로 거부한다.

검증:

- 주문/취소 메서드 미노출 확인.
- 조회 메서드 signature가 delegate와 같은지 확인.
- delegate 호출 인자 확인.
- factory가 live profile만 사용하는지 확인.
- non-live mode 거부 확인.
- import-time network side effect 없음 확인.
- 기존 paper mirroring 경로가 paper profile을 유지하는지 확인.

## Slice 2a 구현 결과

수정/추가 파일:

- `app/storage/contracts.py`
- `app/storage/sqlite_store.py`
- `app/storage/runtime_writer.py`
- `tests/test_live_storage.py`

구현된 초기 원장:

- `market_status_snapshots`
- `live_orders`
- `live_order_events`

핵심 잠금:

- `live_orders.idempotency_key`는 `UNIQUE`이고 duplicate insert가 실패한다.
- `MarketStatusSnapshot.status_json`은 `symbols`, `market_session`, `source_generated_at` 키를 요구한다.
- `LiveOrder.detail_json`은 `order_policy`, `blocking_reasons`, `raw_broker_response` 키를 요구한다.
- `LiveOrderEvent.detail_json`은 `reason`, `source`, `raw_broker_response` 키를 요구한다.
- `LiveOrderEvent.actor`는 `system`, `account_owner`, `recovery`, `kill_switch`, `codex`만 허용한다.
- `fetch_open_live_orders()`를 추가해 open 계열 상태 조회를 준비했다.
- `RuntimeWriter`가 live JSONL과 SQLite에 fan-out할 수 있게 했다.

아직 구현하지 않은 것:

- live 주문 제출
- live 주문 취소
- live 체결/포지션 원장
- 감사 hash chain
- live order guard
- live order manager
- market status decision 로직

## 문서 갱신

갱신한 문서:

- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`
- `docs/cowork-reports/README.md`
- `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision.md`

문서상 `운영자`는 Codex나 Claude cowork가 아니라 계좌 소유자 또는 실전 운용 승인권자로 정의했다.

Phase 2는 실전 소액 canary/시범운용으로 정리했다.

계좌 소유자 또는 실전 운용 승인권자가 채택한 권장안:

- Phase 2 보수 모드 첫 20거래일:
  - 1일 최대 손실: `min(운용 배정금 A의 1%, 30,000원)`
  - 종목별 최대 손실: `min(A의 0.5%, 20,000원)`
- Phase 2 기본 모드:
  - 1일 최대 손실: `min(A의 2%, 50,000원)`
  - 종목별 최대 손실: `min(A의 1%, 30,000원)`
- 일반 신규/청산 지정가 주문 슬리피지:
  - warning 10 bps
  - hard 20 bps
  - 호가단위 반영: `max(1 tick, 10 bps)`, `max(2 ticks, 20 bps)`
- Phase 2 신규 진입은 지정가 only.
- 시장가는 기본 금지.
- 비상 청산 시장가는 청산 건별 수동 승인 후보.
- VI 발동 중 신규 주문 금지.
- VI 발동 중 기존 open 주문은 조회 보류.
- 잔량 취소는 cancel-only guard 통과 뒤 허용 후보.

## 검증 결과

Slice 1 targeted test:

- `python -m unittest tests.test_live_readonly_guard tests.test_live_client_isolation tests.test_kis_http_clients tests.test_settings`
- 결과: 통과, 19개.

Slice 2a targeted test:

- `python -m unittest tests.test_live_storage`
- 결과: 통과, 5개.

Storage/paper 회귀:

- `python -m unittest tests.test_live_storage tests.test_sqlite_store tests.test_broker_paper_sync tests.test_paper_reconciliation`
- 결과: 통과, 21개.

전체 테스트:

- `python -m unittest discover -s tests -p "test_*.py"`
- 결과: 통과, 124개.

Diff 검증:

- `git diff --check`
- 결과: 통과.
- 참고: `docs/logbook.md` CRLF/LF 변환 warning만 있음.

## 안전 확인

- 실전 주문 API 호출 없음.
- `ALLOW_LIVE_ORDERS` 변경 없음.
- `app/risk/` 변경 없음.
- gate 기준값 변경 없음.
- `VERSION` 변경 없음.
- `config/` 변경 없음.
- 자동 commit/push 없음.
- KIS app key, app secret, token, 계좌번호 본문 기록 없음.

## cowork 리뷰 요청 질문

토큰이 제한적이면 아래만 봐도 된다.

1. Slice 1 `KisReadOnlyClient`가 Phase 1 read-only 구조적 차단으로 충분한가?
2. Slice 1 allowlist static test가 너무 빡세거나 너무 느슨하지 않은가?
3. Slice 2a `live_orders` / `live_order_events` / `market_status_snapshots` schema가 후속 live order manager와 execution sync에 필요한 최소 필드를 충분히 담는가?
4. `live_orders.idempotency_key UNIQUE + INSERT 실패` 정책이 운영 안전 관점에서 적절한가?
5. JSON 최소 key 검증과 actor enum 후보가 너무 이른 제약이거나, 반대로 부족한 제약은 아닌가?
6. 다음 작업을 Slice 3 market status 순수 로직으로 가는 것이 맞는가, 아니면 Slice 2b 체결/포지션/감사 원장 전에 migration/backup dry-run을 먼저 잠가야 하는가?

## 다음 작업 Codex 권장

🟢 다음 단계 권장: Slice 3 market status 순수 로직을 fixture 기반으로 먼저 구현한다. 외부 API 연결은 market status 원천 결정 뒤 별도 slice로 분리한다.

🟢 다음 단계 권장: Slice 2b 체결/포지션/감사 원장은 운영 DB migration/backup dry-run 절차를 테스트로 먼저 고정한 뒤 진행한다.

## 남은 결정

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요: market status 자동 데이터 원천을 KIS REST, 한국거래소 OpenAPI, 수동 snapshot 중 어디까지 Phase 1/2 필수로 둘지 결정해야 한다.

Codex 권장안: Slice 3은 수동/fixture snapshot 기반 순수 로직으로 시작하고, 자동 원천 연결은 KIS REST 또는 한국거래소 OpenAPI 후보를 비교한 뒤 별도 slice로 분리한다.

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요: audit hash chain anchor 방식, 보관 기간, NAS recovery self-test 미통과 시 Phase 2 금지 여부를 결정해야 한다.

Codex 권장안: live 주문 관련 audit은 append-only hash chain으로 남기고, NAS recovery export self-test 통과 전에는 Phase 2 주문을 열지 않는다.
