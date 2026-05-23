# Claude cowork 리뷰 review_ver_2: Production Implementation Blueprint 통합 보강

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_2`
- 기준 작업본: `2026-05-14-production-architecture-implementation-blueprint-work_ver_2.md`
- 상위 본문: `docs/Production-Implementation-Blueprint.md`

## 요약

`work_ver_2`는 `review_ver_1`(레거시 `cowork-review.md`)의 12개 지적을 거의 빠짐없이 반영했고, 추가로 자율 보강한 항목(allowlist 현실화, Slice 1/2a acceptance criteria, fixture 원칙, kill switch schema, storage 핵심 규약)도 운영 안전 관점에서 옳은 방향이다. 결론은 **보완 권장이지만 보완이 작아 Slice 1 코드 작업 진입 가능**. Slice 1 진입과 함께 보강해도 되는 수준의 미세 조정만 남았다.

핵심 발견 세 가지: (1) Slice 1 acceptance criteria에 시그니처 동등성·factory negative·import-time 부작용 3개 테스트가 추가되어야 wrapper 우회 위험이 완전 차단된다. (2) `KisRestQuoteClient(` allowlist 6개 경로의 현재 mode 용도 분석이 빠져 있어 allowlist 자체의 안전성을 평가할 수 없다. (3) Slice 2a SQLite schema의 NOT NULL 결정이 SQLite의 컬럼 변경 제약 때문에 사실상 영구 결정인데 검토가 한 번 더 필요하다.

Q5 다음 단계 질문에 대한 답: **Slice 1 먼저가 맞다.** Slice 1과 Slice 3는 의존성이 없고, Slice 1 시작 전 composition 가능성 재확인이 후속 slice 전체 설계에 영향을 주므로 가장 먼저 푸는 것이 정보 가치가 높다.

## Q1: Slice 1 acceptance criteria가 구현 직전 기준으로 충분한지

**70% 충분.** 6개 acceptance criteria와 4개 fixture 원칙이 잘 짜여 있고 각 criteria에 테스트 함수명까지 적힌 점이 좋다. 다만 wrapper 우회 위험을 완전 차단하려면 세 가지 보강이 필요하다.

첫째, **시그니처 동등성 테스트가 빠졌다.** 75~101행의 wrapper 메서드 시그니처가 실제 `KisRestQuoteClient`의 시그니처와 1:1로 일치하는지 자동 검증이 없다. 누군가 `KisRestQuoteClient.get_account_balance`에 새 파라미터를 추가하면 wrapper가 silent하게 옛 시그니처로 위임해서 호출이 깨진다. `inspect.signature(wrapper.method) == inspect.signature(delegate.method)` 같은 자동 비교 테스트 한 줄이 필요하다. "조회 메서드 위임"(120행) criteria가 호출 횟수만 보면 이 회귀를 못 잡는다.

둘째, **factory negative 테스트가 빠졌다.** Phase 1 factory는 `live`만 받는다고 본문 112행에 적혔지만, `paper` 또는 잘못된 mode를 넣었을 때 raise하는지 silent fallback하는지 acceptance criteria에 없다. `test_live_readonly_factory_rejects_non_live_mode` 같은 negative 테스트가 잠금에 필요하다.

셋째, **import-time 부작용 검증이 빠졌다.** `KisReadOnlyClient`를 단순 import만 했는데 내부 `KisRestQuoteClient` 초기화에서 토큰 발급이나 네트워크 호출이 발생하면 안 된다. fixture 원칙에 "실제 KIS 네트워크 호출 안 함"(128행)이 있지만 import-time과 instantiate-time을 분리해서 잠그지는 않는다. `test_import_does_not_trigger_network` 한 줄이 안전.

부수: 검증 명령(`python -m unittest tests.test_live_readonly_guard tests.test_live_client_isolation`)이 acceptance criteria 표 자체에는 없고 별도 절차에 있는데, 표 옆 또는 아래에 한 줄 추가하면 PR 검토자가 한눈에 본다.

## Q2: KisRestQuoteClient( allowlist 방식이 우회 차단으로 충분한지

**60% 충분.** 현실주의(직접 생성 0건이 비현실적임을 인정하고 allowlist로 후퇴)는 옳고, 새 경로만 잠그는 접근도 회귀 위험을 만들지 않아 좋다. 그러나 네 가지 위험이 명시되지 않았다.

첫째, **allowlist 6개 경로(`historical.py`, `runtime.py`, `collector.py`, `kis_account.py`, `broker_paper.py`, `__main__.py`)의 현재 mode 용도 분석이 빠졌다.** 각 경로가 어떤 mode(paper/live)로 `KisRestQuoteClient`를 만들고, 만든 client에서 어떤 메서드(조회만/주문 포함)를 호출하는지가 본문에 없다. 만약 6개 중 하나가 이미 live profile을 받아 `submit_cash_order`를 호출하는 코드라면, allowlist에 두는 것 자체가 P0 위험이다. **6개 경로별 표(파일 / 받는 mode / 호출하는 메서드 카테고리) 한 번 정리**가 필요하다.

둘째, **allowlist의 영구성이 명시되지 않았다.** 103행에 "live profile을 받을 수 있는 경로는 read-only wrapper 전환 후보로 남기되"가 있지만 전환 일정이 없다. "임시 면제"인지 "영구 예외"인지가 작업자에게 모호하다. 6개 경로 각각 옆에 "Slice X에서 wrapper 전환 예정" 또는 "Phase 1 이후로도 paper 전용으로 유지"를 명시하면 allowlist 부풀림을 막는다.

셋째, **문자열 검색의 false positive 처리 정책이 없다.** 131행 "문자열 검색 기반"이라 주석/docstring/문자열 리터럴 안의 `KisRestQuoteClient(`도 매치된다. AST 기반은 무겁지만 grep은 false positive가 흔하다. 시작은 grep이 맞으나 false positive 발견 시 어떻게 처리할지(테스트 ignore 주석, 별도 화이트리스트, AST 전환 trigger) 한 줄 정책이 필요하다.

넷째, **이론적 우회 경로(subclass, getattr, dynamic import)는 grep으로 잡히지 않는다.** "정상 코드 작업에서 실수로 우회하지 않게"가 합리적 목표지 "이론적 우회까지 차단"이 아닌 점을 명시하면 작업자가 안전 한계를 안다. "이 isolation 테스트는 실수 차단용이며 의도적 우회는 별도 코드 리뷰로 잡는다"는 한 줄이 적당하다.

## Q3: Slice 2a dataclass/schema/smoke query 기준이 너무 크거나 빠진 필드가 있는지

**80% 충분. 누락 필드는 모두 반영됐고, 크기는 적절하다.** review_ver_1에서 지적한 12개 필드(filled_qty, remaining_qty, avg_fill_price, reject_reason, cancel_reason, parent_order_id, mid_price_at_fill, intended_price, slippage_bps, trading_session, actor, chain_id, symbol_set_hash)가 모두 schema에 들어갔다. 흡수율이 높다. index 9개도 운영 시 자주 쓰는 조회 패턴(open status, broker no, parent chain, audit chain)을 모두 cover한다.

다만 다섯 가지 미세 결함이 있다.

첫째, **NOT NULL 결정의 영구성이 한 번 더 검토되어야 한다.** SQLite는 273행에서 인지한 대로 컬럼 변경/삭제가 제한적이라 Slice 2a 이후 NOT NULL 변경은 사실상 불가다. 현재 `live_orders` 18개 NOT NULL 컬럼 중 `parent_order_id`, `reject_reason`, `cancel_reason`은 브로커 응답 전에 빈 문자열로 채워진다(346행). 이는 정상 케이스지만 **"빈 문자열 NOT NULL"과 "NULL 허용"의 의미가 다르다**. 빈 문자열은 "값 있음(없음을 뜻하는 빈 값)"이고 NULL은 "정보 없음"이다. SQL `IS NULL` 검색이 안 되면 사후 분석이 어렵다. Slice 2a 진입 전 이 세 컬럼만이라도 NULL 허용으로 재검토할지 결정 필요.

둘째, **dataclass↔schema 자동 검증 테스트가 없다.** acceptance criteria 표(348~358행)에 dataclass 직렬화와 schema 추가가 각각 있지만, "dataclass 필드가 SQL의 모든 NOT NULL 컬럼을 빠짐없이 채운다"는 자동 비교 테스트가 없다. 누군가 dataclass에 새 필드를 추가하고 SQL에는 빠뜨리면(또는 반대로) write 시점에 silent하게 깨진다. `test_live_order_dataclass_matches_schema` 같은 테스트 한 줄이 안전.

셋째, **`detail_json` 컬럼의 최소 schema가 정의되지 않았다.** `live_orders.detail_json`, `live_order_events.detail_json`, `market_status_snapshots.status_json` 모두 TEXT NOT NULL이지만 그 안의 JSON 구조 schema가 없다. 사후 JOIN/parsing 일관성을 위해 "detail_json은 최소한 키 X, Y를 보장한다"는 한 줄이 있으면 좋다. 본격 schema는 Slice 5 이후로 미뤄도 되지만 최소 키 한두 개는 Slice 2a에서 잠궈야 검색 가능성이 생긴다.

넷째, **`live_order_events.actor` 표준 값이 정의되지 않았다.** dataclass에 `actor: str`로 들어 있지만 어떤 값을 가질 수 있는가? `system`, `operator`, `recovery`, `audit`, `kill_switch` 같은 enum 또는 표준 문자열 목록이 없으면 작업자별로 다른 값을 써서 사후 group by가 깨진다. Slice 2a 또는 Slice 5 시작 전 표준 목록 한 줄 명시 필요.

다섯째, **migration dry-run의 자동화 부재.** acceptance criteria의 "수동 검증 절차"가 들어가 있지만 운영 DB(`runtime-data/dev.db`)는 매일 사용 중이라 사람이 수동으로 backup → init → smoke → restart를 매번 정확히 하기 어렵다. `scripts/run_storage_migration_dry_run.sh` 같은 후보 스크립트 명시(파일 신규 생성 전이라도 절차를 한 명령으로 묶을 수 있다는 표시)가 있으면 안전. 이건 Slice 2a 작업 자체가 아니라 작업 후 운영 적용 단계의 안전망이다.

## Q4: Slice 1 go/no-go 기준이 실전 안전 관점에서 충분한지

**75% 충분.** stop line이 명확하고 No-go 트리거 3개가 적절하다. 다만 작업자가 회색 지대에서 판단할 때의 가이드가 부족하다.

첫째, **No-go가 발동되면 어떻게 절차적으로 처리하는지 빠졌다.** "변경이 필요하면 보류" 또는 "별도 설계로 분리"가 적혀 있지만, **누가 보류 결정을 내리고, PR을 어떻게 닫고, 누구에게 보고하는지** 절차가 없다. Slice 1 PR 작업 중 No-go가 발동되면 작업자는 "PR을 닫고 cowork-reports에 결정 요청 파일 작성"처럼 명시적 다음 행동이 필요하다. 그렇지 않으면 작업자가 "조금만 손대면 될 것 같은데"로 회색 진입할 위험이 있다.

둘째, **"실제 KIS 네트워크 호출 0건" invariant가 Go/No-go 한 줄로 잠겨 있지 않다.** fixture 원칙(128행)에 "실제 KIS 네트워크를 호출하지 않는다"가 들어 있지만, Slice 1 작업 중 실수로 네트워크 호출이 일어나면 토큰 발급이나 trace 로그가 외부에 남을 수 있다. **Go 조건에 "테스트 실행 시 네트워크 0건"을 명시적으로 추가**하면 fixture 원칙이 운영 안전 invariant로 격상된다.

셋째, **PR 크기 한도가 없다.** Stop line으로 "wrapper와 isolation 테스트까지만"이 잠겨 있지만 line 수 가이드는 없다. 새 파일 1개 + 테스트 2개면 보통 200~400줄 범위인데, 그 이상으로 부풀면 작업이 너무 커진 신호다. "Slice 1 PR은 X줄 이내, 초과 시 분할 검토" 같은 후보 한 줄이 작업자에게 self-check가 된다.

넷째, **rollback 절차 한 줄이 없다.** Slice 1은 새 파일만 추가하므로 git revert가 안전한 rollback이지만, **rollback 후 누가 wrapper를 import했는지 점검** 같은 부수 효과 처리가 없다. 작은 항목이지만 명시되어 있으면 안전.

## Q5: 다음 단계가 Slice 1 구현이어도 되는지, Slice 3 fixture 표 보강이 먼저인지

**Slice 1 먼저가 맞다.** 세 가지 이유.

첫째, **Slice 1과 Slice 3는 의존성이 없다.** Slice 1은 read-only wrapper와 isolation 테스트, Slice 3는 market status 순수 로직 fixture로 둘이 별개 영역이다. 어느 것을 먼저 해도 다른 쪽에 영향이 없다.

둘째, **Slice 1 시작 전 composition 가능성 재확인의 정보 가치가 높다.** work_ver_2의 Go 첫 항목(81행)이 "`KisRestQuoteClient.__init__`가 profile/token manager를 받는 composition 가능한 구조임을 코드로 재확인"이다. 이 검증 결과가 후속 slice(특히 Slice 4 guard, Slice 5 manager)의 설계에 영향을 준다. 만약 composition이 불가능하다면 Slice 1 자체가 design rework로 빠지고, 그 결과가 Slice 3 fixture 설계에도 간접적으로 영향을 줄 수 있다(어떤 데이터 형태로 fixture를 만들지 결정에 영향). **불확실성을 가장 많이 해소하는 슬라이스를 먼저 푸는 게 합리적**이다.

셋째, **Slice 1은 가장 작고 가장 안전하다.** 첫 코드 작업으로 워크플로우/툴링/PR 검토 흐름을 검증하는 효과가 있다. Slice 3은 fixture 설계가 외부 데이터 원천(KIS REST 또는 거래소 OpenAPI) 결정에 따라 달라질 수 있어 더 큰 의사결정과 묶여 있다.

다만 한 가지 권고: **Slice 3 fixture 표 보강은 Slice 1 진행 중 또는 직후 병행해서, Slice 4 진입 전 준비를 끝내야 한다.** Slice 3의 VI/거래정지/상하한가/corporate action fixture가 충분히 풍부해야 Slice 4 guard 테스트가 진행 가능하다. Slice 1만 끝내고 Slice 3을 미루면 Slice 4 진입에서 막힌다.

## P0 결정 6개에 대한 cowork 보충 의견

work_ver_2가 113~125행에 남긴 P0 결정 3개와 별도로 review_ver_1에서 적은 6개를 함께 본다.

- **Phase 1 read-only 차단 방식** (work_ver_2에서 결정 완료: 메서드 미노출): 동의. Codex 권장안이 옳다.
- **VI 발동 중 open 주문 처리** (work_ver_2 P0 잔여): Codex 권장안(신규 금지 + 기존 open 조회 보류 + 잔량 취소 cancel-only guard)에 동의. 다만 "VI 발동 중 KIS가 미체결 주문을 어떤 상태로 반환하는지"가 169행에서 "확인 필요"로 남아 있는데, **이건 Slice 1 진입 전 KIS 문서 또는 모의계좌 fixture로 확인이 가능**한 항목이라 미루지 말고 Slice 3 시작 전 답을 받아두는 게 안전.
- **Phase 2 주문 타입** (work_ver_2 P0 잔여): Codex 권장안(지정가 only, 시장가 비상 청산 건별 수동 승인) 동의. 다만 "kill switch 발동 시 자동 fallback 별도 검토"가 미정인데, **kill switch ON 상태에서 비상 청산이 매번 사람 승인을 기다린다면 정작 사고 시점에 청산이 늦어진다**. kill switch 발동 사유가 "일일 손실 한도 도달"인 경우는 자동 fallback, "운영자 수동 ON"인 경우는 수동 승인 — 이런 사유별 분기가 합리적 후보.
- **일일 손실 한도와 슬리피지 budget**: 이게 P0 중 가장 시급. 운영자 결정 없으면 Phase 2 자체가 영원히 못 열린다. Slice 1 코드 작업과 병행해서 운영자 결정 받아두는 게 좋다.
- **market status 데이터 원천** (P1): Codex 권장안(fixture + 수동 calendar로 시작) 동의. Slice 3 진입 전 결정.
- **audit chain과 NAS 백업** (P1): Codex 권장안(append-only hash chain + recovery self-test 통과 전 Phase 2 금지) 동의. Slice 7 진입 전 결정.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Slice 1 acceptance criteria | 70% | 시그니처 동등성, factory negative, import-time 부작용 3개 테스트 |
| KisRestQuoteClient allowlist | 60% | 6개 경로 mode/메서드 분석, allowlist 영구성 명시, false positive 정책, 이론적 우회 한계 명시 |
| Slice 2a dataclass/schema | 80% | NOT NULL 결정 재검토, dataclass↔schema 자동 검증, detail_json 최소 schema, actor enum, migration dry-run 자동화 |
| Slice 1 go/no-go | 75% | No-go 발동 시 절차, 네트워크 0건 invariant, PR 크기 한도, rollback 부수 효과 |
| 다음 단계 권장 | Slice 1 먼저 | Slice 3 fixture는 Slice 1과 병행 또는 직후 |

## 다음 단계 권장

1. work_ver_3 또는 Slice 1 코드 작업 진입 전, **`KisRestQuoteClient` allowlist 6개 경로의 mode/메서드 사용 분석**을 추가 (Q2의 첫 번째 위험). 표 한 개 분량.
2. Slice 1 acceptance criteria에 **시그니처 동등성 + factory negative + import-time 부작용** 3개 테스트 명시 (Q1 보강).
3. Slice 1 go/no-go에 **네트워크 0건 invariant + No-go 절차** 추가 (Q4 보강).
4. Slice 2a 진입 전 **NOT NULL 결정 재검토**(특히 `parent_order_id`, `reject_reason`, `cancel_reason`)와 **dataclass↔schema 자동 검증 테스트** 추가 결정 (Q3 보강).
5. 운영자 결정 6개 중 **(a) 일일 손실 한도/슬리피지 budget**과 **(b) VI 발동 중 KIS 응답 상태**는 Slice 1과 병행해서 답을 받아두기 (Phase 2 진입 차단 항목).
6. Slice 1 진입 가능. work_ver_3가 위 1~4 보강을 합쳐서 나오면 추가 review_ver_3 없이 코드 진입해도 안전.

## 명명 규칙 메모

새 명명 규칙(`work_ver_N` ↔ `review_ver_N`) 적용 첫 라운드. 같은 topic 안에서 같은 숫자 매칭이 깔끔하다. 레거시 파일 3개(`-report.md`, `-cowork-review.md`, `-codex-followup.md`)는 README.md(20행)에 명시된 대로 그대로 보존.
