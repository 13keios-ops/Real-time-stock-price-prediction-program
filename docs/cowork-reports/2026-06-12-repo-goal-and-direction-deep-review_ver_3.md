# 방향성 심층 리뷰 ver_3 — Codex 조치 재검증 + 다음 라운드 지시 통합본 (2026-06-12)

## 1. 버전 맥락

- topic: `repo-goal-and-direction-deep-review`
- 이 파일: `2026-06-12-repo-goal-and-direction-deep-review_ver_3.md` (구 ver_2 재검증 내용을 통합한 단일 정본. ver_2 파일은 이 파일로 대체됨)
- 기준: ver_1(2026-06-11 방향성 심층 리뷰, F-1~F-6) → Codex 6-12 조치(logbook `[2026-06-12] Codex -> cowork deep review 반영과 대시보드 scope 경량화`, work_ver 파일 없음) → 본 통합 리뷰
- 리뷰 방식: 조치 주장 전건을 정본 저장소 코드·리포트로 직접 검증 (`dashboard.py`, `broker_paper_sync.py`, `runtime_scope.py`, README, 진행판, `latest-challengers-h15.json`, `latest-kis-live-data-quality.json`, 테스트 파일)
- 작성자: cowork(Claude). 운영자(Keios) 확인 후 Codex 전달용.

## 2. 요약 (핵심 발견 3가지)

1. **Codex 6-12 조치는 주장-실제 일치율 100%** (검증 8건 전건 일치). F-2(지표 오독)·F-4(stale 문서)·F-6(+50% 문구) 닫힘, F-5 부분 닫힘. 실행 신뢰도는 높다.
2. **ver_1 최대 지적인 모델 트랙(F-1)은 여전히 미착수**이고, 운영자 인식("후보모델이 학습하며 승격 대기중")과 실제 상태(심사 자격 무효 + 매수 신호 0건 + 정본 게이트 리포트 구식 포맷, 3중 차단) 사이에 큰 차이가 확인됐다. 이번 라운드의 핵심은 모델 트랙 P0 격상이다.
3. **daemon 유지 문제**: 운영자 확인대로 장전/장후 자동화가 런타임 상태 체크와 프로세스 on/off, 장후 학습을 수행하므로 "아침 미기동" 위험은 닫는다. 남는 것은 장중 심박 유지 검증 1건이다(P0-4).

## 3. F-1~F-6 closure 매핑 (검증 결과)

| ver_1 발견 | Codex 조치 주장 | 검증 결과 | 판정 |
|---|---|---|---|
| F-1 알파 부족·작업 비중 불균형 | 미조치 (gate walk-forward 재생성도 WSL 불안정으로 재보류) | 보류 사실이 logbook에 정직하게 기록됨 | **열림 → 이번 라운드 P0** |
| F-2 virtual direction 오독 위험 | 대시보드에 `단순합산(연구용)` 표기 + 경고 고정 | `dashboard.py` 4603, 5078, 5084, 5401~5404행에서 `가상 방향 순수익률(단순합산)` 컬럼명과 "복리·실거래·포트폴리오 수익률이 아닙니다" 문구 확인 | **닫힘** |
| F-3 cowork 리뷰 루프 중단 | 진행판에 "6월 통합본 + deep review 반영 결과를 묶어 전달" 명시 | 진행판 갱신 확인. 통합 work_ver 파일은 아직 없음 | **부분** |
| F-4 stale readiness/진행판 | 진행판 2026-06-12 01:16 갱신, stale readiness "재사용하지 않는다" 명시 | 진행판 22~36행 확인 | **닫힘** |
| F-5a EGW00201 반복 | 30분 rate-limit cooldown guard 추가 | `broker_paper_sync.py`: `BATCH_ORDER_FILL_RATE_LIMIT_COOLDOWN_SECONDS=30.0*60.0`, `cooldown_active`/`skipped_broker_call`/`retry_after_seconds` 필드, `tests/test_broker_paper_sync.py` 존재 확인 | **부분** (4절 약점 1) |
| F-5b data quality watch 반복 | 보정: 최신은 ok | `latest-kis-live-data-quality.json`에서 `latest_trade_date=2026-06-11`, `status=ok` 직접 확인 — Codex 보정 타당. 과거 watch(6-05/08/09) 원인 추적은 미착수 | **부분** |
| F-5c 373220 local-only mismatch | 자동 정렬로 덮지 않고 원장 원인 추적하기로 보류 | 진행판에 `needs_review` 그대로 명시. 덮지 않은 판단은 옳음 | **열림** (의도적, P1) |
| F-6 월 +50% 문구 | README 1차 검증 목표(비용 반영 양수 기대값, 재현성, 최대낙폭, 연속손실, paper 안정성)로 교체, +50%는 stretch로 격하 | README 10행 확인 | **닫힘** |

