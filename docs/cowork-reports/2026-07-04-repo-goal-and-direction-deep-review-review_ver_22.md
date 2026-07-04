# repo-goal-and-direction deep review review_ver_22

작성 시각: 2026-07-04 KST
작성자: cowork(Claude)
직전 기준: `review_ver_21` (2026-06-14) → 2026-06-15~07-03 약 3주치 미검토 작업 종합 검증

---

## 0. 중요 공지: 3주 리뷰 공백

`docs/cowork-reports/`에 2026-06-15~2026-07-03 사이 날짜의 리뷰 요청 파일이 하나도 없다. Codex가 이 기간 동안 cowork에 리뷰를 요청하지 않고 작업을 계속 쌓았다. 리뷰가 놓친 게 아니라 애초에 요청 자체가 생성되지 않았다.

이번 review_ver_22는 이 공백을 메우기 위해 logbook.md, Production-Transition-Progress.md, 최신 runtime 리포트를 직접 대조해서 검증했다.

---

## 1. 검증 요약 (3주치 핵심 이벤트)

| 시점 | 작업 | 판정 |
|---|---|---|
| 06-17~06-19 | hold-rescue paper replay feasibility → 본 replay 구현 | **완료.** 판정 `diagnostic_only_no_hold_rescue_candidate`로 탈락 확정 |
| 06-19 | rescue/avoid 3종 동시 관측 자동화 기준을 AGENTS.md/skill에 반영 | **완료, 적절** |
| 06-27 | 주말 전체 점검, `.tmp-tests` 2.0G 정리, buy-avoid freshness 경고 자체 인지 | **완료, 정직한 자기 보고** |
| 07-03 | 모델 overlay 비교(LightGBM vs linear-score), Cybos-KIS 전이성 진단, meta-policy shadow, social signal shadow 4건 신규 구현 | **완료, 수치 확인** |

---

## 2. buy-avoid shadow — 실질적으로 가장 중요한 변화

**샘플이 목표치를 크게 초과했다.**

`latest-lightgbm-defensive-shadow-h15.json` (generated_at=2026-07-03T20:54:40):
- joined_rows: **25,198건** (기준 1,000건의 25배)
- 기간: 2026-06-11 ~ 2026-07-03 (약 22거래일, 기준 10거래일의 2배 이상)
- 종목: **10종목** (기준 5종목의 2배)
- threshold 0.4 회피 후보(skipped signals): **6,694건** (기준 200건의 33배)
- best_by_net_delta: net improvement **+486.38%p** (baseline -2679.60% → filtered -2193.23%)

**결론: 이전에 정의한 4개 사전 기준(연결표본 1,000건, 거래일 10일, 종목 5개, 회피후보 200건)을 전부 큰 폭으로 충족했다.**

**문제는 이 사실이 문서상 명시적으로 판정되지 않았다는 것이다.** 06-27 logbook에 "buy-avoid 최신 리포트는 06-23 기준이라 fresh evidence 부족"이라는 자기 인지가 있었는데, 이후 07-03까지 데이터는 계속 쌓았지만 "기준 충족 → walk-forward 재검증 실행"이라는 다음 단계로 넘어간 흔적이 없다. `latest-walk-forward-h15.json`은 여전히 `walk-forward-h15-20260612042842731771`, 06-12 생성물 그대로다.

**즉 재검증 조건은 이미 충족됐는데 재검증 자체가 실행되지 않았다.** 이건 Codex가 다음 지시를 스스로 만들지 못하고 새 곁가지 실험(overlay 비교, Cybos-KIS 전이성, meta-policy, social signal)으로 흘러간 것으로 보인다.

kept net이 여전히 -2193%로 깊은 음수인 점은 이전과 동일하다. 손실 축소 효과는 있지만 흑자 전환 근거는 아니다.

---

## 3. 07-03 신규 실험 4건 검증

### 모델 overlay 비교 (LightGBM vs linear-score)
`latest-model-overlay-comparison-h15.json`: since 06-11, 57,858 라벨행.
- LightGBM: 3분류 정확도 0.3509, buy-avoid best delta +560.8%p
- linear-score: 3분류 정확도 0.2788, buy-avoid best delta +1,966.2%p
- 조합 정책 `either_model_down_veto_0.40`: delta +2,046.7%p, 단 실행 row가 23,675건→5,818건(24.6%)으로 급감하는 강한 필터

평가: 두 모델 다 방향성 매수보다 회피 판정에서 강점을 보인다는 일관된 결론. `either_model_down_veto`는 방어력은 크지만 거래를 4분의 3 가까이 줄이는 필터라 실용성 검토가 더 필요하다. 진단 전용으로 남긴 판단은 적절하다.

### Cybos-KIS 전이성 진단
`latest-cybos-kis-transfer-review.json`: Cybos 20만행 vs KIS live 57,858행(16거래일) 비교.
- source_stable_candidate(양쪽에서 같은 방향 강신호): **0개**
- bid_ask_imbalance/spread_bps는 Cybos에 구조적으로 없어 KIS 전용 shadow 후보로만 분류

평가: 이 결과는 중요하다. Cybos 5년치와 KIS live 사이에 공통으로 신뢰할 수 있는 신호가 하나도 없다는 뜻이다. Cybos 백테스트 결과를 KIS live 전이 근거로 쓰면 안 된다는 이전 가드레일(`self_filter_proxy` 해석 제한)이 이 진단으로 다시 한번 뒷받침됐다.

