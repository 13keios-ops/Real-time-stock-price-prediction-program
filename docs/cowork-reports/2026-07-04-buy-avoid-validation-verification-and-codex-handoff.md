# buy-avoid 방법론 리뷰(review_ver_23) 2차 검증 + Codex 전달 자료

작성 시각: 2026-07-04 KST (2차 검증 세션)
작성자: cowork(Claude)
대상: `2026-07-04-buy-avoid-validation-methodology-review.md`(review_ver_23)의 전 수치 재검증
목적: Codex가 다음 라운드(work_ver_23)에서 정확한 근거로 작업할 수 있도록 검증 완료된 사실만 정리

---

## 1. 검증 방법

review_ver_23이 인용한 모든 원자료 파일을 정본 저장소에서 직접 열어 수치를 1건씩 대조했다. 산수(무작위 대조군 기대치)는 독립적으로 재계산했다.

## 2. 검증 결과 종합표

| # | review_ver_23 주장 | 원자료 | 판정 |
|---|---|---|---|
| 1 | walk-forward id `walk-forward-h15-20260704201528027664`, three_class_accuracy 0.416342 | `runtime-data/reports/backtests/latest-walk-forward-h15.json` (evaluation_id 일치, 0.41634169) | ✅ 일치 |
| 2 | challenger `keep_active`, promotion 없음, gate 사유 "accuracy too low (0.4163)" | `runtime-data/reports/challengers/leaderboard-h15.json` | ✅ 일치 |
| 3 | mismatch_count=5, 종목 005380/035420/086520/105560/247540 | `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json` | ✅ 일치 |
| 4 | live-readiness status=blocked, 차단 사유 token_refresh/account_snapshot/system_clock | `runtime-data/reports/live-readiness/latest-readiness.json` (blocking_reasons 3건 일치) | ✅ 일치 |
| 5 | threshold 0.40 baseline: 25,198건 / -0.1063% / -2,679.60%p / 승률 39.94% | `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json` | ✅ 일치 |
| 6 | skipped: 6,694건 / -0.0727% / -486.38%p / 승률 42.67% (=2,856/6,694) | 같은 파일 | ✅ 일치 |
| 7 | filtered: 18,504건 / -0.1185% / -2,193.23%p / 승률 38.95% | 같은 파일 | ✅ 일치 |
| 8 | skip 비율 26.66% | 같은 파일 `coverage_rate`=0.265656 | ❌ **26.57%가 맞음** — 원문 정정 완료 |
| 9 | 무작위 대조군 산수: 기대 회피 -711.85%p, 기대 잔존 -1,967.75%p, 실제 잔존이 약 225%p 더 나쁨 | 독립 재계산 (6,694×0.10634=711.85 / 2,679.60-711.85=1,967.75 / 2,193.23-1,967.75=225.48) | ✅ 산수 정확 |
| 10 | Cybos 0.3665: baseline 7,807건 / -538.04%p, skipped 2,824건 / -367.72%p | `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json` (net_improvement_pct=367.715) | ✅ 일치 |
| 11 | Cybos 무작위 기대 회피 -194.61%p → 실제(-367.72)가 더 나쁜 거래를 골라냄 = 필터 정상 작동 | 독립 재계산 (538.04/7,807=0.0689%, 2,824×0.0689=194.6) | ✅ 산수 정확 |
| 12 | `trade_cost_pct=0.108%` (KIS shadow) | shadow JSON 필드 | ✅ 일치 |
| 13 | `latest-cybos-regime-performance-h15.json` 존재, high_vol이 가장 취약 + buy-avoid 효과 최대 | 해당 파일: high_vol accuracy 0.4672(최저), buy_net -435.71(최악), delta 220.79(최대) | ✅ 일치 |
| 14 | 전이성 진단 source_stable_candidate 0개 | `runtime-data/reports/research/latest-cybos-kis-transfer-review.md` (후보 2건 모두 `regime_avoid_watch`) | ✅ 일치 |
| 15 | "무작위 대조군 비교를 한 번도 안 했다" | `scripts/summarize_lightgbm_defensive_shadow.py`, `scripts/summarize_cybos_buy_avoid_proxy.py` — random/shuffle/seed 코드 없음 | ✅ 사실 |

