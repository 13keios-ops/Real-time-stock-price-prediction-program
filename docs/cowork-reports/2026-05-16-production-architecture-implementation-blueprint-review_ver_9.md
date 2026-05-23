# Claude cowork 리뷰 review_ver_9: Slice 5 LiveOrderManager + Slice 5-2 LiveExecutionSync + kill switch CLI + database smoke 보강

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_9`
- 기준 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_9-2.md` (work_ver_9 + 9-1 통합본)
- cowork 직접 검증 파일: `app/services/live_order_manager.py`(600행), `app/services/live_execution_sync.py`(298행), `scripts/set_live_kill_switch.sh`, `scripts/script_dispatch.sh`(`live_kill_switch_cli` 함수, `sqlite_readonly_smoke` 보강분)

## 요약

work_ver_9-2는 review_ver_8의 다음 단계 권장 4가지(database smoke 보강, JSON-only docstring 명시, kill switch CLI, Slice 5 진입)를 모두 한 라운드에 흡수했다. 더해 Slice 5-2(live execution sync mapper + status apply)까지 연속 진행. 205개 전체 테스트 통과 + protocol 주입 패턴 + 상태 머신 + 5층 guard 호출 + fail-safe unknown 정책이 모두 코드와 테스트로 단단하게 잠겨 있다. 결론은 **그대로 사용 가능. Slice 5-3 `live_fills` delta idempotency 진입 권장.**

핵심 발견 세 가지: (1) `LiveOrderManager`의 protocol 주입 패턴이 매우 안전하게 짜여 있고 `LiveSubmitBroker`/`LiveCancelBroker` 분리도 의도적. (2) `blocked` 상태가 terminal로 잠겨 있어 idempotency key 재사용 시 새 intent 생성이 차단된다 — 의도된 보수 정책이지만 운영 시 새 prediction_id 발급이 필요함을 docstring으로 명시하면 좋다. (3) live execution sync가 `live_orders` status/quantity까지만 반영하고 `live_fills`/position은 분리한 경계는 단계 진입에 적절.

## Q1: LiveOrderManager가 broker를 직접 만들지 않고 protocol 주입형으로 둔 경계가 실전 안전 기준에 맞는지

**매우 안전. P0 의도와 정확히 일치한다.**

`live_order_manager.py` 99~121행에서 `LiveSubmitBroker`와 `LiveCancelBroker` 두 Protocol을 분리 정의. `__init__`(129행)은 `writer: RuntimeWriter`만 받고 KIS client를 직접 생성하지 않는다. `submit_intent`/`request_cancel`이 `broker` 인자로 받는 의존성 주입.

장점 4가지:
1. **테스트 가능성**: Mock broker로 모든 lifecycle 시나리오 검증 가능. 실제 KIS 호출 0건으로 unit test.
2. **broker 교체 유연성**: Phase 1에서는 read-only client(주문 메서드 미노출)만 노출, Phase 2 진입 시 submit broker 추가 — 같은 manager 코드로 두 phase 모두 운용.
3. **manager 자체에 KIS 의존성 없음**: storage와 guard만 의존. broker는 외부 의존성으로 격리.
4. **review_ver_4 요구사항 충족**: review_ver_4 Q1 "read-only Phase 1에서 주문 메서드 노출 차단" 원칙이 manager 진입 시점에도 깨지지 않는다.

추가로 `LiveSubmitBroker`와 `LiveCancelBroker`를 별도 Protocol로 분리한 것도 좋다. submit-only 환경, cancel-only 환경, 둘 다 가능한 환경을 broker 인스턴스 분리로 표현 가능.

미세 약점 두 가지:

