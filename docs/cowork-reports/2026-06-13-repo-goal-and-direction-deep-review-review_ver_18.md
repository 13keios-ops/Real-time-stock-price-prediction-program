# repo-goal-and-direction deep review review_ver_18

작성 시각: 2026-06-13 KST
작성자: cowork(Claude)
직전 기준: `review_ver_17` (2026-06-12) → Codex 6-13 작업 2건 반영

---

## 1. 검증 요약: "장중에 할 일만 남았다"는 주장은 사실인가?

**결론: 부분 사실 — 주요 장외 항목은 처리됐지만 미착수 장외 항목이 여전히 존재한다.**

Codex가 2026-06-13에 review_ver_17의 P1 장외 항목 대부분을 성실하게 처리한 것은 사실이다. 그러나 아래 두 항목은 장외에서 가능한데 미착수 상태로 남아 있다.

- runtime scope minute-bar 전환 후 수집 장애 감지 민감도 점검
- work_ver_18 통합본 미생성 (진행판에 "아직 생성하지 않았다" 명시)

따라서 "장중에 할 일만 남았다"는 표현은 과장이다.

---

## 2. 6-13 Codex 작업 2건 검증

### 작업 1: review_ver_17 비판적 반영과 원장 추적 리포트

| review_ver_17 항목 | Codex 주장 | 검증 결과 | 판정 |
|---|---|---|---|
| 5종목 only_local mismatch 원장 추적 | `trace_paper_kis_mismatch.py` 추가, mismatch trace 리포트 생성 | `latest-paper-kis-mismatch-trace.json` (generated_at=2026-06-13T13:25:26) 확인. 4종목 `only_local`, 원인 `close_order_fill_unknown_due_rate_limit`으로 분류 | **완료** (원인 분류까지. 실제 체결 확인은 rate_limit 해소 후) |
| 373220 원장 추적 | trace에 포함 | `mismatch_rows`에 373220(1주, avg 401,132원) 포함 확인 | **완료** |
| gate walk-forward 극단 fold(0.118, 0.144) 분석 | `summarize_walk_forward_extreme_folds.py` + `analyze_walk_forward_extreme_fold_regimes.py` 추가 | `latest-walk-forward-extreme-folds-h15.json`, `latest-walk-forward-extreme-fold-regimes-h15.json` 확인. fold 5/12/11 → flat 비중 0.77/0.74/0.72 + flat hit rate 붕괴 + 고변동 구간 특성 분석 완료 | **완료** |
| Execution-Plan.md 보강 (plan B, 데이터 최소 기준 등) | plan B, KIS live 데이터 축적 최소 기준, mismatch 시간 격상 기준, lineage 용량/아카이브 설계 추가 | logbook에 "보강했다" 기록. 파일 직접 확인은 금번 리뷰 범위 밖이나 logbook 기술이 구체적 | **주장 일치** |
| data quality watch 반복 원인 기록 | "수집 누락 보완 아닌 데이터 다양성 확보 목적"으로 정리 | 진행판 108~113행에 동일 문구 확인 | **완료** (방향 정리됨. 구체 날짜별 원인은 별도) |
| KIS 포털 공식 호출 제한 수치 확인 | KIS-Connection-Runbook.md에 "구체 수치 로그인/동적 UI 또는 지원 채널 확인 필요" 기록 | logbook 73행에 구체 내용 기록됨. 공개 HTML 확인 한계 인정하고 미확인 상태를 정직하게 기재한 것은 올바른 처리 | **완료** (공개 접근 한계 내에서) |
| LightGBM 방어 신호/shadow 분석 (plan B 첫 결과) | defensive candidates, defensive shadow 리포트 생성 | `latest-lightgbm-defensive-signal-candidates-h15.json`, `latest-lightgbm-defensive-shadow-h15.json` 확인. buy-avoid down threshold 0.40에서 +114.8%p delta 확인, 조기청산은 악화 | **완료** |
| runtime scope minute-bar 전환 후 수집 장애 감지 점검 | logbook 어디에도 언급 없음 | 미착수 | **미착수 (장외 가능)** |

### 작업 2: 장외 정합성 / Phase 1a readiness 마무리

