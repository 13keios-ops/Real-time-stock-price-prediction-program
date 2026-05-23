# Claude cowork 리뷰 review_ver_10: Slice 5-3 live_fills delta + Phase 2 pre-submit 정책 + 정합성 report + monitoring + position helper

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_10`
- 기준 작업본: `2026-05-17-production-architecture-implementation-blueprint-work_ver_10.md`
- cowork 직접 검증 파일: `app/services/live_execution_sync.py`(`apply_order_snapshot_and_fill_delta`, `validate_live_order_fill_qty`, `_derive_delta_fill_price`, `_live_fill_id`), `app/services/live_order_manager.py`(`LivePreSubmitPolicy`, `_pre_submit_blocking_reasons`, `_pre_submit_policy`, `_is_parent_live_order`)

## 요약

work_ver_10은 review_ver_9의 권장 1순위(`live_fills` delta idempotency)와 병행 권장(Phase 2 pre-submit 정책)을 모두 한 라운드에 흡수 + dashboard/runtime report 정합성 노출 + unknown/stuck monitoring + 순수 position accounting helper까지 다섯 영역을 동시 진행. 220개 전체 테스트 통과. **deterministic fill_id + consistency 검증 + 정책 위반 시 broker 호출 없이 blocked + dashboard/runtime report read-only 노출** 모든 면에서 보수적이고 단단하다. 결론은 **그대로 사용 가능. 다음 1순위 = KIS 실제 응답 fixture 확대.**

핵심 발견 세 가지: (1) `fill_id` deterministic hash가 `applied_fill_qty + delta_fill_qty`를 둘 다 포함해 broker가 cumulative를 잘못 감소시키는 비정상 시나리오에서도 안전. (2) Phase 2 "1거래일 1부모 주문서" 정책이 **filled 후에도 같은 날 두 번째 부모 주문을 차단**한다 — 의도된 보수 정책이고 매우 적절. (3) `_derive_delta_fill_price`의 누적 평균가 기반 계산은 임시 원장으로 허용 가능하지만 다중 체결 평탄화 한계가 있어 Phase 3 진입 전 KIS 개별 체결 ID 확보가 필요.

## Q1: live_fills delta idempotency 정책이 Phase 2 canary 전제에 충분히 보수적인지

**충분히 보수적이다. fill_id deterministic hash가 핵심 잠금이고 broker 비정상 시나리오까지 안전 처리.**

`live_execution_sync.py` 482~493행의 `_live_fill_id`를 직접 봤다:

```python
def _live_fill_id(order_id: str, decision: LiveOrderSyncDecision) -> str:
    return "live-fill-" + _short_hash(
        "|".join([order_id, decision.broker_branch_no, decision.broker_order_no,
                  str(decision.applied_fill_qty), str(decision.delta_fill_qty)])
    )
```

key 구성 요소 5개(order_id, broker_branch_no, broker_order_no, applied_fill_qty, delta_fill_qty)가 deterministic hash로 들어가고, SQLite PRIMARY KEY 제약(`live_fills.fill_id`)이 중복 insert를 차단한다. 같은 snapshot을 반복 적용하면 같은 (applied_fill_qty, delta_fill_qty) 쌍이 나와 같은 fill_id가 생성되어 SQLite가 자동 차단.

`apply_order_snapshot_and_fill_delta`(197~276행)의 흐름:
1. `fetch_live_fill_totals(order_id)`로 기존 누적 fill 수량/notional 가져옴
2. broker cumulative와 비교해 delta만 계산(`build_live_order_sync_decision`)
3. delta > 0이고 matched면 fill 생성, fill_id 충돌 시 silent skip(`write_live_fill_if_absent`)
4. 마지막에 `validate_live_order_fill_qty`로 정합성 검증

**broker가 cumulative를 잘못 감소시키는 비정상 시나리오 분석**: 만약 broker가 잠시 filled_qty를 줄여서 응답하면 `delta_fill_qty = max(snapshot.filled_qty - applied_before, 0) = 0`(`build_live_order_sync_decision` 145행)으로 처리. fill 생성 안 됨. 다음 정상 snapshot에서 새 (applied_fill_qty, delta_fill_qty) 쌍이 만들어져 새 fill_id로 정상 진행. **회복 가능한 fail-safe.**

미세 약점 한 가지:
- **`broker_order_no`가 빈 문자열인 단계(intent_created/blocked/submit_pending)에서는 fill_id가 약하다.** 다만 이 단계에서는 `decision.matched=False`이거나 `delta_fill_qty=0`이라 fill 생성 자체가 안 됨. 우회 위험 0.

종합: **Phase 2 canary 전제에 매우 보수적.** delta_fill_qty의 음수 자연 방지, snapshot 반복 적용 idempotency, broker_order_no 빈 단계 차단 모두 코드로 잠겨 있다.

## Q2: 누적 평균가 기반 delta 체결가 계산이 임시 원장으로 허용 가능한지

**Phase 2 canary 검증 기간(첫 30거래일)에는 허용 가능. Phase 3 진입 또는 실전 정산 직전 KIS 개별 체결 ID 기반 source를 추가하면 완전.**

`_derive_delta_fill_price`(472~479행)의 계산:

```python
cumulative_notional = max(decision.filled_qty * decision.avg_fill_price, 0.0)
delta_notional = cumulative_notional - max(float(previous_notional or 0.0), 0.0)
if delta_notional <= 0 and decision.avg_fill_price > 0:
    return decision.avg_fill_price