**결론: review_ver_23의 핵심 주장("KIS live에서 buy-avoid 필터가 무작위 제거보다 약 225%p 못하다")은 원자료 기준으로 정확하다.** 유일한 오류는 skip 비율 표기(26.66→26.57%)였고 결론에 영향 없다. 원문은 정정 완료.

## 3. 검증 중 발견한 추가 뉘앙스 (Codex가 알아야 할 것)

1. **Cybos proxy와 KIS shadow는 방법론이 다르다 — 직접 비교에 주의.**
   - KIS shadow: 고정 threshold 0.40 + `require_down_argmax`, trade_cost 0.108%.
   - Cybos proxy: fold별 calibration으로 target skip rate(0.3665)에 맞춰 threshold를 매번 다시 잡음(fold별 0.13~0.29), trade_cost 0.13%, baseline도 runtime baseline이 아니라 "LightGBM self-filter 후보군(prob_up≥0.58)".
   - 따라서 "Cybos에서는 됐는데 KIS에서는 안 된다"는 대조는 방향성 참고용이지 동일 조건 비교가 아니다. 무작위 대조군 필드를 추가할 때 **두 리포트 모두** 같은 정의로 넣어야 이 대조가 비로소 공정해진다.

2. **live-readiness의 KIS 실패는 fault-injection dry-run 경로로 기록된 것.**
   - `latest-readiness.json`은 `job_type=live-readiness-fault-dry-run`, `source=fixture-dry-run`이고, 실패 증거는 `local-fixture-snapshot.json`에 담긴 실제 KIS read-only probe의 `KisApiError` 결과다. 즉 "실제 probe 실패 → fixture 스냅샷 → dry-run 소비" 구조. work_ver_22의 서술은 맞지만, 리포트만 보면 합성 장애로 오해할 수 있으니 다음 리포트부터 "실제 probe 실패 증거 기반"임을 명기할 것.

3. **무작위 대조군 산수의 한계.**
   - 위 계산은 기댓값 1점 비교다. 결론의 부호(무작위보다 나쁨)는 225%p 차이라 뒤집히기 어렵지만, 유의성(z-score)은 실제 시뮬레이션 분포가 있어야 말할 수 있다. 아래 P0가 그 작업이다.

## 4. Codex 지시 (다음 work_ver)

### P0 — 무작위 대조군 구현 → **cowork가 2026-07-04 직접 구현 완료. Codex는 구현하지 말고 아래 "실행·검증"만 수행할 것**

구현 내역 (모두 커밋 전 상태로 저장소에 반영됨):

| 파일 | 내용 |
|---|---|
| `scripts/buy_avoid_random_control.py` | **신규.** 공용 모듈: 해석적 기대값/분산(비복원 유한모집단 보정) + seed 고정 100회 시뮬레이션 + self-check + z-score + verdict + fold 집계 |
| `scripts/summarize_lightgbm_defensive_shadow.py` | threshold 블록마다 `random_control` 필드, `buy_avoid_shadow.random_control_gate`(fail-closed), markdown에 Random Control 섹션, Interpretation 문구 격하 |
| `scripts/summarize_cybos_buy_avoid_proxy.py` | fold별 target_result마다 `random_control`, target summary마다 `random_control_aggregate`, markdown에 Random Control 섹션 |
| `tests/test_buy_avoid_random_control.py` | **신규.** DB 없이 도는 수식 검증(조합론적 엄밀값 대조, 부호 규약, 방향성, 집계, shadow 통합) |
| `docs/Buy-Avoid-Random-Control-Methodology.md` | **신규. 방법론 단일 기준 문서. buy-avoid 코드를 만지기 전 필독.** 공식, 부호 규약, seed, 회귀 anchor, 체크리스트 |