첫째, **Protocol return type이 `BrokerSubmitResult | dict[str, Any]`로 dict도 허용**한다(109행, 120행). KIS REST 응답을 직접 받아 normalize하는 유연성을 위한 것이지만 type 강제가 약해진다. `_normalize_submit_result`(565~576행)가 `accepted`, `ok` 키만 보고 그 외 키는 무시. 만약 broker가 정의되지 않은 형태의 dict를 반환하면 silent하게 `rejected`로 normalize될 위험. **권장 보강**: 향후 KIS broker adapter 구현 시 항상 `BrokerSubmitResult` 인스턴스를 반환하도록 합의하고 dict 우회 경로는 점진적으로 제거.

둘째, **broker protocol에 mode 검증 마커가 없다.** submit broker가 실수로 paper profile로 생성된 경우 manager가 알 수 없다. profile mode 검증은 `LiveOrderGuard.assert_can_submit`에서 별도로 하지만 broker 자체에는 mode 정보가 없다. KIS adapter 구현 시 broker 생성자에 mode 확인 단계가 들어가야 안전. 우선순위 중간.

## Q2: guard 차단을 blocked 상태로 저장하는 정책이 적절한지

**적절. 다만 blocked가 terminal이라는 정책의 운영 의미를 docstring에 명시 권장.**

코드 검증(`live_order_manager.py` 220~236행):
- `LiveOrderGuard.assert_can_submit` raise → `LiveOrderGuardError` catch
- `_transition(row, "blocked", ...)` 수행 + detail_json에 `blocking_reasons` 저장
- broker 호출 없이 audit event(`submit_blocked`)만 기록

장점 4가지:
1. **audit 보존**: guard 차단도 audit event로 기록되어 사후 분석 가능. "왜 차단됐는지"가 `blocking_reasons`로 추적.
2. **상태 머신 일관**: `intent_created → blocked`가 ALLOWED_TRANSITIONS(20행)에 있음.
3. **blocked는 terminal**: `"blocked": set()`(21행), 다시 살아나지 않음.
4. **broker 호출 없음**: blocking 시 KIS API 호출 0. rate limit 영향 0.

**단 한 가지 운영 시나리오 정책 명시 필요**: blocked가 terminal이라 같은 idempotency key로는 새 intent 생성이 차단된다(140~144행 `fetch_live_order_by_idempotency_key`). 만약 차단 사유가 일시적(예: kill switch 일시 ON, market_status stale)이고 운영자가 해제 후 같은 신호로 재시도하려면:

- (a) **같은 prediction_id/signal_id로는 재시도 불가**: idempotency key가 동일하므로 기존 blocked LiveOrder가 반환되어 새 intent 생성 차단.
- (b) **운영자는 새 prediction을 받거나 새 signal_id를 만들어야** 같은 의도의 주문을 재시도 가능.

이는 **의도된 보수 정책**(silent re-submit 방지)이지만 운영 시 운영자가 의아할 수 있다. `LiveOrderManager.create_intent` docstring에 "blocked 상태는 terminal이며, 차단 사유 해제 후 재시도하려면 새 prediction_id 또는 새 signal_id가 필요" 한 줄 추가 권장.

대안 후보(권장하지 않음): blocked 상태에서 unblock 후 새 intent 허용하는 별도 method(예: `force_retry(order_id, override_reason)`). 운영 안전 측면에서 silent re-submit 위험이 있어 현재 보수 정책이 맞다.

## Q3: live unmatched 상태를 pending_lookup 대신 unknown으로 두는 보수 정책이 맞는지

**적절. paper의 pending_lookup과 의도적으로 분리한 것이 옳다.**

`live_execution_sync.py` 84~85행: `if not snapshot.matched: return "unknown"`. paper의 `pending_lookup`("broker 응답 못 받음 → 잠시 후 재조회 예정")과 의미가 다르다.

live의 `unknown` 의미:
1. "broker로부터 명확한 응답이 없음 → 운영자 또는 명시적 재조회 필요"라는 fail-safe.
2. 신규 주문 차단(다음 같은 종목 intent는 `LiveOrderManager.create_intent`에서 storage UNIQUE로 또는 fetch_open_live_orders로 차단).
3. 자동 다음 신호 처리 차단(`recover_open_orders`가 명시적 호출되어야 정상화).