| 항목 | 검증 결과 | 판정 |
|---|---|---|
| broker paper sync 장외 재시도 | 2분 내 미완료, 시작한 프로세스만 정리. 동일 endpoint 반복 호출 안 함 | 올바른 판단 |
| reconcile-paper-accounts | 4종목 local-only 유지, `needs_review` 확인됨 | **일치** |
| dashboard + watchdog 재기동 | 진행판 2-섹션 "runtime watchdog: running, fresh / dashboard: running" 확인 | **일치** |
| Phase 1a readiness 최신화 | `latest-readiness.json` generated_at=2026-06-13T13:34:06, status=ok 확인 | **완료** |
| holiday-before-weekend ordering 버그 수정 | logbook 76행 `common_process_helpers.sh` 수정 기록, 테스트 7개 통과 | **완료** |
| work_ver_18 통합본 생성 | 진행판 30~32행: "아직 별도 work_ver_18로 생성하지 않았다" | **미착수 (장외 가능)** |

---

## 3. 현재 상태 종합 (2026-06-13 13:35 기준)

### Phase 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| Phase 0 | 진행 중 | local-only 4종목 needs_review 유지 |
| Phase 1a | 1차 리허설 통과 | readiness 최신화 완료, status=ok |
| Phase 1b | 대기 | live credentials 미준비 |
| Phase 2/3 | 미시작 | - |

### runtime 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| live runtime | 정지 (weekend 정상) | logbook 시작 상태 |
| watchdog | running | 진행판 확인 |
| dashboard | running | http://127.0.0.1:8765 응답 |
| broker sync | rate_limited, open order 5건 | latest-sync.json synced_at=2026-06-12T17:29:39 |

### 모델 상태

| 항목 | 상태 |
|---|---|
| active model | baseline-h15-v1, keep_active |
| LightGBM challenger | independent_challenger_holdout 자격 회복, 매수 신호 0건, 승격 불가 |
| gate walk-forward | needs_review (3class=0.4163) |
| buy-signal diagnostics | no_positive_expected_value_threshold |
| label band 재현성 | 0.35/0.40/0.50 전부 not_reproducible 또는 not_period_reproducible |
| plan B defensive | buy-avoid 후보 유효, early-exit 보류 |

---

## 4. Codex 주장 "장중에 할 일만 남았다" — 항목별 분류

### 진짜 장중에만 가능한 항목 (2건)

1. **watchdog heartbeat 10분 이내 유지 실측**
   다음 거래일 09:00~15:30 중 `last_checked_at` 갱신 간격이 10분 이내인지 read-only 관측.
   → **장중에만 가능, Codex 주장 타당**

2. **장후 EGW00201 재발 여부 실측**
   다음 거래일 장후 order-fill sync에서 rate-limit이 재발하는지, 2시간 cooldown이 충분한지 판정.
   → **다음 거래일 장후에 가능**

### 장외에서 가능하지만 미착수인 항목 (2건) — Codex 주장 반박 근거

1. **runtime scope minute-bar 전환 후 수집 장애 감지 민감도 점검** ← **장외 가능, 미착수**
   `build_runtime_scope()`가 `curated_minute_bars` 기반으로 바뀐 뒤, bar builder 자체 장애 구간에서 수집 이상이 대시보드 경고에 잡히는지 테스트 1회가 필요하다. 장이 열리지 않아도 테스트 실행 가능.

2. **work_ver_18 통합본 작성** ← **장외 가능, 미착수**
   진행판이 "아직 생성하지 않았다"고 명시하고 있다. 6-13 작업 2건(원장 추적, plan B 첫 결과, Phase 1a readiness)이 묶인 상태로 통합 리포트가 없으면 다음 라운드에서 cowork가 baseline으로 쓸 Codex 자체 요약이 없다.

### 장외 가능 + 외부 의존 (사용자/시스템 협력 필요)

- **4종목 local-only 체결 상태 최종 확인**: broker sync `rate_limited` cooldown(2시간) 해소 후 order-fill 1회 재확인. 6-13 장외 재시도가 2분 내 완료 안 됐으므로 주말에 조용히 풀릴 가능성 있음. Codex가 감지하면 재시도 가능.
- **KIS 포털 공식 호출 제한 수치**: 로그인/동적 UI 필요 — 운영자 직접 확인이 필요.

---

## 5. P0 (다음 거래일 필수)

### P0-4. 장중 watchdog heartbeat 유지 확인 (진짜 장중 필요)
- 다음 거래일 정규장 중(예: 10시, 14시) watchdog `last_checked_at` 간격이 10분 이내인지 read-only 확인.
- live runtime이 정상 기동됐는지, 수집이 dashboard에 반영되는지 확인.
- 세션 종료와 무관하게 살아남는지(setsid/nohup/Windows 스케줄러) 확인.
- 수용 기준: 정규장 1일치 이상 watchdog fresh 상태 유지 증거.

