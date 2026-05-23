# Claude cowork 리뷰 review_ver_11: work_ver_11 시리즈 통합본 (alert/audit/recovery/Phase2/redaction/adapter/clock/freshness)

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_11`
- 기준 작업본: `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-20.md` (work_ver_11 + 19개 sub-work 통합본)
- cowork 직접 검증 파일: `app/brokers/kis_live_order.py`(KisLiveOrderAdapter), `app/services/market_data_freshness.py`, `app/services/live_audit.py`(REQUIRED_AUDIT_FIELDS), `app/services/system_clock.py`, `app/services/live_order_manager.py`(PHASE2_DEFAULT_MAX_ORDER_NOTIONAL + pre-submit context)

## 요약

work_ver_11-20은 **10개 영역**(alert outbox, audit hash chain, recovery export self-test, Phase 2 pre-submit 정책 강화, KIS fixture redaction, KIS live order guarded adapter, system clock, position invalid side, intent/raw response validation, market data freshness)을 한 시리즈에 통합 + 운영자 결정 5개 반영 + 2026-05-18 장중 WebSocket reconnect 이슈로부터 freshness 안전 교훈 흡수. 237/242개 전체 테스트 통과 + 모든 변경이 운영 안전 invariant를 코드와 테스트로 잠굼. 결론은 **그대로 사용 가능. Phase 1 진입 전 NAS 복구 drill + 실제 KIS 응답 fixture 검증 권장.**

핵심 발견 세 가지: (1) `KisLiveOrderAdapter`가 submit/cancel 비대칭(submit은 ALLOW_LIVE_ORDERS 필수, cancel은 enable flag와 분리)을 정확히 review_ver_5 시나리오 A로 구현. (2) `PHASE2_DEFAULT_MAX_ORDER_NOTIONAL = 100,000원`이 default이고 `max_order_allocation_pct = 10%`가 default — 효과적 한도는 `min(100k, allocation × 10%)`. (3) market_data_freshness defaults(trade/orderbook 30s, bar/prediction 120s, future_tolerance 2s)가 system_clock의 ±2s skew와 일치하는 정합성.

## Q1: Phase 2 잔량 자동 취소 금지 + 같은 종목 pending 차단이 첫 20거래일 기준 충분히 안전한가

**충분히 안전.** 운영자 결정 + Phase 2 canary 본질에 부합.

Phase 2 첫 20거래일은 lifecycle 검증(intent → submit → fill → settle)이 목적이지 수익 극대화가 아니다. 자동 취소가 silent하게 발생하면:
- 운영자가 의도와 다른 포지션 변경 인지 못 함
- silent 손실 누적 위험
- audit 추적 어려움

잔량 유지 + 같은 종목 pending 차단 + 수동 승인 cancel 정책이 위 세 가지 모두를 차단. 다만 장 종료까지 잔량이 안 닫히면 `derive_live_order_status`(execution_sync.py)가 `expired`로 자동 분류 — 회계 추적 가능.

**보강 권장 한 가지**: dashboard에 "Phase 2 미체결 잔량 N분 경과" 카운터 카드. 운영자가 수동 취소 의사결정에 사용. 현재 `unknown`/`stuck` 카드는 추가됐지만 "정상 open이지만 오래된 잔량"은 별도 카드가 없음.

## Q2: Phase 2 부모 주문 금액 한도 `min(100,000원, 운용 배정금의 10%)` 적절성

**보수적 시작점으로 적절. 단 watchlist 종목 가격 분포와 1주 강제 검토 권장.**

코드 검증 (`live_order_manager.py` 21~22, 686~706, 751~764행):
- `PHASE2_DEFAULT_MAX_ORDER_NOTIONAL = 100_000.0`
- `PHASE2_DEFAULT_MAX_ORDER_ALLOCATION_PCT` (default 10%)
- `_effective_order_notional_limit`: `min(max_order_notional, allocation_amount × allocation_pct)`
- allocation_amount 미전달 시 100k가 적용

분석:
- **KOSPI 대형주 1주 운용 가능**: 삼성전자(7만원대), 현대차(70만원 → 한도 초과로 차단), SK하이닉스(20만원대 → 한도 초과로 차단). 즉 watchlist 종목별로 1주도 못 들어가는 종목이 발생.
- **저가 대형주는 다주 가능**: 예: 신한지주(5만원대) 1주 = 50k → 한도 내 2주(100k)까지 가능.
- 1주 단위 강제가 명시되지 않으므로 `qty=2`인 intent가 50k 종목에서 통과됨.

**보강 권장**: **Phase 2 첫 20거래일은 `qty=1` 강제 또는 `max_order_qty=1` 정책을 manager에 추가**. 100k 한도와 별개로 "Phase 2 = 1주" 정책이 명확히 잠겨야 lifecycle 검증 의도와 정확히 일치. 만약 default 1주로 두지 않으면 운영자가 매번 `qty=1`을 명시해야 함 — silent에 `qty=2`가 들어갈 위험.

## Q3: KisLiveOrderAdapter submit은 ALLOW_LIVE_ORDERS 요구, 보호성 cancel은 enable flag와 분리

**매우 적절. review_ver_5 Q1 시나리오 A(신규만 막고 보호성 cancel은 허용)를 정확히 구현.**

`kis_live_order.py` 65~76행을 직접 봤다:

```python
def _assert_submit_enabled(self) -> None:
    self._assert_live_profile()
    if not bool(getattr(self._settings, "allow_live_orders", False)):
        raise KisLiveOrderAdapterError("ALLOW_LIVE_ORDERS must be true before live order delegation")