장점:
1. **paper-vs-live 의미 분리 명확**: 같은 이름을 쓰지 않으니 운영자가 두 환경의 다른 정책을 혼동하지 않는다. paper는 transient 자동 재조회, live는 사람 개입 fail-safe.
2. **fail-safe**: unmatched는 신규 주문 차단으로 이어져 silent하게 잘못된 주문이 나가지 않는다.
3. **`recover_open_orders` 명시 호출**: 재시작 시 자동 unknown 처리되고 정상화에 broker 조회가 필요.

미세 약점 두 가지:

첫째, **재조회 빈도/주기 정책이 manager에 없다.** unknown 상태가 누적되면 운영자가 매번 수동으로 sync를 트리거해야 한다. 자동 재조회 정책(예: 5분 cooldown 후 자동 sync 1회 시도)이 있으면 운영 부담이 줄지만, 자동 재조회는 silent fix 위험이 있어 보수적 결정. **operator-facing CLI/dashboard에 "unknown 상태 주문 N건, 마지막 sync로부터 M분 경과" 알림이 있으면 운영자 호출 부담을 줄일 수 있다.** 우선순위 중간.

둘째, **`unknown → stuck` 시간 기반 자동 전이가 manager에 없다.** ALLOWED_TRANSITIONS(34행)에 `unknown → stuck`이 있지만 시간 기반 트리거가 코드에 없다. 일정 시간 후 자동 stuck 처리는 stuck 알림 SLA의 기반이 되므로 별도 slice에서 추가 필요. work_ver_9-2 본문 명시는 없지만 향후 작업 항목.

## Q4: 주문 상태 업데이트와 live_fills/position 반영을 분리한 경계에 이견이 없는지

**이견 없음. 단계 분리가 정확하다.**

`live_execution_sync.py` 131~157행 `apply_order_snapshot`이 `live_orders` status + filled_qty/remaining_qty/avg_fill_price + `live_order_events`만 업데이트. `live_fills`, `live_positions`, 회계 원장은 미반영(work_ver_9-2 60행 명시).

장점 3가지:
1. **상태 머신 안정화 우선**: 상태 전이(`submitted → accepted → open → filled` 등)의 정확성이 먼저 검증되어야 fill 누적/회계가 의미를 가짐. 거꾸로 가면 잘못된 fill이 누적되어 회계 깨짐.
2. **변경 영향 최소화**: 한 slice에서 많은 테이블을 건드리면 회귀 위험 증가. 분리해서 step-by-step 진입이 안전.
3. **delta_fill_qty 계산 완료**: `build_live_order_sync_decision`의 `previous_applied_fill_qty`(106~121행)로 delta가 정확히 계산됨. 다음 단계 `live_fills` insert 시 이 delta를 그대로 사용 가능.

`_transition_path` 헬퍼(207~235행)도 좋다. broker가 직접 `submitted`에서 `filled`로 점프한 응답을 줘도 `submitted → accepted → filled` 같은 path를 자동 탐색해 ALLOWED_TRANSITIONS를 우회하지 않는다. 상태 머신 invariant 잠금.

미세 약점 두 가지:

첫째, **state machine과 회계의 일관성 위험**: `live_orders.status=filled`로 업데이트됐는데 `live_fills`가 비어 있으면 두 테이블의 의미가 일시적으로 어긋난다. dashboard/reconciliation이 둘 다 보면 헷갈린다. **다음 slice 진입 전까지 이 어긋남이 운영 환경에 노출되지 않도록 정책 명시 필요**. 즉 운영 DB apply 후에는 (a) `live_fills` slice가 끝나기 전까지 LiveExecutionSync를 일반 호출 경로에 연결하지 않거나, (b) dashboard가 "fills 미반영" 경고를 명시.

