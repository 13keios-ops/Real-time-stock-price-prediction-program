# Claude cowork 리뷰: Production Implementation Blueprint

## 검토 대상

- 요청서: `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-report.md`
- 본문: `docs/Production-Implementation-Blueprint.md` (531행 전체)
- 상위 기준: `docs/Production-Architecture.md` v2

## 요약

전반적으로 청사진은 **"한 PR에 어디까지 넣을지"가 잘 보이는 수준**까지 내려와 있고, 1차/2차 리뷰의 핵심 지적(read-only 구조적 차단, hard limit 슬롯 분리, market status snapshot, VI 처리, 주문 타입 정책, audit hash chain, NAS recovery self-test)이 모두 반영됐습니다. Slice 1은 즉시 코딩 가능한 수준이고, Slice 3·4도 적정 크기입니다. **유일하게 보강이 필요한 큰 구조 결함은 Slice 2의 크기**이며, 그 외는 누락 필드와 일부 단정조 보강 정도입니다. 결론은 **보완 권장**이고, 보완 후 Slice 1부터 코드 작업 진입해도 안전합니다.

## 질문 1: Slice 1~4가 실제 코드 작업 단위로 충분히 잘게 나뉘었는지

**Slice 1, 3, 4는 적정**, **Slice 2는 너무 큼**.

Slice 1은 새 파일 1개(`app/brokers/kis_readonly.py`) + 테스트 1개 + 기존 클래스 미수정으로 묶여 있어 한 세션 안에 완료 가능한 좋은 크기입니다. 469~478행의 절차가 명확하고, 검증 명령(`python -m unittest tests.test_live_readonly_guard tests.test_kis_http_clients tests.test_settings`)까지 명시되어 있어 그대로 진입 가능합니다.

Slice 3은 외부 API 없이 fixture 기반 순수 로직만 만들기 때문에 부담 적고 회귀 위험도 낮습니다.

Slice 4는 read-only / submit / cancel-only 세 guard의 분리가 명확하고, paper mirroring을 건드리지 않는다는 invariant(500행)도 좋습니다.

**Slice 2는 한 번에 너무 많이 넣습니다.** 8장에서 dataclass 9개(`MarketStatusSnapshot`, `LiveOrder`, `LiveOrderEvent`, `LiveFill`, `LivePosition`, `LivePortfolioSnapshot`, `LiveAuditEvent`, `LivePhaseApproval`, `LiveReadinessRun`) + SQLite 테이블 7개 + write 메서드 7개 + index 5개를 한 슬라이스로 묶었습니다. 코드 양으로는 300~500줄, 추가로 회귀 테스트 영향을 받는 파일이 `app/storage/contracts.py`, `sqlite_store.py`, `runtime_writer.py` 세 곳입니다. 한 PR에서 검토 가능한 크기를 넘습니다. **두 슬라이스로 쪼갤 것을 권장**합니다.

- Slice 2a: `market_status_snapshots` + `live_orders` + `live_order_events` + 관련 dataclass + write 메서드 (Slice 3·5 의존성 해소)
- Slice 2b: `live_fills` + `live_positions` + `live_portfolio_snapshots` + `ops_live_audit_events` + `live_phase_approvals` + `live_readiness_runs` (Slice 6·7·8 의존성 해소)

이렇게 쪼개면 Slice 2a 통과 후 Slice 3과 Slice 5 일부를 병행 시작할 수 있어 전체 일정에도 유리합니다.

**의존성 한 가지 누락**: Slice 4 guard가 kill switch 상태 파일(`runtime-data/reports/live-risk/kill-switch.json` 후보, 501행)을 읽어야 하는데, 이 파일의 스키마/관리 주체/생성 시점이 어느 슬라이스에서 정의되는지 청사진에 명시 없습니다. 아마 Slice 4에서 함께 만든다는 전제겠지만, **kill switch 파일 형식·관리 CLI·atomic write 정책**이 별도 문단으로 빠져 있어 Slice 4 작업 시작 전 추가 명시가 필요합니다.

## 질문 2: read-only client + live order guard 이중 차단이 Phase 1 P0로 충분한지

**구조적으로 충분하지만, 우회 경로 차단이 한 줄 추가되어야 완전합니다.**

이중 차단의 두 층(주문 메서드 미노출 + 런타임 enable/phase/kill switch 검증)은 서로 다른 종류의 실수에 대응하므로 좋은 구조입니다. 한 층은 "코드를 잘못 썼을 때"를 잡고, 다른 층은 "설정을 잘못 했을 때"를 잡습니다.

**보강 필요한 두 가지**:

