# repo-goal-and-direction deep review review_ver_21

작성 시각: 2026-06-14 KST  
작성자: cowork(Claude)  
직전 기준: `review_ver_20` (2026-06-13) → Codex 2026-06-14 전체 작업 검증

---

## 1. 검증 요약

| 작업 | Codex 주장 | 판정 |
|---|---|---|
| Step 0: BaselineDirectionModel Cybos 재현 불가 확인 | `bid_ask_imbalance`, `spread_bps` 누락 → `proxy_buy_rescue`로 고정 | **완료, 정확** |
| Cybos proxy buy-rescue 구현 + full 12 fold 실행 | rescue 0.05~0.30 전부 음수, 0/12 fold | **완료, 수치 확인** |
| buy-rescue precision review (0.001~0.05) | 가장 강한 후보도 거래당 순수익 -0.12%, 비용 0.13% 미달 | **완료, 수치 확인** |
| hold-rescue lifecycle synthetic helper 추가 | 함수 추가 + 테스트 4건, full fold 실행 아님 | **완료, 범위 정확** |
| 4종목 position mismatch 해소 | mismatch_count=0, assessment.status=ok | **완료, JSON 확인** |
| open order backlog 153건 해소 | open_order_count=0, effective cash gap 0원 | **완료, JSON 확인** |
| broker_paper_sync.py 상태 보존 보강 | KIS lookback 소멸 row → 이전 final 상태 보존 | **완료, 주의 필요** |
| 전체 테스트 412개 통과 | 진행판 기준 최신 | **확인** |

주장-실제 일치율: **높음.**

---

## 2. 모델 연구 트랙 결론

### buy-avoid — 계속 관찰 근거 있음

Cybos 5년치 proxy 기준:
- target skip 0.3665에서 12/12 fold 개선, net improvement +367.7%p
- 단, kept net은 여전히 음수. 손실 축소 후보이지 수익 창출 모델 아님
- 해석 제한 고정: `lightgbm_self_filter_buy_avoid_proxy` — runtime baseline 판단 재현 아님

→ KIS live buy-avoid shadow 10거래일 관측 유지 결정 타당.

### buy-rescue — 명확하게 탈락

결과:
- 넓은 grid (0.05~0.30): 모두 0/12 fold, 음수 net
- 정밀 grid (0.001~0.05): 가장 강한 상승 후보(0.001 coverage, 727건)도 거래당 평균 총수익 0.0055%, 순수익 -0.1245% → 0.13% 비용 미달
- 결론: "넓게 잡아서 실패"가 아니라 "가장 강한 상승 후보도 비용 초과 증거 없음"

이로써 이전 우려("LightGBM UP 신호 품질 미확인")가 Cybos 5년 데이터로 명확히 답변됐다.  
**KIS live buy-rescue shadow 추가 없음. 결정 타당.**

### hold-rescue — 설계 단계, 보류 유지

lifecycle helper 함수와 synthetic 테스트 4건이 추가됐다. full Cybos fold 실행은 하지 않았고, 계획 문서 기준 "별도 설계 선행" 원칙이 지켜졌다.

---

## 3. P0-broker 선행 해소 — 중요

이 부분이 이번 회차에서 가장 주목할 변화다.

**이전 상태 (review_ver_20 기준):**
- 4종목 local-only mismatch, 원인 `close_order_fill_unknown_due_rate_limit`
- open_order_count=0이었으나 6/12 rate limit 이후 잔여 추적 불확실

**현재 상태 (2026-06-14T05:37 기준):**
- `latest-paper-kis-mismatch-trace.json`: mismatch_count=0, assessment.status=ok
- `open_order_count=0`, `pending_symbols=[]`
- dual_account: position mismatch=0, effective cash gap=0원
- 남은 것: raw_cash_gap 29,991원 — dual account match 상태는 `matched_waiting_first_submission`