둘째, **filled_qty/remaining_qty 업데이트만으로는 회계 추적 불완전**: avg_fill_price도 업데이트되지만 매수 cost basis, 매도 수익, 수수료/세금 같은 회계 영향은 별도. 운영 dashboard가 잘못된 PnL을 표시할 위험. Phase 1 read-only에서는 PnL이 별 의미 없으므로 안전, Phase 2 canary 진입 전 `live_fills`/position이 반영되어야 함.

## Q5: 다음 라운드를 live_fills delta idempotency로 진행해도 되는지

**동의. 가장 자연스러운 다음 단계.**

이유 4가지:
1. **Slice 5-2가 delta_fill_qty 계산까지 마침**: `LiveOrderSyncDecision.delta_fill_qty`/`applied_fill_qty`가 이미 있음. `live_fills` insert 시 그대로 사용 가능.
2. **회계 정합성 우선순위**: state machine 안정화 후 회계 원장 정합성이 다음 우선순위. position/portfolio는 그 후.
3. **delta idempotency가 핵심 invariant**: 같은 broker_fill_id로 두 번 insert되면 회계가 깨진다. UNIQUE constraint + delta 계산이 한 라운드에 잠겨야 안전.
4. **범위 적절**: work_ver_9-2 6.1 권장안("LiveFill record 생성 + 중복 delta 차단 테스트까지, position/portfolio는 다음 slice")이 적정 크기.

권고 추가 한 가지: **live_fills delta idempotency 라운드에서 `live_orders.filled_qty`와 `live_fills.SUM(fill_qty)`의 정합성 검증도 함께 잠가야 한다.** 두 값이 어긋나면 silent bug. 테스트로 잠금하고 정합성 위반 시 `unknown`/`stuck`으로 다운그레이드하는 정책을 manager에 두면 fail-safe.

또한 work_ver_9-2 6.2의 "Phase 2의 1일 1부모주문/동일 종목 pending 차단" 정책 결정도 같은 라운드에 함께 합의하면 효율. Codex 권장안(manager 내부 pre-submit policy + 수치 한도는 risk/live gate 분리)에 cowork 동의 — manager가 부모 주문 수 카운트와 pending 검증을 직접 하는 게 자연스럽고, 수치 한도는 별도 gate가 정책 변경 시 manager를 안 건드리도록 분리.

## 추가 발견 (코드 직접 본 결과)

work_ver_9-2 본문에 명시되지 않은 미세 항목 세 가지.

첫째, **`set_live_kill_switch.sh` CLI(`script_dispatch.sh` 1727~1840+행)가 단단하게 짜여 있다.** `--enable`/`--disable`/`--status` 분리, `--disable --apply`는 `--confirm-disable` 필수(1816~1817행), actor enum 검증(1811~1813행), reason 비어있으면 거부(1814~1815행), path traversal 방지(1802~1803행). 5층 잠금이 review_ver_5/8의 "kill switch CLI 도구 부재" 위험을 정확히 해소.

둘째, **`LiveOrderManager`가 `RuntimeWriter.sqlite_store is None`이면 ValueError를 raise**(130~131행). storage 없는 manager 생성을 차단하는 fail-fast 패턴이 좋다. 다만 paper/synthetic 환경에서 `RuntimeWriter`를 만들 때 SQLite를 disable한 경우라면 manager 생성 자체가 실패해서 silent fallback이 안 됨 — 의도된 strict 정책이지만 향후 synthetic/test 환경 통합 시 검토 필요.