**Codex가 해야 할 일 (구현 아님, 실행과 검증):**
1. `python3 -m pytest tests/test_buy_avoid_random_control.py tests/test_lightgbm_defensive_shadow.py tests/test_cybos_buy_avoid_proxy.py -q` → 전부 통과 확인. **cowork 환경에서는 이 테스트를 실행할 수 없었으므로(sandbox가 WSL 경로 접근 불가) 이 실행이 첫 검증이다. 실패하면 고치되, 수식은 방법론 문서 §2 기준으로만 고칠 것.**
2. `scripts/summarize_lightgbm_defensive_shadow.py` 재실행 → 새 JSON의 threshold 0.40 `random_control`을 방법론 문서 §7 anchor와 대조.
3. Cybos proxy 재생성(장시간 학습이 필요하면 다음 정기 재생성 때) → `random_control_aggregate` 부호 확인 (excess < 0 기대).
4. 결과를 work_ver에 기록. 공식·seed·부호 규약 변경 금지 (변경 절차는 방법론 문서 §0).

### P1 — 표현 격하 및 소급 정리
- `random_control_gate.passed=true`가 확인되기 전까지, 문서·리포트에서 buy-avoid를 "손실 축소 후보 유지"로 표현하지 말고 **"재검증 필요, 무작위 대조군 대비 우위 미확인"**으로 통일. (KIS 0.40은 anchor상 passed=false로 나와야 정상)
- 기존 문서(SPRINT_CURRENT, plan 문서 등)에서 buy-avoid를 후보로 언급한 부분을 위 문구로 갱신.

### P2 — 후속 실험 (순서대로)
1. IC(Spearman rank correlation: `probability_down` vs 실제 미래수익률) 계산 필드 추가.
2. EV 기반 필터(3클래스 확률 가중 기댓값 - cost) 실험.
3. regime 조건부(high_vol 한정) 필터 실험 — 근거: `latest-cybos-regime-performance-h15.json`.
4. 07-04~07-18 관측 구간에서 "down 신호가 오히려 나은 거래를 가리키는" 역설 패턴 재현 여부 확인(재현 전 방향 전환 금지).

### 금지선 (기존과 동일)
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 임계값 수정 금지.
- 모델 승격/주문 정책 변경 금지 — 이번 작업은 전부 리포트/진단 코드 추가다.
- 자동 commit/push 금지.

## 5. 이번 세션에서 cowork가 저장소에 가한 변경

### 1차 (검증 세션)
1. `docs/cowork-reports/2026-07-04-buy-avoid-validation-methodology-review.md`
   - skip 비율 26.66% → 26.57% 정정(2곳) + 정정 각주 추가, 오타 수정("때만"→"때문에"), 문서 말미에 "6. 검증 이력" 절 추가.
2. `docs/cowork-reports/2026-07-04-buy-avoid-validation-verification-and-codex-handoff.md` (이 파일) 신규 생성.

### 2차 (직접 구현 세션, 같은 날)
3. `scripts/buy_avoid_random_control.py` 신규 — 무작위 대조군 공용 모듈.
4. `scripts/summarize_lightgbm_defensive_shadow.py` 수정 — `random_control` + `random_control_gate` + markdown 섹션. 기존 필드/`status` 문자열은 불변(하위 소비자 호환).
5. `scripts/summarize_cybos_buy_avoid_proxy.py` 수정 — fold별 `random_control` + `random_control_aggregate` + markdown 섹션. 기존 conclusion 문자열 불변.
6. `tests/test_buy_avoid_random_control.py` 신규 — DB 불필요 수식 검증 테스트.
7. `docs/Buy-Avoid-Random-Control-Methodology.md` 신규 — 방법론 단일 기준 문서.
8. 이 파일 §4 갱신 (P0 구현 완료 반영).

공통: `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 임계값, 리포트 JSON(runtime-data) 일절 미접촉. commit/push 없음.

**한계 고지: cowork sandbox가 WSL 저장소 경로에서 코드를 실행할 수 없어, 위 코드는 정적 검토만 거쳤고 실행 검증은 되지 않았다. 그래서 DB 없이 도는 테스트를 함께 만들어 두었다 — Codex(또는 운영자)가 §4의 pytest 명령을 첫 번째로 실행해야 한다.**