## 4. 추가 발견 / 미세 약점

1. **cooldown guard는 봉합의 개선이지 근본 해결이 아니다.** 30분 내 동일 endpoint 재호출은 막지만 장후 일괄 조회 호출량 설계는 그대로다. 다음 거래일 장후 EGW00201 재발 여부가 실효성 판정 기준이다. 진행판 기준 open order 5건 + `rate_limited` 상태도 여전하다.
2. **runtime scope 변경의 의미 변화 확인 필요.** `build_runtime_scope()`를 raw tick 전체 그룹화에서 `curated_minute_bars` 기반으로 바꾼 것은 성능상 옳지만, bar builder 자체 장애 구간은 scope에서 보이지 않게 될 수 있다. 분봉 지연 경고가 이 scope를 참조한다면 감지 민감도 점검 1회가 필요하다.
3. **테스트 378개 통과는 logbook 주장으로, 이번 리뷰에서 실행 재현은 하지 않았다.** 신규 테스트 파일 2건(`test_runtime_scope.py`, `test_broker_paper_sync.py`) 존재는 확인했다.
4. **daemon 유지 관측.** dashboard·watchdog 모두 시작 JSON 후 `stale`로 떨어진 기록이 있다. 장전/장후 자동화가 매일 재기동하므로 심각도는 P0에서 한 단계 내리되, 장중에 watchdog이 죽으면 다음 자동 체크까지 수집 자동 복구 공백이 생기므로 장중 심박 유지 검증을 P0-4로 남긴다.

## 5. 모델 승격 상태 — 사실 정리 (운영자 인식 교정 포함)

`runtime-data/reports/challengers/latest-challengers-h15.json` (run `challenger-h15-20260611212023862868`) 기준:

| 항목 | LightGBM 후보 실측값 | 의미 |
|---|---|---|
| `promotable` | `false` | 승격 불가 |
| `evaluation_independence_status` | `holdout_window_mismatch` | 검증용 holdout 경계가 학습 후 데이터 추가로 바뀌어 평가 무효 (fail-safe 정상 동작) |
| `three_class_accuracy` | 0.3607 | 3분류 36.1% (active baseline 26.6%보다 높음) |
| `up_hit_rate` | 0.1675 | 실제 상승 5,701건 중 955건만 상승 예측. 매수 수익의 원천인 상승 포착이 약함 |
| `buy_signal_hit_rate` / `trades_taken` | 0.0 / 0 | 신뢰도 기준을 넘긴 매수 신호 0건 → 비용 차감 수익률 평가 자체가 비어 있음 |
| `virtual_direction_cumulative_net_return_pct` | 111.03 | 단순합산 연구 지표. 승격 근거 아님 (6-12 대시보드 경고 반영 완료) |

mismatch의 직접 원인(6-11 사례): 16:07 LightGBM 학습 → 16:45 장후 label refresh가 데이터 추가 → 21:20 challenger 재평가 → holdout 경계 변경으로 무효. **학습과 challenger 평가 사이에 데이터 변경 작업이 끼어드는 순서 문제**로, 매일 재발할 수 있는 구조다.

결론: 현재 상태는 "승격 대기"가 아니라 (a) 심사 자격이 구조적으로 무효화되고, (b) 자격을 회복해도 매수 신호 0건이라 핵심 승격 기준(비용 차감 양수)을 평가할 수 없으며, (c) 정본 게이트(gate walk-forward) 리포트가 구식 포맷으로 멈춰 있는 **3중 차단** 상태다. 매일의 동일 레시피 재학습(운영)만으로는 어느 것도 해소되지 않으며, 레시피를 바꾸는 실험(연구)이 필요하다.

## 6. Codex P0 (이번 라운드)

### P0-1. 학습→challenger 원자적 실행으로 holdout mismatch 구조 해소