**의미:**
- 월요일 P0-broker 항목 중 "4종목 체결 상태 확인"은 이미 해소됐다.
- 단, 해소는 Codex가 주말에 직접 broker paper sync를 재실행해서 이뤄진 것이다.
- 월요일 장후 P0-broker 잔여 목표: **EGW00201 재발 여부 확인**. 이것은 장후 order-fill sync를 실제로 실행해봐야 알 수 있으므로 여전히 장후에 확인 필요하다.

---

## 4. 주의 항목 — broker_paper_sync.py 코드 변경

이번 작업에서 `app/services/broker_paper_sync.py`가 수정됐다. 이것은 production paper trading의 broker sync 로직이다.

변경 내용:
- 이전: KIS lookback에서 row가 사라지면 이전 final/applied 상태를 잃고 pending으로 되살아날 수 있었음
- 이후: 이전 final 상태 보존. 이전 체결이 주문 수량 덮으면 `filled`, 과거 주문일 잔량은 `expired`/`expired_partial`로 닫음

이 변경으로 153건 backlog가 해소됐고 관련 테스트 19건이 통과했다.

평가: 변경 방향은 타당하다. KIS lookback window에서 사라진 주문을 pending으로 되살리는 것이 더 위험하다. 단 한 가지 회귀 위험이 있다 — 당일 open 주문이 lookback에서 일시적으로 빠진 경우(KIS WS 일시 중단 등) 조기 final 처리될 수 있다. Codex가 "주문일과 조회 성공 여부를 기준으로 분기하고, rate-limit 조회 실패 경로에서는 pending 보존"이라고 명시한 것은 이 위험을 인지하고 처리한 것이다. 월요일 장중 실제 주문이 발생할 때 이 경로가 올바르게 작동하는지 관찰이 필요하다.

---

## 5. 현재 잔여 항목

### 월요일 P0 (변경 없음)

**P0-4. 장중 watchdog heartbeat 10분 이내 유지 실측**
- 4종목 position mismatch는 이미 해소됐으나, 이 항목은 살아있는 장중 runtime이 필요하다.

**P0-broker. 장후 EGW00201 재발 여부 확인**
- position mismatch는 해소됐다. 남은 것은 EGW00201이 월요일 장후에 재발하는지 여부다.
- 재발 없음: cooldown guard 정상 동작 확인 → Phase 0 blocker 해소.
- 재발 있음: 호출량 축소 설계 필요.

### 모델 연구 트랙

| 항목 | 상태 |
|---|---|
| buy-avoid KIS live shadow 10거래일 누적 | 진행 중 (월요일부터 카운트) |
| buy-rescue | 탈락 확정 — KIS live shadow 불필요 |
| hold-rescue | 보류 — Cybos lifecycle 설계 미완, full fold 미실행 |
| walk-forward 재검증 기준 | 이미 정의됨 (60k행, 30거래일, shadow 10거래일) |

### raw_cash_gap 29,991원

`matched_waiting_first_submission` 상태로 남아 있다. 이것은 Phase 0 blocker가 아니고 actual open position은 0이므로 지금 조치할 필요는 없다. 첫 실제 주문 제출 후 자연스럽게 정산되는 항목으로 판단한다.

---

## 6. 신뢰 수준

2026-06-14 Codex 작업 주장-실제 일치율: **높음.**

- mismatch trace JSON, rescue proxy JSON 수치가 logbook 기술과 일치
- buy-rescue 실패가 "넓은 grid 탓"이 아님을 정밀 grid로 재확인한 점은 연구 품질이 높다
- 계획 문서(cybos-rescue-experiment-plan.md)에서 정한 guardrail을 실제 실행에서 지켰다
- broker_paper_sync.py 변경은 적절하나 월요일 장중 관찰 필요

---

## 7. 다음 cowork 리뷰 권장 시점

**월요일 장후.**

전달 묶음:
- P0-4 장중 watchdog heartbeat 실측 결과
- P0-broker 장후 EGW00201 재발 여부
- broker_paper_sync.py 신규 경로가 실제 주문 처리에서 올바르게 작동했는지 확인