### meta-policy shadow
정책 후보 비교 리포트. 모든 후보가 여전히 `policy_net_return_pct` 음수. `either_model_down_veto_0.40`이 개선폭은 가장 크지만 손익 자체는 -768.9%로 마이너스. 모든 플래그(active_model_change, gate_change, kis_live_shadow_expansion, paper_order_policy_change)가 false로 고정된 점은 안전 원칙을 지켰다.

### social signal shadow
`event_count=0`, `matched=0`, `status=no_events_file`. **사실상 미가동 상태다.** SNS 이벤트 파일 자체가 없어 인프라만 만들어놓고 실제 데이터 연동은 안 됐다. 사용자가 "SNS 실시간 추적도 검토해봐"라고 지시했던 항목인데, 지금은 뼈대만 있고 실질 검증은 0건이다.

---

## 4. 안전 제약 — 확인 방식의 한계 명시

3주간 모든 logbook 항목에 "app/risk/, config/, VERSION, ALLOW_LIVE_ORDERS, gate 기준값 변경 없음", "실전 주문/취소 없음"이 반복 기재되어 있다. 위반 흔적은 발견되지 않았다.

**단, 이것은 Codex의 자기 신고이지 cowork가 git diff나 파일 직접 대조로 독립 검증한 것이 아니다.** 이번 회차에서도 해당 파일들을 직접 열어 대조하지 않았다. 안전이 걸린 항목이므로 다음 리뷰에서는 `config/`, `app/risk/`, `VERSION`을 최근 3주 git 이력과 대조해 실제로 변경이 없었는지 직접 확인하는 것을 권장한다.

---

## 5. broker/reconciliation 상태 — 신선도 불일치

- `latest-sync.json` (broker paper sync): synced_at **2026-07-03T16:49:28**, status=ok, total_submissions=269, open_order_count=0 → 최신
- `latest-paper-kis-mismatch-trace.json`: generated_at **2026-06-14T05:37:05** → **3주 전 정체**
- `live-readiness/latest-readiness.json`: generated_at **2026-06-13T13:34:06** → **3주 전 정체**

broker sync 자체는 최신이지만 mismatch trace와 readiness 리포트가 갱신되지 않고 있다. 이 두 리포트가 실제로 stale한 건지, 아니면 최근 mismatch가 없어서 재생성할 계기가 없었던 건지 구분이 필요하다. 06-26 logbook에는 "dual-account match는 needs_review"라는 기록이 있어 최소 한 번은 재확인이 필요한 상태였는데 mismatch trace가 갱신 안 된 점이 걸린다.

---

## 6. Phase / active model 상태

- Phase 0~3 상태 변화 없음 (review_ver_21과 동일)
- active model 여전히 `baseline-h15-v1`, `keep_active`, `promotion applied=false`
- walk-forward gate 여전히 `needs_review` (06-12 리포트 그대로, 재실행 안 됨)
- 06-27 기준 top challenger `lightgbm-h15-v1`: 3분류 정확도 0.356, 실거래 표본 4건 — 표본 부족으로 승격 근거 아님(적절한 판단)

---

## 7. 이번 회차 종합 판단

**주장-실제 일치율: 높음.** logbook 기술과 실제 JSON 수치가 대부분 일치했다.

**가장 중요한 발견 2가지:**

1. **buy-avoid shadow 재검증 조건이 이미 충족됐는데 재검증이 실행되지 않았다.** 다음 지시로 명확히 넘겨야 한다.
2. **3주간 cowork 리뷰 요청 없이 작업이 누적됐다.** Codex가 곁가지 실험(overlay, transfer, meta-policy, social signal)을 계속 늘리는 동안 정작 예정된 체크포인트(10거래일 재검증)를 스스로 트리거하지 않았다. 이것은 "실험을 계속 늘리지 않는다"는 이전 가드레일과 배치되는 방향이다.

**social signal shadow는 사실상 빈 인프라다.** 이벤트 파일 연동이 안 됐으므로 다음 지시에서 "실제로 가동할지 여부"를 결정해야 한다. 지금처럼 두면 코드만 있고 쓰지 않는 죽은 기능이 된다.

---

## 8. 다음 조치 권장

**즉시 지시할 것:**
1. buy-avoid shadow 재검증 조건 충족 확인 및 walk-forward 재검증 실행 (현재 사용 가능한 25,198건, 22거래일, 10종목 데이터로 즉시 가능)
2. `latest-paper-kis-mismatch-trace.json`과 `live-readiness` 재생성 — 3주 정체 해소
3. social signal shadow: 실제 이벤트 연동 여부 결정 (가동 안 할 거면 인프라만 있는 상태임을 문서에 명시)

**cowork가 다음에 직접 확인할 것:**
- `config/`, `app/risk/`, `VERSION` git 이력 직접 대조 (자기 신고 검증)
- walk-forward 재검증 결과가 나오면 즉시 리뷰

**운영 습관 관련:**
Codex에게 앞으로는 예정된 체크포인트(예: N거래일 후 재검증)가 도래하면 새 실험을 늘리기 전에 그 체크포인트부터 먼저 처리하도록 지시하는 것을 권장한다.