- post-close 흐름에서 `train-lightgbm-bounded`와 `run-challengers-bounded` 사이에 label refresh 등 데이터 변경 작업이 끼지 않도록 실행 순서를 고정하거나, challenger가 학습 시점의 데이터 경계를 기준으로 평가하도록 한다.
- 수용 기준: 다음 장후 자동화에서 LightGBM 후보의 `evaluation_independence_status=independent_challenger_holdout`이 자동 산출된다.
- 금지선 준수: `app/risk/`, `config/`, `VERSION`, gate 임계값 수정 없이 실행 순서/평가 기준선만 조정한다.

### P0-2. gate reference walk-forward 새 3분류 포맷 재생성

- 두 차례 보류된 작업. WSL 불안정 회피를 위해 snapshot DB + 경량 wrapper 경로로 실행한다 (`scripts/create_research_db_snapshot.sh` + `--run-gate-walk-forward`).
- 수용 기준: `parameter_profile=gate_reference_v1` 리포트에 fold별 3분류/가상 방향 지표가 채워지고 대시보드 `-` 표시가 사라진다.

### P0-3. 매수 신호 0건 원인 진단 (모델 연구 1단계)

- LightGBM holdout에서 confidence threshold를 넘긴 매수 신호가 0건인 원인을 진단한다: threshold 과도 여부, `probability_up` 분포, 라벨 불균형.
- 기존 연구 도구를 재사용한다: expected-value review의 train-tail calibration 방식(fold train 구간에서만 threshold 선택, test 적용)을 KIS live feature 데이터에 적용한 진단 리포트 1건.
- 수용 기준: "어떤 threshold에서 매수 신호 N건, 비용 차감 기대값 양수/음수"를 보여주는 연구 리포트. 자동 승격·threshold 자동 채택 금지.

### P0-4. 장중 watchdog 심박 유지 검증

- 운영자 확인대로 장전/장후 자동화가 프로세스 on/off를 수행하므로 "아침 미기동" 위험은 닫는다.
- 남은 검증: 다음 거래일 정규장 중(예: 10시, 14시) watchdog `last_checked_at` 심박이 10분 기준 내로 유지되는지, 6-12에 관측된 "시작 후 곧 stale" 현상이 Codex/WSL 호출 세션 종료에 묶인 문제인지 확인한다.
- 세션 종료와 무관하게 살아남도록 프로세스 소유권(setsid/nohup/Windows 스케줄러 위임)을 점검한다.

## 7. Codex P1

- `373220` local-only 1주: 자동 alignment로 덮지 말고(현 판단 유지) 주문/체결/청산 원장에서 생성 경로를 추적해 원인을 기록한다.
- 다음 거래일 장후 EGW00201 재발 여부로 cooldown guard 실효성을 판정하고, 재발 시 장후 일괄 조회 호출량 자체를 줄이는 설계로 넘어간다.
- `build_runtime_scope()` minute-bar 전환 후, bar builder 자체 장애 시 수집 이상이 대시보드 경고에 잡히는지 1회 점검한다.
- 과거 data quality `watch` 반복(6-05/08/09)의 원인을 기록으로 남긴다 (최신은 `ok` 확인됨, blocker 아님).

## 8. 운영자 결정 요청

1. **작업 비중 재배분**: 다음 N라운드를 모델 트랙(P0-1~P0-3) 중심으로 둘지 승인. 인프라는 P0-4와 P1 유지보수로 제한.
2. **work_ver 루프 재개**: 이번 조치부터 logbook 기록과 별도로 `work_ver_17` 형식 리포트로 cowork에 전달 (6월 무리뷰 누적 방지).

## 9. 신뢰 수준

이번 라운드 조치는 주장-실제 일치율 100%(검증 8건 전건 일치)로 실행 신뢰도가 높다. 문서 closure 3건, 부분 3건, 의도적 보류 2건. 남은 위험은 실행 품질이 아니라 **우선순위**다 — 모델 트랙이 또 미뤄지면 시스템은 "안전하게 영원히 Phase 0"에 머문다. P0-1~P0-3 완료 시 처음으로 "승격 심사가 유효하게 작동하는 상태"가 되며, 그 결과가 음수여도 그것 자체가 다음 연구 방향을 정하는 증거가 된다. 다음 cowork 리뷰는 P0 완료 + 첫 장후 cooldown 실측 결과를 묶은 work_ver_17 전달 시점을 권장한다.