return max(delta_notional / decision.delta_fill_qty, 0.0)
```

방법론: **delta_notional = (broker cumulative qty × broker cumulative avg price) − (기존 live_fills notional)**. 이를 delta qty로 나눠 delta price 계산. delta_notional이 음수면 broker avg_fill_price로 fallback(안전 측). `detail_json["sync"]["delta_price_method"]`에 `cumulative_avg_minus_internal_notional` 명시되어 사후 분석 가능.

**근본 한계**: 한 snapshot 안에 묶인 다중 체결의 개별 가격이 평탄화된다. 예: 첫 체결 100원 5주 + 두 번째 체결 110원 5주가 같은 snapshot에 cumulative로 들어오면 우리는 105원 평균 1건의 fill로만 기록.

**Phase 2 canary 단계에서 허용 가능한 이유**:
1. **1거래일 1부모 주문 정책 + 소액 canary**: 한 주문 내 다중 가격 체결이 흔하지 않다. 안정 대형주 + 소량 주문이라면 보통 1~2개 가격에 체결.
2. **개별 체결 ID는 KIS 별도 API**: 현재 daily order/fill API로 개별 체결 ID를 받을 수 있는지 확인 필요(work_ver_10 본문 6.1에서 fixture 확대 1순위로 인지됨). 별도 API가 필요하면 별도 slice.
3. **임시 원장 vs 정본 분리**: 우리 회계는 진단/검증 용도, **실전 정산(세금 신고, KIS 거래 명세서)은 KIS 정산 자료가 정본**. live_fills는 reconciliation 비교 대상.
4. **detail_json 방법론 명시**: 향후 정확한 회계가 필요해지면 raw_broker_fill로 재계산 가능.

**Phase 3 진입 또는 실전 정산 전 보강 권장**: KIS 개별 체결 ID 확보 후 별도 `live_broker_fills` source(또는 live_fills의 `broker_fill_id` 컬럼 활용) 추가하고, 다중 체결 분해 정합성을 검증하는 slice. 우선순위 중간(Phase 3 진입 전).

**중요 보완 한 가지**: live_fills 기록을 보류하라는 옵션(work_ver_10 6.2 자체 질문)에 대해서는 **반대**. 임시 원장이라도 있으면 dashboard 정합성 검증과 신규 intent 차단(`block_live_fill_mismatch`)이 작동하지만, 보류하면 그 안전 잠금이 모두 비활성. **현재 임시 원장 + 방법론 명시 + Phase 3 전 정밀화 계획**이 균형 잡힌 결정.

## Q3: Phase 2 pre-submit 정책 manager 내부 + "1거래일 1부모 주문서" filled 후에도 차단

**적절. 그리고 네, filled 후에도 차단됩니다 — 의도된 보수 정책이고 Phase 2 본질에 맞다.**

`live_order_manager.py` 458~491행의 `_pre_submit_blocking_reasons`를 직접 봤다. parent_orders 카운트(465~474행):

```python
parent_orders = [
    row
    for row in self.store.fetch_live_orders_for_trading_day(request.trading_day)
    if _is_parent_live_order(row)
    and str(row["idempotency_key"]) != idempotency_key
    and str(row["status"]) != "blocked"
]
if len(parent_orders) >= policy.max_parent_orders_per_day:
    reasons.append("phase2_parent_order_limit_exceeded")