### P0-broker. 다음 거래일 장후 EGW00201 재발 여부 확인
- 2시간 cooldown guard가 실제로 장후 order-fill 재발을 막는지 첫 실측.
- 재발 시: 장후 일괄 조회 호출량 자체를 줄이는 설계 변경 필요.
- 재발 없음 시: cooldown guard 정상 동작 확인.

---

## 6. P1 (장외 가능, 우선도 순)

### P1-1. runtime scope 수집 장애 감지 민감도 점검 ← 미착수
- `build_runtime_scope()`가 `curated_minute_bars` 기반으로 바뀐 후, bar builder 중단 구간이 경고에 잡히는지 1회 테스트.
- bar 생성이 멈춰도 scope 크기가 줄어들지 않으면 수집 이상을 탐지 못할 수 있다.

### P1-2. work_ver_18 통합본 작성 ← 미착수
- 6-13 두 작업의 결과(원장 추적 분류, 극단 fold 장세 분석, defensive shadow 결과, Phase 1a readiness 갱신)를 work_ver_18 형식으로 생성.
- 이 리뷰(review_ver_18)를 Codex에 전달하면서 동시에 요청한다.

### P1-3. 4종목 local-only 체결 상태 확인
- broker sync cooldown이 자동 만료되면 order-fill 1회 재확인.
- 005380(1주), 035420(2주), 247540(4주), 373220(1주) 각 종목의 최신 sell close 주문 `submitted`가 체결됐는지 확인.
- 브로커 보유가 여전히 0이면 marker-only alignment 전에 원인 명시 필요.

### P1-4. data quality watch 반복 구체 원인 기록
- 2026-06-05/08/09 watch 사례의 어떤 종목·시간대에서 coverage 미달이 발생했는지 과거 리포트에서 확인해 기록.
- 현재 "다양성 목적"으로 정리됐지만 구체 날짜별 원인이 없어 재발 시 비교 기준이 없다.

---

## 7. 알파 연구 트랙 현황 (장외 독립적으로 진행 가능)

review_ver_17에서 지적한 모델 트랙 현황은 아래와 같이 유지된다.

- LightGBM challenger: 심사 자격은 회복(`independent_challenger_holdout`)됐으나 매수 신호 0건, gate needs_review — 승격 불가.
- plan B 방어 신호: buy-avoid down 0.40 threshold에서 +114.8%p delta 확인 → shadow 검증 단계로 넘어갈 첫 단서 있음. 단, 이것은 back-tested 연구 결과이며 승격 근거가 아니다.
- 모델 성능 개선 경로: 피처 확장, 보합 라벨 분리 (flat 비중 0.77인 fold에서 flat hit rate 0.006 붕괴 확인), LightGBM calibration. 이 중 어느 것도 다음 거래일 장중에만 가능한 항목이 아니다.

---

## 8. 운영자 결정 요청

1. **work_ver_18 통합본**: 이번 리뷰를 Codex에 전달할 때 6-13 작업 결과를 work_ver_18 형식으로 함께 생성할지 지시한다.
2. **plan B shadow 검증 승인**: buy-avoid 후보(down 0.40)를 paper 런타임에서 shadow로 기록 시작할지 결정. 실제 매수 거부 실행이 아닌 관찰 전용.
3. **4종목 mismatch marker-only alignment 기준**: 브로커 체결 확인이 안 된 상태에서 다음 거래일 시작 전 alignment를 적용할지, 체결 확인 후로 미룰지 결정.

---

## 9. 신뢰 수준

6-13 Codex 작업 2건의 주장-실제 일치율: **높음**. 검증 가능한 항목(trace JSON, extreme fold JSON, defensive shadow JSON, readiness JSON, logbook 기술) 전건이 진술과 일치한다.

"장중에 할 일만 남았다"는 주장의 정확도: **부분 거짓**. runtime scope 감지 점검(P1-1)과 work_ver_18 통합본(P1-2)은 장외에서 가능하지만 미착수다. 장중에만 가능한 핵심 항목은 watchdog heartbeat 실측 1건뿐이며, 나머지는 장외 또는 장후 가능하다.

다음 cowork 리뷰 권장 시점: **다음 거래일 장후** — P0-broker(EGW00201 재발), P0-4(watchdog 심박) 실측 결과 + work_ver_18 통합본 전달 시점.