첫째, `KisReadOnlyClient`가 `KisRestQuoteClient`를 composition으로 감싸기 때문에 **코드 어딘가에서 `KisRestQuoteClient`를 직접 인스턴스화하면 우회됩니다.** Slice 1 절차에 "live profile 사용은 반드시 `KisReadOnlyClient`를 통해서만"이라는 invariant(73행)는 있지만, 이걸 자동으로 검증할 수 없습니다. **Slice 1 또는 Slice 4 테스트에 "live profile로 `KisRestQuoteClient`를 직접 인스턴스화하는 경로가 코드베이스에 없음"을 grep 또는 import 검사로 잠그는 회귀 테스트를 추가**해야 우회 위험이 사라집니다. 예: `tests/test_live_client_isolation.py`가 `app/services/`, `app/collectors/` 안에서 `KisRestQuoteClient(`를 직접 호출하는 라인이 0개임을 확인.

둘째, `get_kis_readonly_client(settings, mode="live")` factory가 `paper`와 `live` 모두 받습니다(475행). 의도는 이해되지만, **Phase 1 서비스가 실수로 paper profile로 readonly client를 만들면 paper mirroring 경로가 우회**되어 paper 자동매매가 침묵 실패할 수 있습니다. paper mirroring이 활성인데 readonly로 가면 신호는 생기지만 KIS 모의계좌에 주문이 안 들어가는 상태가 됩니다. **factory에서 paper 모드일 때는 mirroring 활성 여부를 함께 검사해 충돌 시 명시적 오류를 내거나, Phase 1용 factory를 `live`만 받도록 명시적으로 좁히는 게 안전**합니다.

이 두 보강이 들어가면 P0로 충분합니다.

## 질문 3: live order 상태머신에서 빠진 국내 주식 특수 상태가 있는지

14개 상태(intent_created/blocked/submit_pending/submitted/accepted/open/partially_filled/filled/cancel_requested/cancelled/cancelled_partial/rejected/stuck/unknown)는 **국제 표준 lifecycle은 잘 잡았지만 KIS 고유 상황 두 가지가 빠졌습니다.**

첫째, **정정(modify) 상태**입니다. KIS는 주문 정정(가격/수량 변경)을 별도 API로 지원하고, Phase 2 정책(지정가 only)에서는 미체결 잔량의 가격 정정이 흔하게 필요합니다. 정정 없이 취소-재주문으로만 처리하면 idempotency key가 달라지고 audit chain이 길어집니다. **`modify_requested` → `modified` 상태를 추가**하거나, 명시적으로 "Phase 2에서는 정정 금지, 모든 변경은 cancel + new submit"라고 정책을 못 박는 게 필요합니다. 현재 청사진은 둘 중 어느 쪽인지 모호합니다.

둘째, **장 종료 자동 만료(expired) 상태**입니다. 일일 주문(IOC/FOK가 아닌 day order)은 장 종료 시 미체결 상태로 자동 만료됩니다. 현재 청사진은 이걸 `cancelled`로 묶어 처리할 가능성이 큰데, audit 관점에서 "사용자가 취소한 것"과 "시간 만료로 자동 종료된 것"은 의미가 다릅니다. **`expired` 상태 추가 또는 cancelled 상태에 `cancel_reason=auto_expire` 같은 sub-classification**이 필요합니다.

부수적으로 **VI 발동 중 미체결 주문**의 상태도 모호합니다. VI 발동 종목은 2분간 단일가매매로 전환되는데, 그동안 우리 미체결 주문이 KIS 시스템에서 어떻게 표시되는지(open 유지인지, 일시정지 별도 상태인지) 청사진에 없습니다. 데이터 원천 확인 필요 항목으로 적어도 됩니다.

## 질문 4: SQLite schema 초안에서 빠진 필드

**`live_orders`에서 4개, `live_fills`에서 4개, `ops_live_audit_events`에서 1~2개가 빠졌습니다.**

`live_orders` (207~232행) 누락:

- **`filled_qty`, `remaining_qty`**: 부분 체결 추적의 핵심. 게이트가 "잔량 있는 종목 신규 차단"을 평가할 때마다 `detail_json`을 파싱하면 비효율적이고 인덱싱이 어렵습니다. 별도 컬럼으로 두는 게 옳습니다.
- **`avg_fill_price`**: 진행 중에도 평균 체결가가 필요(슬리피지 추적, dashboard 표시).
- **`reject_reason`, `cancel_reason`**: 거절/취소 사유 코드. `detail_json`에 들어갈 수 있지만 별도 컬럼이 사후 분석에서 빠릅니다.
- **`parent_order_id`**: 정정/취소 chain 추적. 정정 상태가 빠져 있어 같이 빠진 듯합니다. 정정 상태를 추가하면 함께 추가 필요.

`live_fills` (248~261행) 누락:

- **`mid_price_at_fill`**: 슬리피지 계산을 위한 시장 중간가 snapshot. 사후 추정은 정확도가 떨어집니다.
- **`intended_price`**: 체결 시점의 의도 가격(주문 당시 limit_price). 정정으로 limit이 바뀌면 fill 시점 의도 가격이 사라집니다. fill별로 보존해야 슬리피지 분해가 정확합니다.
- **`slippage_bps`**: 의도 vs 체결 차이. 미리 계산해 저장하면 dashboard 빠른 표시.
- **`trading_session`**: 정규장 / 시초가 동시호가 / 종가 동시호가 / 단일가 구분. 슬리피지 분석에 핵심.

`ops_live_audit_events` (298~308행) 누락:

- **`actor`**: 누가 만든 이벤트인지(시스템/운영자/Codex). `live_order_events`에는 actor가 있는데(241행) audit에는 없습니다. 일관성 깨짐.
- **`chain_id` 또는 `chain_namespace`**: 단일 chain은 verify 비용이 큽니다. event_type 또는 entity_type별로 별도 chain을 두면 검증이 빠릅니다. 운영 관점 결정 사항이지만 컬럼은 미리 두는 게 안전.

부수: `market_status_snapshots`(196~204행)에 **`symbol_set_hash`** 또는 명시적 symbols 컬럼이 있으면 snapshot id로 watchlist 변경을 빠르게 비교 가능합니다. `status_json`에 들어 있겠지만 인덱싱 안 됩니다.

## 질문 5: "제안 신규"와 "현재 구현" 경계가 흐릿한 부분

대부분 잘 표시되어 있습니다. 다섯 군데 보강이 필요합니다.

첫째, **68행의 composition wrapper 가능성이 검증 안 됐습니다.** "Slice 1은 ... composition wrapper로 조회 메서드만 노출한다"는 목표가 적혀 있지만, **`KisRestQuoteClient`가 정말 composable한지(stateful resource를 점유하는 singleton이 아닌지, 토큰/세션이 instance에 묶여 있는지)** 가 청사진에 확인 안 됐습니다. Slice 1 시작 전 `KisRestQuoteClient.__init__` 시그니처와 의존성을 한 번 더 짚는 게 안전합니다. composition이 불가능하면 Slice 1이 design rework가 필요할 수 있습니다.

둘째, **138행의 재시작 복구 동작.** "재시작 시 `live_orders`에서 open 계열 상태를 먼저 조회하고 KIS live 주문/체결 조회로 복구한 뒤에만 새 신호 처리를 시작한다." — 목표 동작입니다. 그런데 **현재 `streaming.py`의 재시작 흐름이 어떻게 처리하는지** 본문에 없어 "어떻게 바뀌는지"가 모호합니다. Slice 5 또는 Slice 6 전에 현 동작을 한 줄로 적고 변경 내용을 표시하는 게 좋습니다.

셋째, **174~179행의 storage anchor.** "기존 RecordMixin dataclass 패턴", "`_initialize_schema()`, `_run_write_query()` / `_run_write_many()` 패턴"이 anchor로 적혀 있지만 각각이 무엇을 강제하는지(필드 직렬화 규칙, primary key 규약, 트랜잭션 보장)는 본문에 없습니다. **Slice 2 작업자가 `app/storage/contracts.py`를 읽어야 알 수 있는 상태**입니다. 청사진은 코드 직전이니 한 단락으로 RecordMixin/_initialize_schema의 핵심 규약을 옮겨 적는 게 작업 효율에 좋습니다.

넷째, **Slice 2의 SQLite migration 리스크가 빠졌습니다.** 484행 "schema 추가는 destructive migration이 아니어야 한다"는 좋은 invariant이지만, **SQLite는 ALTER TABLE 제한**이 있어 컬럼 추가는 가능해도 변경/삭제는 어렵습니다. 또한 **운영 중 DB(`runtime-data/dev.db`)에 새 테이블을 추가할 때의 lock·downtime·backup 절차**가 청사진에 없습니다. P2-B에 NAS recovery self-test가 있지만, Slice 2 직후의 운영 DB migration 한 번이 더 위험할 수 있습니다. Slice 2 절차에 "live runtime/dashboard 정지 → backup → migration → 검증 → 재기동" 같은 1줄 절차가 필요합니다.

다섯째, **393~398행의 5개 새 report 경로가 어느 슬라이스에서 처음 생성되는지 모호합니다.** `latest-readiness.json`은 Slice 1의 fault injection 결과인지, Slice 8의 dashboard 합치는 단계인지 표시 없습니다. 각 report 경로 옆에 "(Slice N)" 한 단어 추가하면 의존성이 분명해집니다.

## Codex가 적은 P0 결정 6개에 대한 cowork 의견

Codex 권장안 6개에 대한 cowork 입장만 짧게:

- **read-only client 차단 방식**: 권장안에 동의(별도 client 기본). 추가로 "주문/취소 메서드를 아예 만들지 vs hard fail로 둘지"는 **아예 만들지 않는 쪽**을 권합니다. hard fail은 호출 시점에 실패해서 audit이 남지만 코드 분석 도구(IDE, type checker)에서 "호출 가능"으로 보입니다. 메서드를 아예 노출하지 않으면 type 단계에서 차단됩니다.

- **VI 발동 중 open 주문 처리**: 권장안(신규 금지 + open 조회 보류 + 잔량 취소 cancel-only guard 통과 후 허용)에 동의. 다만 위 질문 3에서 적은 대로 **VI 발동 중 KIS 시스템에서 우리 미체결 주문이 어떤 상태로 표시되는지**가 데이터 원천 확인 필요 항목입니다.

- **Phase 2 주문 타입**: 권장안(신규 진입 지정가 only, 시장가 금지, 비상 청산도 수동 승인 시 시장가 예외)에 동의. **비상 청산 시장가 예외는 운영자 1회 승인으로 그날 모든 비상 청산에 자동 적용 vs 청산 건별 승인** 중 어느 쪽인지 명시되어야 합니다. 후자가 안전하지만 운영 부담이 크므로, 청산 건별 승인을 기본으로 하되 kill switch 발동 시(즉 일일 손실 한도 도달 시)에는 자동 적용으로 fallback하는 정책이 합리적 후보입니다.

- **일일 손실 한도와 슬리피지 budget**: 권장안(값 정해지기 전까지 live 주문 금지)에 강하게 동의. 이건 P0의 최우선 결정 항목입니다. 운영자에게 직접 "Phase 2에서 잃어도 운용 의사결정이 흔들리지 않을 일일 손실 한도가 얼마인지"를 묻는 게 가장 빠른 결정 경로입니다.

- **market status 데이터 원천**: 권장안(1차는 운영자 수동 calendar + fixture 순수 로직, KIS REST/거래소 OpenAPI 연동은 별도 slice)에 동의. Slice 3가 외부 API 없이 fixture로 시작하는 구조는 매우 좋습니다.

- **audit chain과 NAS 백업**: 권장안(append-only hash chain + recovery self-test 통과 전 Phase 2 주문 금지)에 동의. 추가로 위 질문 4에서 적은 `chain_id`/`actor` 필드 누락을 schema에 미리 반영하면 좋습니다.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Slice 1 크기 | 적정 | 없음 |
| Slice 2 크기 | 너무 큼 | 2a/2b로 분할 |
| Slice 3 크기 | 적정 | 없음 |
| Slice 4 크기 | 적정 | kill switch 파일 스키마 명시 |
| 이중 차단 충분성 | 충분 | 우회 경로 자동 검증 + factory 좁히기 |
| 상태머신 완성도 | 80% | modify, expired 상태 추가 또는 정책 명시 |
| live_orders 컬럼 | 80% | filled_qty, remaining_qty, avg_fill_price, reject_reason, cancel_reason, parent_order_id |
| live_fills 컬럼 | 70% | mid_price_at_fill, intended_price, slippage_bps, trading_session |
| audit 컬럼 | 90% | actor, chain_id |
| 단정조 정리 | 90% | composition 가능성·재시작 동작·storage anchor 1단락·migration 절차·report-slice 매핑 |

## 다음 단계 권장

1. Slice 2를 2a/2b로 분할하고 누락 컬럼 4개 카테고리(live_orders 6개, live_fills 4개, audit 2개, market_status 1개)를 schema 초안에 반영.
2. 상태머신에 정정 정책(modify 추가 또는 "Phase 2 정정 금지" 명문화)과 expired 처리 결정.
3. P0 결정 6개 중 (a) read-only 차단 방식 = 메서드 미노출 권장, (b) 일일 손실 한도/슬리피지 budget = 운영자 수치 결정 — 이 두 개가 풀리면 Slice 1 코드 진입 가능.
4. Slice 1 시작 전 `KisRestQuoteClient`의 composition 가능성 한 번 더 확인.
5. cowork-reports 폴더 핑퐁 운용 합의(이번 파일이 첫 케이스).

## 명명 규칙 제안

이 폴더에서의 핑퐁 운용 명명 규칙 후보:

- Codex → cowork 요청: `YYYY-MM-DD-{topic}-report.md`
- cowork → Codex 응답: `YYYY-MM-DD-{topic}-cowork-review.md`
- Codex 후속 보강: `YYYY-MM-DD-{topic}-codex-followup.md`
- 운영자 결정 기록: `YYYY-MM-DD-{topic}-operator-decision.md`

같은 topic의 여러 라운드는 같은 `{topic}` 키를 유지해 grep으로 history 추적이 가능합니다.