```

제외되는 status는 `blocked` 하나뿐. **`filled`, `cancelled`, `cancelled_partial`, `expired`, `rejected` 같은 terminal 상태도 모두 카운트된다.** 즉 오늘 이미 한 부모 주문이 체결/취소/거절되었어도 두 번째 부모 주문 시도는 차단된다.

**Phase 2 본질에 맞는 이유 4가지**:

1. **Phase 2 canary는 실전 진입 첫 단계.** 운용 의사결정 검증이지 수익 극대화가 아님. 1거래일 1주문이라는 작은 단위로 lifecycle 전체(intent → submit → fill → settle)를 검증하는 게 목적.
2. **filled 후 같은 종목 추가 매수가 정말 필요하다면 의도적 retry**: 새 prediction_id/signal_id로 새 intent 발급 필요. 운영자 인지 가능 + audit 추적 가능.
3. **자동 추가 주문 방지**: 모델이 같은 신호를 반복 발생시키는 경우(예: 호가 흔들림)에도 자동으로 두 번째 주문이 안 나감.
4. **Phase 3에서 정책 완화**: `max_parent_orders_per_day`를 N으로 늘리거나 정책 자체 제거. Phase 단계별 완화 경로가 자연스럽다.

manager 내부 정책 결정의 적절성:
- 정책이 storage state(parent_orders 카운트, fill mismatch, same symbol pending)에 의존하므로 storage caller인 manager에 두는 게 자연스럽다.
- review_ver_9 권장(manager 내부 pre-submit policy + 수치 한도 별도 gate)과 일치.

**보강 권장 두 가지**:

첫째, **운영자 인지를 위한 dashboard 카드**. "Phase 2 오늘의 부모 주문 카운트 1/1, 다음 주문 차단" 같은 카운터가 dashboard에 있으면 운영자가 차단 사유를 즉시 알 수 있다. 현재 fill consistency와 unknown/stuck 카드는 추가됐지만 parent order limit 카운터는 없다.

둘째, **차단 사유 메시지 구체화**. `phase2_parent_order_limit_exceeded`만으로는 "이미 N건 있어서 차단"인지 알 수 없다. 메시지에 카운트 정보 포함이 audit 분석 시 유리. 예: `phase2_parent_order_limit_exceeded:current=1,limit=1`. 우선순위 낮음.

미세 약점 한 가지: **`max_parent_orders_per_day=1`이 manager 내부 default로 하드코드**(_pre_submit_policy 600~603행)되어 있다. review_ver_9에서 "수치 한도는 별도 risk/live gate로 분리"라고 합의했는데, 현재 default 1이 manager 안에 묶여 있다. 운영자가 한도를 바꾸려면 `request.order_policy`에 명시해야 함. **권장**: 수치 한도를 별도 settings/gate config로 분리하고, manager는 정책 evaluator로만 사용. 우선순위 중간(Phase 3 진입 전).

## Q4: 다음 slice 우선순위 — KIS fixture → 알림/리뷰 → live_positions

**순서 동의. 단 1순위와 2순위는 의존성 없어 병행 가능.**

1순위 **KIS 실제 응답 fixture 확대 + mapper 검증**: 가장 시급. `snapshot_from_kis_daily_order_fill`이 가정한 필드명이 실제 KIS 응답과 일치하지 않으면 운영 진입 시 silent 매핑 실패 위험. Codex가 대체 필드명(`ord_orgno`, `ccld_qty`, `ord_remn_qty`, `avg_ccld_unpr`, `ord_dvsn_cd_name`, `excg_dvsn_cd`)과 연속 조회(`tr_cont=M`) fixture는 추가했지만 실제 운영 환경 응답 sample이 필요. 비밀값 제거한 sample을 운영자가 제공해야 다음 단계 가능.

2순위 **mismatch/unknown/stuck 외부 알림 + 장후 review 절차**: 현재 dashboard와 runtime report에 read-only로 노출됐지만 외부 알림(메시지/이메일/푸시)은 없음. review_ver_3부터 일관되게 지적된 "dashboard 외 알림 채널 부재" 작업 영역. 1순위와 의존성 없으므로 **병행 가능**.

3순위 **순수 position 계산을 live_positions에 명시 저장**: 위 1, 2가 충분히 안정화된 후. position 자동 저장은 silent reconciliation 위험이 있어 후행이 맞음. 자동 저장 시 (a) KIS 잔고 조회와의 정합성 검증, (b) 실패 시 자동 align 거부 정책(이전 paper dual account review와 같은 원칙) 필요. 위 2순위 알림이 먼저 있어야 차이 발견 시 운영자 호출 경로가 작동.

**중요 추가 권고**: 운영자 결정 잔여 항목 3개(Phase 2 주문 금액 한도, 부분 체결 잔량 자동 취소, audit hash chain anchor)도 1순위 작업 중 병행 합의 필요. 특히 **부분 체결 잔량 자동 취소는 Phase 2 운영 안전에 직결**. Codex 권장안(work_ver_10 6.3)인 "Phase 2 기본은 잔량 유지 + 같은 종목 신규 차단 + 장후/정해진 시각에 사람 승인 취소"가 합리적이지만 운영자 합의가 필요.

## 추가 발견 (코드 직접 본 결과)

work_ver_10 본문에 명시되지 않은 미세 항목 네 가지.

첫째, **`_apply_status`에서 `update_quantities=final_step and decision.matched`**(193행). matched=False(unknown)인 경우 quantities를 업데이트 안 함. 좋은 fail-safe — unmatched snapshot으로 인해 silent하게 수량이 0으로 덮어쓰여질 위험 차단.

둘째, **`build_live_order_fill_consistency_summary_from_store`(355행)가 별도 함수로 분리**되어 SQLite store만으로 호출 가능. dashboard/reporting에서 LiveExecutionSync 인스턴스 없이 직접 사용. 좋은 디커플링 — read-only 경로가 RuntimeWriter 의존성을 만들지 않는다.

셋째, **`_pre_submit_blocking_reasons`의 SQL 호출이 많음**. 한 intent 검증당 `fetch_live_orders_for_trading_day` + `fetch_open_live_orders` + `sum_live_fill_qty(N)` = 최대 N+2 쿼리. Phase 2에서 N이 1~5이라 OK이지만 Phase 3 다종목 환경(N=10~20)에서는 무거워짐. Phase 3 진입 시 query batching 최적화 후보. 우선순위 매우 낮음.

넷째, **`LivePreSubmitPolicy`의 `block_live_fill_mismatch=True`가 거래일 전체 mismatch를 본다**(483~490행). 즉 다른 종목의 mismatch가 발견되면 이번 intent도 차단된다. **이게 의도된 정책인가?** 동일 종목 mismatch만 차단하는 게 더 정밀할 수 있는데 현재 구현은 더 보수적(전체 차단). Phase 2 단계에서는 보수적인 게 안전하지만 운영 부담 가능 — 한 종목 mismatch가 발견되면 그날 모든 종목 신규 주문 차단. Phase 3 진입 시 정밀화 검토.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 live_fills delta idempotency | 매우 보수적 | broker_order_no 빈 단계는 fill 생성 자체가 안 됨 (현재 안전) |
| Q2 누적 평균가 delta 계산 | 임시 원장으로 허용 가능 | Phase 3 전 KIS 개별 체결 ID source 추가, live_fills 보류는 반대 |
| Q3 Phase 2 pre-submit + filled 후 차단 | 적절 | 운영자 인지용 dashboard 카운터 카드, 차단 메시지 카운트 정보, 수치 한도 별도 gate 분리 |
| Q4 다음 우선순위 | KIS fixture/알림/live_positions 순서 동의 | 1순위와 2순위 병행 가능, 운영자 결정 3개 병행 합의 |
| `block_live_fill_mismatch` 전체 거래일 차단 (cowork 발견) | Phase 2 안전 측 | Phase 3 진입 시 동일 종목만 차단으로 정밀화 검토 |

## 다음 단계 권장

1. **1순위: KIS 실제 응답 fixture 확대 + mapper 검증** — 비밀값 제거한 운영 환경 sample 1~3건 확보 후 `snapshot_from_kis_daily_order_fill` 매핑 검증.
2. **1순위(병행): mismatch/unknown/stuck 외부 알림 + 장후 review 절차** — dashboard read-only는 완료, 외부 알림 채널 결정 후 발송 wrapper 구현.
3. **2순위: 운영자 결정 3개 합의** — Phase 2 주문 금액 한도, 부분 체결 잔량 자동 취소(Codex 권장: 자동 추가 주문 금지 + 자동 취소는 cancel fixture 충분해진 뒤), audit hash chain anchor 방식.
4. **3순위: live_positions 명시 저장** — 위 2개 안정화 후. KIS 잔고 조회 정합성 검증 + 차이 발견 시 사람 호출 경로 함께.
5. **운영자 인지 보강(낮음)**: dashboard에 Phase 2 부모 주문 카운터 카드, 차단 메시지에 카운트 정보 포함.
6. **Phase 3 진입 전 정밀화 후보**: `block_live_fill_mismatch`를 동일 종목만으로 좁히기, `max_parent_orders_per_day` default를 별도 gate로 분리, KIS 개별 체결 ID 기반 정밀 회계.

## 신뢰 수준

work_ver_10은 review_ver_9의 권장 1순위 + 병행 권장 + 추가 4개 영역(monitoring, position accounting, dashboard 정합성, runtime report)을 한 라운드에 모두 흡수했는데도 220개 전체 테스트 통과. **Codex가 큰 라운드에서도 회귀 위험을 만들지 않고 보수적 invariant(deterministic fill_id, broker 비정상 시나리오 안전 처리, filled 후 차단, mismatch 시 신규 차단)를 단단하게 잠근다.**

다음 라운드(review_ver_11 예상)에서 cowork이 (a) KIS 실제 응답 fixture vs `snapshot_from_kis_daily_order_fill` 매핑 검증, (b) 외부 알림 채널 결정 후 발송 wrapper 검증, (c) 운영자 결정 3개 합의 후 코드 반영 검증 — 세 단계로 본다.
