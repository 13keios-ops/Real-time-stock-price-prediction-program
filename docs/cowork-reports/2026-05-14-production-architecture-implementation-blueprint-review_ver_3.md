# Claude cowork 리뷰 review_ver_3: Slice 1/2a 구현 통합본

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_3`
- 기준 작업본: `2026-05-14-production-architecture-implementation-blueprint-work_ver_3.md`
- 이번 라운드 성격: 처음으로 실제 코드가 들어간 라운드(Slice 1 + Slice 2a)
- cowork 직접 검증 파일: `app/brokers/kis_readonly.py`, `tests/test_live_readonly_guard.py`, `tests/test_live_client_isolation.py`, `tests/test_live_storage.py`, `app/storage/contracts.py`, `app/storage/sqlite_store.py`

## 요약

work_ver_3는 review_ver_2의 보강 항목을 모두 흡수했고, Slice 1/2a 구현 자체가 운영 안전 관점에서 단단하게 짜여 있다. 124개 전체 테스트가 통과한 점도 회귀 방지 측면에서 신뢰할 만하다. 결론은 **그대로 사용 가능. Slice 3 진입 권장.** 단 (a) Slice 2a를 실제 운영 DB에 반영하기 전 dry-run 한 번, (b) `LiveOrder` schema에 stuck/retry 카운터 추가 검토, (c) `detail_json` sub-field 타입 검증 추가 — 세 가지를 Slice 3 또는 Slice 5 진입 전에 보강하면 완전해진다.

핵심 발견 세 가지: (1) `KisReadOnlyClient` composition + factory + import-time 부작용 잠금이 구조적으로 매우 단단하며, Python 한계 안에서 P0 차단으로 충분하다. (2) allowlist static test가 정확한 strictness 수준이다 — exact-set 비교로 새 우회 경로를 강제로 잡고, false positive/dynamic dispatch 한계는 work_ver_3에서 솔직히 인정된다. (3) Slice 2a schema는 review_ver_2 누락 12개 필드를 모두 반영했고 nullable 결정도 합리적이지만, **재시도 카운터와 stuck SLA 시각이 살짝 빠져 있어** Slice 5/6 진입 시 detail_json으로 우회해야 할 수 있다.

## Q1: Slice 1 KisReadOnlyClient가 Phase 1 read-only 구조적 차단으로 충분한가

**85% 충분. P0 차단 의도는 단단하다.**

`kis_readonly.py`를 직접 봤을 때 좋은 점부터: composition pattern이 정확히 적용됐고(20행 `self._client = client`), 5개 조회 메서드만 노출하며 `submit_cash_order`/`cancel_order`는 클래스 자체에 정의되지 않았다. `get_kis_live_readonly_client` factory가 `mode != "live"`이면 `ValueError`로 거부하는 부분도 검증된다(87~88행). 토큰 매니저와 REST client를 factory 안에서 생성해 외부에서 raw `KisRestQuoteClient`를 주입할 필요가 없다.

테스트 측면에서도 `test_readonly_method_signatures_match_delegate`가 `inspect.signature` 동등성으로 5개 메서드 시그니처를 라인 단위로 비교한다(test_live_readonly_guard.py 18~32행). 누군가 `KisRestQuoteClient.get_account_balance`에 새 파라미터를 추가하면 즉시 실패한다. `test_live_readonly_factory_rejects_non_live_mode`(97~101행)와 `test_import_does_not_trigger_network`(103~111행)도 review_ver_2 권장 그대로 들어갔다. delegate 호출 인자까지 모든 파라미터로 검증한다(50~72행).

남은 작은 약점들:

첫째, **factory call-time 부작용 잠금이 없다.** `get_kis_live_readonly_client(settings)`가 호출되는 순간 `KisTokenManager(profile)`와 `KisRestQuoteClient(profile=...)`가 즉시 생성된다(89~91행). 만약 두 초기화 중 어느 하나가 token 발급이나 hashkey 발급 같은 네트워크 호출을 일으키면 factory 호출만으로 네트워크 트래픽이 발생한다. import-time 테스트는 이 시나리오를 잡지 못한다. `test_live_readonly_factory_call_does_not_trigger_network` 같은 추가 테스트 한 줄이 있으면 완전해진다.

둘째, **`describe()` 메서드가 signature 동등성 테스트에서 빠졌다.** wrapper의 `describe()`는 delegate를 호출한 뒤 `access: read-only` 키를 추가한다(23~26행). 5개 read 메서드만 signature 비교 대상이라 `describe()` 시그니처가 delegate와 어긋나도 잡히지 않는다. 안전 영향은 작지만 회귀 방지 측면에서 한 줄 추가하면 좋다.

셋째, **`_client` 내부 속성이 Python 단계에서 보호되지 않는다.** `readonly_client._client.submit_cash_order(...)`로 우회 가능하다. 이건 Python 언어 한계라 구조 변경으로 막을 수 없지만, 클래스 docstring 또는 PEP 8 컨벤션상의 underscore prefix가 외부 접근 금지 신호임을 명시한 한 줄 주석이 있으면 좋다. 운영 안전 측면에서는 코드 리뷰가 잡아야 하는 영역이다.

종합: **P0 구조적 차단으로 충분하다.** 위 세 가지는 보강하면 더 단단해지지만 Slice 1 진입을 막을 수준은 아니다.

## Q2: allowlist static test가 너무 빡세거나 너무 느슨하지 않은가

**80% 적절. 정확한 strictness 수준.**

`test_live_client_isolation.py`의 `test_live_readonly_paths_do_not_bypass_wrapper`(10~28행)는 7개 경로(`app/__main__.py`, `app/brokers/kis_readonly.py`, `app/collectors/historical.py`, `app/services/broker_paper.py`, `app/services/collector.py`, `app/services/kis_account.py`, `app/services/runtime.py`)에 대한 exact-set 비교를 한다. 정규식은 `\bKisRestQuoteClient\s*\(`로 적절하다. exact-set 비교라서 새 파일이 `KisRestQuoteClient(`를 사용하면 즉시 실패하고, 기존 7개 경로 중 하나가 제거되어도 실패한다. 이게 정확히 의도된 동작이다.

`test_paper_mirroring_still_uses_paper_profile`(30~35행)이 별도로 `broker_paper.py`가 paper profile을 유지하고 readonly wrapper로 대체되지 않았음을 확인한다. paper mirroring 우회 위험을 막는 좋은 잠금이다.

work_ver_3 본문이 명시한 두 가지 한계는 솔직하게 인정된 부분이고, 이 한계 자체는 합리적이다. 첫째, grep 기반 false positive(주석/docstring/문자열 리터럴 안의 매치)는 발생 시 allowlist reason으로 처리하는 정책이다. 둘째, `getattr(module, "KisRestQuoteClient")(...)` 같은 dynamic dispatch는 잡지 못한다. 둘 다 "실수 차단용이지 의도적 우회 방지용은 아니다"라는 점이 work_ver_3 본문 44행에 명시되어 있다.

남은 미세 결함:

첫째, **`tests/` 디렉토리는 검사 대상이 아니다.** walk가 `PROJECT_ROOT / "app"`만 본다(23행). 후속 slice에서 누군가 test fixture로 raw `KisRestQuoteClient`를 만들면 이 테스트가 잡지 않는다. test fixture에서 실제 KIS 인스턴스를 만들 일은 없겠지만, 명시적으로 `tests/`도 검사 대상에서 제외하는 이유를 한 줄 코멘트로 두면 의도가 분명해진다.

둘째, **7개 allowlist 경로의 mode/method 분석이 work_ver_3 본문에는 표로 있는데(35~42행) 테스트에는 mode 검증이 없다.** 예를 들어 `app/services/broker_paper.py`는 `get_kis_profile(settings, "paper")`로 paper 전용이어야 하는데(work_ver_3 41행), 이 invariant를 잠그는 테스트는 `test_paper_mirroring_still_uses_paper_profile` 하나뿐이고 다른 5개 경로(`historical.py`, `runtime.py`, `collector.py`, `kis_account.py`, `__main__.py`)는 어떤 mode를 받는지 잠겨 있지 않다. 이들이 향후 live profile을 받게 되어도 isolation 테스트는 통과한다. 다음 단계에서 "live profile을 받는 경로는 read-only wrapper로 전환" 작업이 시작되면 그때 각 경로별 mode 잠금 테스트가 필요해진다.

종합: **현 단계 strictness는 정확하다.** 다음 wrapper 전환 작업 시 mode-level 잠금이 추가되면 완전해진다.

## Q3: Slice 2a schema가 후속 live order manager와 execution sync에 필요한 최소 필드를 충분히 담는가

**80% 충분. review_ver_2 누락 12개 필드는 모두 반영됐다.** `live_orders`에 `filled_qty`, `remaining_qty`, `avg_fill_price`, `reject_reason`, `cancel_reason`, `parent_order_id`가 들어갔고(sqlite_store.py 325~342행), `market_status_snapshots`에 `symbol_set_hash`가 들어갔다(307행). `reject_reason`/`cancel_reason`/`parent_order_id`는 nullable로 결정해 의미 있는 NULL을 보존했고(340~342행) 이는 review_ver_2의 권장사항을 정확히 반영한 결정이다.

다만 후속 Slice 5/6 진입 전 보강이 필요한 필드 4가지가 있다.

첫째, **`stuck_since` 또는 `stuck_marked_at`**: 상태머신의 `stuck` 상태는 age threshold 초과 시 진입한다(blueprint 154행). 현재 schema에는 `created_at`과 `last_synced_at`만 있어 stuck 진입 시각이 별도 추적되지 않는다. dashboard의 "oldest stuck age" 표시와 stuck 알림 SLA 분석에 별도 컬럼이 필요. detail_json 또는 live_order_events로 추적 가능하지만 indexing이 안 된다.

둘째, **`submit_attempt_count` / `cancel_attempt_count`**: unknown 상태에서 재조회/재취소 시도 횟수. 무한 retry 방지에 운영 안전상 중요하다. 현재 schema에는 시도 횟수 추적이 없어 detail_json에 누적하거나 live_order_events COUNT 쿼리로 계산해야 한다. dashboard 쿼리 성능 측면에서 별도 컬럼이 유리.

셋째, **`order_validity` 또는 `time_in_force`**: 일일주문/IOC/FOK 같은 주문 유효기간. KIS는 보통 day order이지만 명시 필드 없이 `order_type=limit`만으로는 day인지 즉시인지 구분 안 됨. expired 상태(blueprint 152행)가 의미가 있으려면 어떤 시점에 expire되는지 schema에 있어야 한다.

넷째, **`market_status_snapshots.upstream_lag_seconds`** 또는 `source_received_at`: `created_at`은 우리 시스템이 snapshot을 만든 시각, `status_json["source_generated_at"]`은 외부 데이터 원천 시각. 두 시각의 차이가 곧 stale 가능성. 인덱싱된 컬럼으로 노출되면 운영 dashboard에서 빠르게 표시 가능. status_json 안에 있으면 매번 JSON parsing 비용.

`live_order_events` schema는 minimal하고 좋다. 다만 한 가지: **`event_sequence`(monotonic 카운터)가 없어 같은 `event_time`에 발생한 여러 이벤트의 순서 보장이 안 된다.** `order_event_id`(UUID4)로 unique는 보장되지만 정렬 가능한 시퀀스가 아님. dashboard에서 1ms 단위 이벤트 순서를 정확히 봐야 한다면 필요. 우선순위는 위 4개보다 낮다.

`detail_json` 최소 key 검증 자체는 적절(LiveOrder는 `order_policy`, `blocking_reasons`, `raw_broker_response`). 다만 sub-field type 검증이 없다 — 다음 항목 Q5에서 자세히.

종합: **현 schema로 Slice 3, Slice 4까지는 진입 가능.** Slice 5(order manager)와 Slice 6(execution sync) 진입 전 stuck/retry 카운터와 order_validity 추가 결정이 필요. SQLite는 새 컬럼 추가는 가능하므로 후속 slice에서 점진 보강 가능.

## Q4: idempotency_key UNIQUE + INSERT 실패 정책이 운영 안전 관점에서 적절한가

**90% 적절. DB-level unique constraint는 가장 강한 잠금이다.**

`live_orders.idempotency_key TEXT NOT NULL UNIQUE`(sqlite_store.py 319행)와 `test_live_order_insert_unique_idempotency_and_open_lookup`(test_live_storage.py 194~209행)이 함께 잠그는 구조가 좋다. 애플리케이션 레벨이 아닌 DB 레벨이라 race condition도 막힌다. duplicate insert 시 `sqlite3.IntegrityError`가 explicit하게 raise되어 caller가 명시적으로 처리해야 하고 silent overwrite가 없다.

남은 검토 항목 두 가지:

첫째, **IntegrityError가 raise됐을 때 caller가 어떻게 처리하는지는 Slice 5에서 정의될 예정이다.** Slice 2a 자체에서는 schema layer만 잠그고 호출 처리는 미정인 것이 의도된 분리다. 다만 Slice 5 진입 전 "중복 idempotency_key 감지 시 기존 주문 상태 확인 후 `intent_created`/`submit_pending`/`unknown` 등 어느 상태에서만 재진입 허용하는가" 정책이 명확히 정해져야 한다. blueprint 198~200행에 일부 적혀 있지만 구체적인 caller behavior는 미정.

둘째, **빈 문자열 idempotency_key의 위험.** `NOT NULL UNIQUE`는 빈 문자열 `""`는 NULL과 다르게 처리한다. 누군가 실수로 idempotency_key=""를 만들면 첫 insert는 성공하고 두 번째는 IntegrityError. 의도된 동작일 수도 있고 silent bug일 수도 있다. 현재 테스트에는 빈 문자열 케이스가 없다. `__post_init__`에서 `if not idempotency_key.strip(): raise ValueError`를 추가하면 source-level 잠금이 된다. 우선순위는 낮지만 안전.

종합: **DB-level unique는 매우 좋은 결정.** Slice 5 진입 전 caller behavior 정책 명문화 + 빈 문자열 가드 한 줄 정도가 보강 후보.

## Q5: JSON 최소 key 검증과 actor enum이 너무 이른 제약인지 부족한 제약인지

**85% 적절. 최소 key 검증은 옳고, sub-field 타입 검증과 actor 정의 명확화가 보강 후보.**

`_require_keys`(contracts.py 14행)이 dict의 필수 키 존재만 검증하고 값의 schema는 검증하지 않는 결정은 의도된 균형이다. 너무 일찍 모든 값 schema를 잠그면 후속 slice에서 깨고 다시 만들 위험이 있다. `MarketStatusSnapshot.status_json`이 `symbols`, `market_session`, `source_generated_at` 키를 요구하고, `LiveOrder.detail_json`이 `order_policy`, `blocking_reasons`, `raw_broker_response` 키를 요구하는 결정은 적절하다.

`LIVE_ORDER_EVENT_ACTORS = {"system", "account_owner", "recovery", "kill_switch", "codex"}`(contracts.py 11행)는 enum-like 잠금으로 좋다. `__post_init__`에서 actor 검증이 fail-fast하게 raise한다(303~305행). group by 분석이 안정적.

미세 결함 다섯 가지:

첫째, **`detail_json` sub-field 타입 검증 부재.** `blocking_reasons`가 list여야 한다고 명시되지 않았고, `raw_broker_response`가 dict여야 한다는 명시도 없다. test fixture에서는 `[]`와 `{}`로 만들지만(test_live_storage.py 78~80행), `_require_keys`는 키 존재만 본다. 누가 `blocking_reasons={"v": 1}`로 dict로 만들면 통과하고 후속 코드가 `for reason in blocking_reasons`로 iterate하면 dict의 key를 iterate해 잘못된 동작. `isinstance` 한 줄 추가가 안전.

둘째, **`status_json["symbols"]`의 형태가 미정이다.** test에서는 `{"005930": {"tradable": True}}` 형태이지만, Slice 3에서 `tradable` 외에 `vi_active`, `price_limit`, `corporate_action` 같은 키가 늘어날 것이 명백. 현재처럼 "키 존재만 검증, 값 schema는 미정"이 적절. 다만 Slice 3 시작 시 sub-field schema 한 번 더 잠그는 결정이 필요.

셋째, **`"codex"` actor의 운영 시점 정의가 모호하다.** enum에 codex가 들어 있는데(11행) 운영 단계에서 codex가 audit event를 작성하는 시나리오가 명시되지 않았다. 만약 "운영 단계에서는 codex actor가 0이어야 한다"는 invariant라면 그것을 잠그는 별도 테스트가 필요. 만약 "디버깅/migration 단계에만 허용"이라면 docstring 한 줄로 명시.

넷째, **actor enum의 미래 확장 후보.** `dashboard_user`(대시보드 사람 액션), `scheduled_task`(스케줄러), `migration`(DB 도구) 같은 추가 후보가 있다. enum은 추가가 안전하지만, 추가 시점이 새 코드 작성 시점이라 testing 측면에서 사전 등록이 안 됨. 향후 확장 후보 한 줄 주석이 contracts.py에 있으면 좋다.

다섯째, **`_require_keys`가 string 키만 체크한다.** 만약 someone이 `status_json={1: "x", 2: "y", 3: "z"}` 같은 비-string 키 dict를 넣어도 `_require_keys`는 string `"symbols"`를 찾을 수 없어 raise한다. 결과적으로 정상 잠금이지만, 의도된 동작인지 명시는 없다.

종합: **현재 검증 수준이 적절하다.** Slice 3 진입 전 sub-field 타입 검증 한 줄(`isinstance(blocking_reasons, list)` 등)과 actor 운영 시점 docstring 추가가 후속 보강 항목.

## Q6: 다음 작업 = Slice 3 market status vs Slice 2b 전 migration dry-run

**Slice 3 먼저 가는 게 맞다. 단, Slice 2a 운영 DB 적용 dry-run을 별도 마이크로 작업으로 끼워 넣자.**

세 가지 이유.

첫째, **의존성 측면에서 Slice 3가 후속 진입을 막지 않는다.** Slice 4 guard가 `MarketStatusSnapshot`을 입력으로 받고, Slice 5 order manager가 `market_status_snapshot_id`를 참조한다. Slice 3 없이는 Slice 4/5가 진입 불가. Slice 2b 없이도 Slice 4까지는 진입 가능(Slice 4 guard는 fills/positions를 쓰지 않음).

둘째, **Slice 3은 외부 API 없이 fixture 기반 순수 로직으로 시작 가능하다.** work_ver_3 본문 209행과 215행 Codex 권장안 그대로. 외부 데이터 원천 결정 전에 게이트와 상태 머신 테스트를 먼저 잠글 수 있어 의사결정 지연 없이 진행 가능.

셋째, **Slice 2b는 migration 위험이 크다.** 6개 테이블(`live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs`)을 운영 DB에 추가하는 작업은 Slice 2a의 3개 테이블보다 약 2배 크다. Slice 2a를 운영 DB에 적용한 뒤 며칠 안정성을 본 다음 Slice 2b로 가는 게 더 안전. Codex 권장안 211행도 같은 방향.

다만 한 가지 추가 권고: **Slice 2a 자체의 운영 DB 적용 dry-run을 명시적으로 한 번 거치자.** 현재 `test_live_storage`는 임시 DB에서만 검증한다. 운영 DB(`runtime-data/dev.db`)에 적용 시 (a) live runtime이 connection을 잡고 있어 schema 변경이 lock되는지, (b) dashboard/watchdog가 새 테이블 존재를 정상 인식하는지, (c) `CREATE TABLE IF NOT EXISTS`가 기존 운영 데이터를 건드리지 않는지 — 세 가지를 한 번에 검증하는 dry-run 절차가 필요. blueprint 274행에 "live runtime/dashboard 정지, DB backup, schema 초기화, smoke query, 재기동" 순서가 있는데 이를 한 명령으로 묶는 wrapper script(예: `scripts/run_storage_migration_dry_run.sh`)가 Slice 3 진입 전 또는 병행해서 만들어지면 안전. 이건 작은 작업이지만 Slice 2b 진입 안전성을 미리 보장한다.

권장 순서: **Slice 3 (market status fixture) → migration dry-run wrapper → Slice 4 (guard) → Slice 2b → Slice 5 (order manager) → Slice 6 (execution sync) → ...**

## 추가 발견 (코드 직접 본 결과)

work_ver_3 본문에는 명시되지 않은 미세 항목 세 가지를 코드에서 확인했다.

첫째, **`live_orders.market_status_snapshot_id`가 NOT NULL이지만 외래키 제약이 없다.** SQLite는 기본적으로 FK enforcement가 꺼져 있어 `PRAGMA foreign_keys = ON`을 명시하지 않으면 dangling reference가 발생할 수 있다. 즉 `market_status_snapshot_id`에 존재하지 않는 ID를 넣어도 통과한다. Slice 5 order manager에서 application-level 검증이 들어가야 한다. 또는 SQLite FK enforcement를 켜는 정책 결정이 필요.

둘째, **`live_orders.parent_order_id`도 nullable이지만 자기 참조 FK가 없다.** 정정 정책이 "Phase 2 정정 금지"라(blueprint 159행) Phase 2 동안에는 사용 안 되지만, Phase 3에서 정정 추가 시 chain 무결성 검증이 application 레벨에서 들어가야 한다. 미래 작업.

셋째, **`RuntimeWriter.write_live_order` 등의 fan-out 패턴이 test_live_storage.py 211~225행에서 검증된다.** JSONL과 SQLite에 동시에 쓰는데, 둘 중 하나가 실패하면 다른 쪽은 어떻게 되는지(rollback? 그대로 진행?) 코드에 명시 없음. 운영 안전 측면에서 partial write가 발생하면 reconciliation이 어려워질 수 있다. write 트랜잭션 정책을 한 번 결정해야 함. 우선순위는 Slice 5 진입 시 함께 검토.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Slice 1 KisReadOnlyClient 차단 | 85% | factory call-time 부작용 잠금, `describe()` 시그니처 잠금 |
| allowlist static test | 80% | tests/ 제외 이유 명시, 5개 경로 mode 잠금(다음 wrapper 전환 시) |
| Slice 2a schema 충분성 | 80% | stuck_since, attempt 카운터, order_validity, upstream_lag (Slice 5/6 진입 전) |
| idempotency_key UNIQUE 정책 | 90% | caller behavior 정책(Slice 5), 빈 문자열 가드 |
| JSON key + actor 검증 | 85% | sub-field 타입 검증, codex actor 운영 시점 명시 |
| Slice 3 vs Slice 2b 우선순위 | Slice 3 먼저 | Slice 2a 운영 DB dry-run wrapper를 별도 마이크로 작업으로 |

## 다음 단계 권장

1. **Slice 2a 운영 DB 적용 dry-run**: `scripts/run_storage_migration_dry_run.sh` 또는 동등한 wrapper. live runtime 정지, DB backup, schema 초기화, smoke query, 재기동을 한 명령으로. Slice 3 진입과 병행 가능.
2. **Slice 3 market status 순수 로직 구현**: work_ver_3 권장안 그대로. fixture/수동 snapshot 기반.
3. **Slice 3 시작 시 보강 항목**: `status_json["symbols"]` sub-field schema 잠금, `detail_json` sub-field 타입 검증 한 줄.
4. **Slice 4 진입 전 보강 항목**: allowlist 5개 경로의 mode 잠금 테스트(`historical.py`, `runtime.py`, `collector.py`, `kis_account.py`, `__main__.py`가 어떤 mode를 받는지 명시).
5. **Slice 5 진입 전 schema 보강**: `live_orders`에 `stuck_since`, `submit_attempt_count`, `cancel_attempt_count`, `order_validity` 추가 결정. SQLite는 ALTER TABLE ADD COLUMN이 가능하므로 destructive 아님.
6. **운영자 결정 항목 잔여 2개 (work_ver_3 215~221행)**: market status 데이터 원천 우선순위는 Slice 3 외부 연결 진입 전, audit hash chain은 Slice 7 진입 전 결정 필요. 둘 다 Codex 권장안에 동의.

## 신뢰 수준 변화

work_ver_1~2는 문서만이라 cowork이 본문 정확성만 검증했다. work_ver_3는 실제 코드가 들어가 cowork이 (a) 본문 주장과 코드 일치, (b) 코드 자체의 안전성, (c) 테스트 잠금의 strictness 세 층을 모두 직접 봤다. **세 층 모두 통과했다.** 124개 테스트 통과와 `git diff --check` 통과는 회귀 안전 측면에서 신뢰할 만하다.

이번 라운드부터는 cowork 리뷰가 "설계 비판"에서 "구현 검증"으로 무게 중심이 이동한다. 다음 work_ver_4 또는 후속 slice에서도 cowork이 (a) 변경된 파일 직접 읽기, (b) 운영 안전 invariant 잠금 확인, (c) 회귀 테스트 통과 확인 — 세 단계를 유지하면 된다.