셋째, **`_normalize_cancel_result`(579~588행)가 `status` 기본값을 `"cancel_requested"`로 둔다.** broker 응답에 status가 없으면 안전 측 fallback. 다만 broker가 `accepted=True, status="cancelled"`(즉시 취소 완료)를 줬을 때 `target_status = result.status.strip().lower()`(372행)로 받아 `cancel_requested → cancelled` 전이를 따라 정상 처리. 좋은 결정. 단 manager의 `request_cancel`이 broker 응답을 받기 전에 `cancel_requested`로 전이하는데(330~339행), broker가 즉시 `cancelled`를 응답하면 `cancel_requested → cancelled` 추가 전이로 두 번째 event가 기록됨. audit 측면에서는 옳지만 dashboard 표시 시 "cancel_requested → cancelled" 두 event가 같은 시각에 보일 수 있어 운영자 혼동 가능. 우선순위 낮음.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 protocol 주입 broker 경계 | 매우 안전 | dict 우회 경로 점진 제거, broker에 mode 검증 마커 |
| Q2 guard 차단 → blocked 정책 | 적절 | blocked terminal 정책의 운영 의미 docstring 명시 |
| Q3 live unmatched → unknown 보수 정책 | 적절 | 운영자 알림(unknown N건/sync M분 경과), 시간 기반 stuck 자동 전이 별도 slice |
| Q4 상태/회계 분리 경계 | 이견 없음 | 다음 slice 전까지 운영 환경 노출 정책(dashboard "fills 미반영" 경고) |
| Q5 다음 = live_fills delta idempotency | 동의 | `live_orders.filled_qty` vs `live_fills.SUM` 정합성 검증 함께 |
| set_live_kill_switch CLI 추가 발견 | 5층 잠금 단단 | 없음 |

## 다음 단계 권장

1. **Slice 5-3 `live_fills` delta idempotency 진입**: `LiveFill` dataclass + 중복 delta 차단 + `live_orders.filled_qty` vs `live_fills.SUM(fill_qty)` 정합성 테스트. position/portfolio는 다음 slice로 분리.
2. **Phase 2 pre-submit policy 결정 (병행)**: "1일 1부모주문, 동일 종목 pending 차단"을 manager 내부 pre-submit policy로 두는 Codex 권장안에 cowork 동의. 같은 라운드에서 구현 가능. 수치 한도는 별도 gate.
3. **`apply_storage_migration.sh --apply` 운영자 결정 (병행)**: Slice 5/5-2/5-3 리뷰가 끝난 다음 장외 시간에 dashboard/live runtime 정지 확인 후 1회 적용. Codex 권장 시점.
4. **docstring 보강 (낮음, 1줄 단위)**:
   - `LiveOrderManager.create_intent` — blocked terminal 정책과 재시도 시 새 prediction_id 필요
   - `live_phase_readiness.py` — JSON only 정책 명시(review_ver_8 권장)
   - `live_execution_sync.py` — `live_fills` 분리로 인한 일시적 어긋남 정책
5. **운영 dashboard 보강 후보**:
   - "unknown 상태 주문 N건, 마지막 sync M분 경과" 경고 카드
   - "fills 미반영 모드" 안내 (Slice 5-3 완료 전까지)
6. **Slice 5-2 → Slice 5-3 다음 후속**:
   - 시간 기반 stuck 자동 전이 정책
   - `live_positions`/`live_portfolio_snapshots` 반영
   - 수수료/세금/T+2 결제일 반영
   - `ops_live_audit_events` hash chain

## 신뢰 수준

work_ver_9-2는 review_ver_8의 다음 단계 권장 4가지를 모두 한 라운드에 흡수 + Slice 5-2까지 연속 진행한 큰 라운드인데도 205개 테스트 통과 + 5층 운영 안전 잠금 유지. **Codex가 cowork 권장을 흡수하는 속도와 정확도가 일관되게 높고, 한 라운드에 두 slice를 통합해도 회귀 위험을 만들지 않는다.** protocol 주입 패턴 + fail-safe unknown + blocked terminal + delta_fill_qty 계산 — 모든 핵심 invariant가 코드와 테스트로 잠겨 있다.

다음 라운드(review_ver_10 예상)에서 cowork이 (a) `LiveFill` UNIQUE 제약 검증, (b) delta idempotency + `live_orders.filled_qty` 정합성 검증, (c) Phase 2 pre-submit policy(부모 주문 카운트, 동일 종목 pending 차단) 검증 — 세 단계로 본다.