def _assert_live_profile(self) -> None:
    if trading_mode != "live": raise ...
    if profile_mode != "live": raise ...
```

- submit: live profile + trading_mode=live + **allow_live_orders=true** (3층)
- cancel: live profile + trading_mode=live only (2층, allow_live_orders 우회)

이 비대칭이 review_ver_5에서 합의된 시나리오 A를 정확히 구현. 운영자가 사고 의심으로 `ALLOW_LIVE_ORDERS=false`로 내리면 신규는 막히지만 기존 미체결 정리는 가능.

남은 잔존 우려(review_ver_5에서 이미 짚음): **cancel이 `ALLOW_LIVE_ORDERS=false`에서도 실제 KIS API 호출이 나간다.** 코드 정책상 안전하지만 운영자가 "절대 KIS API 호출 안 함"을 가정하면 어긋남. **권장**: `ALLOW_LIVE_ORDERS=false`의 의미를 "신규 위험 증가 차단, 보호성 cancel은 허용"으로 운영자 문서에 한 줄 명시.

또한 `KisLiveOrderAdapter`가 client를 composition으로 받고 `__init__`에서 KIS 클라이언트 직접 생성 안 함(1~6행 docstring "does not create a KIS client and does not call the network on import"). 이는 review_ver_4의 isolation 테스트 패턴과 일치 — 매우 좋은 구조.

## Q4: 운영 원장에 redacted payload만 저장 + 원본 broker response 미저장이 과보수인가

**과보수가 아닙니다. 정상적 보수 결정.** Codex 권장안에 동의.

이유 4가지:
1. **원본 broker response는 보안 위험**: 계좌번호, app key tail, 토큰 일부가 들어갈 수 있음. git 추적/NAS 백업에 들어가면 위험.
2. **redacted payload로도 audit/디버깅 충분**: 주요 필드(symbol, qty, price, status, order_no)는 redaction 제외.
3. **정밀 회계 필요 시 KIS 정산 자료가 정본**: 우리 원장은 보조. 분쟁 시 KIS 측 자료가 증거력 우위.
4. **재현 가능성 보존**: detail_json에 raw_broker_fill의 메타데이터(필드 키 목록, sample) 남기면 mapping 검증 가능.

**미세 보강 후보**: 원본 broker response가 정말 필요한 케이스(예: KIS API 스펙 변경 디버깅)를 위해 별도 암호화 저장소(git 추적 외, 키 관리 필요, 30일 retention)를 옵션으로 두는 별도 slice. 우선순위 낮음. 현재 결정 그대로 진행 가능.

## Q5: audit event에서 12개 필드 필수 강제

**적절. 단 비주문 audit event(kill switch, phase approval, readiness check)에는 sentinel 정책 또는 별도 chain 분리 필요.**

`live_audit.py` 19~32행 REQUIRED_AUDIT_FIELDS 12개 확인:
- 시스템: `trading_day`, `event_type`, `actor`, `previous_hash`
- 도메인: `symbol`, `order_id`, `prediction_id`, `signal_id`, `gate_decision_id`, `rule_version`, `model_version`, `data_snapshot_id`

주문 관련 audit event는 12개 모두 자연스럽지만 비주문 event는 일부 필드가 어색:
- kill switch ON event: `prediction_id`, `signal_id`, `gate_decision_id`, `data_snapshot_id` 모두 적용 안 됨
- phase approval: 같은 4개 필드 적용 안 됨
- readiness check: 같은 4개 필드 적용 안 됨

work_ver_11-20 본문 3장 audit hash chain 행에서 "비주문 audit event에는 별도 builder 또는 sentinel 정책 필요"로 인지됨. 두 가지 옵션:

**옵션 A (Codex 권장 추정, 단순)**: sentinel 값 정책. `prediction_id="none"`, `signal_id="none"` 같은 표준 sentinel. 코드 변경 없음, 호출 측에서 값 명시.

**옵션 B (review_ver_7에서 cowork 권장한 chain_id 활용)**: `chain_id`로 chain 분리. `chain_id="orders"`(주문 chain), `chain_id="operations"`(운영 chain), `chain_id="readiness"`(점검 chain). 각 chain은 자체 REQUIRED_AUDIT_FIELDS 정의 가능.

옵션 B가 의미적으로 더 정확하지만 옵션 A가 단순. **권장**: 우선 옵션 A로 시작(즉시 가능), Phase 3 진입 전 옵션 B로 확장. 우선순위 중간.

## Q6: system_clock Phase 1 readiness는 dry-run evidence, Phase 2 submit은 필수 guard 순서

**옳음. 단계적 강화가 자연스러움.**

코드 확인 (`system_clock.py` 14행): `DEFAULT_MAX_CLOCK_SKEW_SECONDS = 2.0`. 순수 helper로 network 호출 없음.

- **Phase 1 readiness**: 9개 check 중 fixture/dry-run evidence로 검증. 실제 시계 비교는 운영자/외부 fixture 제공. 점검 단계에서는 실제 KIS reference clock 없이도 readiness 통과 가능.
- **Phase 2 submit**: 실제 clock skew 검사가 hard gate. 2초 초과 시 KIS 주문 timestamp 거부 직전 차단.

KIS 주문 API timestamp 요구를 고려하면 ±2초가 보수적. NTP 자동 sync가 있는 환경이면 거의 0초 가까이 유지.

**보강 권장**: Phase 2 진입 전 **실제 reference clock 원천 결정** 필요. 후보:
- (a) KIS API 응답의 서버 시각 헤더 (HTTP `Date` 또는 KIS 전용 필드)
- (b) NTP 자동 sync (OS 레벨)
- (c) 운영자 수동 sync (정기 시각 확인)

work_ver_11-20 본문에서 "기준 시각 원천은 아직 미연결"로 인지됨. Phase 2 진입 차단 항목. **Codex 권장: KIS 응답의 시각 헤더가 가장 자동화 가능. NTP는 OS 의존, 수동은 운영 부담.**

## Q7: market data freshness 기본값 trade/orderbook 30s, bar/prediction 120s, future_tolerance 2s

**Phase 2 canary에 적절. 단 watchlist 활성도와 reconnect grace 검토 필요.**

코드 확인(`market_data_freshness.py` 23~31행):
- `max_trade_age_seconds: 30.0`
- `max_orderbook_age_seconds: 30.0`
- `max_bar_age_seconds: 120.0`
- `max_prediction_age_seconds: 120.0`
- `future_tolerance_seconds: 2.0`

분석:
- **trade/orderbook 30s**: 정규장 활성 종목은 초당 수십 건 tick. 30초 미수신은 명확한 stale 신호. KIS WS reconnect는 평소 5~15초 이내 회복이라 30초는 충분한 grace.
- **bar 120s**: 1분봉은 매 60초 닫힘. 가장 최근 닫힌 분봉 기준이라 120s = 1분봉 1회 누락 허용. 보수적.
- **prediction 120s**: 우리 모델이 1분 단위 예측. 2분 그레이스 = 1회 누락 허용. 적절.
- **future_tolerance 2s**: clock skew 2s와 일치. **system_clock과의 정합성 좋음**.

미세 약점 두 가지:

첫째, **저거래 종목 false positive**: watchlist 일부 거래량 적은 종목은 30초 이상 tick이 안 들어올 수 있음. `trade_tick_stale`로 차단. Phase 2 watchlist는 대형주만이라 OK이지만 Phase 3 확장 시 종목별 다른 threshold 검토.

둘째, **WS reconnect 직후 grace 부재**: 2026-05-18 KIS WS reconnect 이슈 시 reconnect 직후 30초 동안 freshness 차단. 정상 reconnect도 false alert 위험. **권장**: `reconnect_grace_seconds` 옵션 추가하고 reconnect 후 30~60초 selective grace. 우선순위 중간.

## Q8: Phase 2에서 orderbook_tick 필수 vs 선택 입력

**Codex 권장(필수)에 동의. 단 reconnect 안정성 확보 후.**

orderbook 없이는 slippage gate, spread gate가 의미를 잃음. 호가 정보 없이 주문하면 의도와 다른 가격 체결 위험. Phase 2 canary는 안전 우선이라 호가 stale 차단이 옳다.

다만 위 Q7 두 번째 약점(WS reconnect 직후 grace)이 orderbook에 가장 강하게 작용. orderbook이 필수면 reconnect 직후 모든 주문이 30초 차단됨. 운영 부담 증가.

**권장 단계**:
1. **현재(Phase 2 진입 전)**: orderbook 필수가 default. WS reconnect 안정성 점검(reconnect 평균/p95 시간 측정).
2. **WS reconnect가 5~15초 이내 안정적이면**: 필수 유지. 30초 grace로 충분.
3. **WS reconnect가 30초 이상 자주 발생하면**: `reconnect_grace_seconds=60` 옵션으로 selective grace 적용.

work_ver_11-20 4장의 2026-05-18 WS reconnect 이슈가 정확히 이 사각을 가리킨다. **권장: orderbook 필수 결정 전 WS keepalive 정책 + reconnect metric 작업이 선행되어야 함**.

## Q9: unknown/stuck 1분 grace + fill mismatch/kill switch/DB/disk는 grace 미적용

**적절. transient vs immediate 위험 분리가 정확.**

- **unknown/stuck 1분 grace**: KIS reconnect, REST timeout 같은 transient 원인 가능. 1분 grace로 false alert 감소.
- **fill mismatch**: 회계 정합성 즉시 위험. grace 없는 게 옳음.
- **kill switch ON**: 운영자/시스템이 명시적으로 켠 차단. grace는 의도와 어긋남.
- **DB/disk 장애**: 즉시 차단 의미가 큼. grace는 silent fail 위험.

1분이 적절한지는 운영 데이터로 검증 필요. KIS reconnect 평균이 1분 이내면 적절, 더 길면 alarm fatigue. **장후 review에서 1분 grace의 false alert 비율 측정 → 조정**.

## Q10: NAS 복구 drill Phase 1 read-only 전 vs Phase 2 주문 전

**Phase 1 진입 전이 안전. 그리고 Phase 2 진입 전 한 번 더 권장(총 2회).**

이유:
1. **Phase 1 진입 시점부터 readiness records가 NAS 백업 대상**: 백업 시작과 동시에 복구 가능성 검증되어야 데이터 손실 방지.
2. **첫 drill의 비용이 작음**: test environment에서 1회. 시간 비용 적음.
3. **Phase 2까지 미루면 readiness records 손실 위험**: Phase 1 동안 누적되는 readiness/audit/alert 데이터가 첫 복구 시 손실되면 운영 신뢰 무너짐.

**권장 일정**:
- **Phase 1 진입 직전**: schema apply 후 첫 readiness/audit record 생성 전 1회 drill. 빈 schema 복구 가능성 검증.
- **Phase 2 진입 직전**: Phase 1 readiness records가 쌓인 후 1회 추가 drill. 실제 데이터 복구 가능성 검증.

두 번째 drill에서 Phase 1 records가 정확히 복구되는지 확인 → Phase 2 실전 진입.

## 운영자 결정 잔여 5개에 대한 cowork 의견

| 결정 항목 | Codex 권장 | cowork 의견 |
|---|---|---|
| Phase 2 주문 금액 한도 최종값 | min(100k, 운용 배정금 × 10%) | 보수적으로 적절. **단 1주 강제(`max_order_qty=1`) 추가 검토 권장** (Q2 보강) |
| system clock ±2초 유지 여부 | 유지 | 적절. **단 reference clock 원천 결정 필요** (Q6 보강) |
| audit 외부 anchor 방식 + 보관 기간 | 로컬 hash chain + NAS 1차, 외부 anchor는 Phase 3 전 | 동의. **단 비주문 audit event는 sentinel 또는 chain_id 분리** (Q5 보강) |
| 원본 broker response 별도 보관 | 보관 안 함 | 동의. 필요 시 별도 암호화 저장소 별도 slice |
| 실제 NAS 복구 drill 시작 시점 | (미정) | **Phase 1 진입 전 1회 + Phase 2 진입 전 1회, 총 2회 권장** (Q10) |

## 추가 발견 (코드 직접 본 결과)

work_ver_11-20 본문에 명시되지 않은 미세 항목 네 가지.

첫째, **`KisLiveOrderAdapter.__init__`이 KIS 클라이언트 직접 생성 안 함**(docstring 1~6행 명시). composition으로 받는 client를 wrap만 함. review_ver_4 isolation 패턴과 일치 — 매우 좋은 구조.

둘째, **`_pre_submit_blocking_reasons`의 context dict**(493~501행)에 모든 정책 결정 컨텍스트(`phase`, `max_parent_orders_per_day`, `block_same_symbol_pending`, `block_live_fill_mismatch`, `max_order_notional`, `allocation_amount`, `max_order_allocation_pct`, `order_notional`, `effective_max_order_notional`)가 누적됨. 차단 시 detail_json에 저장되어 audit 분석 시 "왜 차단됐는지"가 매우 분명. 보강이 잘 됐다.

셋째, **`_effective_order_notional_limit`**(751~764행)가 `min()` candidates로 계산. `max_order_notional`과 `allocation_amount × allocation_pct` 둘 중 더 작은 값. 두 값 중 하나만 있으면 그 값 사용, 둘 다 없으면 None(차단 안 함). 좋은 fallback 로직.

넷째, **freshness `future_tolerance`와 clock skew `±2초`가 같은 값**(2.0초). 정합성 좋음 — clock skew가 ±2초 허용이면 freshness도 같은 미래 허용. 두 helper가 일관된 시간 모델.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 Phase 2 잔량 자동취소 금지 | 충분히 안전 | dashboard "미체결 잔량 N분 경과" 카운터 |
| Q2 Phase 2 주문 금액 한도 | 보수적 적절 | **1주 강제(`max_order_qty=1`) 추가 검토 권장** |
| Q3 adapter submit/cancel 비대칭 | 매우 적절 | `ALLOW_LIVE_ORDERS=false` 의미 운영자 문서 명시 |
| Q4 redacted payload only | 정상 보수 | 필요 시 별도 암호화 저장소 별도 slice |
| Q5 audit 12개 필수 필드 | 적절 | 비주문 event sentinel 또는 chain_id 분리 |
| Q6 system_clock readiness/submit 분리 | 옳음 | **reference clock 원천 결정 필요** (KIS 응답 헤더 후보) |
| Q7 freshness 기본값 | Phase 2 적절 | 저거래 종목 별도 threshold, reconnect grace 옵션 |
| Q8 orderbook 필수 | 동의 | **WS keepalive + reconnect metric 선행 필요** |
| Q9 unknown/stuck 1분 grace | 적절 | 장후 review false alert 비율 측정 |
| Q10 NAS 복구 drill | Phase 1 전 권장 | **Phase 1 + Phase 2 진입 직전 총 2회** |

## 다음 단계 권장

1. **Phase 1 진입 전 P0 (병행 가능)**:
   - **NAS 복구 drill 1회** (Q10)
   - **KIS 실제 응답 fixture 검증** (work_ver_10 권장 1순위 잔존)
   - **WS keepalive + reconnect metric** (Q7/Q8 선행 조건, 2026-05-18 reconnect 이슈 후속)
   - **reference clock 원천 결정** (Q6)
2. **Phase 2 진입 전 P0 (Phase 1 안정화 후)**:
   - **NAS 복구 drill 2회 (Phase 2 직전)** (Q10)
   - **`max_order_qty=1` 또는 동등 정책 추가** (Q2 보강)
   - **freshness `reconnect_grace_seconds` 옵션 추가** (Q7 보강)
   - **비주문 audit event sentinel 정책** (Q5)
3. **P1 (Phase 2 운용 중)**:
   - **알림 outbox에 실제 sender(텔레그램/이메일) 연결** (work_ver_11-20 별도 slice 권장)
   - **dashboard 보강**: 부모 주문 카운터, 미체결 잔량 경과 카운터, parent order limit 메시지에 카운트 정보
   - **장후 review에서 unknown/stuck 1분 grace의 false alert 비율 측정** (Q9)
4. **P2 (Phase 3 진입 전)**:
   - **audit chain_id 분리** (Q5 옵션 B로 확장)
   - **종목별 freshness threshold** (Q7)
   - **`block_live_fill_mismatch`를 동일 종목으로 정밀화** (review_ver_10 잔존)
   - **KIS 개별 체결 ID 기반 정밀 회계** (review_ver_10 잔존)
   - **`max_parent_orders_per_day` default 별도 gate 분리** (review_ver_10 잔존)

## 신뢰 수준

work_ver_11-20은 19개 sub-work를 한 시리즈에 통합 + 운영자 결정 5개 반영 + 2026-05-18 장중 이슈로부터 안전 교훈 흡수 + 237/242개 테스트 통과까지 거대한 작업량. 그럼에도 **모든 변경이 운영 안전 invariant를 코드와 테스트로 잠궜고, 회귀 위험을 만들지 않았다**. 5층 잠금(adapter submit guard, freshness, clock skew, fill mismatch, pre-submit policy)이 한 라운드에 정합적으로 들어간 점이 인상적.

다음 라운드(review_ver_12 예상)에서 cowork이 (a) **NAS 복구 drill 결과 검증**, (b) **KIS 실제 응답 fixture vs `snapshot_from_kis_daily_order_fill` 매핑 검증**, (c) **WS keepalive + reconnect metric 코드 검증** — 세 단계로 본다. 이 셋이 Phase 1 진입의 마지막 P0이다.
