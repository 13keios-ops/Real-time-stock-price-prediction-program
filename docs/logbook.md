# 작업 기록

## [2026-06-13] Codex -> review_ver_18 반영과 work_ver_18 통합본

- 사용자 지시:
  - cowork review ver18을 확인하고 모두 조치한다.
- 시작 상태:
  - KST 2026-06-13 16:25, 토요일 `weekend`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`, heartbeat fresh.
  - `./scripts/get_dashboard_status.sh`: dashboard 와 API가 `http://127.0.0.1:8765`에서 응답 중.
  - 작업트리는 `main...origin/main` 상태였고 `review_ver_18.md`만 untracked 로 들어와 있었다.
- 조치:
  - `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-review_ver_18.md`를 확인했다.
  - review_ver_18이 지적한 장외 미착수 항목 중 `runtime scope minute-bar 전환 후 수집 장애 감지 민감도 점검`을 테스트로 보강했다.
  - `tests/test_runtime_scope.py`에 raw KIS 이벤트는 10:44까지 있지만 `curated_minute_bars`는 10:43에서 멈춘 상황을 재현하는 테스트를 추가했다.
  - 이 테스트는 dashboard용 curated scope와 data-quality raw coverage 역할이 분리되어 있음을 회귀 잠금한다.
  - 2026-06-05, 2026-06-08, 2026-06-09 data quality watch 사례를 `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`과 `runtime-data/dev.db` read-only 조회로 재확인했다.
  - 세 날짜 모두 feature/bar 비율은 `1.0`이라 feature 생성 장애 증거는 없고, 2026-06-08만 raw market symbol-minute 약한 구간이 길어 다음 거래일 재발 여부를 별도 관찰 대상으로 남겼다.
  - cowork 전달용 통합본 `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-work_ver_18.md`를 작성했다.
  - `docs/Current-Implementation.md`, `docs/Execution-Plan.md`, `docs/Production-Transition-Progress.md`에 runtime scope 테스트 목적과 data-quality watch 해석 기준을 반영했다.
- 검증:
  - `python -m unittest tests.test_runtime_scope`: 4개 통과.
  - `python -m unittest discover -s tests -p 'test_*.py' -q`: 385개 통과.
  - `git diff --check`: 통과. 기존 문서 CRLF 변환 경고만 출력.
- 금지/안전:
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 실전 주문/취소 없음.
  - NAS 백업 실행 없음.
- 남은 작업:
  - 다음 실제 거래일 정규장 중 watchdog heartbeat 장시간 유지 여부를 read-only로 확인한다.
  - 다음 거래일 장후 broker order-fill 회수와 `EGW00201` 재발 여부를 확인한다.
  - 2026-06-08과 같은 raw market 약한 구간이 재발하면 watchdog heartbeat, KIS WS frame, raw market/orderbook coverage를 함께 비교한다.

## [2026-06-13] Codex -> 장외 정합성/Phase 1a readiness 마무리

- 사용자 지시:
  - 장외에 해야 할 작업들을 모두 마무리한다.
- 시작 상태:
  - KST 2026-06-13 13:14, 토요일 `weekend`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=stale`, process not running.
  - `./scripts/get_dashboard_status.sh`: `status=stale`, port not bound.
  - 작업트리는 `main...origin/main` clean 상태였다.
- 조치:
  - KIS 모의계좌 order-fill sync를 cooldown 이후 장외 1회 재시도했지만 2분 안에 완료되지 않아, Codex가 시작한 sync 프로세스만 정리했다. 같은 endpoint 반복 호출은 하지 않았다.
  - `python3 -m app --reconcile-paper-accounts`는 정상 완료했고 최신 브로커 계좌 snapshot은 보유 0, 로컬 장부는 `005380` 1주, `035420` 2주, `247540` 4주, `373220` 1주가 남아 `needs_review`다.
  - `scripts/trace_paper_kis_mismatch.py`가 최신 `paper-account-sync` mismatch 목록을 우선 기준으로 쓰고, 없을 때만 `dual-account-match`로 fallback 하도록 보강했다.
  - `tests/test_paper_kis_mismatch_trace.py`를 추가해 stale dual report가 최신 account sync mismatch에 섞이지 않도록 잠갔다.
  - 최신 mismatch trace는 `mismatch_source_report=paper_account_sync`, mismatch `4`종목으로 갱신됐다.
  - dashboard와 runtime watchdog를 장외 기준으로 재기동했다. live runtime은 주말이라 켜지지 않은 상태가 정상이다.
  - `python3 -m app --build-runtime-report`는 2분 timeout 뒤에도 프로세스가 계속 실행됐고, 추가 대기 중 종료됐다.
  - `python3 -m app --build-dashboard`로 dashboard snapshot을 `2026-06-13T13:33:09+09:00` 기준으로 갱신했다.
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness --dry-run`을 다시 실행해 `status=ok`, warnings 없음으로 갱신했다.
  - token refresh cache, KIS paper account snapshot, KIS HTTP Date 기반 system clock, synthetic WS recovery evidence를 최신화했다.
  - `latest-fixture-snapshot.json`, `latest-phase1a-readiness.json`, `latest-readiness.json`을 `phase1a_paper_readonly`, `status=ok`로 갱신했다. `market_status`와 `kill_switch`는 Phase 1a read-only에서 비차단 관측 실패로 남는다.
  - `docs/Current-Implementation.md`와 `docs/Production-Transition-Progress.md`를 최신 동작과 상태에 맞춰 갱신했다.
- 검증:
  - `python3 -m py_compile scripts/trace_paper_kis_mismatch.py tests/test_paper_kis_mismatch_trace.py`: 통과.
  - `python3 -m unittest tests.test_paper_kis_mismatch_trace -q`: 2개 통과.
  - `python3 scripts/trace_paper_kis_mismatch.py`: 통과.
  - `python3 -m app --reconcile-paper-accounts`: 통과, `needs_review` 유지.
  - `python3 -m app --build-dashboard`: 통과.
  - `./scripts/run_live_readiness_dry_run.sh --phase phase1a_paper_readonly ...`: 통과.
  - `python3 -m unittest discover -s tests -p 'test_*.py' -q`: 384개 통과.
  - `git diff --check`: 통과. 기존 문서 CRLF 변환 경고만 출력.
- 금지/안전:
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 실전 주문/취소 없음.
  - NAS 백업 실행 없음.
- 남은 작업:
  - 다음 실제 거래일 정규장 중 dashboard/watchdog heartbeat 장시간 유지 여부를 read-only로 확인한다.
  - 다음 거래일 장후 broker order-fill 회수와 `EGW00201` 재발 여부를 다시 본다.
  - 4종목 local-only mismatch는 order/fill 감사가 복구되기 전까지 marker-only alignment로 덮지 않는다.

## [2026-06-13] Codex -> review_ver_17 비판적 반영과 원장 추적 리포트

- 사용자 지시:
  - `docs/cowork-reports/2026-06-12-repo-goal-and-direction-deep-review-review_ver_17.md`를 확인하고 비판적으로 검토한 뒤 모두 진행한다.
- 시작 상태:
  - KST 2026-06-13 00:06, 토요일 `weekend`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - `./scripts/get_dashboard_status.sh`: dashboard 와 API가 `http://127.0.0.1:8765`에서 응답 중.
  - 작업트리는 `main...origin/main` clean 이었고 cowork review 파일만 untracked 로 들어와 있었다.
- 비판적 검토:
  - 타당: 모델 심사 체인은 유효해졌지만 매수 알파는 아직 없고, 하락/회피 단서를 방어적으로 검증하는 plan B가 필요하다.
  - 타당: paper/KIS mismatch 는 5종목으로 악화됐고, order-fill rate limit 때문에 자동 alignment로 덮으면 위험하다.
  - 보정: watchdog/dashboard 는 현재 running 이지만 정규장 중 장시간 유지 증거는 다음 거래일 장중에만 확인 가능하다.
- 조치:
  - `scripts/trace_paper_kis_mismatch.py`를 추가해 최신 reconciliation, broker sync, SQLite 원장을 read-only로 묶는 mismatch trace 리포트를 생성했다.
  - `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.{json,md}`를 생성했다.
  - 5종목 모두 최신 local/broker 청산 주문이 `submitted`이고 broker order-fill 회수가 `EGW00201`로 막혀 `close_order_fill_unknown_due_rate_limit` 후보로 분류됐다.
  - `scripts/summarize_walk_forward_extreme_folds.py`를 추가해 최신 gate walk-forward 에서 극단 저성능 fold를 요약했다.
  - `runtime-data/reports/backtests/latest-walk-forward-extreme-folds-h15.{json,md}`를 생성했다. 118개 fold 중 정확도 0.20 미만 fold가 3개, 최저 정확도는 0.11842다.
  - `scripts/analyze_walk_forward_extreme_fold_regimes.py`를 추가해 극단 fold 기간을 h15 label 분포와 분봉 장세로 read-only 분석했다.
  - `runtime-data/reports/backtests/latest-walk-forward-extreme-fold-regimes-h15.{json,md}`를 생성했다.
  - 최저 fold `5`, `12`, `11`은 flat 라벨 비중이 각각 약 `0.77`, `0.74`, `0.72`인데 flat hit rate 가 `0.0061`, `0.0119`, `0.0074`로 붕괴했고, 분봉 변동성도 높은 구간이었다. 우선 가설은 `보합 라벨 우세 + 고변동 + flat 판별 실패`이며 label/gate 기준값은 바꾸지 않는다.
  - `scripts/summarize_lightgbm_defensive_signal_candidates.py`를 추가해 기존 LightGBM 성능 진단과 calibration 결과에서 하락/회피 방어 신호 후보를 추렸다.
  - `runtime-data/reports/challengers/latest-lightgbm-defensive-signal-candidates-h15.{json,md}`를 생성했다. 이 리포트는 live short 또는 매수 승격 근거가 아니라 buy-avoid / early-exit paper shadow 검증 후보를 고르는 자료다.
  - `scripts/summarize_lightgbm_defensive_shadow.py`를 추가해 baseline 매수 허용 신호와 같은 시각의 `lightgbm-h15-v1` shadow 예측, 닫힌 h15 label, closed paper lot 을 read-only 로 비교했다.
  - `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.{json,md}`를 생성했다.
  - 첫 결과는 `buy-avoid` 쪽에만 후보성이 있다. down threshold `0.40`은 baseline 매수 신호 `3,130`건 중 `1,147`건을 회피했을 때 비용 차감 누적 순수익률 delta `+114.8758%p`였고, 조기 청산 shadow 는 best threshold `0.58`에서도 delta `-48.7958%p`, cash delta `-178,007원`으로 악화됐다.
  - `docs/Execution-Plan.md`에 plan B, KIS live 데이터 축적 최소 기준, mismatch 시간 격상 기준, lineage 용량/아카이브 설계를 보강했다.
  - `docs/Current-Implementation.md`, `README.md`, `docs/Production-Transition-Progress.md`에 새 리포트와 현재 해석을 연결했다.
  - KIS Developers 포털과 공식 GitHub 공개 HTML을 2026-06-13 기준으로 재확인했고, `docs/KIS-Connection-Runbook.md`에 `초당 호출 제한 공지 존재는 확인`, `구체 수치는 로그인/동적 UI 또는 지원 채널 확인 필요` 상태를 최신화했다.
  - `runtime-data/reports/data-quality/latest-kis-live-data-quality.json` 기준 최신 거래일 `2026-06-12` watchlist 10종목 coverage 는 `ok`라, watchlist 확대는 수집 누락 보완이 아니라 데이터 다양성 확보 목적으로만 검토한다고 정리했다.
  - 전체 테스트 중 주말 날짜에서 post-close holiday 테스트가 weekend skip으로 먼저 분기되는 날짜 의존 실패를 확인했다.
  - `scripts/common_process_helpers.sh`의 `market_session_status`에서 명시 holiday를 weekend보다 먼저 판정하도록 바꿔, calendar에 명시된 휴장 사유가 skip_reason에 보존되게 했다.
- 검증:
  - `python3 scripts/trace_paper_kis_mismatch.py`: 통과.
  - `python3 scripts/summarize_walk_forward_extreme_folds.py`: 통과.
  - `python3 scripts/analyze_walk_forward_extreme_fold_regimes.py`: 통과.
  - `python3 scripts/summarize_lightgbm_defensive_signal_candidates.py`: 통과.
  - `python3 scripts/summarize_lightgbm_defensive_shadow.py`: 통과.
  - `python3 -m py_compile scripts/trace_paper_kis_mismatch.py scripts/summarize_walk_forward_extreme_folds.py scripts/analyze_walk_forward_extreme_fold_regimes.py scripts/summarize_lightgbm_defensive_signal_candidates.py scripts/summarize_lightgbm_defensive_shadow.py`: 통과.
  - `python3 -m unittest tests.test_walk_forward_extreme_fold_regime_analysis -q`: 1개 통과.
  - `python3 -m unittest tests.test_lightgbm_defensive_shadow -q`: 1개 통과.
  - `bash -n scripts/common_process_helpers.sh scripts/run_post_close_label_refresh.sh scripts/run_post_close_ml_maintenance.sh`: 통과.
  - `python3 -m unittest tests.test_post_close_label_refresh_script tests.test_post_close_maintenance_script -q`: 7개 통과.
  - `python3 -m unittest discover -s tests -p 'test_*.py' -q`: 382개 통과.
- 금지/안전:
  - read-only 분석과 문서 보강만 수행했다.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 실전 주문/취소, NAS 백업 없음.
- 다음 작업:
  - 다음 거래일 장중 watchdog heartbeat 유지와 장후 `EGW00201` 재발 여부를 실측한다.
  - KIS live 데이터가 더 쌓이면 보합 regime 분리와 변동성 피처 후보가 worst fold에서 개선되는지 재검증한다.

## [2026-06-12] Codex -> 전체 실행 계획 문서화

- 사용자 지시:
  - 모든 계획을 순서대로 방법과 이유를 상세하게 정리해 md로 출력한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - `./scripts/get_dashboard_status.sh`: dashboard 와 API가 `http://127.0.0.1:8765`에서 응답 중.
  - 작업트리는 `main...origin/main` clean 상태였다.
- 조치:
  - `docs/Execution-Plan.md`를 추가했다.
  - 현재 상태에서 작업을 진행할 순서를 `안전 확인 -> Phase 0 정합성 -> KIS 연결 -> 모델 성능개선 -> 모델 심사 -> 예측 lineage -> dashboard -> 자동화 -> Phase 1a/1b -> Phase 2/3 -> cowork/백업` 순서로 정리했다.
  - 각 단계에 방법, 이유, 완료 기준, 관련 문서/코드 경로를 적었다.
  - README와 AGENTS 문서 역할 목록에 새 실행 계획 문서를 연결했다.
  - `docs/Production-Transition-Progress.md`의 상단 현재 스냅샷을 2026-06-12 23시대 실제 runtime/dashboard/watchdog 상태와 최신 label band 재현성 결과 기준으로 갱신했다.
- 금지/안전:
  - 코드, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 실전 주문과 NAS 백업 실행 없음.
- 다음 작업:
  - 다음 장후 또는 장외에는 `docs/Execution-Plan.md`의 권장 순서대로 KIS live feature 후보 모델 실험과 paper/KIS 정합성 확인을 이어간다.

## [2026-06-12] Codex -> LightGBM label band 재현성 리뷰

- 사용자 지시:
  - 직전 LightGBM 성능개선 트랙의 다음 단계를 진행한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 대시보드는 `http://127.0.0.1:8765`에서 응답 중이었고 작업트리는 clean 상태였다.
- 조치:
  - `python -m app --run-lightgbm-label-band-reproducibility-review --horizon-min 15` CLI를 추가했다.
  - label band 후보 `0.35 / 0.40 / 0.50`을 최근 KIS live labeled row `60,000`건 기준으로 full walk-forward 와 3개 기간 분리 fold 에서 다시 검증한다.
  - 기존 `_run_lightgbm_walk_forward` 결과에 가상 방향 거래 지표(`virtual_direction_*`)를 추가해 상승=가상 매수, 하락=가상 매도, 보합=거래 없음 기준의 기간별 재현성을 볼 수 있게 했다.
  - 대시보드 `ML/데이터 > 챌린저 및 워크포워드`에 `LightGBM label band 재현성` 카드를 추가했다.
  - `README.md`와 `docs/Current-Implementation.md`에 새 명령과 자동 threshold 채택 금지 기준을 반영했다.
- 결과:
  - 실행 리포트: `runtime-data/reports/challengers/latest-lightgbm-label-band-reproducibility-h15.json` / `.md`.
  - 데이터 범위: `2026-05-08T10:18:00+09:00`부터 `2026-06-12T15:04:00+09:00`, KIS live feature `6`개, `60,000` rows.
  - `0.35`: full walk-forward 3분류 정확도 `0.418417`, 가상 방향 거래 `737건`, 가상 방향 순수익률 `-4.071976%`, 양수 기간 `1/3`, 판정 `not_reproducible`.
  - `0.40`: full walk-forward 3분류 정확도 `0.435333`, 가상 방향 거래 `684건`, 가상 방향 순수익률 `+12.267219%`, 양수 기간 `0/3`, 판정 `not_period_reproducible`.
  - `0.50`: full walk-forward 3분류 정확도 `0.446583`, 가상 방향 거래 `776건`, 가상 방향 순수익률 `-16.142871%`, 양수 기간 `1/3`, 판정 `not_reproducible`.
  - 해석: `0.40`은 단일 전체 walk-forward에서는 좋아 보이지만 기간 분리에서 재현되지 않아 `config`의 label threshold 를 바꾸면 안 된다.
  - dashboard snapshot 은 `generated_at=2026-06-12T23:02:16.779655+09:00`로 갱신됐다.
- 검증:
  - `python -m py_compile app/services/research.py app/__main__.py app/services/dashboard.py tests/test_research_pipeline.py`: 통과.
  - `python -m unittest tests.test_research_pipeline -q`: 10개 통과.
  - `python -m app --run-lightgbm-label-band-reproducibility-review --horizon-min 15`: 통과.
  - `python -m app --build-dashboard`: 통과.
- 금지/안전:
  - active model, gate 기준값, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, 실전 주문 변경 없음.
  - NAS 백업 실행 없음.
- 다음 작업:
  - label band 변경은 보류한다.
  - 다음 모델 트랙은 `0.40` threshold 적용이 아니라, 하락/회피 신호와 상승 매수 신호를 분리해 feature/profile 후보를 다시 좁히는 방향이 맞다.

## [2026-06-12] Codex -> LightGBM feature profile / label band / probability calibration 실험

- 사용자 지시:
  - LightGBM을 바로 승격하지 않고 KIS live 전용 feature 보강, 시간대/모멘텀/최근 변동성 feature 후보, label band 재점검, probability calibration 순서의 성능개선 트랙을 모두 진행한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 대시보드는 `http://127.0.0.1:8765`에서 응답 중이었다.
- 조치:
  - `python -m app --run-lightgbm-feature-profile-experiment --horizon-min 15` CLI를 추가했다.
  - KIS live 피처에 시간대, 모멘텀, 최근 변동성 후보를 메모리 안에서만 붙여 `base`, `time`, `momentum`, `volatility`, `time_momentum_volatility` 후보를 비교한다.
  - `python -m app --run-lightgbm-label-band-experiment --horizon-min 15` CLI를 추가했다.
  - label band 후보는 메모리 안에서만 재라벨링하고 `config/`, gate 기준값, 실제 label threshold 를 자동 변경하지 않는다.
  - `python -m app --run-lightgbm-calibration-experiment --horizon-min 15` CLI를 추가했다.
  - probability calibration 후보는 최신 LightGBM artifact의 확률을 온도 보정과 prior blending 으로 후처리해 비교하고, calibration 결과를 자동 채택하지 않는다.
  - 대시보드 `ML/데이터 > 챌린저 및 워크포워드`에 feature profile, label band, probability calibration 연구 카드 3개를 추가했다.
  - `README.md`와 `docs/Current-Implementation.md`에 세 실험의 위치와 자동 승격/자동 threshold 변경 금지 기준을 반영했다.
- 결과:
  - feature profile experiment: `status=completed`, 3분류 정확도 기준 최고 후보는 `time_momentum_volatility`, 가상 방향 순수익률 기준 최고 후보는 `volatility`였지만 전체 상태는 `no_positive_direction_expected_value`다.
  - label band experiment: `status=completed`, 현재 실행 기준 label threshold 는 `0.35`, 3분류 정확도 기준 최고 후보는 `0.5`, 가상 방향 순수익률 기준 최고 후보는 `0.4`다. 결과는 `positive_direction_candidate_requires_review` 연구 후보이며 자동 채택하지 않는다.
  - probability calibration experiment: `status=completed`, NLL/Brier 기준 최고 후보는 `cal-t2p00-a0p35`, 가상 방향 순수익률 기준 최고 후보는 `cal-t0p75-a0p10`이다. 결과는 하락/회피 쪽 신호가 주도하는 `positive_downside_direction_candidate_requires_review`이며 현물 매수 승격 근거가 아니다.
  - dashboard snapshot 은 `generated_at=2026-06-12T22:03:30.798142+09:00`로 갱신됐다.
- 검증:
  - `python -m py_compile app/services/research.py app/__main__.py app/services/dashboard.py tests/test_research_pipeline.py`: 통과.
  - `python -m unittest tests.test_research_pipeline -q`: 10개 통과.
  - `python -m unittest tests.test_dashboard -q`: 22개 통과.
  - `python -m unittest discover -s tests -p "test_*.py" -q`: 380개 통과.
  - `python -m app --run-lightgbm-feature-profile-experiment --horizon-min 15`: 통과.
  - `python -m app --run-lightgbm-label-band-experiment --horizon-min 15 --lightgbm-feature-source-max-rows 50000`: 통과.
  - `python -m app --run-lightgbm-calibration-experiment --horizon-min 15 --challenger-max-rows 150000`: 통과.
  - `python -m app --build-dashboard`: 통과.
- 금지/안전:
  - active model, gate 기준값, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, 실전 주문 변경 없음.
  - NAS 백업 실행 없음.
- 다음 작업:
  - label band 후보는 바로 정책 변경하지 않고, 기간 분리 재현성 / walk-forward / paper shadow 기준으로 다시 검증한다.
  - calibration 후보는 하락/회피/청산 연구 신호로 분리해서 보고, 현물 매수 승격과 혼동하지 않는다.

## [2026-06-12] Codex -> LightGBM 성능개선 트랙 1차 진단과 source experiment

- 사용자 지시:
  - 모델 성능개선 트랙을 진행한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 대시보드 서버는 `http://127.0.0.1:8765`에서 응답 중이었다.
- 조치:
  - `python -m app --run-lightgbm-performance-diagnostics --horizon-min 15` CLI를 추가했다.
  - 최신 LightGBM artifact를 독립 holdout 기준으로 평가해 3분류 정확도, 클래스별 적중률, 혼동행렬, 확률 분포, 방향별 threshold 비용 차감 수익률을 `runtime-data/reports/challengers/latest-lightgbm-performance-diagnostics-h15.{json,md}`로 남기게 했다.
  - `python -m app --run-lightgbm-feature-source-experiment --horizon-min 15` CLI를 추가했다.
  - `mixed_recent`, `kis-ws`, `cybos-historical` 후보를 메모리 안에서만 학습/평가하고 artifact를 덮어쓰지 않는 source experiment 리포트를 `runtime-data/reports/challengers/latest-lightgbm-feature-source-experiment-h15.{json,md}`로 남기게 했다.
  - 대시보드 `ML/데이터 > 챌린저 및 워크포워드`에 `LightGBM 성능 진단`과 `LightGBM 원천별 실험` 요약 카드를 추가했다.
- 결과:
  - LightGBM 성능 진단: `status=positive_downside_direction_candidate_requires_review`, `three_class_accuracy=0.358843`, 상승 적중률 `0.264706`, 보합 적중률 `0.278094`, 하락 적중률 `0.577875`.
  - 기본 threshold `0.58`의 가상 방향 거래는 `344건`, 순수익률 단순합산 `+98.1520%`였지만, 대부분은 하락 예측 쪽이었다. 상승 예측 23건은 순수익률 `-8.2416%`, 하락 예측 321건은 `+106.3936%`였다.
  - source experiment: `mixed_recent`은 3개 피처, `3class_acc=0.365476`, 방향 순수익률 `+1.049924%`였으나 소수 하락/회피 후보에 치우쳤다.
  - `kis-ws`는 6개 피처(`mid_price`, `spread_bps`, `bid_ask_imbalance` 포함)를 사용했지만 `3class_acc=0.354458`, 방향 순수익률 `-44.673720%`로 아직 개선 후보가 아니다.
  - `cybos-historical`은 `3class_acc=0.544328`로 높지만 보합 적중에 치우치고 방향 순수익률 `-1.759200%`라 KIS live 매수 승격 근거가 아니다.
- 해석:
  - threshold를 낮추는 단순 조정은 권장하지 않는다.
  - 현재 유의미한 단서는 `하락/회피/청산 후보 신호`이며, 현물 매수 승격 근거는 아직 부족하다.
  - 다음 모델 연구는 KIS-only 피처를 그대로 승격하는 것이 아니라 시간대/모멘텀/최근 변동성/라벨 폭/확률 보정 후보를 분리 실험하는 방향이 맞다.
- 검증:
  - `python -m py_compile app/services/research.py app/__main__.py tests/test_research_pipeline.py`: 통과.
  - `python -m unittest tests.test_research_pipeline -q`: 10개 통과.
  - `python -m py_compile app/services/dashboard.py`: 통과.
  - `python -m unittest tests.test_dashboard -q`: 22개 통과.
  - `python -m app --run-lightgbm-performance-diagnostics --horizon-min 15`: 통과.
  - `python -m app --run-lightgbm-feature-source-experiment --horizon-min 15`: 통과.
  - `python -m app --build-dashboard`: 통과, `generated_at=2026-06-12T19:45:48.128797+09:00`.
- 금지/안전:
  - active model, gate 기준값, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, 실전 주문 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-12] Codex -> KIS 연결 장애 공식 문서 확인과 rate limit 대응 보강

- 사용자 지시:
  - KIS 연결 문제가 계속되는 것으로 보이므로 공식 문서/가이드를 확인하고 해결 기준을 md에 남긴다.
  - `https://apiportal.koreainvestment.com/intro`도 확인한다.
- 공식 원천 확인:
  - KIS Developers 포털은 API 문서, API 가이드 문서, FAQ/오류코드, 공식 GitHub 샘플 코드, 테스트베드를 제공한다.
  - 포털 메인 공지에는 `[중요] 한국투자증권 Open API 신규 고객 초당 호출 제한 안내`가 노출된다. 상세 수치/대상은 포털 동적 UI 또는 로그인 확인이 필요하다.
  - 공식 GitHub 샘플 README는 `EGW00201`을 초당 거래건수 초과로 설명하고, 모의투자 계좌 REST API 호출 제한이 낮다고 안내한다.
  - 공식 GitHub 샘플 README는 WebSocket `No close frame received`류 문제 해결 후보로 HTS ID 확인을 안내한다.
- 관측:
  - 2026-06-12 장후 `python -m app --sync-broker-paper-orders`는 KIS 모의계좌 order-fill 조회에서 `EGW00201`로 실패했다.
  - `runtime-data/reports/broker-paper/latest-sync.json`: `status=rate_limited`, `open_order_count=5`, `pending_symbols=005380,005930,035420,247540,373220`.
  - `python -m app --reconcile-paper-accounts`는 계좌 snapshot을 갱신했지만 broker 포지션 0, local 포지션 5라 `needs_review`가 유지됐다.
  - 장전 WebSocket은 `no close frame received or sent`로 여러 번 재연결됐지만 `storm=false`였고 runtime/watchdog은 유지됐다.
- 조치:
  - `app/services/broker_paper_sync.py`의 order-fill rate-limit 기본 cooldown을 30분에서 2시간으로 늘렸다.
  - `tests/test_broker_paper_sync.py`에 app-level 기본 cooldown이 2시간인지 잠그는 검증을 추가했다.
  - `docs/KIS-Connection-Runbook.md`를 추가해 공식 원천, 현재 증상, `EGW00201` 대응, WebSocket reconnect 대응, 정상/주의/실패 기준을 정리했다.
  - `README.md`, `AGENTS.md`, `.agents/skills/daily-ops-check/SKILL.md`에 새 runbook과 2시간 cooldown 기준을 연결했다.
- 남은 작업:
  - KIS 포털 공지의 구체 호출 제한 수치는 로그인/동적 UI 또는 KIS 지원 채널에서 확인 필요다.
  - cooldown 이후 장외에 order-fill sync를 1회만 재시도하고, 계속 `EGW00201`이면 추가 호출을 멈춘다.
  - `pending_symbols` 5종목 mismatch는 자동 align으로 덮지 않고 order-fill 감사 복구 뒤 판단한다.

## [2026-06-12] Codex -> repo 방향성 deep review ver_3 P0 모델 트랙 조치

- 사용자 지시:
  - `docs/cowork-reports/2026-06-12-repo-goal-and-direction-deep-review_ver_3.md`를 확인하고 비판적으로 검토한 뒤 조치한다.
- 시작 상태:
  - KST 03:06, `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=stale`.
  - 작업 트리는 `main...origin/main`이었고 cowork review ver_2/ver_3 파일이 untracked였다.
- cowork 리뷰 비판적 확인:
  - 타당: 모델 트랙이 P0이고, LightGBM `holdout_window_mismatch`, gate reference 구식 포맷, 매수 신호 0건이 실제 병목이다.
  - 보정: dashboard/watchdog daemon 유지 문제는 여전히 P0 운영 blocker지만, 이번 라운드의 핵심은 모델 심사 체인 유효화다.
- 조치:
  - `app/services/research.py`의 challenger 평가가 최신 LightGBM 학습 run의 challenger holdout 시작 시각을 anchor 로 삼아 `challenger_holdout_training_anchor` 평가 구간을 만들도록 보강했다.
  - `python -m app --run-lightgbm-buy-signal-diagnostics --horizon-min 15` CLI를 추가해 threshold별 매수 신호 수, 적중률, 비용 차감 수익률을 별도 리포트로 남기게 했다. threshold 는 자동 채택하지 않는다.
  - snapshot DB `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/gate-ref-h15-20260612-033742.db`를 생성했다. 원본/스냅샷 크기는 `13302407168` bytes, `quick_check=ok`.
  - snapshot DB를 `DATABASE_URL`로 사용해 gate reference walk-forward를 재생성했다.
  - 새 gate reference 를 반영해 challenger를 다시 실행했고 dashboard snapshot도 갱신했다.
- 결과:
  - 최신 gate reference: `walk-forward-h15-20260612042842731771`, `parameter_profile=gate_reference_v1`, `folds=118`, `rows_evaluated=5,900,000`, `three_class_accuracy=0.416342`, `virtual_direction_trades_taken=2,675,212`, gate 는 `needs_review`.
  - 최신 challenger: `challenger-h15-20260612045334514142`, `dataset_scope=challenger_holdout_training_anchor`, `recommended_action=keep_active`.
  - LightGBM 후보: `evaluation_independence_status=independent_challenger_holdout`, `artifact_training_status=artifact_training_run_match`, `three_class_accuracy=0.366625`, `up_hit_rate=0.168684`, `trades_taken=0`.
  - LightGBM buy-signal diagnostics: `status=no_positive_expected_value_threshold`. threshold `0.40`에서도 `trades_taken=1845`, `cumulative_net_return_pct=-199.849736`으로 비용 차감 양수 기대값 근거가 없다.
  - dashboard snapshot: `generated_at=2026-06-12T04:54:41.287826+09:00`.
- 검증:
  - `python -m py_compile app/services/research.py app/__main__.py tests/test_research_pipeline.py`: 통과.
  - `python -m unittest tests.test_research_pipeline`: 10개 통과.
  - `python -m unittest tests.test_research_pipeline.ResearchPipelineTests.test_sqlite_pipeline_builds_and_trains`: 통과.
  - `python -m app --run-challengers --horizon-min 15`: 통과, 최신 challenger 갱신.
  - `python -m app --run-lightgbm-buy-signal-diagnostics --horizon-min 15`: 통과.
  - `python -m app --build-dashboard`: 통과.
- 남은 작업:
  - 모델 쪽 다음 단계는 threshold 조정이 아니라 피처 확장, 라벨 분포/보합 폭 재검토, LightGBM calibration 실험이다.
  - dashboard/watchdog daemon 장시간 유지 검증은 계속 P0 운영 blocker다.
  - `373220` local-only mismatch와 KIS `EGW00201` 재발 여부는 다음 거래일 장후에 이어서 본다.

## [2026-06-12] Codex -> cowork deep review 반영과 대시보드 scope 경량화

- 사용자 지시:
  - `docs/cowork-reports/2026-06-11-repo-goal-and-direction-deep-review.md`를 확인하고 비판적으로 검토한 뒤 조치한다.
  - C드라이브는 꼭 필요한 앱 내부 상태 외에는 사용하지 않고, 프로젝트 산출물·테스트 로그·캐시·대용량 출력은 D/WSL 저장소 내부에 둔다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - dashboard 와 runtime watchdog 은 중지 상태였다.
  - 작업 트리에는 cowork deep review 파일이 untracked 로 있었다.
- cowork 리뷰 비판적 확인:
  - 타당: alpha/model predictive power 부족, `virtual_direction_cumulative_net_return_pct` 오독 위험, stale readiness/progress, KIS `EGW00201` 반복, `373220` local-only mismatch.
  - 보정: 최신 `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`은 latest trade date `2026-06-11`, `assessment.status=ok`라 현재 blocker 는 아니고 과거 반복 watch 원인 추적 항목이다.
- 조치:
  - dashboard 챌린저 표와 운영 콘솔에서 가상 방향 수익률을 `가상 방향 순수익률(단순합산)` / `가상 방향 단순합산(연구용)`으로 표시하고, 복리·실거래·포트폴리오 수익률이 아니라는 경고를 고정했다.
  - `README.md`의 월 `+50%` 문구를 장기 stretch target 으로 낮추고, 1차 검증 목표를 비용 반영 후 양수 기대값·구간 분리 재현성·최대 낙폭·연속 손실·paper 안정성으로 명확히 했다.
  - `app/services/broker_paper_sync.py`에 KIS order-fill rate-limit cooldown guard 를 추가했다. 최근 `rate_limited` 리포트가 30분 안이면 같은 endpoint 를 재호출하지 않고 `cooldown_active=true`, `skipped_broker_call=true`, `retry_after_seconds`를 남긴다.
  - `app/services/runtime_scope.py`와 `app/services/dashboard.py`를 보강해 기본 대시보드가 raw tick 전체를 직접 그룹화하지 않도록 했다. 최신 거래일은 data-quality 리포트의 `latest_trade_date`를 쓰고, 대시보드 scope 는 기간 내 `curated_minute_bars`로 만든다.
  - `docs/Production-Transition-Progress.md`를 2026-06-12 기준으로 갱신하고, stale readiness 와 최신 challenger/paper-KIS 상태를 분리했다.
- 관측:
  - 기존 대시보드 빌드는 `build_runtime_scope()`가 raw tick 전체를 `symbol × minute × source`로 그룹화하다가 WSL 명령 세션이 끊기는 형태로 실패했다.
  - scope 를 minute bar 기반으로 바꾼 뒤 `python -m app --build-dashboard`가 통과했고, 최신 snapshot 은 `generated_at=2026-06-12T01:07:58.385467+09:00`이다.
- 검증:
  - `python -m py_compile app/storage/sqlite_store.py app/services/runtime_scope.py app/services/dashboard.py app/services/broker_paper_sync.py`: 통과.
  - `python -m unittest tests.test_runtime_scope tests.test_broker_paper_sync`: 11개 통과.
  - `python -m unittest tests.test_dashboard`: 22개 통과.
  - `python -m app --build-dashboard`: 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 378개 통과.
  - `git diff --check`: 통과. CRLF/LF 경고만 있고 diff 오류 없음.
  - dashboard 재기동 스크립트는 시작 JSON을 냈지만, 후속 `./scripts/get_dashboard_status.sh`에서 `status=stale`, `dashboard_responding=false`로 돌아왔다. snapshot 생성은 정상이나 장시간 서버 유지 문제는 별도 P0로 남긴다.
  - runtime watchdog 재기동 스크립트도 시작 JSON을 냈지만, 후속 `./scripts/get_runtime_watchdog_status.sh`에서 `status=stale`로 돌아왔다. live runtime 은 `overnight`라 정지 상태가 정상이고, watchdog daemon 유지 문제는 별도 P0로 남긴다.
  - live runtime 은 `overnight`라 `status=stopped`가 정상이다.
- 남은 작업:
  - gate reference walk-forward 새 3분류 포맷 재생성은 이전 시도에서 WSL 불안정이 있어 snapshot/경량 wrapper 로 별도 진행한다.
  - `373220` local-only mismatch 는 자동 alignment 로 덮기 전에 주문/체결/청산 원장 원인을 추적한다.

## [2026-06-11] Codex -> 챌린저 3분류 지표와 가상 방향 거래 평가 분리

- 사용자 지시:
  - 상승/보합/하락을 모두 예측·학습·평가 기준으로 보고, 대시보드도 이 기준으로 보여준다.
  - 기존 `거래 적중률`이 보유종목 한도, 매수 전용 운용, 강제청산과 섞여 보이는 문제를 바로잡는다.
  - 재학습부터 하지 않고 기존 LightGBM artifact를 새 지표로 재평가한다.
- 시작 상태:
  - PC 재부팅 뒤 `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: process false인 stale 상태였고, `./scripts/get_dashboard_status.sh`도 stale 상태였다.
  - 장후이고 live runtime 이 꺼져 있어 코드/대시보드/테스트 작업을 진행했다.
- 조치:
  - `app/services/research.py`의 모델 평가 metrics에 `three_class_accuracy`, `class_hit_rates`, `confusion_matrix`, `buy_signal_hit_rate`, `virtual_direction_*` 지표를 추가했다.
  - 기존 `trade_hit_rate`는 호환용 legacy key로 유지하되, 의미는 `predicted_label=up`이고 신뢰도 기준을 넘긴 매수 후보의 적중률로 문서화했다.
  - 가상 방향 거래는 상승 예측=가상 매수, 하락 예측=가상 매도, 보합 예측=거래 없음으로 계산한다. 이 값은 연구용 방향 성과이며 실제 현물 paper 주문, 보유한도, 미체결, 포지션 관리 청산과 분리한다.
  - `app/services/dashboard.py`의 챌린저 표와 운영 콘솔을 `3분류 정확도`, `상승/보합/하락 적중률`, `매수 신호 적중률`, `가상 방향 거래 수`, `가상 방향 적중률`, `가상 방향 순수익률`, `혼동행렬` 중심으로 바꿨다.
  - `평가 자격`은 독립 holdout/아티팩트 기준일 뿐 승격 가능 표시가 아니라고 대시보드 설명을 고정했다.
  - 기존 LightGBM artifact를 재학습 없이 `python -m app --run-challengers --horizon-min 15`로 재평가했다.
- 재평가 결과:
  - 최신 challenger run: `challenger-h15-20260611212023862868`.
  - 활성 모델은 계속 `baseline-h15-v1`, `recommended_action=keep_active`.
  - LightGBM 후보는 `three_class_accuracy=0.360671`, `up_hit_rate=0.167514`, `flat_hit_rate=0.290851`, `down_hit_rate=0.651619`, `virtual_direction_cumulative_net_return_pct=111.03129`.
  - LightGBM은 `evaluation_independence_status=holdout_window_mismatch`라 승격 대상이 아니며 shadow/관찰 후보로만 본다.
  - 기존 게이트 기준 워크포워드 리포트는 오래된 포맷이므로 fold별 새 3분류/가상 방향 지표 일부는 대시보드에서 `-`로 보인다. 게이트 참고 리포트를 임의 ad-hoc 설정으로 덮지 않기 위해 이번 작업에서는 워크포워드 재생성을 보류했다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py`: 통과.
  - `python -m unittest tests.test_dashboard`: 22개 통과.
  - `python -m unittest tests.test_research_pipeline`: 9개 통과.
  - `python -m app --run-challengers --horizon-min 15`: 통과, 최신 challenger 리포트 갱신.
  - `python -m app --build-dashboard`: 통과, `generated_at=2026-06-11T21:23:04.845728+09:00`.
  - `python -m unittest discover -s tests -p 'test_*.py'`: 375개 통과.
  - `git diff --check`: 통과. CRLF/LF 경고만 있고 diff 오류 없음.
  - 재부팅 뒤 stale였던 runtime watchdog은 재시작 후 `status=running`, `heartbeat_stale=false`.
  - dashboard는 재시작 후 `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`, URL `http://127.0.0.1:8765`.
- 금지/안전:
  - 실전 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-11] Codex -> LightGBM shadow serving 예측 저장 적용

- 사용자 지시:
  - LightGBM을 바로 active로 승격하지 않고, baseline은 주문 판단에 계속 쓰며 LightGBM은 같은 시각/종목의 shadow 예측으로 저장한다.
  - 대시보드에서 baseline vs LightGBM을 나란히 비교하고, 실제 결과/신호/주문/체결과 함께 판단할 수 있게 한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 장중 수집 보호 모드가 아니므로 코드/문서 변경과 격리 테스트를 진행했다.
- 조치:
  - `app/models/loader.py`에 최신 LightGBM artifact를 shadow 모델로만 불러오는 loader를 추가했다.
  - `app/services/streaming.py`는 active 모델 예측을 먼저 만들고, 최신 LightGBM artifact가 있는 horizon 에 대해 shadow 예측을 `serving_predictions`에 추가 저장한다.
    - 신호, target, paper 주문은 계속 active 예측 ID를 사용한다.
    - LightGBM shadow 로딩 실패나 artifact 부재는 런타임 실패가 아니라 shadow 생략으로 처리한다.
  - `app/services/dashboard.py`의 예측흐름 primary 선택을 15분 baseline 우선으로 고정했다.
    - LightGBM shadow row가 먼저 조회되어도 주문 연결 기준은 baseline active 예측이다.
    - 표시 영역은 기존처럼 Baseline/LightGBM 예측을 같은 종목/시각 라인에 나란히 둔다.
  - `README.md`와 `docs/Current-Implementation.md`에 현재 사실을 반영했다.
    - 현재 active 모델은 `baseline`.
    - LightGBM은 최신 artifact가 있는 horizon 에 한해 shadow serving 예측만 저장하며, 승격이나 주문 판단 변경을 의미하지 않는다.
- 검증:
  - `python -m unittest tests.test_model_loader tests.test_streaming_pipeline.StreamingPipelineTests.test_lightgbm_shadow_predictions_are_written_without_driving_orders tests.test_dashboard.DashboardTests.test_prediction_flow_prefers_baseline_primary_when_lightgbm_shadow_exists`: 6개 통과.
  - `python -m unittest tests.test_model_loader tests.test_streaming_pipeline tests.test_dashboard`: 37개 통과.
  - `python -m app --build-dashboard`: 통과, `generated_at=2026-06-11T07:20:37.842844+09:00`.
  - dashboard 서버 stop/start 후 `./scripts/get_dashboard_status.sh`: `status=running`, 새 PID `18430`, `dashboard_responding=true`, `dashboard_api_responding=true`.
  - `python -m unittest discover -s tests -p 'test_*.py'`: 375개 통과.
  - `git diff --check`: 통과. CRLF/LF 경고만 있고 diff 오류 없음.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-10] Codex -> 장후 자동화 보고 경로와 운영 blocker 복구

- 사용자 지시:
  - 장전 자동화만 보이고 장후 자동화가 안 되는 것처럼 보이는 원인을 확인하고 조치한다.
- 확인:
  - 현재 시각 기준 장 상태는 `post-close`, live runtime 은 `stopped` 정상.
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PostCloseOps`: `LastRunTime=2026-06-10 16:40:40`, `LastTaskResult=0`, `NumberOfMissedRuns=0`.
  - `runtime-data/logs/automation/postclose-ops.log`: `Wed Jun 10 16:40:05 KST 2026` 실행 이력 확인.
  - `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`: `status=ok`, completed `2026-06-10 16:52:36 +0900`.
  - `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`: `status=ok`, completed `2026-06-10 16:57:05 +0900`.
  - 장후 자동화는 실행됐지만 마지막 local setup check 가 `dashboard_not_running`, `watchdog_not_running` blocker 를 남겼다.
  - Codex 앱 heartbeat 는 현재 스레드에 1개만 붙일 수 있어 장전 heartbeat 만 active 상태였고, 장후 결과가 이 스레드로 자동 보고되지 않았다.
- 조치:
  - `./scripts/start_dashboard_background.sh`와 `./scripts/start_runtime_watchdog_background.sh`로 dashboard 와 runtime watchdog 을 복구했다.
  - `./scripts/check_local_setup.sh` 재실행 결과 `ok=true`, blockers/warnings 없음.
  - Codex 앱 heartbeat `automation`을 장전/장후 공용으로 업데이트했다. KST 장전 08:25~08:45, 장후 17:10~17:30 외 교차 실행은 DONT_NOTIFY 로 조용히 종료하도록 prompt 를 바꿨다.
- 남은 운영 이슈:
  - `runtime-data/reports/broker-paper/latest-sync.json`: KIS `EGW00201` rate limit 으로 `status=rate_limited`, open order `2`, pending symbols `247540`, `373220`.
  - `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`: `status=needs_review`.
    - 브로커 모의계좌 보유: `247540` 4주.
    - 로컬 paper 보유: `247540` 4주, `373220` 1주.
    - `373220`은 local only mismatch 이므로 align 으로 덮지 않았다.
  - KIS order-fill 조회가 반복 rate limit 상태라 추가 KIS 호출은 중지했다. 다음 장전 전 또는 rate limit 이 풀린 뒤 order-fill 조회 복구가 필요하다.
- 금지/안전:
  - 실전 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-10] Codex -> 예측 정확도와 수익률 판단 분리

- 사용자 지시:
  - 매수 전용 paper 운용에서 매도 신호가 차단되더라도, 수익률 평가는 매수/매도 신호가 실제로 거래됐다고 보는 별도 replay가 필요하다는 권장안을 적용한다.
  - 예측 정확도만으로 승격 판단을 오해하지 않도록 신호 기준 가상 수익률과 실제 paper 체결 수익률을 분리해 보여준다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 장중 보호 모드가 아니므로 dashboard 코드, 테스트, snapshot 재생성, dashboard 서버 재시작을 진행했다.
- 조치:
  - `app/services/dashboard.py`에 `long_only_signal_replay` 요약을 추가했다.
    - `미보유+매수 허용`은 진입으로 계산한다.
    - `보유+매도 신호`는 현물 포지션 청산으로 계산한다.
    - `미보유+매도 신호`는 신규 숏이 아니라 진입 회피로 집계한다.
    - 왕복 슬리피지만 반영한 대시보드용 가상 수익률이며, 세금/수수료 정산 원장은 아니다.
  - 실제 paper 체결 원장은 FIFO 기준으로 맞춰 청산손익과 수익률을 별도로 집계한다.
  - 예측현황 요약에 `수익률 해석 분리`와 `신호 replay 기준` 카드를 추가했다.
  - 운영 콘솔의 모델 판단 카드에도 `신호 replay`와 `실제 paper 체결` 손익을 함께 표시한다.
  - `tests/test_dashboard.py`에 sell 신호가 신규 숏이 아니라 보유 포지션 청산으로 replay 되는지, 실제 paper fill 손익이 FIFO로 계산되는지 확인하는 회귀 테스트를 추가했다.
- 실제 2026-06-09 snapshot 확인:
  - `signal_replay_summary`: 관측 신호 `3799`, 진입 `578`, 청산 `578`, 신호 청산 `577`, 시간 청산 `1`, 미보유 매도 회피 `1526`, 추정 순손익 약 `-63,485원`, 거래합산 순수익률 약 `-9.07%`.
  - `paper_fill_return_summary`: FIFO 청산 `25건`, 승률 `56.0%`, 실제 paper 청산손익 약 `+10,687원`, basis 기준 수익률 약 `+0.075%`.
- 검증:
  - `python -m unittest tests.test_dashboard`: 21개 통과.
  - `python -m app --build-dashboard`: 통과, `generated_at=2026-06-10T05:20:26.972903+09:00`.
  - `runtime-data/reports/dashboard/latest-dashboard.json`: `signal_replay_summary`, `paper_fill_return_summary` 블록 존재 확인.
  - dashboard 서버 재시작 후 `./scripts/get_dashboard_status.sh`: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-10] Codex -> 예측 흐름 표 의미/수익 표시 개선

- 사용자 지시:
  - `예측 흐름` 표에서 baseline/LightGBM 모델별 예측 방향과 예상 변동 금액을 함께 보고 싶다.
  - 모델별 예측과 실제 결과를 15분/60분 단락으로 나눠 보고 싶다.
  - 신호 설명 폭을 줄이고 3줄 정도로 요약하고 싶다.
  - 2026-06-09 예측흐름에서 `매도 차단`인데 매도가 보이거나, `매수 허용`인데 매수가 없고 매도가 보이는 행의 원인을 설명하고 개선한다.
  - 체결 옆에 주문으로 인한 수익 금액과 수익률을 `+/-`로 표시한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 장중 보호 모드가 아니므로 dashboard 코드, 테스트, snapshot 재생성을 진행했다.
- 원인:
  - 과거 `paper_orders`에는 `prediction_id/signal_id`가 없어서 예측흐름이 동일 종목/동일 시각 주문을 보조 연결했다.
  - 이때 `paper-order-close-*` 포지션 관리용 청산 주문까지 신호 주문처럼 같은 칸에 붙어, `매도 차단인데 매도 체결`, `매수 허용인데 매도 주문`처럼 보였다.
  - 2026-06-09 기준 `serving_predictions`에는 baseline h15/h60 예측만 있고 LightGBM serving 예측 row는 없었다. 따라서 LightGBM 값은 생성된 것처럼 보이지 않게 `저장된 serving 예측 없음`으로 명시한다.
- 조치:
  - `app/services/dashboard.py`의 예측흐름 표를 15분/60분 단락형으로 바꿨다.
    - 모델별 예측: Baseline/LightGBM별 방향, 신뢰도, 예상 변동 금액/수익률 표시.
    - 실제 결과: 15분/60분별 실제 방향, 실제 변동 금액/수익률, 성공/실패/대기 표시.
  - `ops_risk_events`를 함께 읽어 신호 칸을 3줄 요약으로 바꿨다.
    - `신호`: 매수/매도, 허용/차단, 신뢰도.
    - `판단`: 시간 게이트, 스프레드 게이트, 매수전용 정책 등 전략 판단.
    - `실행`: 최대 보유종목 수, 브로커 미체결/조회 대기, 직전 청산 후 재진입 대기 등 주문 미발생 이유.
  - 예측흐름 주문 연결을 `신호 주문`과 `별도 청산`으로 분리했다.
    - `prediction_id/signal_id`가 있으면 우선 사용.
    - 추적 ID가 없는 과거 기록은 동일 종목/동일 시각 보조 연결하되, `paper-order-close-*`는 포지션 관리 청산 주문으로 따로 표시한다.
  - 체결 옆에 `수익` 열을 추가했다.
    - 같은 종목의 매수/매도 체결을 FIFO 기준으로 맞춰 paper 표시용 실현손익과 수익률을 계산한다.
    - 미체결/거절 주문은 `체결 없음`, 매수 진입은 `실현손익 대기`로 표시한다.
  - 예측흐름 표 전용 CSS를 추가해 멀티라인 줄바꿈을 보존하고 신호 칸 폭을 좁혔다.
  - `tests/test_dashboard.py`에 청산 주문이 신호 주문으로 오인되지 않고 수익이 표시되는 회귀 테스트를 추가했다.
- 실제 2026-06-09 확인:
  - `LG에너지솔루션 (373220)` 15:19 행은 `매수 차단`, `주문 없음`, `실행: 브로커 미체결/조회 대기`로 표시된다.
  - 09:39 같은 청산 행은 `신호: 매수 허용`, `실행: 직전 청산 후 재진입 대기`, `주문: 별도 청산`, `수익: 청산 +2,243원 (+0.58%)`로 분리된다.
  - 10:53 같은 매도 차단 행은 `매수전용 정책으로 매도 차단`과 `별도 청산`이 분리되어, 신호 매도와 포지션 청산 매도가 다른 흐름임을 표시한다.
- 검증:
  - `python -m py_compile app/services/dashboard.py tests/test_dashboard.py`: 통과.
  - `python -m unittest tests.test_dashboard.DashboardTests.test_prediction_flow_separates_close_orders_and_shows_profit`: 통과.
  - `python -m unittest tests.test_dashboard`: 19개 통과.
  - `python -m app --build-dashboard`: 통과, `generated_at=2026-06-10T04:03:13.714366+09:00`.
  - `http://127.0.0.1:8765/api/dashboard.json?range=day&date=2026-06-09`: `prediction_flow_rows=3799`, `first_flow_no=1`, `profit_text` 포함 확인.
  - dashboard 서버 재시작 후 `./scripts/get_dashboard_status.sh`: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
- 운영 상태:
  - dashboard: `http://127.0.0.1:8765`, 새 PID `29000`.
  - runtime watchdog: 기존 PID `23954`, `errors=[]`, `heartbeat_stale=false`.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-10] Codex -> 예측 흐름 일자 선택 전체 표시 보정

- 사용자 지시:
  - `예측 흐름`이 마지막 시각 예측만 보여서 모두 `결과 없음`으로 보인다.
  - 요일/일자를 선택하면 하루치가 모두 보이고, 장 시작 시각부터 순서대로 보이게 한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main`.
- 원인:
  - `예측 흐름`은 `recent_limit=100`으로 잘린 최신 예측만 표시했고, 정렬도 최신순이었다.
  - 따라서 2026-06-09 같은 장마감 이후 화면에서는 15:19 예측이 먼저 나오고, 15분/60분 미래 결과가 없는 행이 집중됐다.
- 조치:
  - `app/services/dashboard.py`에서 하루 단위 기간(`today`, `day`)이면 `prediction_flow_rows`를 제한 없이 만들고, 장 시작 시각부터 오름차순으로 정렬하게 했다.
  - 3일/7일/30일/전체 기간은 대시보드 부하를 막기 위해 기존처럼 최신 제한을 유지한다.
  - `예측 흐름` 안내 문구에 일자 선택 화면은 하루 전체 흐름을 장 시작 시각부터 보여준다고 명시했다.
  - `tests/test_dashboard.py`에 일자 선택 시 전체 8개 예측 흐름이 10:00부터 10:07까지 오름차순으로 표시되는 회귀 테스트를 추가했다.
  - dashboard 서버와 runtime watchdog 을 장외 상태에서 재시작해 최신 코드가 반영되게 했다.
- 검증:
  - `python3 -m py_compile app/services/dashboard.py`: 통과.
  - `python3 -m unittest tests.test_dashboard.DashboardTests.test_dashboard_prediction_detail_shows_all_selected_predictions`: 통과.
  - `python3 -m unittest tests.test_dashboard`: 18개 통과.
  - `python3 -m app --build-dashboard`: 통과, `generated_at=2026-06-10T03:04:36.299005+09:00`.
  - 실제 API `range=day&date=2026-06-09` 확인:
    - `prediction_flow_full_day=true`
    - `prediction_flow_rows=3799`
    - 첫 행 `2026-06-09T09:00:00+09:00`
    - 마지막 행 `2026-06-09T15:19:00+09:00`
    - 첫 행 실제 결과는 성공/실패 판정이 채워지고, 마지막 장마감 직전 행만 결과 없음으로 남는다.
- 운영 상태:
  - dashboard: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
  - runtime watchdog: `status=running`, `heartbeat_stale=false`.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-10] Codex -> 예측-신호-주문-체결 흐름 추적 보강

- 사용자 지시:
  - 예측 상세가 날짜별로 저장되는지 확인하고, 저장 필요성을 검토한다.
  - 예측, 모델별 판단, 실제 결과, 신호, 주문, 체결을 한 줄의 흐름으로 보고 싶다.
  - 최소 6개월 보관, 용량 부담이 작고 유용하면 장기 보관하는 방향을 검토한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 장중 보호 모드는 아니므로 dashboard, paper 주문 추적 필드, 저장 테스트를 수정했다.
- 확인:
  - `runtime-data/dev.db` 기준 `serving_predictions`는 `2026-04-11`부터 `2026-06-09`까지 182,653건, `serving_trade_signals`는 91,327건, `paper_orders`는 3,876건, `paper_fills`는 1,395건이었다.
  - 날짜별 JSONL 원장도 이미 존재한다.
    - `runtime-data/serving/YYYY-MM-DD/predictions.jsonl`
    - `runtime-data/serving/YYYY-MM-DD/trade_signals.jsonl`
    - `runtime-data/paper/YYYY-MM-DD/orders.jsonl`
    - `runtime-data/paper/YYYY-MM-DD/fills.jsonl`
  - `runtime-data/serving`은 약 104MB, `runtime-data/paper`는 약 5.5MB였다. 예측/신호/주문/체결 lineage 원장은 6개월 이상 보관해도 부담이 작고, 감사/모델 개선/PC 이전 연속성에 유용하다고 판단했다.
  - 반대로 `runtime-data/dev.db` 전체는 약 12GB로, 대용량 부담은 예측 lineage보다 raw/feature/label 계열에서 크므로 보관 정책은 분리하는 것이 맞다.
- 조치:
  - `app/services/dashboard.py`에 `예측현황 > 예측 흐름` 하위 탭을 추가했다.
    - 한 줄에 시각, 종목, 15분/60분 모델별 예측, 실제 결과, 신호, 주문, 체결, 연결 방식을 표시한다.
    - 과거 주문처럼 추적 ID가 없는 기록은 동일 종목/동일 시각으로 보조 연결하고, 체결은 주문 ID 기준으로 연결한다.
  - `paper_orders`에 `prediction_id`, `signal_id`, `target_id` 선택 컬럼을 추가했다.
    - 기존 DB는 schema 초기화 시 `ALTER TABLE`로 컬럼만 추가된다.
    - 과거 주문은 `NULL`로 남고, 신규 paper 진입 주문부터 정확한 예측/신호/타깃 ID가 저장된다.
  - `app/paper_trading/engine.py`와 `app/services/streaming.py`를 연결해 신규 진입 주문이 예측 ID, 신호 ID, 타깃 ID를 함께 기록하도록 했다.
  - 전체 테스트 중 `tests.test_market_status_probe`의 스크립트 fixture가 현재 날짜에 따라 stale 처리되는 시간 의존 실패를 확인했다.
    - 변경 전: `probe_market_status_snapshot.py`가 항상 현재 시각으로 manual snapshot 신선도를 평가해, 고정 fixture 날짜가 지나면 테스트가 실패했다.
    - 변경 후: 운영 기본값은 현재 시각 그대로 두고, 테스트/재현 실행에서만 `--checked-at`으로 기준 시각을 고정할 수 있게 했다.
    - 영향 범위: `scripts/probe_market_status_snapshot.py`와 해당 스크립트 테스트.
    - 회귀 위험: 운영 실행에서 `--checked-at`을 잘못 쓰면 stale 판단을 우회할 수 있으나, 기본 실행은 기존처럼 현재 시각 기준이며 테스트 재현용 옵션으로만 사용한다.
  - dashboard 서버와 runtime watchdog 이 이전 코드 프로세스를 들고 있어, 장외 상태에서 둘 다 재시작해 최신 화면/API를 반영했다.
- 검증:
  - `python3 -m py_compile app/storage/contracts.py app/storage/sqlite_store.py app/paper_trading/engine.py app/services/streaming.py app/services/dashboard.py`: 통과.
  - `python3 -m py_compile scripts/probe_market_status_snapshot.py`: 통과.
  - `python3 -m unittest tests.test_sqlite_store`: 11개 통과.
  - `python3 -m unittest tests.test_dashboard tests.test_streaming_pipeline`: 28개 통과.
  - `python3 -m unittest tests.test_market_status_probe.MarketStatusProbeTests.test_script_generates_check_from_snapshot_file -v`: 통과.
  - `python3 -m unittest discover -s tests -p 'test_*.py'`: 368개 통과.
  - `python3 -m app --build-dashboard`: 통과, `generated_at=2026-06-10T02:21:19.376102+09:00`.
  - 실제 DB `paper_orders`에 `prediction_id`, `signal_id`, `target_id` 컬럼이 존재함을 확인했다.
  - `http://127.0.0.1:8765/` HTML에 `예측 흐름`이 포함되고, `/api/dashboard.json`에서 `prediction_flow_rows=100`이 반환됨을 확인했다.
- 보관 판단:
  - 권장안은 예측/신호/주문/체결 lineage 원장을 최소 6개월이 아니라 장기 보관으로 두는 것이다.
  - raw tick, feature snapshot, label, broker raw 응답은 별도 용량 정책으로 관리한다.
- 운영 상태:
  - dashboard: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
  - runtime watchdog: `status=running`, `heartbeat_stale=false`.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-10] Codex -> 대시보드 UI/UX 제로베이스 재구성

- 사용자 지시:
  - 현재 대시보드가 산만하고 찾기 어렵기 때문에, 제로베이스에서 다시 검토해 최대한 단순하게 재구성한다.
  - 사용자가 봐야 하는 항목은 빠뜨리지 않고, 통화 표시가 필요한 값에는 `원` 표기를 누락하지 않는다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `live_runtime_should_run=false`, `errors=[]`.
  - 장중 보호 모드는 아니므로 dashboard 렌더링 코드와 테스트를 수정했다.
- 조치:
  - `app/services/dashboard.py`의 v2 대시보드 화면을 좌측 내비게이션, 상단 명령 영역, 핵심 KPI 카드, `오늘/계좌/데이터·모델/예측·주문/운영` 탭 구조로 재구성했다.
  - 첫 화면 `오늘` 탭에 `오늘 해야 할 일`, `상태 요약`, `계좌 정합성 요약`, `모델 판단`, `챌린저 비교`를 배치해 장중/장후 확인 순서대로 볼 수 있게 했다.
  - 계좌/주문/체결/손익/수수료 등 금액 값은 `_money()`에서 `원`을 붙이도록 통일했고, 거래량은 `_number()`로 분리해 원화처럼 보이지 않게 했다.
  - 비율 값은 `_pct()`에서 `%`를 붙이도록 정리했다.
  - `#tab-ops` 같은 기존 해시 URL을 유지하되, 탭 패널 DOM id를 `data-tab-id`로 바꿔 브라우저 기본 앵커 스크롤 때문에 상단이 비어 보이는 문제를 막았다.
  - dashboard 서버와 runtime watchdog 이 이전 렌더러를 메모리에 들고 있어 스냅샷을 옛 UI로 덮는 현상을 확인했고, 장외 상태에서 둘 다 재시작해 새 코드가 반영되도록 했다.
  - `tests/test_dashboard.py`의 대시보드 문구/탭 구조 기대값을 새 UI 구조에 맞췄다.
- 검증:
  - `python3 -m py_compile app/services/dashboard.py`: 통과.
  - `python3 -m app --build-dashboard`: 통과, `generated_at=2026-06-10T01:06:05+09:00`.
  - `python3 -m unittest tests.test_dashboard`: 18개 통과.
  - Edge headless 로 `http://127.0.0.1:8765/#tab-ops` 데스크톱/모바일 폭을 캡처해 상단 공백 제거, 주요 카드, 금액 `원` 표기를 확인했다.
  - D드라이브 `D:\CodexData\Real-time-stock-price-prediction-program\qa-temp`에 만든 검증용 스크린샷/브라우저 프로필은 확인 후 삭제했다.
- 운영 상태:
  - dashboard: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
  - runtime watchdog: `status=running`, `heartbeat_stale=false`.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-09] Codex -> 첨부 KIS 모의계좌 화면 기준 paper/KIS 정합성 조치

- 사용자 지시:
  - KIS 모의계좌 잔고, 거래내역, 기간별 수익률 화면을 첨부했고 조치할 것이 있으면 조치한다.
- 시작 상태:
  - 현재 시각: `2026-06-09T19:39:14+09:00`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`, live runtime 은 `2026-06-09 15:30:47 +0900`에 정상 정지.
  - `./scripts/get_runtime_watchdog_status.sh`: 재부팅/세션 이후 stale PID 상태였고 실제 프로세스는 없었다.
  - `./scripts/get_dashboard_status.sh`: stale PID 상태였고 dashboard/API 응답이 없었다.
  - `git status --short --branch`: `main...origin/main`.
- 첨부 화면 확인:
  - 누적 수익률: `-6.98%`, 손익금액 `-698,243원`, 기초자산 `10,000,000원`, 평가시점자산 `9,301,757원`.
  - 주간 2026-06-09: 수익률 `-0.60%`, 손익금액 `-56,332원`.
  - 계좌잔고: 보유종목 없음, 예수금총액 `8,009,590원`, 총평가금액/일일정산액/D+2정산액 `9,301,757원`.
  - 거래내역: 2026-06-09에 `373220` LG에너지솔루션 매도 체결이 여러 건 있으며, 마지막 화면 기준 보유 잔고가 0으로 정리됐다.
- 자동화 확인:
  - 장전 readiness: `generated_at=2026-06-09 08:20:01 +0900`, `status=ok`.
  - 장후 ML maintenance: `completed_at=2026-06-09 16:09:51 +0900`, `status=ok`.
  - 장후 label refresh: 최신 상태 파일은 `2026-06-08 16:43:21 +0900`, `status=ok`로 남아 있었다.
  - KIS live data quality: latest trade date `2026-06-09`, `assessment.status=watch`.
    - intraday coverage 는 raw market `97.6215%`, minute bar/feature `97.3657%`로 정상 범위다.
    - watch 이유는 당일 h15 label coverage 가 아직 낮다는 신선 데이터 주의다.
- 조치:
  - watchdog 과 dashboard 를 재기동했다.
    - watchdog: `status=running`, `errors=[]`.
    - dashboard: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
  - `python3 -m app --sync-broker-paper-orders`를 cooldown 뒤 재실행했으나 KIS `EGW00201` rate limit 이 유지됐고, local 쪽에는 open order 5건이 남아 있었다.
  - `python3 -m app --reconcile-paper-accounts` 결과 broker 는 보유 0, local 은 5종목 보유로 `needs_review`였다.
    - broker effective cash/total asset 은 첨부 화면과 같은 `9,301,757원`.
    - local snapshot 은 `2026-06-09T14:42:59+09:00` 기준이라 장후 실제 계좌 상태를 따라오지 못했다.
  - broker account snapshot 이 정상/최신이고 첨부 화면상 보유종목이 없으므로, 다음 거래일 기준선 보호를 위해 `-SyncInitialCash` 없이 `python3 -m app --align-local-paper-to-broker` marker-only alignment 를 적용했다.
  - 조치 후:
    - `python3 -m app --sync-broker-paper-orders`: `status=no_submissions`, `open_order_count=0`.
    - `python3 -m app --reconcile-paper-accounts`: `ok=true`, `status=aligned_waiting_first_submission`, mismatch 0, `cash_gap=0`, `total_asset_gap=0`.
    - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
  - `scripts/wsl_ops.py`의 dual-account 검증에서 marker-only 정렬 상태를 인식하도록 보강했다.
    - 변경 전: 거래 후 계좌가 flat 이어도 `PAPER_INITIAL_CASH`가 KIS 원시 예수금과 다르면 `initial_cash_mismatch`로 실패했다.
    - 변경 후: `aligned_to_broker_marker`와 `aligned_waiting_first_submission`이 동시에 확인되고 계좌 비교가 이미 일치하면 초기 예수금 검사를 건너뛰고 사유를 `broker_alignment_marker_active`로 기록한다.
    - 영향 범위: `scripts/verify_paper_dual_account_match.sh`가 호출하는 WSL 운영 helper의 리포트 판정.
    - 회귀 위험: marker 파일이 잘못 남아 있으면 초기 예수금 불일치 감지가 약해질 수 있으나, reconciliation 이 `ok`이고 mismatch/cash/total gap 이 모두 일치하는 경우에만 skip 하도록 제한했다.
  - `python3 -m app --build-runtime-report`는 shell timeout 이 발생했지만 파일은 `2026-06-09 19:56:32 +0900`로 갱신됐고 남은 프로세스는 없었다.
  - `python3 -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-06-09T20:01:02+09:00`.
  - PC 재부팅 후 추가 확인:
    - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, live runtime 정지 상태 정상.
    - `./scripts/get_runtime_watchdog_status.sh`와 `./scripts/get_dashboard_status.sh`: 재부팅 전 PID가 남은 `stale` 상태였다.
    - `./scripts/start_runtime_watchdog_background.sh`와 `./scripts/start_dashboard_background.sh`로 재기동했다.
    - 재기동 후 watchdog 은 `status=running`, `errors=[]`, dashboard 는 `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
    - 재부팅 전 WSL `git push` timeout 으로 로컬 `main`이 원격보다 1커밋 앞선 상태였고, Windows Git fallback 으로 `3ba6ca9` 푸시를 완료했다.
- 검증:
  - `python3 -m unittest tests.test_wsl_ops`: 16개 통과.
  - `bash -n scripts/verify_paper_dual_account_match.sh`: 통과.
  - `./scripts/verify_paper_dual_account_match.sh -AsJson`: 통과, `status=matched_waiting_first_submission`.
- 남은 주의:
  - KIS order-fill endpoint 는 오늘도 `EGW00201`를 반환했으므로 같은 endpoint 추가 호출은 중단했다.
  - order-level fill 감사가 완전히 복구된 것은 아니고, 이번 조치는 broker account snapshot 과 첨부 화면을 기준으로 다음 거래일 paper baseline 을 보호한 것이다.
  - 장후 label refresh 최신 상태 파일이 2026-06-08 기준으로 남아 있어 다음 장후 자동화에서 갱신 여부를 다시 확인한다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-09] Codex -> ML dashboard 챌린저 승격 표기 정리

- 사용자 질문:
  - 장중 점검 필요성, 예수금 미일치 반복 원인, 데이터 품질 `watch` 이유, 모델 정확도 위치, 챌린저 지표 의미, `fresh_centroid` 승격 가능 표기, 학습 상태와 수익률 반영 여부를 확인했다.
- 확인:
  - 현재 시각 기준 장 상태는 `post-close`, live runtime 은 `stopped` 정상, watchdog/dashboard 는 `running`.
  - 최신 paper/KIS dual-account match 는 `ok=true`, `status=matched_waiting_first_submission`.
    - KIS 원시 예수금과 총평가금액 차이는 KIS 표시 항목 차이이고, reconciliation 은 총평가금액 기준 유효현금으로 `cash_gap=0`, `total_asset_gap=0`이다.
  - KIS live data quality 는 `assessment.status=watch`.
    - raw market/분봉/feature coverage 는 97%대라 장중 수집 자체는 정상 범위다.
    - watch 이유는 최신 거래일의 h15/h60 label 이 아직 닫히지 않은 상태로 남아 있기 때문이다.
  - 최신 학습 모델은 `lightgbm-h15-v1`, 학습 validation 정확도는 `41.46%`, challenger holdout 에서 latest_lightgbm 정확도는 `39.10%`, 거래 적중률은 `60.00%`, 거래 수는 10건이다.
  - 실제 활성 모델은 `baseline-h15-v1`이고, challenger report 는 `recommended_action=keep_active`, `promotion_applied=false`다.
- 조치:
  - `app/services/dashboard.py`의 챌린저 비교 표에서 `승격 가능`을 `평가 자격`으로 바꾸고, `승격 판단`과 `거래 수`를 별도 표시했다.
  - `fresh_centroid`처럼 독립 holdout 평가 자격은 있지만 거래 수 0, 거래 적중률 0, 누적 순수익률 0인 후보는 화면에서 `승격 판단=관찰`로 보이게 했다.
  - 실제 승격/유지 판단은 `recommended_action`, `promotion_applied`, 워크포워드 게이트를 함께 보도록 설명 문구를 보강했다.
  - dashboard snapshot 을 `generated_at=2026-06-10T00:04:43+09:00`로 재생성했다.
- 검증:
  - `python3 -m unittest tests.test_dashboard.DashboardTests.test_challenger_decision_label_distinguishes_eligibility_from_promotion tests.test_dashboard.DashboardTests.test_challenger_dashboard_guard_marks_legacy_lightgbm_not_promotable`: 통과.
  - `python3 -m app --build-dashboard`: 통과.
- 남은 주의:
  - 장중 점검은 필요하다. 권장안은 장중 1회 read-only 점검으로, broker/KIS 정합성, 수집 coverage, dashboard freshness 만 확인하고 code/schema/runtime restart 는 하지 않는 방식이다.
  - 장후 label refresh 최신 상태 파일은 아직 2026-06-08 기준이라 다음 장후 자동화에서 2026-06-09 라벨 마감 여부를 다시 본다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-08] Codex -> Daily Ops Check와 paper/KIS 장후 정합성 복구

- 사용자 지시:
  - `.agents/skills/daily-ops-check/SKILL.md` 기준으로 운영 상태를 확인한다.
- 시작 상태:
  - 현재 시각: `2026-06-08T21:34:26+09:00`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`, live runtime 은 `2026-06-08 15:30:58 +0900`에 정상 정지.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - `./scripts/get_dashboard_status.sh`: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
  - `git status --short --branch`: `main...origin/main`, 최신 커밋 `4e287ae reboot-overnight-runtime-restore`.
- 자동화 확인:
  - 장전 readiness: `generated_at=2026-06-08 08:20:02 +0900`, `status=ok`, blockers/warnings 없음.
  - 장후 ML maintenance: `completed_at=2026-06-08 16:11:44 +0900`, `status=ok`.
  - 장후 label refresh: `completed_at=2026-06-08 16:43:21 +0900`, `status=ok`.
  - KIS live data quality: latest trade date `2026-06-08`, `assessment.status=watch`.
    - watch 이유는 최신일 market tick/minute bar/feature coverage 가 기대 symbol-minute 의 95% 미만이라는 진단이다.
  - local setup: `ok=true`, blockers/warnings 없음.
- 조치:
  - `python3 -m app --sync-broker-paper-orders`를 cooldown 뒤 1회 재시도했다.
  - 결과는 KIS `EGW00201` rate limit 유지, `open_order_count=2`, pending symbols `005380`, `247540`.
  - 같은 order-fill endpoint 추가 호출은 중단했다.
  - `python3 -m app --reconcile-paper-accounts` 재계산 결과 수량 mismatch 0이지만 `cash_gap=40037.439979999326`, `total_asset_gap=52237.43998000026`로 `needs_review`였다.
  - DB/read-only 확인 결과 open 2건은 모두 `2026-06-08` 당일 sell close 주문이고 최신 snapshot 기준 체결수량 0, 잔량 전체 유지였다.
    - `005380`: sell 1주, filled 0, remaining 1, status `open`.
    - `247540`: sell 4주, filled 0, remaining 4, status `open`.
  - broker account snapshot 은 정상/최신이고 보유 수량은 local 과 일치했으므로, 다음 거래일 기준선 보호를 위해 `-SyncInitialCash` 없이 `python3 -m app --align-local-paper-to-broker` marker-only alignment 를 적용했다.
  - 조치 후:
    - `python3 -m app --sync-broker-paper-orders`: `status=no_submissions`, `open_order_count=0`.
    - `python3 -m app --reconcile-paper-accounts`: `ok=true`, `status=aligned_waiting_first_submission`, mismatch 0, `cash_gap=0`, `total_asset_gap=0`.
    - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
  - `python3 -m app --build-runtime-report`: 통과.
  - `python3 -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-06-08T21:44:01+09:00`.
- 남은 주의:
  - KIS order-fill endpoint 는 오늘도 `EGW00201`를 반환했으므로, 같은 endpoint 추가 호출은 중단했다.
  - order-level fill 감사가 완전히 복구된 것은 아니고, 이번 조치는 broker account snapshot 을 기준으로 다음 거래일 paper baseline 을 보호한 것이다.
  - KIS live data quality `watch`가 2026-06-05에 이어 반복됐으므로 최신일 coverage 미달 원인을 별도 확인 대상으로 둔다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-08] Codex -> PC 재부팅 후 overnight runtime 복구

- 사용자 지시:
  - PC 재부팅 후 상태를 체크하고 필요한 프로세스를 실행한다.
- 시작 상태:
  - 현재 시각: `2026-06-08T02:05:37+09:00`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: 재부팅 전 PID가 남은 `status=stale`, `process_running=false`.
  - `./scripts/get_dashboard_status.sh`: 재부팅 전 PID가 남은 `status=stale`, dashboard/API 응답 없음.
  - `./scripts/get_runtime_startup_launcher_status.sh`: Windows startup launcher 설치 상태 `ok=true`.
  - `git status --short --branch`: `main...origin/main`, 최신 커밋 `8be7aa9 reboot-ops-recovery`.
- 조치:
  - 현재 장 상태는 `overnight`이고 `live_runtime_should_run=false`라 live runtime은 켜지 않았다.
  - `./scripts/start_runtime_watchdog_background.sh`로 watchdog을 재기동했다.
  - `./scripts/start_dashboard_background.sh`는 최초 응답이 `failed`였지만, watchdog이 dashboard를 `restart`했고 이후 dashboard/API 응답이 정상화됐다.
  - `./scripts/check_local_setup.sh`: `ok=true`, blockers/warnings 없음.
  - `python3 -m app --build-runtime-report`: 통과.
  - `python3 -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-06-08T02:12:44+09:00`.
- 판단:
  - 장전 readiness와 장중 live runtime은 아직 시간상 실행 대상이 아니다.
  - watchdog이 이후 pre-open warmup 시점에 live runtime을 판단해 켜는 구조다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-05] Codex -> PC 재부팅 후 runtime 복구와 paper/KIS 정합성 조치

- 사용자 지시:
  - PC 재부팅 후 필요한 작업을 진행한다.
- 시작 상태:
  - 현재 시각: `2026-06-05T19:38:50+09:00`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`, live runtime 은 `2026-06-05 15:30:43 +0900`에 정상 정지.
  - `./scripts/get_runtime_watchdog_status.sh`: 재부팅 전 PID가 남은 `status=stale`, `process_running=false`.
  - `./scripts/get_dashboard_status.sh`: 재부팅 전 PID가 남은 `status=stale`, dashboard/API 응답 없음.
  - `git status --short --branch`: `main...origin/main`, 최신 커밋 `da2501d fix-stale-broker-paper-orders`.
- 자동화 확인:
  - 장전 readiness: `generated_at=2026-06-05 08:20:02 +0900`, `status=ok`, blockers/warnings 없음.
  - 장후 ML maintenance: `completed_at=2026-06-05 16:21:43 +0900`, `status=ok`.
  - 장후 label refresh: `completed_at=2026-06-05 16:53:25 +0900`, `status=ok`.
  - KIS live data quality: latest trade date `2026-06-05`, `assessment.status=watch`.
    - watch 이유는 최신일 market tick/minute bar/feature coverage 가 기대 symbol-minute 의 95% 미만이라는 진단이다.
  - local setup: `ok=true`, blockers/warnings 없음.
- 조치:
  - `./scripts/start_runtime_watchdog_background.sh`로 watchdog 재기동.
  - `./scripts/start_dashboard_background.sh`는 최초 응답이 `failed`였으나 watchdog 이 dashboard 를 재시작했고, 이후 dashboard/API 응답 정상.
  - `python3 -m app --sync-broker-paper-orders`를 cooldown 뒤 1회 재시도했다.
  - 결과는 KIS `EGW00201` rate limit 유지, `open_order_count=5`, pending symbols `005380`, `035420`, `068270`, `086520`, `247540`.
  - 같은 order-fill endpoint 추가 호출은 중단했다.
  - DB/read-only 리포트 확인 결과 5건은 `2026-06-05` 당일 주문이었다.
    - `035420` buy 2주, `068270` buy 4주: 최신 snapshot 은 `open`.
    - `247540` sell 4주, `005380` sell 1주, `086520` sell 6주: snapshot 없는 `submitted`.
  - `python3 -m app --reconcile-paper-accounts` 재계산 결과 `mismatch_count=3`, `cash_gap=-716232.4992000014`, `total_asset_gap=56167.50079999864`.
  - broker account snapshot 은 정상/최신이고 장후라 다음 거래일 기준선 보호가 우선이므로, `-SyncInitialCash` 없이 `python3 -m app --align-local-paper-to-broker` marker-only alignment 를 적용했다.
  - 조치 후:
    - `python3 -m app --sync-broker-paper-orders`: `status=no_submissions`, `open_order_count=0`.
    - `python3 -m app --reconcile-paper-accounts`: `ok=true`, `status=aligned_waiting_first_submission`, mismatch 0, `cash_gap=0`, `total_asset_gap=0`.
    - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
  - `python3 -m app --build-runtime-report`: 통과.
  - `python3 -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-06-05T19:55:02+09:00`.
  - `./scripts/get_dashboard_status.sh`: `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
- Skill 보강:
  - `.agents/skills/daily-ops-check/SKILL.md`에 장후 order-fill rate limit 지속 + broker account snapshot 정상 + 다음 거래일 기준선 보호가 필요한 paper mirroring mismatch 의 제한적 marker-only alignment 기준을 추가했다.
  - 이 경로는 order-level fill 감사가 복구되지 않았다는 한계가 있으므로 logbook 기록을 필수로 둔다.
- 남은 주의:
  - `latest-kis-live-data-quality.json`은 `assessment.status=watch`다. 수집 latest trade date 는 `2026-06-05`로 맞지만, 최신일 coverage 미달 원인은 다음 장후에도 재확인한다.
  - KIS order-fill endpoint 는 오늘도 `EGW00201`를 반환했으므로, 같은 endpoint 추가 호출은 중단했다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-04] Codex -> broker paper stale open order 원인 해결과 정합성 복구

- 사용자 지시:
  - 장전/장후 자동화 이후 남은 이슈를 해결한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main`.
- 원인 분석:
  - `runtime-data/reports/broker-paper/latest-sync.json`은 KIS `EGW00201` rate limit, `open_order_count=3`, pending symbols `105560`, `247540`, `373220`였다.
  - 운영 DB read-only 확인 결과 3건은 모두 `order_date=20260602`인 과거 주문일 주문이었다.
    - `247540`: sell 3주, filled 0, remaining 3, status `open`.
    - `373220`: sell 1주, filled 0, remaining 1, status `open`.
    - `105560`: buy 3주, filled 0, remaining 3, status `open`.
  - 최신 broker 계좌와 local 계좌의 보유 수량 mismatch 는 0이었다.
  - 문제는 과거 주문일의 stale open snapshot 을 active open 으로 계속 세어 marker-only alignment 를 막는 구조였다.
- 코드 조치:
  - `app/services/broker_paper_sync.py`에 prior-day stale open 주문 해석을 추가했다.
  - 변경 전 / 변경 후 / 영향 범위 / 회귀 위험:
    - 변경 전: KIS order-fill 조회가 rate-limit 으로 막히면 과거 주문일 open snapshot 도 계속 active open 으로 계산했다.
    - 변경 후: 이미 broker status snapshot 이 있는 주문 중 주문일이 동기화일보다 이전이고 잔량이 남은 주문은 `expired` 또는 `expired_partial` final 상태로 해석한다.
    - 영향 범위: KIS 모의계좌 paper sync 의 상태 해석과 `tests/test_broker_paper_sync.py`.
    - 회귀 위험: 당일 주문을 잘못 만료 처리할 위험이 있으나, snapshot 이 없는 단순 제출 주문은 제외하고 prior-day snapshot 에만 적용해 줄였다.
- 운영 조치:
  - `python3 -m app --align-local-paper-to-broker`로 `-SyncInitialCash` 없이 marker-only alignment 를 적용했다.
  - alignment 결과: `status=aligned_to_broker_marker`, broker position count 2, broker cash balance 8,414,055원.
  - `python3 -m app --sync-broker-paper-orders`: `status=no_submissions`, `open_order_count=0`, pending symbols 없음.
  - `python3 -m app --reconcile-paper-accounts`: `ok=true`, `status=aligned_waiting_first_submission`, mismatch 0, `cash_gap=0`, `total_asset_gap=0`.
  - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
  - `python3 -m app --build-runtime-report && python3 -m app --build-dashboard && ./scripts/get_dashboard_status.sh`는 shell timeout이 발생했으나, 남은 build 프로세스가 없고 runtime report는 `2026-06-04 22:58:57 +0900`, dashboard snapshot은 `generated_at=2026-06-04T23:04:32+09:00`로 갱신됨을 확인했다.
  - dashboard server는 `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
- 문서/skill 보강:
  - `.agents/skills/daily-ops-check/SKILL.md`에 prior-day stale open 주문의 marker-only alignment 허용 조건과 보류 조건을 추가했다.
  - `docs/Current-Implementation.md`에 KIS 모의계좌 stale open 주문 해석 기준을 추가했다.
  - `docs/Production-Transition-Progress.md`의 Phase 0 상태를 최신 정상 상태로 갱신했다.
- 검증:
  - `python3 -m py_compile app/services/broker_paper_sync.py tests/test_broker_paper_sync.py`: 통과.
  - `python3 -m unittest tests.test_broker_paper_sync`: 7개 통과.
  - `python3 -m unittest tests.test_broker_paper_sync tests.test_paper_reconciliation`: 11개 통과.
  - `bash -n scripts/sync_broker_paper_orders.sh scripts/reconcile_paper_accounts.sh scripts/verify_paper_dual_account_match.sh`: 통과.
  - `git diff --check`: 통과. 기존 문서 CRLF 경고만 확인.
  - `git diff -- app/risk config VERSION`: 변경 없음.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-04] Codex -> 장전/장후 자동화 실행 확인과 rate-limit 재점검

- 사용자 질문:
  - 오늘 장전/장후 자동화가 된 것이 맞는지 확인 요청.
  - 스레드 선택 시 아무 내용이 보이지 않는다고 보고.
- 시작 상태:
  - 현재 시각: `2026-06-04T21:44:39+09:00`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `ml_maintenance_action=already_ok`.
  - `git status --short --branch`: `main...origin/main`.
- 자동화 실행 확인:
  - 장전 readiness: `2026-06-04 08:20:18 +0900`, `status=ok`, blockers/warnings 없음.
  - 장후 ML maintenance: `2026-06-04 16:18:21 +0900`, `status=ok`, `mode=quick-live-train`.
  - 장후 label refresh: `2026-06-04 16:50:21 +0900`, `status=ok`, `mode=post-close-label-refresh-live-db`.
  - KIS live data quality: `assessment.status=ok`, latest trade date `2026-06-04`.
  - local setup: `ok=true`, blockers/warnings 없음.
  - dashboard snapshot 자동화 산출물: `generated_at=2026-06-04T16:57:28+09:00`.
- 조치:
  - 장후 자동화 자체는 정상 실행된 것으로 확인했다.
  - broker paper sync는 자동화 시점에 KIS `EGW00201` rate limit으로 `status=rate_limited`였고 open order 3건(`105560`, `247540`, `373220`)이 남아 있었다.
  - cooldown 뒤 `python -m app --sync-broker-paper-orders`를 1회 재시도했으나 `EGW00201`가 계속되어 같은 endpoint 추가 호출을 중단했다.
  - `python -m app --reconcile-paper-accounts` 재계산 결과 포지션 mismatch 0, `cash_gap=41829.05498999916`, `total_asset_gap=41429.05498999916`, `status=needs_review`.
  - open order가 남아 있어 marker-only alignment는 보류했다.
  - `python -m app --build-runtime-report`: shell timeout처럼 보였으나 `runtime-data/reports/runtime/latest-runtime-report.json`이 `2026-06-04 21:55:32 +0900`로 갱신됨을 확인했다.
  - `python -m app --build-dashboard`: shell timeout처럼 보였으나 dashboard snapshot `generated_at=2026-06-04T21:56:15+09:00`로 갱신됨을 확인했다.
  - dashboard server는 `status=running`, `dashboard_responding=true`, `dashboard_api_responding=true`.
- 판단:
  - 자동화는 실행됐다.
  - 스레드 UI에 내용이 안 보이는 문제는 자동화 미실행과 별개로 보이며, 실제 결과는 `runtime-data/reports/` 아래에 남아 있다.
  - 현재 남은 운영 이슈는 KIS order-fill rate limit과 open broker order 3건이다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-02] Codex -> Daily Ops Check 실행과 open order 보류 기준 보강

- 사용자 지시:
  - `.agents/skills/daily-ops-check/SKILL.md` skill을 사용해 장전/장후 상태체크를 수행한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main`.
- 오늘 자동화 확인:
  - 장전 readiness: `status=ok`, blockers/warnings 없음.
  - 장후 ML maintenance: `status=ok`, `mode=quick-live-train`, completed `2026-06-02 16:14:41 +0900`.
  - 장후 label refresh: `status=ok`, `mode=post-close-label-refresh-live-db`, completed `2026-06-02 16:45:19 +0900`.
  - KIS live data quality: `assessment.status=ok`, latest trade date `2026-06-02`.
  - source drift: `source_drift_detected`.
  - feature diagnostics: `no_clear_single_feature_signal`.
  - local setup: `ok=true`, blockers/warnings 없음.
- 조치:
  - `python -m app --sync-broker-paper-orders`를 cooldown 뒤 1회 재시도했다.
  - 결과는 KIS `EGW00201` rate limit 유지, `status=rate_limited`, open order 3건, pending symbols `105560`, `247540`, `373220`.
  - 같은 order-fill endpoint 추가 호출은 중단했다.
  - `python -m app --reconcile-paper-accounts`로 계좌 조회 기반 정합성을 재계산했다.
  - 포지션 mismatch는 0건이지만 `cash_gap=25177.399659998715`, `total_asset_gap=24377.399659998715`로 `needs_review`가 유지됐다.
  - open broker order 3건이 남아 있으므로 marker-only alignment는 보류했다.
  - `python -m app --build-runtime-report`: 통과.
  - `python -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-06-02T18:52:39+09:00`.
- Skill/문서 보강:
  - `.agents/skills/daily-ops-check/SKILL.md`에 `open_order_count > 0`이고 order-fill 조회가 rate limit이면 align을 보류한다는 기준을 추가했다.
  - `docs/Codex-Operating-Feedback.md`와 `docs/Production-Transition-Progress.md`에 같은 기준과 오늘 상태를 반영했다.
- 남은 조치:
  - 다음 cooldown 또는 다음 장후에 broker paper sync를 1회 재시도한다.
  - open order 3건의 최종 상태가 확인되기 전에는 alignment로 gap을 덮지 않는다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-06-01] Codex -> 장전/장후 상태체크 조치와 Daily Ops skill 승격

- 사용자 지시:
  - 장전/장후 상태체크 결과를 확인하고 조치한다.
  - 이 절차를 저장소 전용 skill로 만든다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `ml_maintenance_action=already_ok`.
  - `git status --short --branch`: `main...origin/main`.
- 오늘 자동화 확인:
  - 장전 readiness: `status=ok`, blockers/warnings 없음.
  - 장후 ML maintenance: `status=ok`, `mode=quick-live-train`, completed `2026-06-01 16:14:29 +0900`.
  - 장후 label refresh: `status=ok`, `mode=post-close-label-refresh-live-db`, completed `2026-06-01 16:44:59 +0900`.
  - KIS live data quality: `assessment.status=ok`, latest trade date `2026-06-01`.
  - source drift: `source_drift_detected`.
  - feature diagnostics: `no_clear_single_feature_signal`.
  - broker paper sync: `status=ok`, KIS rate limit 없음.
  - local setup: `ok=true`, blockers/warnings 없음.
- 조치:
  - `python -m app --sync-broker-paper-orders`: `status=ok`, rate limit 없음.
  - `python -m app --reconcile-paper-accounts`: `needs_review`, 포지션 mismatch 0, `cash_gap=28937.82866`, `total_asset_gap=71937.82866`.
  - 원인은 로컬 paper portfolio 최신 snapshot이 `2026-05-29` 평가가격에 머문 상태에서 브로커 모의계좌가 `2026-06-01` 현재가를 쓰는 stale valuation 차이로 확인했다.
  - 보유 수량 mismatch가 없고 broker account 조회가 정상이라 `./scripts/verify_paper_dual_account_match.sh -AlignToBroker -AsJson`로 marker-only alignment를 적용했다.
  - 조치 후 dual match는 `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`, 포지션 mismatch 0이다.
  - `python -m app --build-runtime-report`: 통과.
  - `python -m app --build-dashboard`: 1회 shell timeout 후 timeout을 늘려 재실행했고, dashboard snapshot `generated_at=2026-06-01T18:58:47+09:00`로 갱신했다.
- Skill 승격:
  - `.agents/skills/daily-ops-check/SKILL.md`를 추가했다.
  - 장전/장후 자동화 결과 확인, paper/KIS 정합성 조치, dashboard/runtime 갱신, logbook 기록, 최종 보고 형식을 skill 절차로 고정했다.
  - `AGENTS.md`, `README.md`, `.agents/skills/README.md`, `docs/Codex-Operating-Feedback.md`, `docs/Production-Transition-Progress.md`에 새 skill과 오늘 상태를 반영했다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-05-29] Codex -> 반복 지적 체크리스트와 skill 후보 구조화

- 사용자 지시:
  - 반복해서 지적한 부분을 점검하고, MD에 반영할 수 있게 조치한다.
  - skill화할 수 있는 부분도 계속 체크할 수 있게 구조화한다.
- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`.
  - `git status --short --branch`: `main...origin/main`.
- 조치:
  - `docs/Codex-Operating-Feedback.md`를 추가했다.
  - 반복 지적을 작업 시작, 작업 중, 최종 답변 체크리스트로 나눴다.
  - commit/push 반복 문의 방지, 권장안 동반, 전체 흐름 중심 최종 답변,
    운영자 의미, NAS 명시 지시, side panel 친화 문서 기준을 한곳에 모았다.
  - skill 후보 판정 기준과 현재 후보
    `Daily Ops Check`, `Cowork Ping-Pong`, `Market-Safe Work Mode`,
    `Final Report Shape`, `Recovery And Backup Discipline`을 정리했다.
  - `AGENTS.md`와 `README.md`의 핵심 문서/문서 역할 목록에 새 문서를 추가했다.
  - `.agents/skills/README.md`에 skill 후보 관리 기준과 새 문서 링크를 추가했다.
- 현재 판단:
  - 지금은 실제 skill 파일을 만들기보다 체크리스트와 후보 관리 문서로 1차 고정한다.
  - 반복 누락이 계속되는 절차부터 `.agents/skills/` 아래의 저장소 전용 skill로 승격한다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`,
    `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음.

## [2026-05-29] Codex -> 장전/장후 자동화 확인과 paper/KIS 정합성 보강

- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `ml_maintenance_action=already_ok`.
  - `git status --short --branch`: `main...origin/main [ahead 4]`.
- 오늘 자동화 확인:
  - `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`: `status=ok`, blockers/warnings 없음.
  - `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`: `status=ok`, `mode=quick-live-train`.
  - `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`: `status=ok`.
  - `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`: `assessment.status=ok`, latest trade date `2026-05-29`.
  - `runtime-data/reports/data-quality/latest-kis-live-feature-source-drift.json`: `posture=source_drift_detected`.
  - `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.json`: `posture=no_clear_single_feature_signal`.
  - `runtime-data/reports/broker-paper/latest-sync.json`: `status=rate_limited`, KIS `EGW00201` 초당 거래건수 제한.
  - `runtime-data/reports/reconciliation/latest-paper-reconciliation.json`: 기존 `status=needs_review`, 큰 현금 갭 확인.
- 원인 분석:
  - `paper_portfolio_snapshots`에 같은 `event_time`을 가진 스냅샷이 여러 개 있었다.
  - 공통 SQLite helper가 `ORDER BY event_time DESC`만 사용해, 같은 시각의 최신 삽입 행 대신 오래된 행을 최신 스냅샷으로 고를 수 있었다.
  - 이 때문에 reconciliation이 오래된 open position/cash snapshot을 참조하며 약 104만 원 규모의 gap을 크게 보였다.
- 조치:
  - `app/storage/sqlite_store.py`의 최신/최근 행 조회를 `ORDER BY <time> DESC, rowid DESC`로 보강했다.
  - `tests/test_sqlite_store.py`에 동일 timestamp tie-break 회귀 테스트를 추가했다.
  - `app/services/broker_paper_sync.py`의 수동/배치 broker-paper sync는 KIS rate limit 완화를 위해 기본 재시도 간격을 `10/30/60/120초`로 늘렸다.
  - `tests/test_broker_paper_sync.py`에 app-level sync가 느린 배치 backoff를 쓰는지 잠갔다.
  - 수정 후 `python -m app --reconcile-paper-accounts` 기준 gap은 약 `1,042,508원`에서 `28,938원` 수준으로 줄었고 포지션 mismatch는 0건이다.
  - 남은 gap은 자동 align으로 덮지 않고, KIS 주문체결 조회 rate limit 해소 뒤 재확인 대상으로 남겼다.
- 실행/검증:
  - `python -m py_compile app/storage/sqlite_store.py app/services/broker_paper_sync.py tests/test_sqlite_store.py tests/test_broker_paper_sync.py`: 통과.
  - `python -m unittest tests.test_sqlite_store tests.test_broker_paper_sync tests.test_paper_reconciliation`: 19개 통과.
  - `python -m unittest tests.test_dashboard`: 17개 통과.
  - `python -m app --build-runtime-report`: 통과.
  - `python -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-05-29T18:31:42+09:00`.
  - 대시보드 서버 재시작 후 `./scripts/get_dashboard_status.sh`: `status=running`, dashboard/api 응답 정상.
- 남은 조치:
  - KIS order fill 조회 endpoint는 오늘 여러 번 `EGW00201` rate limit을 반환했으므로 추가 호출을 중단했다.
  - 다음 장후 또는 충분한 cooldown 뒤 broker-paper sync를 1회 재시도하고, 잔여 `cash_gap=28,937.82866`을 재평가한다.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - NAS 백업 실행 없음. 현재 정책대로 명시 지시가 있을 때만 실행한다.

## [2026-05-28] Codex -> NAS 백업 실행 기준 변경

- 사용자 지시:
  - NAS 백업은 용량이 크고 너무 잦으므로 앞으로 지시할 때만 실행한다.
- 조치:
  - `AGENTS.md`, `README.md`, `RECOVERY.md`의 NAS 백업 정책을 갱신했다.
  - `docs/Production-Transition-Progress.md`에 현재 기준을 추가했다.
- 현재 기준:
  - Codex는 주간/강제 NAS 백업을 자율 실행하지 않는다.
  - 코드 변경, 장후 조치, Phase readiness 생성, release/복구 직전이라도 자동 실행하지 않는다.
  - 사용자가 해당 작업에서 `NAS 백업 실행`처럼 명시적으로 지시한 경우에만 실행한다.
- 금지/안전:
  - 실제 NAS 백업 실행 없음.
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-28] Codex -> 대시보드 운영 콘솔형 UI 정리

- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`.
  - `git status --short --branch`: `main...origin/main [ahead 2]`.
- 조치:
  - 대시보드 첫 화면을 `운영 콘솔`로 바꿨다.
  - 첫 화면에 Phase readiness, 계좌 정합성, 데이터 품질, 장후 파이프라인, 실전 주문 안전 상태를 먼저 보이도록 정리했다.
  - 기존 10개 상위 탭을 `운영 콘솔`, `계좌`, `ML/데이터`, `예측/주문`, `리포트/설정` 5개로 묶었다.
  - 기존 상세 카드와 표는 제거하지 않고 각 묶음 탭 안에 보존했다.
  - 대시보드 색상과 카드 반경을 운영 도구형으로 정리하고 첫 화면의 과도한 히어로 느낌을 줄였다.
- 실행/검증:
  - `python -m py_compile app/services/dashboard.py`: 통과.
  - `python -m unittest tests.test_dashboard`: 17개 통과.
  - `python -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-05-28T22:40:46+09:00`.
  - 대시보드 서버만 재시작했고 `http://127.0.0.1:8765` 응답 HTML에서 `운영 콘솔`, `Phase readiness`, `tab-ops` 노출을 확인했다.
  - Codex in-app browser에서 `운영 콘솔` 표시, `계좌` 탭 전환, 콘솔 error/warn 0건을 확인했다.
  - 스크린샷 캡처는 in-app browser의 `Page.captureScreenshot` 명령이 타임아웃되어 남기지 못했다.
- 커밋/백업:
  - 로컬 커밋을 생성했다.
  - forced NAS backup 완료:
    `/mnt/backup/repos/real-time-stock-price-prediction-program/recovery-exports/real-time-stock-price-prediction-program-recovery-20260528-224455.tar.gz`
    (`5558128973` bytes).
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-28] Codex -> 장후 paper/KIS 모의계좌 정합성 조치

- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `ml_maintenance_action=already_ok`.
  - `./scripts/get_dashboard_status.sh`: `status=running`, dashboard/api 응답 정상.
- 장후 체크 결과:
  - `latest-post-close-ml.json`: `status=ok`, `mode=quick-live-train`.
  - `latest-post-close-label-refresh.json`: `status=ok`.
  - `latest-kis-live-data-quality.json`: `assessment.status=ok`.
  - `latest-local-setup-check.json`: `ok=true`, blockers/warnings 없음.
  - `latest-paper-dual-account-match.json`: `status=initial_cash_mismatch`, `ok=false`.
- 조치:
  - `./scripts/verify_paper_dual_account_match.sh -SyncInitialCash -AlignToBroker -AsJson` 실행.
  - 로컬 paper 기준선을 KIS 모의계좌 기준으로 정렬했다.
  - 정렬 후 `paper_initial_cash_after=8748211`.
  - 브로커 유효현금 기준 `cash_gap=0`, `total_asset_gap=0`, 포지션 mismatch 0.
  - KIS raw cash와 effective cash 사이에는 `raw_cash_gap=747827`이 남지만, 이 값은 브로커 유효현금 계산 기준과 raw cash 표시의 차이로 따로 기록한다.
- 후속 갱신:
  - `./scripts/reconcile_paper_accounts.sh`: `ok=true`, `status=aligned_waiting_first_submission`.
  - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
  - `python -m app --build-runtime-report`: 통과.
  - `./scripts/check_local_setup.sh`: `ok=true`, blockers/warnings 없음.
  - `python -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-05-28T20:12:27+09:00`.
- 금지/안전:
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-28] Codex -> Phase 1a KIS 모의투자 read-only 리허설 진행

- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=overnight`, `live_runtime_should_run=false`.
  - `git status --short --branch`: `main...origin/main`.
- 구현:
  - `app/services/live_phase_readiness.py`에 `phase1a_paper_readonly` readiness 프로필을 추가했다.
  - Phase 1a 필수 check는 `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`다.
  - `market_status`와 `kill_switch`는 Phase 1a에서는 비차단 관측 항목으로 기록한다.
  - 기존 `phase1_readonly`, Phase 2, Phase 3 기준은 그대로 보수적으로 유지한다.
- 실행:
  - `./scripts/check_local_setup.sh`: `ok=true`.
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`: `status=ok`.
  - `./scripts/probe_kis_token_refresh.sh`: `status=ok`, `mode=paper`.
  - `./scripts/probe_kis_account_snapshot.sh`: `status=ok`, `mode=paper`, position row 2개.
  - `./scripts/probe_kis_ws_recovery.sh`: `status=ok`, synthetic fault injection.
  - `./scripts/probe_kis_clock_reference.sh`: `status=ok`, KIS paper read-only current-price HTTP `Date` 기준 skew 약 `0.628s`.
  - `./scripts/build_live_readiness_fixture_snapshot.sh`: local fixture snapshot 갱신.
  - `./scripts/run_live_readiness_dry_run.sh --phase phase1a_paper_readonly --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --report-path runtime-data/reports/live-readiness/latest-readiness.json`: `status=ok`, `passed=true`.
  - `market_status_fault_dry_run_failed`, `kill_switch_fault_dry_run_failed`는 non-blocking reasons로 남겼다.
  - `python -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-05-28T05:14:31+09:00`.
- 검증:
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 29개.
  - `python -m py_compile app/services/live_phase_readiness.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 다음:
  - Phase 1a는 1차 리허설 통과.
  - 다음 권장 작업은 Phase 1b 실전 계좌 read-only shape 확인 준비다.

## [2026-05-28] Codex -> 진행상태 문서 sidebar 호환 정리와 Phase 1 분리

- 원인/조치:
  - `docs/Production-Transition-Progress.md`가 메모장에서는 열리지만 Codex sidebar에서 열리지 않는 문제가 있었다.
  - 파일은 UTF-8이었지만 긴 표 행이 많아 sidebar markdown/file viewer가 불안정할 수 있는 구조였다.
  - 긴 표 중심 문서를 짧은 section/bullet 중심 문서로 재구성했다.
  - 파일은 UTF-8 text이고 220자 초과 줄이 없음을 확인했다.
- Phase 1 정리:
  - Phase 1a를 KIS 모의투자 read-only 리허설로 분리했다.
  - Phase 1b를 실전 계좌 read-only 확인으로 분리했다.
  - Phase 1a는 지금 모의투자계좌로 진행 가능하다.
  - Phase 1b는 실제 자금 운용 전 실전 계좌 응답 shape와 권한 차이를 확인하기 위해 필요하다.
- 실전 계좌 read-only 방법:
  - KIS 실전 credentials는 git 추적 파일이나 문서에 기록하지 않는다.
  - `ALLOW_LIVE_ORDERS=false`를 유지한다.
  - 주문 메서드가 없는 read-only client로 token/account/current-price probe만 실행한다.
  - raw response와 계좌번호는 저장하지 않고 sanitized shape/count만 readiness 증거로 남긴다.
- 검증:
  - `git diff --check` 통과.
  - `file docs/Production-Transition-Progress.md`: UTF-8 text.
  - `grep -n -E ".{221}" docs/Production-Transition-Progress.md`: 결과 없음.
  - 실전 주문, live account 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-28] Codex -> 장전 운영 준비 작업

- 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=overnight`, `live_runtime_should_run=false`, `errors=[]`.
  - `./scripts/get_dashboard_status.sh`: `status=running`, dashboard/api 응답 정상.
- 장전 점검:
  - `./scripts/check_local_setup.sh`: `ok=true`, blockers/warnings 없음.
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`: `status=ok`, blockers/warnings 없음.
  - `./scripts/start_runtime_autoboot.sh` 기본 실행은 `--cleanup-runtime-test-data` 단계가 5분 이상 CPU/메모리를 크게 쓰며 장전 병목이 되어 종료했다. 과거 기록에도 이 cleanup이 DB lock으로 live runtime을 방해한 이력이 있어 장전 fast-start에서는 cleanup을 건너뛰는 것이 맞다.
  - `scripts/script_dispatch.sh`의 Windows startup launcher 명령을 `./scripts/start_runtime_autoboot.sh --skip-runtime-cleanup --skip-dashboard-build`로 보강했고, `./scripts/install_runtime_startup_launcher.sh`를 재실행해 실제 `RealTimeStockRuntime.cmd`도 갱신했다.
  - `./scripts/start_runtime_autoboot.sh --skip-runtime-cleanup --skip-dashboard-build`: `ok=true`, `market_session_status=overnight`, live runtime 중지 유지.
- readiness 증거:
  - `token_refresh`: 통과, KIS paper auth-only token refresh 성공.
  - `account_snapshot`: 통과, KIS paper account read-only snapshot shape 정상, position row 2개.
  - `ws_recovery`: 통과, synthetic fault injection 기준.
  - `system_clock`: 통과, KIS paper current-price read-only HTTP Date 기준 skew 약 `0.166s`.
  - `system_clock paper/live comparison`: blocked, live reference time 미확보. 주문은 없었고 read-only quote 비교만 시도했다.
  - `market_status`: failed, `runtime-data/reports/live-readiness/market-status-snapshot.json` 수동 snapshot 없음.
  - `kill_switch`: failed, `runtime-data/reports/live-risk/kill-switch.json` 없음. 안전 측 기본값으로 submit 차단 상태다.
  - `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json`: `status=blocked`, blocking reasons는 `market_status_fault_dry_run_failed`, `kill_switch_fault_dry_run_failed`.
- 계좌/리포트:
  - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`, positions match.
  - `python -m app --build-runtime-report`: 통과, `latest-runtime-report.json` 갱신.
  - `python -m app --build-dashboard`: 통과, dashboard snapshot `generated_at=2026-05-28T04:23:09+09:00`.
  - 최종 `./scripts/check_local_setup.sh`: `ok=true`, blockers/warnings 없음.
- 남은 조치:
  - Phase 1 readiness 통과에는 장전 수동 market status snapshot 생성과 kill switch OFF 파일 적용 여부에 대한 명시 승인/절차가 필요하다.
  - 현 상태는 실전 주문 안전 측 차단 상태이며, `ALLOW_LIVE_ORDERS`, `app/risk/`, `config/`, `VERSION`, gate 기준값 변경 없음.

## [2026-05-28] Codex -> PC 재시작 후 runtime 상태 확인과 startup launcher 보강

- 재시작 후 최초 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`. 장외 시간이므로 live runtime 중지는 정상 상태다.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=stale`, 이전 pid는 종료됨.
  - `./scripts/get_dashboard_status.sh`: `status=stale`, 이전 pid는 종료됨, `dashboard_responding=false`.
  - `./scripts/get_runtime_startup_launcher_status.sh`: Windows 시작프로그램 launcher는 설치됨.
- 조치:
  - `./scripts/start_runtime_watchdog_background.sh`로 watchdog 재기동.
  - `./scripts/start_dashboard_background.sh` 호출 중 1회 `Address already in use`가 stderr에 남았지만, watchdog이 먼저 dashboard를 정상 재시작한 상태였고 최종 상태는 정상이다.
  - 최종 `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=overnight`, `live_runtime_should_run=false`, `errors=[]`.
  - 최종 `./scripts/get_dashboard_status.sh`: `status=running`, `port_bound=true`, `dashboard_responding=true`, `dashboard_api_responding=true`.
- 원인/보강:
  - 기존 `RealTimeStockRuntime.cmd`는 Windows 시작프로그램에서 WSL 명령을 조용히 실행해, PC 재시작 직후 실제 실행 여부와 실패 원인이 repo 내부에 남지 않았다.
  - `scripts/script_dispatch.sh`의 Windows startup launcher 생성 로직에 로그인 직후 짧은 대기와 `runtime-data/logs/automation/RealTimeStockRuntime.log` 기록을 추가했다.
  - `./scripts/install_runtime_startup_launcher.sh`를 재실행해 실제 Windows 시작프로그램 cmd도 새 형식으로 갱신했다.
- 검증:
  - `bash -n scripts/script_dispatch.sh` 통과.
  - `python -m unittest tests.test_wsl_ops` 통과, 15개.
  - `git diff --check` 통과.
  - 실전 주문, live account 주문/취소, 운영 DB schema apply, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-28] Codex -> C드라이브 저장소 전용 산출물 감사와 D드라이브 이동

- 작업 시작 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=overnight`, `live_runtime_should_run=false`, `errors=[]`.
- C드라이브 감사:
  - `C:\CodexData\Real-time-stock-price-prediction-program`, `C:\Users\Keios\CodexData\Real-time-stock-price-prediction-program`, `C:\Temp\Real-time-stock-price-prediction-program`, 사용자 `Temp/Downloads/Documents/Desktop`의 저장소명 후보는 발견되지 않았다.
  - `C:\Temp\cybos_collect.db` 본체는 이미 삭제된 상태였다.
  - `C:\Users\Keios\AppData\Local\wsl`에는 과거 WSL stub로 보이는 `shortcut.ico`만 남아 있었고, 현재 실제 WSL 디스크는 `D:\WSL\Ubuntu\ext4.vhdx`로 확인했다.
  - `C:\Users\Keios\.codex`, `C:\Users\Keios\AppData\Local\Codex`, `C:\Users\Keios\AppData\Local\OpenAI` 안에서 이 저장소명 후보는 발견되지 않았다. 이 경로들은 저장소 전용 산출물이 아니라 앱/도구 내부 캐시이므로 이동하지 않았다.
- 이동:
  - `C:\Temp\cybos_collect_005930_chunk60.err.log`
  - `C:\Temp\cybos_collect_005930_chunk60.log`
  - `C:\Temp\cybos_collect_005930_early.err.log`
  - `C:\Temp\cybos_collect_005930_early.log`
  - 위 4개 파일을 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\logs\`로 이동했다.
  - 이동 뒤 `C:\Temp\cybos_collect*` 잔여 파일 없음, D드라이브 대상 폴더의 4개 파일 존재를 확인했다.
- 기준:
  - 이 저장소에서 경로를 지정할 수 있는 캐시, 다운로드, 임시 데이터, 수집 데이터, 모델 산출물, 리포트, 스냅샷은 계속 D드라이브만 사용한다.
  - Codex Desktop, OpenAI 앱, Windows/WSL 자체가 강제하는 내부 캐시는 저장소 전용 산출물이 아니며, 이동 시 도구 실행을 깨뜨릴 수 있어 별도 검증 전에는 옮기지 않는다.

## [2026-05-27] Codex -> 장후 label refresh full build 실패 원인 수정

- 원인:
  - `./scripts/run_post_close_label_refresh.sh --recent-days 10`가 내부에서 `python -m app --build-feature-dataset`를 제한 없이 호출해 전체 이력 feature/label build를 수행하고 있었다.
  - 현재 `runtime-data/dev.db` 기준 `minute_bars`와 `feature_rows`가 643만 건 이상이라 장후 운영 작업으로는 과도했고, 2026-05-27 수동 full 재시도는 약 23분 뒤 실패했다.
- 변경:
  - `python -m app --build-feature-dataset --feature-dataset-recent-days N` 옵션을 추가했다.
  - `app/storage/sqlite_store.py`의 minute bar/orderbook 조회에 `start_time/end_time` 필터를 추가해 Python 메모리 필터가 아니라 SQLite 조회 단계에서 최근 구간만 읽도록 했다.
  - `build_feature_dataset_from_sqlite(..., recent_days=N)`가 최근 N일 구간과 직전 1일 orderbook context만 읽도록 했다.
  - `run_post_close_label_refresh.sh`는 `--recent-days` 값을 `--feature-dataset-recent-days`로 넘긴다.
- 검증:
  - `python -m py_compile app/__main__.py app/services/research.py app/storage/sqlite_store.py` 통과.
  - `bash -n scripts/script_dispatch.sh scripts/run_post_close_label_refresh.sh` 통과.
  - `python -m unittest tests.test_post_close_label_refresh_script tests.test_research_pipeline` 통과, 13개.
  - 실제 `./scripts/run_post_close_label_refresh.sh --recent-days 10 --force` 재실행 통과.
- 실제 재실행 결과:
  - feature build: `features_written=26450`, `labels_written=47683`, `source_window_start=2026-05-17T20:43:14.976481+09:00`.
  - `latest-post-close-label-refresh.json`: `status=ok`, `skipped_feature_label_build=false`, `completed_at=2026-05-27 20:54:58 +0900`.
  - dashboard snapshot: `generated_at=2026-05-27T20:56:27.461218+09:00`.
  - `373220` h15 label symbol-minute는 `0`에서 `352`로 회복됐다.
  - `latest-kis-live-data-quality.json`은 여전히 `assessment.status=watch`지만, 이는 오늘 raw market/minute/feature closed coverage가 약 `94.3%`로 95% 기준을 소폭 하회하기 때문이다.
- 백업/푸시:
  - 로컬 커밋 `a838f11`, `4e361fd` 생성 후 `git push origin main`은 도구 안전 정책에서 차단됐다. 확인된 원격은 `https://github.com/13keios-ops/Real-time-stock-price-prediction-program`이며, 이 원격으로 push 하려면 위험 고지 후 명시 재승인이 필요하다.
  - 사용자 승인 기준에 따라 forced NAS backup을 실행했다.
  - NAS backup 경로: `/mnt/backup/repos/real-time-stock-price-prediction-program/recovery-exports/real-time-stock-price-prediction-program-recovery-20260527-210445.tar.gz`.
  - 최종 크기: 약 `5.2G`.
  - `gzip -t` 무결성 검사 통과.
  - 이번 백업은 `runtime-data`가 약 67GB라 1시간 가까이 소요됐다. 중요 체크포인트 백업은 허용하되, 향후 sanitized recovery export와 재난 복구용 대용량 export의 범위/시간 예산을 분리하는 개선이 필요하다.
- 주의:
  - 전체 이력 feature/label 재생성은 연구/복구용 명시 작업으로만 둔다.
  - 실전 주문, live account 주문/취소, live runtime restart, 운영 DB schema apply, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-27] Codex -> 장후 운영상태 확인과 마감 조치

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PostCloseOps`: `LastRunTime=2026-05-27 16:40:40`, `LastTaskResult=0`, `NumberOfMissedRuns=0`.
- 장후 자동화 확인:
  - `latest-post-close-ml.json`: `status=ok`, `mode=quick-live-train`, `completed_at=2026-05-27 16:20:24 +0900`.
  - 자동화의 `latest-post-close-label-refresh.json`는 `status=ok`였지만 `skipped_feature_label_build=true`였다. 30분 제한 뒤 fallback 진단/대시보드 갱신으로 끝난 상태로 판단했다.
  - 수동 full `./scripts/run_post_close_label_refresh.sh --recent-days 10`를 재시도했지만 `python -m app --build-feature-dataset` 단계에서 exit code 1로 종료됐다. 이후 상태 파일이 `running`으로 남아 있어 `--skip-build --force` fallback을 실행해 운영 마감 상태를 `status=ok`, `completed_at=2026-05-27 18:36:37 +0900`로 정상화했다.
  - fallback 결과 `runtime-data/reports/runtime/latest-runtime-report.json`과 dashboard snapshot은 각각 `18:36`, `18:38` 기준으로 갱신됐다.
- paper/KIS 모의계좌 정합성 조치:
  - 장후 자동화 직후 `latest-paper-dual-account-match.json`는 `status=needs_review`, `positions_match=true`, `cash_gap=398157.96565999836`, `total_asset_gap=784157.9656599984`였다.
  - 열린 포지션이 있어 `SyncInitialCash`는 실행하지 않고 `./scripts/align_local_paper_to_broker.sh`로 브로커 기준 marker 정렬을 수행했다.
  - 정렬 backup: `runtime-data/backups/paper-alignment/260527_1752_marker-only.sqlite3`.
  - 정렬 뒤 `./scripts/reconcile_paper_accounts.sh`: `ok=true`, `cash_gap=0`, `total_asset_gap=0`, `status=aligned_waiting_first_submission`.
  - 정렬 뒤 `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
- 데이터 품질:
  - `latest-kis-live-data-quality.json`: `assessment.status=watch`.
  - 최신 거래일 2026-05-27 기준 raw market coverage `0.943734`, minute/feature closed coverage `0.943333`으로 95% 기준을 소폭 하회했다.
  - `373220`의 h15 label symbol-minute가 `0`으로 나타나 full feature/label build 실패와 함께 다음 장전 전 확인이 필요하다.
- 장전 자동화 보강:
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PreOpenCheck` 액션에 `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`를 `start_runtime_autoboot.sh --skip-runtime-cleanup --skip-dashboard-build`와 `check_local_setup.sh` 사이에 추가했다.
  - 새 액션 기준 manual dry-run `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`: `status=ok`, `session_status=post-close`, `protected_session=false`, blockers/warnings 없음.
  - 다음 실제 확인 지점은 2026-05-28 08:20 자동 실행 결과다.
- 최종 런타임 정리:
  - 최종 점검 중 runtime watchdog pid가 죽어 `status=stale`로 확인됐다.
  - `./scripts/start_runtime_watchdog_background.sh`로 watchdog만 재기동했다.
  - 재기동 뒤 watchdog은 `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`이고 dashboard도 `status=running`, HTTP/API 응답 정상이다.
  - 최종 `./scripts/check_local_setup.sh`: `ok=true`, blockers/warnings 없음, `checked_at=2026-05-27 18:42:33 +0900`.
- 주의:
  - 실전 주문, live account 주문/취소, live runtime restart, 운영 DB schema apply, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-27] Codex -> 장중 premarket-readiness 수동 보강

- 상태:
  - 장 시작 후 확인 시 `./scripts/get_live_runtime_status.sh`: `status=running`, `session_status=regular-session`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=regular-session`, `live_runtime_should_run=true`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main` clean.
- 장전 자동화 확인:
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PreOpenCheck`: `LastRunTime=2026-05-27 08:20:20`, `LastTaskResult=0`, `NumberOfMissedRuns=0`.
  - 등록된 액션은 `start_runtime_autoboot.sh --skip-runtime-cleanup --skip-dashboard-build` 실행 뒤 `check_local_setup.sh`를 실행하는 구성이다.
  - `runtime-data/logs/automation/preopen-check.log`에서도 08:20 실행, `market_session_status=pre-open`, `live_window_fast_start=true`, `check_local_setup ok=true`를 확인했다.
  - 따라서 자동화 자체는 실행됐고, `premarket-readiness` dry-run report 생성이 스케줄러 액션에 아직 포함되지 않은 것이 직접 원인이다.
- 장중 수동 보강:
  - 사용자 지시에 따라 `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`를 수동 실행했다.
  - 결과: `status=ok`, `session_status=regular-session`, `protected_session=true`, live runtime/watchdog/dashboard/KIS 시세 자격정보/SQLite read-only smoke/disk/storage migration/manifest policy 모두 ok.
  - `manifest_policy.storage_apply_blocking_reasons`에 `action_not_allowed_during_protected_session`이 포함되어 장중 보호 세션에서 storage apply가 차단되는 것을 확인했다.
- 후속 권장:
  - 장후에 Windows `RealTimeStockRuntime_PreOpenCheck` 액션에 `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`를 `check_local_setup.sh` 전후로 연결하는 작업을 진행한다.
  - 장중에는 스케줄러 등록 변경, runtime restart, dashboard rebuild, 운영 DB write, 코드 적용은 하지 않는다.
- 주의:
  - 실전 주문, live runtime restart, dashboard rebuild, 운영 DB schema apply, `app/risk/` 추적 파일, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-27] Codex -> Phase 1 blocker 장전 보호모드 리허설

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=running`, `session_status=pre-open`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=pre-open`, `live_runtime_should_run=true`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main` clean.
  - 장중 수집 보호 모드로 보고 루트 코드 변경, 운영 DB 접근, runtime restart, dashboard rebuild, 실전 주문 관련 변경은 하지 않았다.
- market status 수동 snapshot 리허설:
  - `config/watchlist.txt` 기준 대상 종목은 10개다.
  - 현재 watchlist hash 는 `symbols-sha256-bde8bc3841c52c29`이다.
  - 운영 readiness 기본 snapshot 경로에는 실제 snapshot이 없어 `scripts/probe_market_status_snapshot.sh --symbols-file config/watchlist.txt --print-symbol-set-hash` 실행 결과가 fail-closed check를 남겼다.
  - `.tmp-tests/phase1-readiness-rehearsal/market-status-snapshot.json`에 형식 리허설용 snapshot을 만들고, `.tmp-tests/phase1-readiness-rehearsal/market-status-check.json`으로 probe를 실행했다.
  - 리허설 check 결과는 `passed=true`, `allowed_count=10`, `blocked_symbols={}`였다.
  - 이 리허설은 실제 거래 가능 증거가 아니며, 실제 Phase 1 readiness 통과에는 계좌 소유자/실전 운용 승인권자가 당일 거래정지/VI/관리/투자유의/상하한가 상태를 확인한 snapshot이 필요하다.
- kill switch 상태 파일 정책:
  - `./scripts/set_live_kill_switch.sh --status`: `status=missing`, `enabled=true`, `submit_blocking_reason=kill_switch_state_missing`.
  - `./scripts/set_live_kill_switch.sh --disable --reason phase1-readonly-readiness-rehearsal --actor account_owner --stale-after-minutes 480 --confirm-disable`를 dry-run으로 실행했다.
  - dry-run 결과는 `would_write=true`, `enabled=false`, `stale_after=2026-05-27T16:26:42+09:00` 후보였고 실제 파일은 쓰지 않았다.
  - dry-run 직후 status 재확인 결과는 여전히 `missing`으로, fail-closed 상태가 유지됐다.
- readiness dry-run 리허설:
  - `.tmp-tests/phase1-readiness-rehearsal/full-readiness-fixture.json`에 market_status와 kill_switch를 포함한 전체 fixture를 만들었다.
  - `./scripts/run_live_readiness_dry_run.sh --fixture-path .tmp-tests/phase1-readiness-rehearsal/full-readiness-fixture.json --report-path .tmp-tests/phase1-readiness-rehearsal/readiness-dry-run.json` 실행 결과 `status=ok`, `passed=true`.
  - 이 결과는 `.tmp-tests` 격리 fixture 경로 검증이며 실제 운영 readiness 파일이나 DB record를 갱신하지 않았다.
- 다음 연결점:
  - 실제 Phase 1 readiness 통과를 위해서는 `runtime-data/reports/live-readiness/market-status-snapshot.json`에 당일 수동 snapshot을 만들고, 계좌 소유자/실전 운용 승인권자 승인 뒤 만료 시간이 있는 kill switch OFF 상태 파일을 생성해야 한다.
  - pre-open/regular-session 중 실제 OFF 파일 적용은 별도 명시 승인 없이는 하지 않는다.
- 주의:
  - 실전 주문, live runtime restart, 운영 DB schema apply, `app/risk/` 추적 파일, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-26] Codex -> Phase 1 readiness 재점검과 cleanup 자동화

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main`.
- 모델 승격 불가 원인:
  - 최신 LightGBM 학습은 성공했다. `training_run_id=train-lightgbm-h15-20260526161241790071`, train rows `176092`, validation rows `52346`, validation accuracy `0.6139724143201009`.
  - 다만 active model 은 계속 `baseline-h15-v1`이고, 최신 challenger 는 `recommended_action=review_required`다.
  - 직접 원인은 gate reference walk-forward 가 `overall_accuracy=0.4163`으로 낮아 승격 게이트를 통과하지 못한 것이다. 파일 손상이나 학습 중단이 아니라 safety gate 차단으로 본다.
- paper/KIS 정합성 재발 원인:
  - 이전 `needs_review`는 보유 수량 불일치가 아니라 현금/총자산 gap 이었다. KIS paper 주문/체결 조회는 `EGW00201` rate limit 으로 일부 재조회가 막힌 기록이 있었다.
  - `align_local_paper_to_broker.sh` 이후 현재 baseline 은 marker 기준으로 재정렬되어 `reconcile_paper_accounts`와 `verify_paper_dual_account_match -AsJson` 모두 gap 0, `matched_waiting_first_submission`으로 확인됐다.
- 변경:
  - `scripts/check_local_setup.sh` 산출물에 `broker_paper_mirroring_level/status/note`, `warnings`, `informational_checks`를 추가했다.
  - `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, `ENABLE_BROKER_PAPER_MIRRORING=true` 조합은 Phase 0 KIS 모의계좌 검증 의도에 맞는 `info / expected_phase0_paper_mirroring`으로 분류한다. 이 조합을 벗어난 mirroring enabled 는 warning 으로 남긴다.
  - 대시보드 `장전 readiness` 카드에 broker paper mirroring level/status 표시를 추가했다.
  - `scripts/cleanup_repo_generated_artifacts.sh`를 추가했다. 기본은 dry-run 이고 `--apply`를 붙일 때만 `.tmp-tests` 하위 산출물, Python `__pycache__`, 루트 PowerShell provider prefix 오염 디렉터리를 삭제한다. `.tmp-tests/codex-ops/`와 `app/risk/` 아래 생성물은 보존한다.
  - `README.md`, `docs/Current-Implementation.md`, `docs/Production-Transition-Progress.md`를 새 동작 기준으로 갱신했다.
- readiness 재점검:
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`: `status=ok`, DB read-only smoke, dashboard, watchdog, disk space 통과.
  - `./scripts/probe_kis_token_refresh.sh --mode paper --use-cache`: 통과, token 원문 미기록.
  - `./scripts/probe_kis_account_snapshot.sh --mode paper --timeout-seconds 10`: 통과, `position_row_count=3`, `summary_row_count=1`, 계좌번호/raw response 미기록.
  - `./scripts/probe_kis_ws_recovery.sh`: 통과, `evidence_type=synthetic_fault_injection`, network call 없음.
  - `./scripts/probe_kis_clock_reference.sh --mode paper --timeout-seconds 10`: 통과, `skew_seconds=0.430729`.
  - `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/latest-fixture-snapshot.json`: `status=blocked`.
  - 통과 항목은 `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`; 차단 항목은 `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed`.
- 검증:
  - `bash -n scripts/script_dispatch.sh scripts/cleanup_repo_generated_artifacts.sh` 통과.
  - `python -m unittest tests.test_wsl_ops tests.test_repo_generated_artifacts_cleanup` 통과, 17개.
  - `python -m unittest tests.test_dashboard` 통과, 17개.
  - `python -m unittest tests.test_wsl_ops tests.test_repo_generated_artifacts_cleanup tests.test_dashboard` 통과, 34개.
  - `./scripts/cleanup_repo_generated_artifacts.sh --apply` 실행 후 최종 dry-run 기준 `target_count=0`.
- 주의:
  - 실전 주문, live runtime restart, 운영 DB schema apply, `app/risk/` 추적 파일, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-26] Codex -> 장전/장후 체크 확인과 데이터 오염 정리

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - `git status --short --branch`: `main...origin/main` clean.
- 장전/장후 체크:
  - `latest-local-setup-check.json`: `ok=true`, blockers 없음, `broker_paper_mirroring_enabled=true`.
  - `latest-post-close-ml.json`: `status=ok`, `mode=quick-live-train`, `completed_at=2026-05-26 16:16:50 +0900`.
  - `latest-post-close-label-refresh.json`: `status=ok`, `completed_at=2026-05-26 17:20:47 +0900`.
  - 장전 mirroring 경고는 `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, `ENABLE_BROKER_PAPER_MIRRORING=true` 조합이라 Phase 0 KIS 모의계좌 검증 의도와 맞는 확인성 경고로 봤다.
- 조치:
  - `./scripts/verify_paper_dual_account_match.sh -AsJson` 재확인 결과 수량은 일치했지만 `cash_gap=-538996.277219994`, `total_asset_gap=49003.722780006006`으로 `needs_review`였다.
  - 열린 포지션이 있으므로 `SyncInitialCash`는 실행하지 않고, `./scripts/align_local_paper_to_broker.sh`로 브로커 기준 정렬을 수행했다.
  - 정렬 backup: `runtime-data/backups/paper-alignment/260526_1749_marker-only.sqlite3`.
  - `./scripts/reconcile_paper_accounts.sh`: `ok=true`, `positions_match=true`, `balance_match=true`, `total_asset_match=true`, `cash_gap=0`, `total_asset_gap=0`.
  - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`.
  - `python -m app --build-dashboard`: `generated_at=2026-05-26T17:54:02.107237+09:00`.
- 데이터 오염 정리:
  - 루트 PowerShell provider prefix 오염 디렉터리는 이전 PR식 점검에서 제거된 상태를 재확인했다.
  - `.tmp-tests` top-level 70개 생성 산출물을 정리했다. 정리 전 `.tmp-tests`는 약 11GB, 83,244개 파일이었다.
  - `app/`, `scripts/`, `tests/` 아래 `__pycache__` 19개 디렉터리를 정리했다.
  - 정리 후 `.tmp-tests`는 4KB, `__pycache__` 잔여 없음.
- 주의:
  - 실전 주문, live runtime restart, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-25] Codex -> 휴장일 post-close 자동화 guard 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=holiday`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=holiday`, `live_runtime_should_run=false`, `errors=[]`.
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PreOpenCheck`, `RealTimeStockRuntime_PostCloseOps`는 고정 시간표대로 실행됐고 `LastTaskResult=0`이었다.
- 확인:
  - `./scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`.
  - KIS 모의계좌와 로컬 paper 모두 `105560` 6주 보유, 현금 `8,680,630`, 총자산 `9,640,630`으로 일치했다.
  - 열린 포지션이 있으므로 `-SyncInitialCash`는 실행하지 않는 것이 맞고, 갭이 0이라 `-AlignToBroker`도 실행하지 않았다.
  - `python -m app --build-dashboard`로 최신 갭 0 리포트를 대시보드에 반영했다. snapshot 갱신 시각은 `2026-05-25 18:07:20 +0900`.
- 변경:
  - `scripts/script_dispatch.sh`에 post-close holiday/weekend guard를 추가했다.
  - `run_post_close_ml_maintenance.sh`와 `run_post_close_label_refresh.sh`는 기본 실행에서 `weekend` 또는 `holiday`이면 `skipped` 상태 파일만 남기고 학습/라벨/dashboard 재생성 작업을 수행하지 않는다.
  - 수동 재실행이 필요한 경우에는 `--force`로 우회할 수 있다.
  - `tests/test_post_close_maintenance_script.py`, `tests/test_post_close_label_refresh_script.py`에 holiday skip 회귀 테스트를 추가했다.
- 검증:
  - `python -m unittest tests.test_post_close_maintenance_script tests.test_post_close_label_refresh_script`: 7개 통과.
  - `bash -n scripts/script_dispatch.sh scripts/run_post_close_ml_maintenance.sh scripts/run_post_close_label_refresh.sh`: 통과.
  - 격리 runtime 기준 실제 holiday skip 확인: `market_session_holiday_no_post_close_maintenance`, `market_session_holiday_no_post_close_label_refresh`.
- 주의:
  - 실전 주문, live runtime restart, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-24] Codex -> D드라이브 저장 원칙 문서화 강화

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=stale`, `market_session_status=weekend`, `live_runtime_should_run=false`, `errors=[]`.
- 변경:
  - `AGENTS.md` 산출물 규칙에 Codex가 경로를 지정할 수 있는 모든 캐시, 다운로드, 임시 데이터, 수집 데이터, 모델 산출물, 리포트, 스냅샷은 D드라이브에만 저장한다는 원칙을 명시했다.
  - `README.md`에 `로컬 데이터 저장 원칙` 섹션을 추가해 저장소 내부 `runtime-data/`, `.tmp-tests/`는 `D:\WSL\Ubuntu` 때문에 물리적으로 D드라이브 기준이고, 저장소 밖 대용량 데이터와 장기 캐시는 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래에 둔다고 정리했다.
  - `README.md`와 `docs/Current-Implementation.md`의 예전 fallback 문구를 제거하고, D드라이브 경로를 사용할 수 없으면 새 다운로드, 캐시, 대용량 실험을 시작하지 않는 기준으로 바꿨다.
- 주의:
  - 코드 변경, 런타임 재시작, DB schema apply, 실전 주문 관련 flag 변경 없음.

## [2026-05-23] Codex -> 휴장일 Phase 1 readiness 리허설

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`, `errors=[]`.
  - 최신 cowork 리뷰는 `docs/cowork-reports/2026-05-22-production-architecture-implementation-blueprint-review_ver_15.md`이며, 관련 P1 보강은 `work_ver_16`에 반영된 상태로 확인했다.
- 실행:
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness`: `status=ok`, dry-run, DB read-only smoke 통과, dashboard reachable, disk space ok.
  - `./scripts/probe_kis_token_refresh.sh --mode paper`: `passed=true`, auth-only, token 원문 미저장.
  - `./scripts/probe_kis_account_snapshot.sh --mode paper --timeout-seconds 10`: `passed=true`, `shape_status=ok`, `position_row_count=1`, `summary_row_count=1`, 계좌번호/raw response 미저장.
  - `./scripts/probe_kis_ws_recovery.sh`: `passed=true`, `evidence_type=synthetic_fault_injection`, `network_called=false`.
  - `./scripts/probe_kis_clock_reference.sh --mode paper --timeout-seconds 10`: `passed=true`, `skew_seconds=0.708244`, HTTP `Date` 초 단위 정밀도 note 포함.
  - `./scripts/build_live_readiness_fixture_snapshot.sh --output-path runtime-data/reports/live-readiness/local-fixture-snapshot.json` 실행.
  - `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --report-path runtime-data/reports/live-readiness/latest-readiness.json` 실행.
- 결과:
  - `runtime-data/reports/live-readiness/latest-readiness.json`: `status=blocked`, `phase=phase1_readonly`, `trading_day=2026-05-23`.
  - 통과 항목: `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`.
  - 차단 항목: `market_status=false`, `kill_switch=false`.
  - 차단 사유: `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed`.
  - 오늘은 토요일 휴장일이라 Phase 1 통과 증거가 아니라 휴장 리허설과 fail-closed 확인으로만 본다.
  - `python -m app --build-dashboard`는 shell timeout 이후 프로세스가 종료됐고, `runtime-data/reports/dashboard/latest-dashboard.html`, `latest-dashboard.json`의 갱신 시각이 `2026-05-23 13:37:22 +0900`로 확인됐다. dashboard server는 계속 정상 응답 중이다.
- 다음 연결점:
  - 다음 거래일 장전에는 수동 `market_status` snapshot 생성, Phase 1 당일 kill switch OFF 승인 파일 생성, fresh paper/read-only probe 재실행이 필요하다.
  - Phase 1 live read-only 통과 증거에는 오늘 휴장일 증거를 그대로 사용하지 않는다.
- 주의:
  - live account 조회, live order submit/cancel, runtime restart, 운영 DB schema apply 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-23] Codex -> 커밋 전 최종 검증과 NAS export 제외 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`, `errors=[]`.
- 변경:
  - `scripts/wsl_ops.py`의 `export-recovery`가 문서 정책과 맞게 루트 `.env*`, KIS token cache, runtime logs, private key 계열을 recovery export에서 제외하도록 보강했다.
  - `tests/test_wsl_ops.py`에 `.env.local`, `.env.example`, `id_ed25519` 제외 검증을 추가했다.
  - Phase 2 submit 성공 fixture인 `tests/test_live_execution_sync.py`에 실제 KIS WS recovery evidence type을 명시해 최신 live submit guard 정책과 테스트를 맞췄다.
- 검증:
  - `python -m unittest tests.test_wsl_ops`: 13개 통과.
  - `python -m unittest tests.test_live_execution_sync`: 12개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 351개 통과.
  - `bash -n scripts/*.sh`: 통과.
  - `python -m app --build-dashboard`: 통과, `runtime-data/reports/dashboard/latest-dashboard.html`, `latest-dashboard.json` 생성.
  - `./scripts/run_live_readiness_dry_run.sh`: fixture 미제공 상태에서 `status=blocked`; 모든 필수 evidence를 `not_verified`로 차단하는 fail-closed 동작 확인.
  - `git diff --check`: 통과. CRLF/LF 안내 warning만 있고 whitespace error 없음.
  - `git status --short -- app/risk config VERSION`: 출력 없음.
- 주의:
  - live account 조회, live order submit/cancel, runtime restart, gate 기준값 변경, `ALLOW_LIVE_ORDERS` 변경 없음.
  - 실제 NAS package는 커밋/푸시 후 `/mnt/backup` 대상 강제 백업으로 별도 실행 예정이다.

## [2026-05-23] Codex -> work_ver_16: review_ver_15 P1 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`, `errors=[]`.
  - 주말 상태라 코드/문서 보강과 read-only 검증만 진행했다.
- 변경:
  - `app/services/ws_recovery_evidence.py`를 추가해 실제 KIS WS recovery evidence enum과 설명을 단일 소스로 분리했다.
  - `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py`가 새 evidence enum helper를 import하도록 바꿨다.
  - readiness evidence freshness를 key별 기준으로 바꿨다. 현재 기준은 `system_clock/ws_recovery=30분`, `account_snapshot/market_status=1시간`, `token_refresh=4시간`이다.
  - `app/services/market_status_probe.py`에 `compute_symbol_set_hash()`를 추가하고, manual snapshot `symbol_set_hash`가 sorted symbols hash와 맞지 않으면 차단하도록 했다.
  - `scripts/probe_market_status_snapshot.py`에 `--print-symbol-set-hash`를 추가했다.
  - `system_clock` check details에 HTTP `Date` 초 단위 정밀도 note를 추가했다.
  - dashboard live readiness 카드가 WS recovery evidence type, 실제 증거 여부, freshness, stable frame, reconnect storm 여부를 표시하도록 보강했다.
  - `scripts/probe_kis_clock_reference.sh --compare-paper-live`로 paper/live HTTP `Date` reference delta를 raw header 없이 비교할 수 있게 했다. 이번 작업에서는 live account 조회를 실행하지 않았다.
  - `app/services/kis_account_probe.py`가 account snapshot 필수 attribute 존재뿐 아니라 row count와 금액 계열 값 타입 drift를 원문 값 없이 차단하도록 보강했다.
  - `docs/Manual-Market-Status-Runbook.md`에 symbol hash 계산과 stale 회복 절차를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Transition-Progress.md`에 Phase 2 모델 성능 선행 게이트를 명시했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-23-production-architecture-implementation-blueprint-work_ver_16.md`를 추가하고 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_order_guard tests.test_live_order_manager tests.test_market_status_probe tests.test_kis_clock_reference_probe` 통과, 61개.
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_order_guard tests.test_live_order_manager tests.test_market_status_probe tests.test_kis_clock_reference_probe tests.test_live_readiness_dry_run_script` 통과, 72개.
  - `python -m py_compile app/services/ws_recovery_evidence.py app/services/live_phase_readiness.py app/services/live_order_guard.py app/services/market_status_probe.py scripts/probe_market_status_snapshot.py tests/test_live_phase_readiness.py tests/test_market_status_probe.py tests/test_kis_clock_reference_probe.py tests/test_live_readiness_dry_run_script.py` 통과.
  - `bash -n scripts/probe_market_status_snapshot.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `python -m unittest tests.test_kis_clock_reference_probe tests.test_dashboard` 통과, 24개.
  - `python -m py_compile app/services/system_clock_probe.py scripts/probe_kis_clock_reference.py app/services/dashboard.py tests/test_kis_clock_reference_probe.py tests/test_dashboard.py` 통과.
  - `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_guard tests.test_live_order_manager tests.test_kis_live_order_adapter tests.test_dashboard` 통과, 166개.
  - `python -m app --build-dashboard` 통과. `runtime-data/reports/dashboard/latest-dashboard.html`에 WS recovery 상세 row가 표시되는 것을 확인했다.
  - `python -m unittest tests.test_kis_account_probe tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness` 통과, 35개.
  - `python -m py_compile app/services/kis_account_probe.py tests/test_kis_account_probe.py` 통과.
  - account snapshot 타입 검증 반영 후 관련 전체 묶음 재실행 통과, 167개.
  - 최종 `py_compile`와 readiness 관련 `bash -n` 통과.
  - `git diff --check` 통과. CRLF/LF 안내 warning만 있었고 whitespace error는 없었다.
  - `git diff --name-only -- app/risk config VERSION`, `git status --short -- app/risk config VERSION` 출력 없음.
- 최신 readiness:
  - `./scripts/run_live_readiness_dry_run.sh --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --report-path runtime-data/reports/live-readiness/latest-readiness.json` 실행.
  - 주말에 어제 증거를 재사용했으므로 `ws_recovery`, `account_snapshot`, `system_clock`은 key별 freshness 기준에 따라 stale 차단됐다. `token_refresh`는 4시간 기준 안이라 통과했다.
  - 전체 status는 `blocked`이며, 이는 Phase 1 장전마다 fresh probe를 다시 만들어야 한다는 fail-closed 동작이다.
- 주의:
  - NAS 실제 package/drill, live account 조회, live order submit/cancel, runtime restart, 운영 DB schema apply 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-23] Codex -> NAS 백업 정책 구분 반영

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`.
- 확인:
  - Windows 경로 `\\192.168.0.2\backup` 접근 가능.
  - 기존 repo 백업 경로 `\\192.168.0.2\backup\repos\real-time-stock-price-prediction-program\recovery-exports`와 2026-05-20 백업 폴더 확인.
  - 사용자 WSL 터미널에서 `/mnt/backup` 마운트 성공.
  - Codex 세션에서는 처음에 마운트가 보이지 않아 `wsl.exe -d Ubuntu -u root`로 같은 공유를 `/mnt/backup`에 다시 마운트했다.
  - Codex 세션 기준 `/mnt/backup/repos/real-time-stock-price-prediction-program/recovery-exports` 확인 완료.
  - `./scripts/run_forced_nas_backup.sh --backup-share-root /mnt/backup --backup-reason phase1-readonly-drill-check --dry-run` 통과. 실제 package 생성 없음.
  - 기존 NAS 백업은 재난 복구용 전체 백업으로 유지하는 운영 의도를 확인했다.
- 변경:
  - `RECOVERY.md`, `README.md`, `AGENTS.md`에서 NAS 백업을 재난 복구용 전체 백업과 실전 전환 검증용 sanitized recovery export로 분리했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`, `docs/cowork-reports/2026-05-23-production-architecture-implementation-blueprint-work_ver_16.md`에 같은 구분을 반영했다.
- 주의:
  - 기존 NAS 전체 백업은 cowork 전달/Phase readiness 증거로 직접 쓰지 않는다.
  - Phase 1 전 복구 drill은 `recovery-drills/phase1-readonly` 같은 별도 폴더에서 비밀값 제외 sanitized export 표본으로 확인하는 것을 권장한다.

## [2026-05-22] Codex -> work_ver_15: review_ver_14 P0 guard 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 review_ver_14 반영 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/services/live_phase_readiness.py`가 Phase 2/3 readiness에서 synthetic `ws_recovery` 증거를 `invalid_evidence`로 차단하도록 했다.
  - `app/services/live_order_guard.py`, `app/services/live_order_manager.py`가 Phase 2/3 live submit 시 실제 KIS WS recovery evidence type을 기본 요구하도록 했다. 없거나 synthetic이면 broker 호출 전에 `ws_recovery_real_evidence_required`로 차단한다.
  - `app/services/kis_account_probe.py`가 account snapshot 필수 shape(`position_row_count`, `summary_row_count`, `cash_balance`, `stock_evaluation_amount`, `total_asset_amount`) 누락을 shape drift로 차단하도록 했다.
  - `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `system_clock` timestamped readiness 증거는 기본 1시간 초과 시 `stale_evidence`로 차단하도록 했다.
  - `docs/Manual-Market-Status-Runbook.md`를 추가하고 `app/services/market_status_probe.py`가 수동 snapshot source를 `manual_operator_snapshot`, `manual_krx_snapshot`, `manual_kis_snapshot`으로 제한하도록 했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`, `README.md`, `AGENTS.md`에 보강 상태를 반영했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-22-production-architecture-implementation-blueprint-work_ver_15.md`를 추가하고 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_order_guard tests.test_live_order_manager tests.test_live_phase_readiness tests.test_kis_account_probe` 통과, 52개.
  - `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_guard tests.test_live_order_manager tests.test_kis_live_order_adapter` 통과, 143개.
  - `python -m py_compile app/services/live_order_guard.py app/services/live_order_manager.py app/services/live_phase_readiness.py app/services/kis_account_probe.py tests/test_live_order_guard.py tests/test_live_order_manager.py tests/test_live_phase_readiness.py tests/test_kis_account_probe.py` 통과.
  - 관련 Python 파일과 probe wrapper `py_compile` 통과.
  - `bash -n scripts/probe_market_status_snapshot.sh scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있고 whitespace error는 없다.
  - `git diff -- app/risk config VERSION` 출력 없음.
- 최신 readiness:
  - paper/read-only probe 재실행 후 `runtime-data/reports/live-readiness/latest-readiness.json` 생성.
  - `token_refresh/ws_recovery/account_snapshot/system_clock/database/disk_space/dashboard/storage_migration_state=true`, `market_status=false`, `kill_switch=false`, 전체 `blocked`.
  - blocking reasons는 `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed` 두 개다.
- 주의:
  - NAS 실제 package/drill은 실행하지 않았다. 운영자 승인 필요 항목으로 유지한다.
  - live account 조회, live order submit/cancel, runtime restart, 운영 DB schema apply 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-22] 장전/장후 자동화 확인과 paper 계좌 재정렬

- 상태 확인:
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PreOpenCheck`: `2026-05-22 08:20:20` 실행, `LastTaskResult=0`, 다음 실행 `2026-05-25 08:20:20`.
  - Windows 작업 스케줄러 `RealTimeStockRuntime_PostCloseOps`: `2026-05-22 16:40:40` 실행, `LastTaskResult=0`, 다음 실행 `2026-05-25 16:40:40`.
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `stopped_at=2026-05-22 15:30:04 +0900`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `errors=[]`, `ml_maintenance_action=already_ok`.
  - `./scripts/get_dashboard_status.sh`: `status=running`, `dashboard_api_responding=true`.
- 장후 자동화 결과:
  - `latest-post-close-ml.json`: `status=ok`, `mode=quick-live-train`, `completed_at=2026-05-22 16:09:02 +0900`, `train-lightgbm-bounded`, `run-challengers-bounded` 포함.
  - `latest-post-close-label-refresh.json`: `status=ok`, `completed_at=2026-05-22 17:00:00 +0900`.
  - 오늘 학습 run: `train-lightgbm-h15-20260522160627281658`, `train_rows=174704`, `validation_rows=53808`, validation accuracy `0.6218406185`.
  - 최신 challenger: `recommended_action=keep_active`, `decision_reason=The top challenger does not have enough trades.`, active model `baseline-h15-v1` 유지.
- 데이터 품질:
  - `latest-kis-live-data-quality.json`: `assessment.status=ok`, `trade_date=2026-05-22`, `raw_market_coverage_ratio=0.973146`, `minute_bar_closed_coverage_ratio=0.973077`, `feature_closed_coverage_ratio=0.973077`.
- 조치:
  - 장후 재대조에서 `latest-paper-dual-account-match.json`가 `needs_review`였고, 수량은 일치하지만 로컬 paper 장부 스냅샷이 오래되어 현금/총자산 차이가 있었다.
  - `./scripts/sync_broker_paper_orders.sh`는 KIS `EGW00201` rate limit으로 주문/체결 상세 동기화는 실패했지만, 포지션 비교에는 영향이 없었다.
  - `./scripts/align_local_paper_to_broker.sh`로 로컬 paper 장부를 KIS 모의계좌 기준으로 정렬했다. backup: `runtime-data/backups/paper-alignment/260522_1744_marker-only.sqlite3`.
  - `./scripts/reconcile_paper_accounts.sh`: `status=aligned_waiting_first_submission`, `positions_match=true`, `balance_match=true`, `total_asset_match=true`, `cash_gap=0`, `total_asset_gap=0`.
  - `python -m app --build-dashboard`: `generated_at=2026-05-22T17:45:23.650020+09:00`.
- 남은 확인:
  - KIS 주문/체결 상세 동기화는 rate limit 이후 재시도 간격을 두는 편이 안전하다. 다음 장전/장후 자동화에서 `broker-paper/latest-sync.json`의 `status`가 회복되는지 확인한다.

## [2026-05-21] Codex -> work_ver_14-6: work_ver_14 시리즈 cowork 전달용 통합본 작성

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 문서/리포트만 갱신했다.
- 변경:
  - `work_ver_14`, `14-1`, `14-2`, `14-3`, `14-4`, `14-5`를 cowork 전달용 한 파일로 압축한 `docs/cowork-reports/2026-05-21-production-architecture-implementation-blueprint-work_ver_14-6.md`를 추가했다.
  - `docs/Production-Transition-Progress.md`의 최신 통합 리포트를 `work_ver_14-6`으로 갱신했다.
  - `docs/cowork-reports/README.md` 색인을 갱신했다.
- 전달 기준:
  - cowork에는 `work_ver_14-6` 하나만 전달하면 된다.
  - 현재 readiness blocker는 `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed` 두 개다.
- 주의:
  - 코드 변경 없음.
  - KIS API 신규 호출 없음.
  - live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_14-5: manual market_status snapshot readiness probe 구현

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/services/market_status_probe.py`를 추가해 repo 내부 수동 market status snapshot을 `app/services/market_status.py`의 순수 판정 로직으로 평가하고 `market_status` readiness check를 만든다.
  - `scripts/probe_market_status_snapshot.py`, `scripts/probe_market_status_snapshot.sh`, `scripts/script_dispatch.sh`를 추가/연결했다.
  - `app/services/live_readiness_fixture.py`와 `scripts/build_live_readiness_fixture_snapshot.py`가 `market-status-check.json`을 local fixture snapshot에 포함할 수 있게 했다.
  - KIS/거래소 자동 market status 원천은 연결하지 않았다. 실제 snapshot 파일이 없으면 readiness는 계속 `market_status_not_verified_by_fault_dry_run`으로 blocked 된다.
  - local fixture snapshot 기반 readiness dry-run 결과는 여전히 `market_status=not_verified`, `kill_switch=failed`라 전체 readiness는 `blocked`다.
- 검증:
  - `python -m unittest tests.test_market_status_probe tests.test_market_status tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager` 통과, 119개.
  - `python -m py_compile app/services/market_status_probe.py app/services/live_readiness_fixture.py scripts/probe_market_status_snapshot.py scripts/build_live_readiness_fixture_snapshot.py tests/test_market_status_probe.py tests/test_live_readiness_fixture_snapshot.py` 통과.
  - `bash -n scripts/probe_market_status_snapshot.sh scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
- 남은 P0:
  - 실제 거래일 market status snapshot 증적 생성. 권장안은 Phase 1 전 수동 snapshot으로 시작하고, KIS/한국거래소 자동 원천은 별도 slice로 분리하는 것이다.
  - kill switch `OFF` 상태 파일 생성 시점 결정. 현재 missing은 fail-closed로 정상 차단이다.
  - Phase 1 승인 뒤 live account read-only header/account shape 확인.
- 주의:
  - KIS API 신규 호출 없음.
  - live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_14-4: account snapshot + synthetic WS recovery readiness probe 구현

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/services/kis_account_probe.py`를 추가해 KIS 계좌 snapshot 조회 결과를 계좌번호 없이 `account_snapshot` readiness check로 만든다.
  - `scripts/probe_kis_account_snapshot.py`, `scripts/probe_kis_account_snapshot.sh`, `scripts/script_dispatch.sh`를 추가/연결했다.
  - `app/services/kis_ws_recovery_probe.py`와 `scripts/probe_kis_ws_recovery.py`, `scripts/probe_kis_ws_recovery.sh`를 추가해 실제 WebSocket 네트워크를 열지 않는 synthetic fault injection 기반 `ws_recovery` check를 만든다.
  - `app/services/live_readiness_fixture.py`와 `scripts/build_live_readiness_fixture_snapshot.py`가 `account-snapshot-check.json`, `ws-recovery-check.json`을 local fixture snapshot에 포함할 수 있게 했다.
  - KIS 모의투자 paper 계좌 snapshot read-only 조회 1회를 실행해 `runtime-data/reports/live-readiness/account-snapshot-check.json`을 생성했다. 결과는 `account_snapshot=true`이고 계좌번호/raw response는 저장하지 않는다.
  - synthetic WS recovery check를 실행해 `runtime-data/reports/live-readiness/ws-recovery-check.json`을 생성했다. 결과는 `ws_recovery=true`, `network_called=false`다.
  - local fixture snapshot 기반 readiness dry-run 결과 `token_refresh`, `ws_recovery`, `account_snapshot`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`는 true, `market_status`는 not_verified, `kill_switch`는 missing으로 failed라 전체 readiness는 `blocked`로 남았다.
- 검증:
  - `python -m unittest tests.test_kis_ws_recovery_probe tests.test_kis_ws_reconnect_metrics tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_kis_account_probe tests.test_kis_token_probe tests.test_kis_clock_reference_probe tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_live_readonly_guard tests.test_system_clock tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager` 통과, 107개.
  - `python -m py_compile app/services/kis_account_probe.py app/services/kis_ws_recovery_probe.py app/services/kis_token_probe.py app/services/system_clock_probe.py app/services/live_readiness_fixture.py scripts/probe_kis_account_snapshot.py scripts/probe_kis_ws_recovery.py scripts/probe_kis_token_refresh.py scripts/probe_kis_clock_reference.py scripts/build_live_readiness_fixture_snapshot.py tests/test_kis_account_probe.py tests/test_kis_ws_recovery_probe.py tests/test_live_readiness_fixture_snapshot.py` 통과.
  - `bash -n scripts/probe_kis_account_snapshot.sh scripts/probe_kis_ws_recovery.sh scripts/probe_kis_token_refresh.sh scripts/probe_kis_clock_reference.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있고 whitespace error는 없다.
  - `git diff -- app/risk config VERSION` 출력 없음.
- 남은 P0:
  - `market_status` 증적 확보. 권장안은 KIS/거래소 상태 원천이 정해지기 전까지 수동 snapshot 또는 fixture로 자동 통과시키지 않는 것이다.
  - kill switch `OFF` 상태 파일 생성 시점 결정. 현재 missing은 fail-closed로 정상 차단이다.
  - Phase 1 승인 뒤 live account read-only header/account shape 확인.
- 주의:
  - 실제 KIS 호출은 모의투자 paper 계좌 snapshot read-only 조회 1회만 추가 수행했다.
  - WS recovery는 실제 KIS WebSocket 연결이 아니라 synthetic/offline check다.
  - live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_14-3: token refresh readiness probe 구현

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/services/kis_token_probe.py`를 추가해 token 원문 없이 `token_refresh` readiness check를 만든다.
  - `scripts/probe_kis_token_refresh.py`, `scripts/probe_kis_token_refresh.sh`, `scripts/script_dispatch.sh`를 추가/연결했다.
  - `app/services/live_readiness_fixture.py`와 `scripts/build_live_readiness_fixture_snapshot.py`가 `token-refresh-check.json`을 읽어 local fixture snapshot에 포함할 수 있게 했다.
  - `tests/test_kis_token_probe.py`, `tests/test_live_readiness_fixture_snapshot.py`를 추가/보강했다.
  - KIS 모의투자 paper token refresh를 1회 실행해 `runtime-data/reports/live-readiness/token-refresh-check.json`을 생성했다. 결과는 `token_refresh=true`, token 원문 미저장이다.
  - local fixture snapshot 기반 readiness dry-run 결과 `token_refresh`, `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`는 true, `kill_switch`는 missing으로 failed, `ws_recovery`, `account_snapshot`, `market_status`는 not_verified라 전체 readiness는 `blocked`로 남았다.
- 검증:
  - `python -m unittest tests.test_kis_token_probe tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_kis_clock_reference_probe` 통과, 38개.
  - `python -m py_compile app/services/kis_token_probe.py app/services/live_readiness_fixture.py scripts/probe_kis_token_refresh.py scripts/build_live_readiness_fixture_snapshot.py tests/test_kis_token_probe.py tests/test_live_readiness_fixture_snapshot.py` 통과.
  - `bash -n scripts/probe_kis_token_refresh.sh scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh` 통과.
- 남은 P0:
  - kill switch 상태 파일을 언제 `OFF`로 생성할지 결정. 현재 missing은 fail-closed로 정상 차단이다.
  - WS recovery, account snapshot, market status 증적 확보.
  - Phase 1 승인 뒤 live account read-only header/token shape 확인.
- 주의:
  - 실제 KIS 호출은 모의투자 paper token refresh 1회만 수행했다.
  - live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_14-2: local readiness fixture snapshot 구현

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/services/live_readiness_fixture.py`를 추가해 premarket report, system clock check, kill switch 상태에서 로컬로 증명 가능한 readiness fixture만 만든다.
  - `scripts/build_live_readiness_fixture_snapshot.py`, `scripts/build_live_readiness_fixture_snapshot.sh`, `scripts/script_dispatch.sh`를 추가/연결했다.
  - token refresh, WS recovery, account snapshot, market status는 별도 증거가 없으면 fixture에 넣지 않아 `not_verified`로 남긴다.
  - `tests/test_live_readiness_fixture_snapshot.py`를 추가했다.
  - fresh `premarket-readiness` dry-run report를 생성하고, `runtime-data/reports/live-readiness/local-fixture-snapshot.json`을 생성했다.
  - fixture snapshot 기반 `run_live_readiness_dry_run.sh` 실행 결과 `system_clock`, `database`, `disk_space`, `dashboard`, `storage_migration_state`는 true, `kill_switch`는 missing으로 failed, token/WS/account/market은 not_verified라 전체 readiness는 `blocked`로 남았다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`, `README.md`, `AGENTS.md`에 반영했다.
- 검증:
  - `python -m unittest tests.test_live_readiness_fixture_snapshot tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness tests.test_live_kill_switch tests.test_kis_clock_reference_probe` 통과, 35개.
  - `python -m py_compile app/services/live_readiness_fixture.py scripts/build_live_readiness_fixture_snapshot.py tests/test_live_readiness_fixture_snapshot.py` 통과.
  - `bash -n scripts/build_live_readiness_fixture_snapshot.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
- 남은 P0:
  - kill switch 상태 파일을 언제 `OFF`로 생성할지 결정. 현재 missing은 fail-closed로 정상 차단이다.
  - token refresh, WS recovery, account snapshot, market status 증적 확보.
  - Phase 1 승인 뒤 live account read-only header shape 확인.
- 주의:
  - live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_14-1: read-only system_clock probe wrapper 구현

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/brokers/kis_readonly.py`에 generic `get_kis_readonly_client()`와 `last_response_headers` copy 노출을 추가했다. 기존 `get_kis_live_readonly_client()`는 live 전용 제약을 유지한다.
  - `app/services/system_clock_probe.py`를 추가해 read-only 현재가 조회 1회 뒤 HTTP `Date` header를 sanitized `system_clock` readiness check로 변환한다. raw header 원문과 예외 메시지는 저장하지 않는다.
  - `scripts/probe_kis_clock_reference.py`, `scripts/probe_kis_clock_reference.sh`, `scripts/script_dispatch.sh`를 추가/연결해 repo 내부 JSON으로 `system_clock` check를 저장할 수 있게 했다.
  - KIS 모의투자 paper 현재가 read-only probe를 1회 실행해 `runtime-data/reports/live-readiness/system-clock-check.json`을 생성했다. 결과는 `system_clock=true`, skew 약 0.167초였다.
  - `scripts/run_live_readiness_dry_run.sh --system-clock-check-path runtime-data/reports/live-readiness/system-clock-check.json` 실행으로 `system_clock`만 통과 병합되는 것을 확인했다. 나머지 fixture가 없어서 전체 readiness는 안전하게 `blocked`로 남았다.
  - `tests/test_kis_clock_reference_probe.py`, `tests/test_live_readonly_guard.py`를 추가/보강했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`, `README.md`, `AGENTS.md`에 wrapper 구현 상태와 남은 증적 확보 작업을 반영했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-21-production-architecture-implementation-blueprint-work_ver_14-1.md`를 추가하고 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_readonly_guard tests.test_kis_clock_reference_probe tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager` 통과, 84개.
  - `python -m py_compile app/brokers/kis_readonly.py app/services/system_clock_probe.py scripts/probe_kis_clock_reference.py tests/test_kis_clock_reference_probe.py tests/test_live_readonly_guard.py` 통과.
  - `bash -n scripts/probe_kis_clock_reference.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
- 남은 P0:
  - 실제 KIS paper probe 1회 실행 증적.
  - Phase 1 승인 뒤 live account read-only header shape 확인.
  - NAS 실제 package/복구 drill.
- 주의:
  - 실제 KIS 호출은 모의투자 paper 현재가 read-only 1회만 수행했다.
  - KIS live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_14: review_ver_13 P0 후속 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/services/system_clock.py`에서 HTTP `Date` header parser가 timezone 없는 값이나 알 수 없는 timezone을 naive datetime으로 허용하지 않고 `ValueError`로 차단하도록 보강했다.
  - `tests/test_system_clock.py`에 timezone 누락, 알 수 없는 `KST`, 숫자 offset normalization 테스트를 추가했다.
  - `scripts/script_dispatch.sh`의 `run_live_readiness_dry_run.sh` dispatch에 `--system-clock-check-path` 옵션을 추가했다.
  - 이 옵션은 repo 내부 sanitized `system_clock` check JSON을 fixture의 `system_clock`보다 우선 병합한다.
  - `tests/test_live_readiness_dry_run_script.py`에 check path override와 repo 내부 경로 제한 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`에 현재 상태와 남은 P0를 갱신했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-21-production-architecture-implementation-blueprint-work_ver_14.md`를 추가하고 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 36개.
  - `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `python -m py_compile app/services/system_clock.py app/services/live_phase_readiness.py tests/test_system_clock.py tests/test_live_readiness_dry_run_script.py` 통과.
- 남은 P0:
  - fresh KIS read-only 조회 직후 sanitized `system_clock` check를 자동 생성하는 probe/caller 연결.
  - live account read-only header shape 확인.
  - NAS 실제 package/복구 drill.
- 주의:
  - KIS API 신규 호출, live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> 실전 전환 진행상태 문서 추가

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=running`, `session_status=regular-session`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=regular-session`, `live_runtime_should_run=true`, `errors=[]`.
  - 장중 수집 보호 모드라 코드, runtime, 운영 DB, 전체 테스트는 건드리지 않고 문서만 갱신했다.
- 변경:
  - `docs/Production-Transition-Progress.md`를 추가해 실전 전환 phase별 목표, P0 진행 보드, 통과 기준 초안, 열린 결정 항목, 작업 종료 체크리스트를 한곳에 정리했다.
  - `README.md` 핵심 문서 목록과 `AGENTS.md` 문서 역할에 새 진행상태 문서를 추가했다.
- 운영 규칙:
  - 앞으로 실전 전환 관련 작업을 끝낼 때마다 `docs/Production-Transition-Progress.md`를 갱신하고 최종 보고에 링크를 출력한다.
- 주의:
  - KIS API 신규 호출, live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_13 통합본 작성

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=overnight`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=overnight`, `live_runtime_should_run=false`, `errors=[]`.
- 확인:
  - Anthropic 공식 문서 기준 Claude 5시간 사용량은 메시지/첨부/대화 길이/모델/도구/수용량에 따라 달라지고 정확한 token quota는 고정 공개값이 아님을 확인했다.
  - `work_ver_13*` 원문 9개 합계는 41,736 bytes, 30,412 characters, 4,465 whitespace words였다.
  - 원문 전체 전달은 대략 input 12K~18K tokens, 통합본 전달은 input 4K~7K tokens 수준으로 추정했다.
- 변경:
  - cowork 전달용 통합본 `docs/cowork-reports/2026-05-21-production-architecture-implementation-blueprint-work_ver_13.md`를 추가했다.
  - 통합본은 `work_ver_13`, `work_ver_13-1`~`13-8`의 핵심 변경, 남은 P0, 검증, cowork 질문 4개만 압축했다.
  - `docs/cowork-reports/README.md` 색인을 갱신했다.
- 주의:
  - 문서/리포트만 변경했다.
  - KIS API 신규 호출, live order submit/cancel, 운영 DB schema apply, runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-21] Codex -> work_ver_13-8: overnight / pre-open 상태 라벨 분리

- 상태:
  - 작업 시작 시 `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=pre-open`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=pre-open`, `live_runtime_should_run=false`, `errors=[]`.
  - 실제 시각은 01시대라 장전 워밍업이 아니었고, 기존 helper가 정규장 시작 전 모든 시간을 `pre-open`으로 표시하는 문제로 확인했다.
- 변경:
  - `app/utils/time.py`, `scripts/wsl_ops.py`, `scripts/common_process_helpers.sh`에서 일반 거래일 정규장 시작 60분 전부터만 `pre-open`으로 표시하고, 그보다 이른 시간은 `overnight`로 표시하도록 수정했다.
  - `app/services/kis_verification.py`가 `overnight`를 시장 데이터 기대 없음으로 처리하게 했다.
  - `app/services/dashboard.py`가 `overnight`를 장외 안내 상태로 처리하게 했다.
  - `AGENTS.md`, `README.md`, `docs/Current-Implementation.md`에 `overnight`/`pre-open` 경계를 반영했다.
  - 새 회귀 테스트 `tests/test_time_utils.py`를 추가하고, `tests/test_codex_ops.py`, `tests/test_kis_ws_verification.py`, `tests/test_wsl_ops.py`를 보강했다.
  - 수정 전 코드를 메모리에 들고 있던 runtime watchdog만 재시작했다. live runtime 은 계속 `stopped` 상태로 유지했다.
- 검증:
  - `python -m unittest tests.test_time_utils tests.test_codex_ops tests.test_kis_ws_verification tests.test_wsl_ops` 통과, 35개.
  - `python -m py_compile app/utils/time.py app/services/kis_verification.py app/services/dashboard.py scripts/wsl_ops.py tests/test_time_utils.py tests/test_codex_ops.py tests/test_kis_ws_verification.py tests/test_wsl_ops.py` 통과.
  - `bash -n scripts/common_process_helpers.sh scripts/script_dispatch.sh scripts/get_live_runtime_status.sh scripts/get_runtime_watchdog_status.sh` 통과.
  - 수정 후 `./scripts/get_live_runtime_status.sh`: `session_status=overnight`, `status=stopped`.
  - watchdog 재시작 후 `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=overnight`, `live_runtime_should_run=false`, `live_runtime_action=off_session_hold_overnight`.
- 주의:
  - KIS API 신규 호출, live order submit/cancel, 운영 DB schema apply, live runtime restart, 자동 commit/push 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.

## [2026-05-21] Codex -> work_ver_13-7: pre-open 보호 모드 next slice 설계

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=pre-open`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=pre-open`, `live_runtime_should_run=false`, `errors=[]`.
  - `pre-open`은 장중 수집 보호 모드라 루트 코드 파일 변경, 운영 DB 접근 가능성이 있는 명령, runtime restart, 전체 테스트는 하지 않았다.
- 확인:
  - 최신 cowork review는 `review_ver_12`이고 새 review 파일은 없었다.
  - `work_ver_13-6` 이후 남은 P0는 runtime caller/readiness runner가 fresh KIS read-only 조회 직후 system clock decision/check를 자동 생성해 주입하는 연결이다.
- 변경:
  - 코드 변경 없이 `docs/cowork-reports/2026-05-21-production-architecture-implementation-blueprint-work_ver_13-7.md`를 추가했다.
  - 리포트에는 다음 코드 slice 권장 순서로 `KIS clock reference probe wrapper -> live readiness dry-run merge -> Phase 2 submit guard 자동 주입`을 적었다.
  - `docs/cowork-reports/README.md` 색인을 갱신했다.
- 보류:
  - KIS live account read-only 조회.
  - 새 코드 파일 생성 또는 루트 코드 수정.
  - runtime restart, dashboard 재생성, 운영 DB schema apply, 전체 테스트.
- 주의:
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13-6: sanitized system_clock readiness check helper

- 상태:
  - `work_ver_13-5` 이후 cowork 리뷰 없이 이어서 진행했다.
  - KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.
- 변경:
  - `app/services/live_phase_readiness.py`에 `build_system_clock_check_from_http_date_headers()`를 추가했다.
  - 이 helper는 HTTP `Date` header와 local time으로 `system_clock` readiness check result를 만들되, raw header 원문은 저장하지 않고 source, skew, local/reference time, blocking reasons만 남긴다.
  - `tests/test_live_phase_readiness.py`에 sanitized check result가 readiness report에 들어가 통과하고 raw HTTP date 문자열이 check JSON에 남지 않는 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 sanitized readiness check helper 상태를 반영했다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13-6.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_phase_readiness tests.test_system_clock tests.test_live_readiness_dry_run_script` 통과, 31개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 89개.
  - `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
  - `git diff -- app/risk config VERSION` 결과는 비어 있었다.
- 남은 P0:
  - runtime caller/readiness runner가 KIS read-only 조회 직후 helper를 호출해 decision/check를 자동 주입하는 연결.
  - live account read-only API response header 확인 여부 결정.
- 주의:
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13-5: 실제 KIS paper HTTP Date header 확인

- 상태:
  - `work_ver_13-4` 이후 cowork 리뷰 없이 이어서 진행했다.
  - 기존 runtime report에 KIS REST response header/date 증거가 있는지 read-only로 먼저 확인했지만, 기존 산출물에는 header 증거가 없었다.
- 확인:
  - KIS REST 현재가 read-only 조회 1회를 `paper` mode로 실행했다.
  - 대상 symbol은 `005930`이다.
  - 실제 response header key에 `date`가 있음을 확인했다.
  - `app/services/system_clock.py`의 parser가 `kis_rest_http_date` source로 reference time을 파싱했다.
  - 출력에는 계좌번호, token, app key/secret을 남기지 않았다.
- 변경:
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 운영자 결정 템플릿에 실제 KIS paper `date` header 확인 사실을 반영했다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13-5.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 88개.
  - `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
  - `git diff -- app/risk config VERSION` 결과는 비어 있었다.
- 남은 P0:
  - KIS live account read-only 응답에서도 `date` header를 추가 확인할지 결정.
  - runtime caller/readiness runner가 fresh read-only 조회 직후 `last_response_headers`에서 decision을 만들고 submit guard/readiness에 주입하도록 연결.
- 주의:
  - KIS 실전 주문 없음.
  - live order submit/cancel 없음.
  - runtime restart 없음.
  - 운영 DB schema apply 없음.
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13-4: HTTP Date readiness wrapper 검증

- 상태:
  - `work_ver_13-3` 이후 cowork 리뷰 없이 이어서 진행했다.
  - KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.
- 변경:
  - `tests/test_live_readiness_dry_run_script.py`에 HTTP `Date` 기반 `system_clock` fixture가 `scripts/run_live_readiness_dry_run.sh` wrapper를 통과하는 테스트를 추가했다.
  - fixture shape는 `{local_time, http_date, reference_source}`이고, output의 `fixture_checks`에서 `source=kis_rest_http_date`, `skew_seconds=1.0`을 확인한다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13-4.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness tests.test_system_clock` 통과, 30개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 88개.
  - `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
  - `git diff -- app/risk config VERSION` 결과는 비어 있었다.
- 남은 P0:
  - 실제 KIS response header fixture 확인.
  - runtime caller/readiness runner가 KIS read-only 조회 직후 decision을 자동 생성해 주입하는 연결.
- 주의:
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13-3: HTTP Date clock decision submit guard 연결 테스트

- 상태:
  - `work_ver_13-2` 이후 cowork 리뷰 없이 이어서 진행했다.
  - KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.
- 변경:
  - `tests/test_live_order_manager.py`에 HTTP `Date` header에서 만든 clock decision이 `require_clock_skew_check=True` submit을 통과시키는 테스트를 추가했다.
  - 같은 파일에 stale HTTP `Date` header decision이 broker 호출 전 `blocked`로 차단되는 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 운영자 결정 템플릿에 live order manager submit guard가 HTTP `Date` 기반 decision을 받을 수 있는 상태와 runtime caller/readiness 자동 주입 전 상태를 분리해 반영했다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13-3.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_order_manager tests.test_system_clock tests.test_kis_http_clients` 통과, 41개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 87개.
  - `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_order_manager.py app/services/live_order_guard.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_order_manager.py tests/test_live_order_guard.py tests/test_live_phase_readiness.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
  - `git diff -- app/risk config VERSION` 결과는 비어 있었다.
- 남은 P0:
  - 실제 KIS response header fixture로 `Date` header 존재 여부 확인.
  - runtime caller/readiness runner가 KIS header에서 `system_clock` decision을 자동 생성해 주입하는 연결.
- 주의:
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13-2: KIS REST header clock 연결점

- 상태:
  - `work_ver_13-1` 이후 cowork 리뷰 없이 이어서 진행했다.
  - KIS API 신규 호출, 실전 주문, runtime restart, 운영 DB schema apply는 하지 않았다.
- 변경:
  - `app/brokers/kis_quote_rest.py`의 `KisRestQuoteClient`에 `last_response_headers` read-only copy 속성을 추가했다.
  - 이 속성은 마지막 성공 KIS REST 응답 header를 메모리에서만 확인하기 위한 진단 연결점이며, 기존 public method 반환값은 바꾸지 않는다. 실패 요청 뒤 이전 header가 clock reference로 오용되지 않도록 요청 시작 시 stale header를 비운다.
  - `app/services/system_clock.py`에 HTTP `Date` header에서 바로 clock skew decision을 만드는 `evaluate_clock_skew_from_http_date_header()` 순수 helper를 추가했다.
  - `tests/test_kis_http_clients.py`에 KIS REST mock 응답의 HTTP `Date` header를 `last_response_headers`로 읽고 `reference_time_from_http_date_header()`로 파싱하는 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 운영자 결정 템플릿에 KIS REST header 노출 완료와 runtime guard/readiness 연결 전 상태를 분리해 반영했다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13-2.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_kis_http_clients tests.test_system_clock` 통과, 18개.
  - helper 추가 후 `python -m unittest tests.test_system_clock tests.test_kis_http_clients` 통과, 20개.
  - stale header clear 보강 후 `python -m unittest tests.test_kis_http_clients tests.test_system_clock` 통과, 21개.
  - `python -m unittest tests.test_kis_http_clients tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops` 통과, 56개.
  - `python -m py_compile app/brokers/kis_quote_rest.py app/services/system_clock.py app/services/live_phase_readiness.py tests/test_kis_http_clients.py tests/test_system_clock.py tests/test_live_phase_readiness.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
  - `git diff -- app/risk config VERSION` 결과는 비어 있었다.
- 남은 P0:
  - 실제 KIS response header fixture로 `Date` header 존재 여부 확인.
  - runtime submit guard/readiness runner가 `last_response_headers`와 `system_clock` decision을 연결하도록 구현.
- 주의:
  - response header는 report/audit에 저장하지 않는다. 저장이 필요하면 별도 redaction 검토 전 금지한다.
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13-1: Phase 1 P0 후속 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강과 read-only recovery dry-run 확인을 진행했다.
- 변경/확인:
  - `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run` 실행을 완료했다.
  - dry-run 출력 후보는 `.tmp-tests/recovery-dry-run/codex-recovery-dry-run-20260520-220625.tar.gz`였고, 실제 tar package는 생성하지 않았다.
  - 저장소는 약 56GB, `runtime-data`는 약 45GB라 실제 local package 생성 또는 NAS 강제 백업은 별도 승인 없이는 진행하지 않는다.
  - `app/services/system_clock.py`에 HTTP `Date` header를 reference timestamp로 파싱하는 순수 helper를 추가했다.
  - `app/services/live_phase_readiness.py`의 `system_clock` fixture가 `local_time`과 `reference_time` 또는 HTTP `Date` header로 skew를 평가할 수 있게 했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 운영자 결정 템플릿에 현재 구현/후속 경계를 갱신했다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13-1.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 27개.
  - `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_wsl_ops` 통과, 51개.
  - `python -m py_compile app/services/system_clock.py app/services/live_phase_readiness.py tests/test_system_clock.py tests/test_live_phase_readiness.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
  - `git diff -- app/risk config VERSION` 결과는 비어 있었다.
- 남은 P0:
  - reference clock 원천 결정과 실제 KIS response header runtime 연결.
  - 실제 recovery package 표본 확인 또는 NAS 강제 백업 drill.
- 주의:
  - KIS API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-20] Codex -> work_ver_13: review_ver_12 후속 보강

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 코드/문서 보강을 진행했다.
- 변경:
  - `app/brokers/kis_quote_ws.py`의 `KisWebSocketReconnectSnapshot`에 `observed_at`, `last_reconnect_at`, `last_stable_at`, `storm_active_since`를 추가했다.
  - dashboard/readiness JSON 연결을 대비해 `KisWebSocketReconnectSnapshot.to_dict()`를 추가했다.
  - `metrics_callback`은 동기 호출이므로 DB/file/network I/O 대신 in-memory update나 worker queue를 쓰라는 docstring을 `listen()`에 추가했다.
  - `tests/test_kis_ws_reconnect_metrics.py`에 timestamp, storm duration, JSON 직렬화 회귀 테스트를 추가했다.
  - `docs/Production-Implementation-Blueprint.md`에 Phase 1 진입 전 P0 4개 진행표를 추가했다.
  - `docs/Production-Architecture.md`에 Phase 2 기본 `max_order_qty=1`과 override 방법을 반영했다.
  - `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision-template.md`에 reference clock 원천과 NAS recovery 실제 dry-run 결정 항목을 추가했다.
  - `docs/cowork-reports/2026-05-20-production-architecture-implementation-blueprint-work_ver_13.md`를 추가하고 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification` 통과, 13개.
  - `python -m py_compile app/brokers/kis_quote_ws.py tests/test_kis_ws_reconnect_metrics.py` 통과.
  - review_ver_12 후속 전체 관련 묶음 `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_live_order_manager tests.test_kis_http_clients tests.test_live_execution_sync tests.test_wsl_ops` 통과, 62개.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- 남은 P0:
  - NAS recovery 실제 dry-run 1회 완료.
  - reference clock 원천 결정과 `system_clock` 연결.
- 주의:
  - KIS API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-19] Codex -> work_ver_12-3: NAS recovery self-test 상태 확인

- 상태:
  - 실제 NAS 공유 쓰기/대용량 백업은 실행하지 않았다.
  - 저장소 내부 recovery export self-test와 기존 runtime report 존재 여부만 확인했다.
- 확인:
  - `tests.test_wsl_ops`는 `runtime-data/reports/alerts/`, `runtime-data/reports/live-risk/`, `runtime-data/reports/live-approvals/`, `runtime-data/ops/`, `runtime-data/ml/registry-backups/` 포함을 검증한다.
  - 같은 테스트가 root `.env`, `runtime-data/cache/kis`, `runtime-data/logs`, `*.pem`, `*.key`, `id_rsa*` 제외를 검증한다.
  - `runtime-data/reports` 아래 기존 `backup`/`recovery`/`nas` report 파일은 확인되지 않았다.
- 검증:
  - `python -m unittest tests.test_wsl_ops` 통과, 11개.
- 미검증:
  - `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run`은 WSL sandbox approval review timeout으로 실행 완료 확인을 하지 못했다. repository 문제로 단정하지 않고 `not_verified`로 남긴다.
- 주의:
  - 실제 NAS 공유 접근 없음.
  - KIS API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - runtime restart 없음.
  - 자동 commit/push 없음.

## [2026-05-19] Codex -> work_ver_12-2: KIS fixture mapper 검증

- 상태:
  - 장후 `post-close` 상태에서 진행했다.
  - KIS API를 새로 호출하지 않고 `runtime-data/dev.db`를 read-only로 읽는 fixture export만 실행했다.
- 변경:
  - `scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings`로 redacted KIS paper fixture 후보를 갱신했다.
  - `broker_paper_order_status_snapshots` richest candidate에 KIS 원 필드 `ord_dt`, `ord_gno_brno`, `odno`, `pdno`, `sll_buy_dvsn_cd`, `ord_qty`, `tot_ccld_qty`, `rmn_qty`, `avg_prvs`, `cncl_yn` 등이 있음을 확인했다.
  - `tests/test_kis_http_clients.py`에 redacted runtime fixture shape 기반 `get_daily_order_fills()` 정규화 테스트를 추가했다.
  - `tests/test_live_execution_sync.py`에 정규화 record가 `snapshot_from_kis_daily_order_fill()`에서 `sell`/`filled` snapshot으로 변환되는 테스트를 추가했다.
  - Phase 2 기본 `max_order_qty=1` 때문에 기존 execution sync helper 주문이 막히는 것을 확인했고, execution sync 테스트 목적에 맞게 helper 정책에 `max_order_qty=10`을 명시했다. 운영 기본값은 바꾸지 않았다.
  - `docs/cowork-reports/2026-05-19-production-architecture-implementation-blueprint-work_ver_12-2.md`를 추가하고, `docs/Production-Implementation-Blueprint.md`와 cowork report 색인을 갱신했다.
- 검증:
  - `python scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings`: `status=ok`, `redaction_ok=true`.
  - `python -m unittest tests.test_kis_http_clients tests.test_live_execution_sync tests.test_live_order_manager` 통과, 38개.
  - `python -m py_compile tests/test_kis_http_clients.py tests/test_live_execution_sync.py` 통과.
  - 오늘 변경 범위 전체 관련 묶음 `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_live_order_manager tests.test_live_order_guard tests.test_kis_http_clients tests.test_live_execution_sync` 통과, 59개.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- 주의:
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-19] Codex -> work_ver_12-1: WS reconnect metric과 Phase 2 1주 제한

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=post-close`, `live_runtime_should_run=false`, `errors=[]`.
  - 장후 상태라 루트 코드 보강과 좁은 테스트를 진행했다.
- 변경:
  - `app/brokers/kis_quote_ws.py`에 `KisWebSocketReconnectMetrics`와 snapshot을 추가했다.
  - WebSocket reconnect 관측값은 누적 reconnect, 연속 reconnect, 안정 frame 수신 후 reset, reconnect storm 판정, optional `metrics_callback`을 포함한다.
  - 관측 callback 예외는 warning으로 흡수해, dashboard/readiness 연결 실패가 WebSocket 수집 자체를 끊지 않게 했다.
  - 기존 `max_reconnects` 동작은 누적 reconnect 기준 그대로 유지했다.
  - `app/services/live_order_manager.py`에 Phase 2 기본 부모 주문 수량 제한 `max_order_qty=1`을 추가했다.
  - Phase 2 부모 주문 수량이 기본 1주를 넘으면 broker 호출 전에 `phase2_order_qty_limit_exceeded`로 `blocked` 처리하고 `{current, limit}` context를 남긴다.
  - `docs/cowork-reports/2026-05-19-production-architecture-implementation-blueprint-work_ver_12-1.md`를 추가하고, `docs/Production-Implementation-Blueprint.md`와 cowork report 색인을 갱신했다.
- 검증:
  - `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_live_order_manager tests.test_live_order_guard` 통과, 39개.
  - `python -m py_compile app/brokers/kis_quote_ws.py app/services/live_order_manager.py tests/test_kis_ws_reconnect_metrics.py tests/test_live_order_manager.py` 통과.
  - `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- 주의:
  - KIS API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - runtime restart 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-19] 장후 자동화 중복 실행 방지 가드

- 확인:
  - Codex 앱 cron `automation-2`는 17:30 KST 상태 관찰용이며, 직접 WSL 명령을 실행하지 않는 설정이다.
  - 실제 장후 실행은 Windows 작업 스케줄러 `RealTimeStockRuntime_PostCloseOps`가 16:40 KST에 `run_post_close_ml_maintenance.sh --quick`, `run_post_close_label_refresh.sh --recent-days 10`, paper 계좌 확인, dashboard build를 실행하는 구조다.
  - 오늘은 16:40 자동 실행 이후 수동으로 장후 ML 유지보수를 다시 실행해 16시 이후 bounded LightGBM training/challenger 그룹이 3개까지 늘었다.
  - 중복 이력은 DB의 과거 training/evaluation row를 늘렸지만, active registry는 `baseline-h15-v1` 유지이고 최신 challenger는 가장 최근 run만 reference 하므로 모델 승격/주문 실행에는 영향이 없었다.
- 조치:
  - `scripts/script_dispatch.sh`의 `post_close_ml_maintenance`에 같은 날짜, 같은 horizon, 같은 maintenance scope가 이미 `status=ok`이면 즉시 skip하는 daily guard를 추가했다.
  - `scripts/script_dispatch.sh`의 `post_close_label_refresh`에도 같은 날짜, 같은 recent-days, 같은 skip-build 옵션이 이미 `status=ok`이면 즉시 skip하는 daily guard를 추가했다.
  - 두 경로 모두 `--force`/`-Force`를 주면 의도적으로 재실행할 수 있다.
  - `--dry-run`은 실행 계획 확인 용도라 label refresh daily guard를 우회하도록 했다.
  - `tests/test_post_close_maintenance_script.py`와 `tests/test_post_close_label_refresh_script.py`에 daily guard 회귀 테스트를 추가했다.
- 검증:
  - `bash -n scripts/script_dispatch.sh` 통과.
  - `./scripts/run_post_close_ml_maintenance.sh --quick --horizon-min 15` 재실행 시 `post-close ML maintenance already ok for today; skipping` 출력 후 종료.
  - `./scripts/run_post_close_label_refresh.sh --recent-days 10` 재실행 시 `post-close label refresh already ok for today; skipping` 출력 후 종료.
  - skip 검증 전후 2026-05-19 16시 이후 `ml_training_runs` 개수와 challenger 그룹 수는 각각 3개로 변동 없음.
  - `python -m unittest tests.test_post_close_maintenance_script tests.test_post_close_label_refresh_script` 통과.
  - runtime watchdog은 `ml_maintenance_action=already_ok`, errors 없음.

## [2026-05-19] 장후 유지보수와 전체 상태 점검

- 실행:
  - `./scripts/run_post_close_label_refresh.sh --recent-days 10 --skip-build`를 실행했다.
  - `./scripts/refresh_kis_account.sh`로 KIS paper 계좌 스냅샷을 갱신했다.
  - `./scripts/run_post_close_ml_maintenance.sh --quick --horizon-min 15`를 실행했다.
- 결과:
  - post-close ML state: `status=ok`, `mode=quick-live-train`, completed_at `2026-05-19 17:14:49 +0900`.
  - latest dashboard generated_at: `2026-05-19T17:15:21+09:00`.
  - KIS live data quality: `status=ok`.
  - feature source drift: Cybos historical에는 live orderbook feature 분포가 없어 KIS live 성능 proxy로 직접 취급하면 안 된다는 기존 경고 유지.
  - KIS live feature diagnostics: 단일 feature의 독립 신호는 아직 약하므로 live data 누적 필요.
  - 최신 bounded LightGBM training: `train-lightgbm-h15-20260519171203590318`, train 171,941 / validation 56,643, validation accuracy 0.621401.
  - 최신 challenger holdout: latest LightGBM accuracy 0.489914, trade_hit_rate 0.285714, cumulative_net_return_pct -30.532644. 추천은 `keep_active`로 baseline 유지.
  - paper account reconciliation: `aligned_waiting_first_submission`, 현금/총자산/수량 gap 0.
  - 새 `OnlinePipelineProcessor` 초기화 기준 pending 주문 set은 비어 있다.
- 운영 상태:
  - live runtime은 장마감 상태로 중지.
  - runtime watchdog과 dashboard는 정상 실행 중이고 errors 없음.
- 주의:
  - 다른 스레드의 실전운용 설계 변경 파일은 건드리지 않았다.

## [2026-05-19] 장후 paper 주문 pending 차단 해소

- 계기:
  - 대시보드 오늘 요약에서 예측 7,600건, 신호 3,800건대가 있었지만 주문/체결은 0으로 표시됐다.
  - DB 확인 결과 오늘 신호 중 허용 신호가 있었으나, 과거 미해결 paper 주문이 `broker_order_pending`과 `max_open_positions_reached`를 유발해 신규 주문 직전에서 차단됐다.
- 원인:
  - 2026-05-15 이전 `pending_lookup`/`submitted`/`open` 주문들이 남아 있었다.
  - `OnlinePipelineProcessor._restore_pending_order_state`가 paper alignment cutoff를 적용하지 않아, alignment 이전 주문까지 다음 런타임의 pending set으로 되살렸다.
- 조치:
  - `app/services/streaming.py`에서 pending 주문 복원 시 `filter_rows_after_alignment(..., time_fields=("event_time",))`를 적용하도록 수정했다.
  - `tests/test_streaming_pipeline.py`에 alignment 이전 pending 주문은 복원하지 않고, alignment 이후 pending 주문만 복원하는 회귀 테스트를 추가했다.
  - `./scripts/align_local_paper_to_broker.sh`를 실행해 현재 KIS 모의계좌 기준으로 로컬 paper baseline을 재정렬했다.
  - `./scripts/sync_broker_paper_orders.sh` 재실행 결과 `status=no_submissions`, `open_order_count=0`, `pending_symbols=[]`를 확인했다.
  - `./scripts/reconcile_paper_accounts.sh`와 `./scripts/verify_paper_dual_account_match.sh -AsJson` 결과 현금/총자산/수량 gap이 모두 0이고, 상태가 `matched_waiting_first_submission`으로 바뀌었다.
  - 대시보드 스냅샷을 2026-05-19T16:54:11+09:00 기준으로 재생성했다.
- 현재 상태:
  - 새 `OnlinePipelineProcessor` 초기화 확인: `pending_order_symbols=[]`, `pending_buy_symbols=[]`.
  - 로컬/브로커 paper 포지션은 005380 1주로 일치한다.
- 검증:
  - `python -m py_compile app/services/streaming.py tests/test_streaming_pipeline.py` 통과.
  - `python -m unittest tests.test_streaming_pipeline` 통과.

## [2026-05-19] Codex -> work_ver_12: review_ver_11 반영 계획

- 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=running`, `trading_mode=paper`, `session_status=regular-session`.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=regular-session`, `live_runtime_should_run=true`, `errors=[]`.
  - 장중 수집 보호 모드라 루트 코드 변경은 하지 않았다.
- 확인:
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`를 확인했다.
  - cowork는 `work_ver_11` 시리즈를 그대로 사용 가능하다고 평가했고, Phase 1 전 P0로 NAS 복구 drill, KIS 실제 응답 fixture 검증, WS keepalive/reconnect metric을 제안했다.
  - 작성 당시 코드 검색상 Phase 2 `max_order_qty=1` 정책과 WS 누적/연속 reconnect metric은 아직 구현되지 않았다.
- 변경:
  - `docs/cowork-reports/2026-05-19-production-architecture-implementation-blueprint-work_ver_12.md`를 추가했다.
  - `docs/cowork-reports/README.md`에 새 report를 등록했다.
- 다음:
  - 장 종료 후 WS reconnect metric, Phase 2 `max_order_qty=1`, KIS fixture mapper 검증, NAS 복구 drill 절차 순으로 진행하기로 했다.
- 주의:
  - 코드 변경 없음.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] LightGBM 안전 학습 제한과 대시보드 ML 표시 최신화

- 계기:
  - 기본 `python -m app --train-lightgbm --horizon-min 15`가 전체 labeled feature dataset을 메모리에 올려 20분 이상 14GB RAM을 사용했다.
  - 대시보드의 최근 학습/평가가 2026-05-09에 머무른 원인은 실제 DB에 새 학습/평가 row가 없었기 때문이다.
- 변경:
  - `fetch_feature_rows`에 `max_rows` 제한을 추가했다.
  - `--train-lightgbm`와 `--run-challengers` 기본 로드 범위를 최근 labeled row 250,000건으로 제한하고, `--train-lightgbm-max-rows 0` / `--challenger-max-rows 0`으로 전체 이력을 명시 실행할 수 있게 했다.
  - 학습 요약과 챌린저 리포트에 `dataset_load` 메타데이터를 기록하도록 했다.
  - 대시보드의 walk-forward 표기를 `워크포워드 설정`과 `게이트 성능 판단`으로 분리해, 설정은 정상이어도 성능 gate가 미달이면 `점검 필요`로 보이게 했다.
  - `run_post_close_ml_maintenance.sh --quick` 경로에 제한 LightGBM 학습과 challenger 평가를 붙이고, state mode를 `quick-live-train`으로 바꿨다.
  - post-close ML state를 쓴 뒤 dashboard를 한 번 더 빌드해 대시보드가 새 `quick-live-train` state를 같은 실행 안에서 보게 했다.
  - runtime watchdog/status의 quick post-close mode 표시도 `quick-live-train`으로 맞췄다.
- 실행 결과:
  - 제한 LightGBM 학습 완료: `train-lightgbm-h15-20260518223024221721`, train 175,600 / validation 53,330, validation accuracy 0.622351, elapsed 2:33, max RSS 약 862MB.
  - 제한 챌린저 평가 완료: `challenger-h15-20260518223134766216`, 최신 LightGBM holdout accuracy 0.517655, trade_hit_rate 0.285714, net -13.599472%, 추천은 baseline 유지.
  - 대시보드 재생성: 2026-05-18T22:40:47+09:00.
  - 대시보드 서버 재시작: pid 112813, `http://127.0.0.1:8765`.
- 확인:
  - 머신러닝 탭에 오늘 학습 1건, 오늘 평가 5건, 최신 학습 run `train-lightgbm-h15-20260518223024221721` 표시 확인.
  - 장후 ML 유지보수 카드는 `quick-live-train`이 제한 학습/평가를 수행하고, legacy `quick-live-report`는 학습/평가 row를 만들지 않는다고 표시한다.
  - 게이트 기준 워크포워드 카드는 설정 상태 `정상`, 게이트 성능 판단 `점검 필요`로 분리 표시한다.
- 검증:
  - `python -m unittest tests.test_research_pipeline` 통과.
  - `python -m unittest tests.test_dashboard` 통과.

## [2026-05-18] 대시보드 ML 최신 시각/장후 상태 불일치 점검

- 원인:
  - 정본 DB의 최신 `ml_training_runs`/`ml_model_evaluations`는 2026-05-09 기록이 맞다.
  - 2026-05-18 장후 `run_post_close_ml_maintenance.sh --quick`는 학습/평가 row를 만들지 않고 리포트, 품질 진단, 대시보드만 갱신한다.
  - `run_post_close_label_refresh.sh --skip-build`는 state를 `ok`로 쓰기 전에 dashboard를 먼저 빌드해 대시보드가 직전 `running` 상태를 물고 있을 수 있었다.
- 조치:
  - `scripts/script_dispatch.sh`에서 label refresh state를 `ok`로 기록한 뒤 dashboard를 빌드하도록 순서를 수정했다.
  - `app/services/dashboard.py`의 장후 카드를 `장후 ML 유지보수 상태`로 바꾸고, quick-live-report가 학습/평가 row를 만들지 않는다는 설명과 `학습/평가 수행` 행을 추가했다.
  - `tests/test_dashboard.py` 기대 문구를 새 의미에 맞게 갱신했다.
  - `./scripts/run_post_close_label_refresh.sh --recent-days 10 --skip-build`와 `python -m app --build-dashboard`를 실행해 latest dashboard에 label refresh `ok`를 반영했다.
- 확인:
  - dashboard generated_at: 2026-05-18T22:14:12+09:00.
  - label refresh state: `ok`, completed_at 2026-05-18 22:13:03 +0900.
  - 최신 학습/평가 시각은 실제 DB 기준 2026-05-09로 유지된다.
  - full `python -m app --train-lightgbm --horizon-min 15`는 20분 이상 14GB RAM을 사용해 시스템 안정성을 위해 중단했다. 현재 CLI는 row 제한 없이 전체 labeled feature dataset을 메모리에 올린다.
- 검증:
  - `bash -n scripts/script_dispatch.sh` 통과.
  - `python -m unittest tests.test_dashboard` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 274개.
  - `git diff --check -- app/services/dashboard.py scripts/script_dispatch.sh tests/test_dashboard.py` 통과.
- 주의:
  - 다른 스레드의 실전 운영 준비 변경이 작업트리에 많아 commit/push는 하지 않았다.
  - 후속 권장 작업은 LightGBM 학습 CLI에 `max_rows` 또는 최근 거래일 제한을 추가해 장후 자동 학습을 안전하게 만드는 것이다.

## [2026-05-18] Codex -> work_ver_11-20: work_ver_11 전체 통합 handoff

- 목적:
  - cowork에 11번대 작업본이 아직 전달되지 않은 상태라 `work_ver_11`부터 `work_ver_11-19`까지를 하나의 토큰 절약형 handoff로 통합했다.
- 변경:
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-20.md`를 추가했다.
  - `docs/cowork-reports/README.md`에 새 통합본을 등록했다.
- 전달 권장:
  - cowork에는 우선 `work_ver_11-20` 하나만 전달한다.
  - 리뷰 파일명은 `2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`를 권장한다.
  - 세부 확인이 필요할 때만 개별 `work_ver_11-*` 파일을 추가로 열어본다.
- 주의:
  - 코드 변경 없음.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-19: market data freshness submit guard hook

- 계기:
  - 장중 KIS WebSocket 반복 재연결 관찰 후, 실전 구조에서도 `runtime running` 또는 `WS connected`만으로 주문을 허용하면 같은 문제가 발생할 수 있음을 확인했다.
  - post-close 상태에서 live runtime이 정지되어 좁은 코드 보강을 진행했다.
- 변경:
  - `app/services/market_data_freshness.py`를 추가해 최신 체결 tick, 호가 tick, 1분봉, 예측 timestamp의 age를 순수 함수로 판정한다.
  - `app/services/live_order_guard.py`의 `assert_can_submit()`에 선택적 `market_data_freshness_decision`과 `require_market_data_freshness_check` hook을 추가했다.
  - `tests/test_market_data_freshness.py`를 추가하고, `tests/test_live_order_guard.py`에 stale freshness 차단/필수 check 누락 차단 테스트를 추가했다.
  - `docs/Production-Implementation-Blueprint.md`와 `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-19.md`에 변경 범위를 기록했다.
- 검증:
  - `python -m unittest tests.test_market_data_freshness tests.test_live_order_guard` 통과, 15개.
  - `git diff --check` 통과. 기존 `docs/Current-Implementation.md`, `docs/logbook.md` CRLF 경고만 확인.
- 주의:
  - 이 helper는 아직 storage/dashboard/runtime 최신 row 조회와 자동 연결하지 않았다. 다음 단계는 runtime/report freshness snapshot을 guard 입력으로 넘기는 연결이다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] 장중 runtime 점검: KIS WebSocket 반복 재연결 관찰

- 계기:
  - 장전/장중 runtime check에서 이슈 가능성이 보여 read-only로 확인했다.
- 확인:
  - `./scripts/get_live_runtime_status.sh`: live runtime `running`, `trading_mode=paper`, `session_status=regular-session`.
  - `./scripts/get_runtime_watchdog_status.sh`: watchdog `running`, `live_runtime_should_run=true`, heartbeat stale 아님.
  - `./scripts/get_dashboard_status.sh`: dashboard/API 응답 정상.
  - `runtime-data/logs/app/live-runtime.stderr.log`: 2026-05-18 08:02~10:04 사이 KIS WebSocket disconnect/reconnect 반복, 마지막 확인 기준 attempt 26.
  - `runtime-data/dev.db` read-only 최신 row 확인:
    - `raw_market_ticks`: 2026-05-18T10:38:00+09:00, 005930.
    - `raw_orderbook_ticks`: 2026-05-18T10:38:00+09:00, 247540.
    - `curated_minute_bars`: 2026-05-18T10:37:00+09:00, 207940.
    - `serving_predictions`: 2026-05-18T10:37:00+09:00, 207940, 60분.
    - `serving_trade_signals`: 2026-05-18T10:37:00+09:00, 207940, `allowed=0`.
- 조치:
  - 데이터 유입은 최신 상태라 장중 runtime restart는 하지 않았다.
  - 현재 조치는 `관찰 지속`이다. 같은 disconnect가 재개되면서 최신 tick/bar가 밀리면 장중 수집 보호 원칙에 따라 재시작 여부를 별도 판단한다.
- 1차 원인 분석:
  - 확정 원인은 아니다. KIS 서버 close code, 서버 로그, 공지 확인이 없으므로 KIS 측 강제 종료인지 로컬 keepalive/구독 처리 문제인지 단정하지 않는다.
  - 로컬 구현상 `app/brokers/kis_quote_ws.py`의 `_connection_kwargs()`는 `ping_interval=None`, `ping_timeout=None`으로 WebSocket ping keepalive를 끈다.
  - 같은 파일의 `listen()`은 disconnect 후 재연결하지만 `reconnect_attempt`를 성공 연결 뒤 0으로 리셋하지 않는다. 현재 `attempt 26/999999`는 연속 실패 횟수라기보다 실행 이후 누적 재연결 횟수에 가깝다.
  - `frame_timeout_seconds=30` 안에 frame이 없으면 `KisApiError`로 재연결한다. 이번 로그의 주된 메시지는 timeout 문구가 아니라 `no close frame received or sent`라서, 로컬 timeout보다 상대 peer 또는 네트워크 계층에서 close frame 없이 연결이 끊긴 상황으로 보인다.
  - 현재 runtime은 최신 tick/bar/prediction/signal을 계속 쓰고 있으므로, 이번 시점에는 `수집 중단`이 아니라 `반복 재연결을 동반한 수집 지속`으로 분류한다.
- 실전 구조 반영 필요:
  - 실전 전환 구조에서도 같은 문제가 날 수 있다. WebSocket 연결은 브로커/네트워크/장 구간 특성에 의해 끊길 수 있다고 가정해야 한다.
  - production 구조에서는 disconnect count보다 `최신 market tick age`, `최신 orderbook age`, `bar/prediction stale`, `연속 실패 시간`, `reconnect storm`를 별도 지표로 봐야 한다.
  - reconnect attempt는 누적 횟수와 연속 실패 횟수를 분리하고, 성공 연결 또는 일정 시간 데이터 유입 후 연속 실패 카운터를 리셋하는 설계가 필요하다.
  - 실전 주문 전에는 WS가 살아 있어도 market data freshness가 stale이면 신규 주문을 차단해야 한다.
  - 코드 변경은 장중 보호 모드라 수행하지 않았다. 후속 권장 작업은 `KisWebSocketQuoteClient`에 keepalive/reconnect metric hook과 테스트를 추가하고, readiness/dashboard에 stale data gate를 연결하는 것이다.
- 주의:
  - KIS API 신규 호출 없음.
  - 실전 주문 없음.
  - runtime DB 쓰기 없음. DB 확인은 read-only connection으로 수행했다.
  - `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-18: cowork 전달용 통합 handoff

- 목적:
  - cowork 토큰 사용량을 줄이기 위해 `work_ver_11-10`부터 `work_ver_11-17`까지의 핵심 변경, 검증, 검토 질문을 하나로 묶었다.
- 변경:
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-18.md`를 추가했다.
  - `docs/cowork-reports/README.md`에 새 handoff 파일을 등록했다.
- 검증:
  - 새 handoff는 기존 개별 report를 대체하지 않고 요약만 제공한다.
- 주의:
  - 코드 변경 없음.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-17: system clock submit guard hook

- 목적:
  - 시스템 시계 오차 check가 readiness에만 머물지 않고 주문 submit guard에서 사용할 수 있는 연결 지점을 만들었다.
  - 기준 시각 원천은 아직 정하지 않았으므로 기본 submit 동작은 clock check를 강제하지 않는다.
- 변경:
  - `app/services/live_order_guard.py`의 `assert_can_submit()`에 선택적 `clock_skew_decision`과 `require_clock_skew_check` hook을 추가했다.
  - `app/services/live_order_manager.py`의 `submit_intent()`가 해당 hook을 guard에 전달할 수 있게 했다.
  - clock decision이 차단이면 `system_clock_skew_exceeded`, 필수 check인데 누락이면 `system_clock_check_missing`으로 broker 호출 전 차단된다.
  - `tests/test_live_order_guard.py`, `tests/test_live_order_manager.py`에 clock hook 차단 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 system clock guard hook 범위를 반영하고, market status가 이미 live submit guard 입력으로 연결된 사실을 문서화했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-17.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_order_guard.py app/services/live_order_manager.py tests/test_live_order_guard.py tests/test_live_order_manager.py app/services/system_clock.py` 통과.
  - `python -m unittest tests.test_live_order_guard tests.test_live_order_manager tests.test_system_clock` 통과, 30개.
  - `python -m unittest tests.test_system_clock tests.test_market_status tests.test_live_order_guard tests.test_live_order_manager tests.test_live_execution_sync tests.test_live_alerting tests.test_live_audit tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_reporting tests.test_dashboard` 통과, 100개.
- 주의:
  - 기준 시각 원천과 기본 강제 여부는 아직 후속 결정 대상이다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-16: live execution sync raw output redaction

- 목적:
  - 체결 sync가 order/fill/event detail에 broker raw output을 저장할 때 비밀값이 남을 위험을 줄였다.
  - 실제 KIS REST 조회나 체결 sync 호출은 추가하지 않았다.
- 변경:
  - `app/services/live_execution_sync.py`에서 order detail, fill detail, order event detail에 raw broker output을 저장하기 전 redaction한다.
  - `tests/test_live_execution_sync.py`에 `account_number`, `app_secret` redaction과 안전 예외 key `pdno` 유지 검증을 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 execution sync raw output redaction을 반영했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-16.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_execution_sync.py tests/test_live_execution_sync.py app/brokers/kis_response_redaction.py` 통과.
  - `python -m unittest tests.test_live_execution_sync tests.test_kis_response_redaction` 통과, 14개.
- 주의:
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-15: live order manager raw response redaction

- 목적:
  - 주문 manager가 `live_orders.detail_json`과 `live_order_events.detail_json`에 broker raw response를 저장할 때 비밀값이 남을 위험을 줄였다.
  - 실제 broker 호출이나 외부 발송은 추가하지 않았다.
- 변경:
  - `app/services/live_order_manager.py`에서 raw broker response를 저장하거나 `LiveOrderManagerResult.raw_response`로 반환하기 전 `app/brokers/kis_response_redaction.py` helper로 redaction한다.
  - `tests/test_live_order_manager.py`에 `account_number`, `app_secret` redaction과 안전 예외 key `pdno` 유지 검증을 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 주문 manager raw response redaction을 반영했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-15.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_order_manager.py tests/test_live_order_manager.py app/brokers/kis_response_redaction.py` 통과.
  - `python -m unittest tests.test_live_order_manager tests.test_kis_response_redaction` 통과, 19개.
  - `python -m unittest tests.test_live_order_manager` 통과, 16개.
- 주의:
  - `app/services/live_execution_sync.py`의 raw output redaction은 아직 후속 점검 필요.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-14: live order intent 입력 검증

- 목적:
  - 잘못된 실전 주문 intent가 broker 호출 전이라도 운영 원장에 남는 위험을 줄였다.
  - 실제 KIS live adapter 연결이나 주문 전송은 추가하지 않았다.
- 변경:
  - `app/services/live_order_manager.py`의 `create_intent()` 시작 지점에서 필수 trace field, side, qty, limit price를 검증한다.
  - 빈 `prediction_id` 등 필수 field, 0 이하 qty, 0 이하 limit 주문 가격은 DB write 전에 `ValueError`로 거부된다.
  - `tests/test_live_order_manager.py`에 invalid intent가 `live_orders`와 `live_order_events`를 쓰지 않는 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 intent 입력 검증을 반영했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-14.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_order_manager.py tests/test_live_order_manager.py` 통과.
  - `python -m unittest tests.test_live_order_manager tests.test_live_order_guard` 통과, 22개.
- 주의:
  - 실제 KIS live adapter 연결 없음.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-13: audit trace 필수 필드 검증

- 목적:
  - 실전 주문 감사 이벤트가 `prediction_id`, `signal_id`, `gate_decision_id` 같은 핵심 trace field 없이 생성되는 위험을 줄였다.
  - 감사 해시 체인 검증 범위는 유지하고, 주문 경로 자동 연결은 아직 추가하지 않았다.
- 변경:
  - `app/services/live_audit.py`의 `build_live_audit_event()`에서 필수 trace field 빈 값을 거부한다.
  - `previous_hash`는 64자리 hex 문자열이어야 한다.
  - `tests/test_live_audit.py`에 `prediction_id` 누락과 invalid `previous_hash` 거부 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 감사 필수 필드 검증을 반영했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-13.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_audit.py tests/test_live_audit.py` 통과.
  - `python -m unittest tests.test_live_audit` 통과, 6개.
- 주의:
  - 모든 주문 decision을 audit chain에 자동 append하는 연결은 아직 후속이다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-12: live position invalid side 기록

- 목적:
  - `live_fills`에 buy/sell로 해석되지 않는 side가 들어왔을 때 포지션 계산에서 조용히 묻히는 위험을 줄였다.
  - 실제 포지션 저장, 브로커 조회, runtime DB 쓰기는 추가하지 않았다.
- 변경:
  - `app/services/live_position_accounting.py`에서 알 수 없는 fill side를 `invalid_side_count`로 기록한다.
  - `LivePositionAccountingResult`와 `LivePosition.detail_json["accounting"]`에 `invalid_side_count`를 남긴다.
  - `tests/test_live_position_accounting.py`에 invalid side가 포지션 수량을 바꾸지 않고 카운트되는 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 invalid fill side 카운트 보강을 반영했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-12.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_position_accounting.py tests/test_live_position_accounting.py` 통과.
  - `python -m unittest tests.test_live_position_accounting` 통과, 5개.
- 주의:
  - invalid side가 있으면 자동으로 live position 저장을 막는 guard는 아직 없다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-11: alert outbox detail redaction

- 목적:
  - 로컬/텔레그램/이메일 outbox JSONL에 계좌, 토큰, app secret 계열 key가 포함될 위험을 낮췄다.
  - 실제 외부 발송기나 네트워크 호출은 추가하지 않았다.
- 변경:
  - `app/services/live_alerting.py`에서 outbox 저장 직전 `detail_json`을 `app/brokers/kis_response_redaction.py` helper로 redaction한다.
  - `tests/test_live_alerting.py`에 outbox 기록의 `account_number`, `app_secret` redaction과 안전 예외 key `pdno` 유지 검증을 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 outbox `detail_json` redaction과 남은 자유 텍스트 redaction 과제를 반영했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-11.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_alerting.py tests/test_live_alerting.py app/brokers/kis_response_redaction.py` 통과.
  - `python -m unittest tests.test_live_alerting tests.test_kis_response_redaction` 통과, 14개.
- 주의:
  - `title`, `message` 같은 자유 텍스트 redaction은 아직 후속 과제다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-10: system_clock readiness dry-run 연결

- 목적:
  - 이미 분리한 `app/services/system_clock.py` 순수 helper를 Phase readiness dry-run의 필수 check 슬롯으로 연결했다.
  - 실제 NTP, KIS API, runtime DB에는 접근하지 않고 fixture가 명시될 때만 통과하는 보수 정책을 유지했다.
- 변경:
  - `app/services/live_phase_readiness.py`의 readiness check key에 `system_clock`을 추가했다.
  - premarket report adapter에서는 `system_clock`을 기본 `not_verified`로 두고, 명시 override나 fault fixture가 없으면 readiness를 차단한다.
  - `tests/test_live_phase_readiness.py`, `tests/test_live_readiness_dry_run_script.py`에 `system_clock` fixture 통과/누락 차단 검증을 추가했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`의 readiness check 수를 10개로 맞췄다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-10.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_phase_readiness.py app/services/system_clock.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py tests/test_system_clock.py` 통과.
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_system_clock` 통과, 20개.
- 주의:
  - `system_clock` check는 아직 실제 기준 시각 원천과 연결하지 않았다.
  - 운영 DB schema apply 없음. 새 check는 기존 `checks_json`에만 저장된다.
  - KIS live/paper API 신규 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-9: system clock skew 순수 helper

- 목적:
  - KIS 주문/취소 timestamp 검증과 운영 정합성에 필요한 시스템 시계 오차 후보를 코드로 검증 가능한 순수 helper로 분리했다.
  - 외부 NTP, KIS API, runtime DB에는 접근하지 않는다.
- 변경:
  - `app/services/system_clock.py`를 추가했다. local timestamp와 reference timestamp 차이가 기본 후보 `±2초` 이내인지 판정한다.
  - `tests/test_system_clock.py`를 추가했다.
  - `README.md`, `docs/Current-Implementation.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-9.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/system_clock.py tests/test_system_clock.py` 통과.
  - `python -m unittest tests.test_system_clock` 통과, 4개.
- 주의:
  - `±2초`는 helper 기본 후보이며, reference timestamp 원천과 runtime 연결은 후속 결정 대상이다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-8: live alert attention grace hook

- 목적:
  - dashboard 외 알림에서 막 생긴 `unknown/stuck` 주문 상태가 짧은 시간 안에 정상화될 경우 false alarm이 되는 것을 줄일 수 있게 grace hook을 추가했다.
  - 기본값은 0분이므로 기존 runtime report/outbox 동작은 바뀌지 않고, payload가 `attention_grace_minutes`를 명시한 경우에만 적용된다.
- 변경:
  - `app/services/live_alerting.py`에서 `live_order_attention` payload의 `max_attention_age_minutes < attention_grace_minutes`이면 attention alert를 만들지 않도록 했다.
  - `tests/test_live_alerting.py`에 grace window 안 억제와 grace 이후 발송 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`를 갱신했다.
- 검증:
  - `python -m py_compile app/services/live_alerting.py tests/test_live_alerting.py` 통과.
  - `python -m unittest tests.test_live_alerting` 통과, 10개.
- 주의:
  - live fill mismatch, kill switch, DB/disk 장애 같은 확정 사고는 grace로 억제하지 않는다.
  - 실제 외부 텔레그램/이메일 발송기는 연결하지 않았다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-7: KIS live order adapter 이중 잠금 골격

- 목적:
  - P0-B live enable guard의 두 번째 방어선인 KIS 어댑터 직전 재검증 골격을 추가했다.
  - raw `KisRestQuoteClient.submit_cash_order`/`cancel_order`를 허용 경계 밖에서 직접 쓰는 회귀를 정적 테스트로 막는다.
- 변경:
  - `app/brokers/kis_live_order.py`를 추가했다. 이미 생성된 KIS client를 감싸고 `submit_cash_order` 위임 직전에 `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=true`, live profile을 다시 확인한다. `cancel_order`는 보호성 cancel-only 정책과 맞추기 위해 `TRADING_MODE=live`와 live profile만 확인한다.
  - `tests/test_kis_live_order_adapter.py`를 추가했다.
  - `tests/test_live_client_isolation.py`에 주문/취소 함수 surface가 `app/brokers/kis_quote_rest.py`, `app/brokers/kis_live_order.py`, `app/services/broker_paper.py`, `app/services/live_order_manager.py` 안에만 남는지 확인하는 정적 테스트를 추가했다.
  - `README.md`, `docs/Current-Implementation.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`를 갱신했다.
- 검증:
  - `python -m py_compile app/brokers/kis_live_order.py tests/test_kis_live_order_adapter.py tests/test_live_client_isolation.py` 통과.
  - `python -m unittest tests.test_kis_live_order_adapter tests.test_live_client_isolation tests.test_live_readonly_guard` 통과, 16개.
- 주의:
  - wrapper import/생성은 KIS 네트워크를 호출하지 않는다.
  - streaming runtime 실제 주문 경로 연결은 하지 않았다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-18] Codex -> work_ver_11-6: KIS fixture redaction audit 보강

- 목적:
  - cowork 전달 전 fixture 후보에 민감 key가 redaction 뒤에도 남아 있는지 기계적으로 확인하는 장치를 추가했다.
  - 장중 수집 보호 모드이므로 KIS API, runtime DB write, dashboard 재생성, 실전 주문 경로는 건드리지 않았다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=pre-open`, `trading_mode=paper`, live runtime 실행 없음.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=pre-open`, `live_runtime_should_run=false`.
- 변경:
  - `app/brokers/kis_response_redaction.py`에 `find_unredacted_sensitive_paths()`를 추가했다. redaction 이후에도 민감 key 값이 `<REDACTED>`가 아니면 JSON path를 반환한다.
  - `scripts/export_kis_paper_fixture_candidates.py`의 각 후보와 summary에 `redaction_ok`, `redaction_findings`, `redaction_findings_count`를 추가했다.
  - `scripts/export_kis_paper_fixture_candidates.py`에 `--fail-on-redaction-findings` 옵션을 추가했다. 정상 redaction이면 기존처럼 성공하고, findings가 생기면 CI/전달 전 확인에서 non-zero exit로 쓸 수 있다.
  - `tests/test_kis_response_redaction.py`, `tests/test_kis_paper_fixture_export_script.py`를 보강했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-work_ver_11-6.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/brokers/kis_response_redaction.py scripts/export_kis_paper_fixture_candidates.py` 통과.
  - `python -m unittest tests.test_kis_response_redaction tests.test_kis_paper_fixture_export_script` 통과, 6개.
  - `python scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings` 통과. 실제 DB 기준 summary `status=ok`, `redaction_ok=true`.
- 주의:
  - 주문번호와 종목코드는 mapper 검증을 위해 보존한다.
  - KIS live/paper API 신규 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-17] Codex -> work_ver_11-5: Phase 2 주문금액 한도와 KIS paper fixture 후보 export

- 목적:
  - 계좌 소유자/실전 운용 승인권자 승인에 따라 Phase 2 부모 주문 금액 한도를 Codex 권장안으로 적용했다.
  - 현재 `runtime-data/dev.db`와 broker paper 기록에 KIS 모의투자 raw 응답이 남아 있는지 read-only로 확인하고, redacted fixture 후보를 생성했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`.
- 변경:
  - `app/services/live_order_manager.py`의 Phase 2 pre-submit 정책에 부모 주문 금액 한도를 추가했다. 기본값은 `min(100,000원, 운용 배정금의 10%)`이고, 운용 배정금이 없으면 100,000원을 쓴다.
  - `order_policy.max_order_notional`, `allocation_amount` 또는 `phase2_allocation_amount`, `max_order_allocation_pct` 또는 `max_order_allocation_ratio`로 한도를 조정할 수 있게 했다.
  - `tests/test_live_order_manager.py`에 기본 한도 초과 차단, 한도 완화, 배정금 비율에 의한 한도 축소 테스트를 추가했다.
  - `app/brokers/kis_response_redaction.py`의 민감 key 후보에 `empno`, `ip_addr`, `tlno`를 추가했고, `tests/test_kis_response_redaction.py`를 보강했다.
  - `scripts/export_kis_paper_fixture_candidates.py`를 추가했다. 이 스크립트는 `runtime-data/dev.db`를 SQLite read-only URI로 열고 broker paper 주문 제출/상태 snapshot의 최신 후보와 가장 풍부한 detail 후보를 redaction 후 JSON으로 저장한다.
  - `tests/test_kis_paper_fixture_export_script.py`를 추가했다.
  - `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json`를 생성했다. 현재 DB 기준 `broker_paper_order_submissions` 530건, `broker_paper_order_status_snapshots` 164,508건이 확인됐다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11-5.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile scripts/export_kis_paper_fixture_candidates.py app/services/live_order_manager.py app/brokers/kis_response_redaction.py` 통과.
  - `python scripts/export_kis_paper_fixture_candidates.py` 통과. KIS live/paper API 신규 호출 없음.
  - `python -m unittest tests.test_kis_paper_fixture_export_script tests.test_kis_response_redaction` 통과, 4개.
  - `python -m unittest tests.test_live_order_manager` 통과, 13개.
  - `python -m unittest tests.test_live_execution_sync tests.test_live_order_manager` 1차 실패 후, 체결 sync 테스트 fixture가 Phase 2 기본 주문금액 한도를 초과하는 문제를 확인했다. 해당 테스트는 이미 제출된 주문 sync 검증 목적이므로 `order_policy.max_order_notional`을 테스트 fixture에 명시해 보정했다.
  - 보정 후 `python -m unittest tests.test_live_execution_sync tests.test_live_order_manager` 통과, 23개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 242개.
  - `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - fixture 후보는 민감 key를 redaction하지만 mapper 검증을 위해 주문번호와 종목코드는 보존한다. cowork 외부 전달 전에는 사람이 한 번 더 확인한다.
  - 실제 KIS live 주문/취소/조회 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-17] Codex -> work_ver_11-4: KIS 실제 응답 fixture redaction helper

- 목적:
  - 다음 1순위인 KIS 실제 주문/체결 응답 fixture 확대를 준비하기 위해, sample 제공 전 민감정보 제거 helper를 추가했다.
  - 실제 KIS 호출 없이 로컬 JSON payload만 대상으로 동작한다.
- 변경:
  - `app/brokers/kis_response_redaction.py`를 추가했다.
  - `redact_kis_payload()`와 `redact_kis_json_text()`는 token, app key/secret, authorization, 계좌번호, 계좌상품코드, 고객 식별값으로 보이는 key를 `<REDACTED>`로 바꾼다.
  - 주문번호, 종목코드, 수량/가격 필드는 mapper 검증에 필요하므로 유지한다.
  - `tests/test_kis_response_redaction.py`를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11-4.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/brokers/kis_response_redaction.py app/services/live_alerting.py app/services/reporting.py app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_kis_response_redaction tests.test_live_alerting tests.test_reporting tests.test_live_order_manager tests.test_dashboard` 통과, 38개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 237개.
  - `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실제 KIS live 조회/주문/취소 호출 없음.
  - 실제 응답 sample 저장 없음.
  - 계좌번호, token, app key/secret 기록 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-17] Codex -> work_ver_11-3: Phase 2 부모 주문 한도 카운터와 pre-submit context

- 목적:
  - cowork `review_ver_10`의 낮은 우선순위 권고였던 Phase 2 부모 주문 카운터와 차단 사유 세부 정보를, KIS 실제 응답 sample 없이 가능한 범위에서 보강했다.
  - Phase 2 canary 이름을 쓰는 경로도 1거래일 1개 부모 주문서 기본 정책 대상이 되도록 맞췄다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`.
- 변경:
  - `app/services/live_order_manager.py`에서 Phase 2 pre-submit 기본 정책 대상에 `phase2_canary`를 추가했다.
  - 차단 사유 문자열은 기존과 호환되게 유지하고, order detail의 `pre_submit_policy_context`에 부모 주문 현재 수/한도, 잔여 수, 같은 종목 pending 수, live fill mismatch 수를 기록한다.
  - `app/services/live_order_monitoring.py`에 Phase 2 부모 주문 한도 read-only summary helper를 추가했다.
  - `app/services/dashboard.py`의 `실 운용계좌` 탭에 `Phase 2 부모 주문 한도`, `Phase 2 부모 주문 상세` 카드를 추가했다.
  - `app/services/reporting.py`의 runtime report JSON/Markdown에도 Phase 2 부모 주문 한도 요약을 추가했다.
  - `app/services/live_alerting.py`에서 live monitoring alert id를 state fingerprint 기반으로 만들고, 같은 날짜 outbox에 동일 alert가 중복 append되지 않게 했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11-3.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_live_order_manager tests.test_dashboard` 통과, 27개.
  - `python -m py_compile app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py app/services/reporting.py` 통과.
  - `python -m unittest tests.test_live_order_manager tests.test_dashboard tests.test_reporting` 통과, 28개.
  - `python -m py_compile app/services/live_alerting.py app/services/reporting.py` 통과.
  - `python -m unittest tests.test_live_alerting tests.test_reporting tests.test_live_order_manager tests.test_dashboard` 통과, 36개.
  - KIS redaction helper 추가 뒤 `python -m unittest tests.test_kis_response_redaction tests.test_live_alerting tests.test_reporting tests.test_live_order_manager tests.test_dashboard` 통과, 38개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 237개.
  - `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실제 KIS live 주문/취소/조회 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-17] Codex -> work_ver_11-2: recovery export self-test와 tar 제외 정책 보강

- 목적:
  - 실전 audit/alert/live-risk 경로가 recovery export에 포함되는지 self-test로 잠갔다.
  - 실제 NAS 접근 없이 임시 저장소를 tar archive로 만들고 포함/제외 경로를 검사했다.
- 발견:
  - 첫 테스트에서 `runtime-data/logs/app/app.log`와 `runtime-data/cache/kis/token.json`이 archive에 포함되는 문제가 드러났다.
  - 원인은 `tar.add(path, arcname=rel)`가 디렉터리를 추가할 때 하위 파일을 재귀적으로 함께 넣어 파일별 제외 정책을 우회할 수 있다는 점이었다.
- 변경:
  - `scripts/wsl_ops.py`의 recovery export에서 `tar.add(..., recursive=False)`를 사용해 디렉터리 재귀 추가를 막았다.
  - `tests/test_wsl_ops.py`에 recovery export self-test를 추가했다.
  - 포함 확인 경로: `runtime-data/reports/alerts/`, `runtime-data/reports/live-risk/`, `runtime-data/reports/live-approvals/`, `runtime-data/ops/`, `runtime-data/ml/registry-backups/`.
  - 제외 확인 경로: root `.env`, `runtime-data/cache/kis`, `runtime-data/logs`, key 파일.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11-2.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m unittest tests.test_wsl_ops` 1차 실패로 기존 제외 정책 우회 문제 확인.
  - 수정 후 `python -m unittest tests.test_wsl_ops` 통과, 11개.
- 주의:
  - 실제 NAS 공유 접근 없음.
  - 실제 backup 실행 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-17] Codex -> work_ver_11-1: live audit hash chain helper와 runtime report integrity

- 목적:
  - cowork 토큰 회복 전까지 외부 sample 없이 진행 가능한 감사 원장 무결성 축을 보강했다.
  - 외부 anchor와 보관 기간은 계좌 소유자/실전 운용 승인권자 결정으로 남기되, 내부 hash chain 생성/검증 helper와 runtime report read-only 요약을 먼저 추가했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`.
- 변경:
  - `app/services/live_audit.py`를 추가했다. `LiveAuditLog.append()`, `compute_live_audit_hash()`, `verify_live_audit_chain()`으로 `ops_live_audit_events` append-only hash chain을 생성/검증한다.
  - `app/storage/sqlite_store.py`에 `fetch_live_audit_events(trading_day=None)`를 추가했다.
  - `app/services/reporting.py`가 runtime report에 `Live Audit Integrity` 절과 JSON payload를 기록하게 했다.
  - `tests/test_live_audit.py`를 추가하고 `tests/test_reporting.py`를 보강했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11-1.md`에 cowork 검토용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_audit.py app/services/reporting.py app/storage/sqlite_store.py` 통과.
  - `python -m unittest tests.test_live_audit tests.test_live_storage tests.test_sqlite_store` 1차 실패 후 fixture를 기존 `LiveAuditEvent` 계약(`reason/source/gate_decision`)에 맞춰 수정.
  - `python -m unittest tests.test_live_audit tests.test_live_storage tests.test_sqlite_store` 통과, 19개.
  - `python -m unittest tests.test_live_audit tests.test_reporting tests.test_live_storage tests.test_sqlite_store` 통과, 20개.
- 주의:
  - 실제 KIS live 주문/취소/조회 호출 없음.
  - 운영 DB schema apply 없음.
  - 외부 anchor 구현 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-17] Codex -> review_ver_10 반영: Phase 2 결정 3건과 alert outbox

- 목적:
  - cowork `review_ver_10`의 후속 권고와 계좌 소유자/실전 운용 승인권자 결정 3건을 반영했다.
  - Phase 2 부분 체결 잔량 자동 취소 금지, `live_positions` 실제 저장 시점 지연, dashboard 외 알림 채널(텔레그램 + 중요 이슈 이메일)을 기준 문서에 반영했다.
  - 실제 외부 발송 없이 로컬/텔레그램/이메일 outbox를 만들 수 있는 alerting 경계를 추가했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
  - `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 주말 대기.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 확인.
- 변경:
  - `app/services/live_alerting.py`를 추가했다. `warning`/`critical`은 텔레그램 outbox 대상, `critical` 또는 중요 event type은 이메일 outbox 대상이다.
  - `app/services/reporting.py`가 live fill mismatch와 `unknown`/`stuck` 미해결 주문을 alert로 변환해 `runtime-data/reports/alerts/{local,telegram,email}/alerts-YYYY-MM-DD.jsonl`에 `delivery_mode=outbox_only` record를 남기도록 했다.
  - `tests/test_live_alerting.py`와 `tests/test_reporting.py`에 alert routing/outbox 검증을 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 Phase 2 부분 체결 잔량 정책, `live_positions` 저장 시점, 텔레그램/이메일 outbox 정책을 반영했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-operator-decision.md`에 운영자 결정 3건을 기록했다.
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11.md`에 cowork 전달용 요약을 남겼다.
- 검증:
  - `python -m py_compile app/services/live_alerting.py app/services/reporting.py` 통과.
  - `python -m unittest tests.test_live_alerting tests.test_reporting` 통과, 7개.
  - `python -m unittest tests.test_live_alerting tests.test_live_order_manager tests.test_live_execution_sync tests.test_live_position_accounting tests.test_dashboard tests.test_reporting` 통과, 46개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 226개.
  - `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실제 텔레그램/이메일 발송 없음. 현재는 outbox 기록만 한다.
  - 실제 KIS live 주문/취소 API 호출 없음.
  - 실제 KIS REST 조회 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.
- cowork 전달:
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_11.md`.

## [2026-05-17] Codex -> review_ver_9 반영: live_fills delta 멱등성과 Phase 2 pre-submit 정책

- 목적:
  - cowork `review_ver_9`의 다음 단계 권장인 Slice 5-3 `live_fills` delta idempotency를 구현했다.
  - 같은 라운드에서 Phase 2의 1거래일 1개 부모 주문서 제한과 같은 종목 pending 차단을 `LiveOrderManager` 내부 pre-submit 정책으로 잠갔다.
  - cowork token 회복 전까지 `unknown`/`stuck` 미해결 실전 주문을 read-only dashboard/runtime report로 노출하는 운영 가시성 보강을 추가했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-16-production-architecture-implementation-blueprint-review_ver_9.md` 확인.
- 변경:
  - `app/services/live_execution_sync.py`에 `LiveFillApplyResult`, `LiveFillConsistency`, `apply_order_snapshot_and_fill_delta()`, `validate_live_order_fill_qty()`를 추가했다.
  - `apply_order_snapshot_and_fill_delta()`는 기존 `live_fills` 합계와 브로커 누적 체결수량을 비교해 미기록 delta만 deterministic `fill_id`로 기록한다. 포지션/포트폴리오/세금 정산은 아직 반영하지 않는다.
  - unmatched broker snapshot은 `unknown`으로만 전이하고 수량/체결 원장에는 반영하지 않도록 보수화했다.
  - `scan_live_order_fill_consistency(trading_day)`와 `build_live_order_fill_consistency_summary(trading_day)`로 거래일 단위 fill/order mismatch를 조회/요약할 수 있게 했다. 아직 gate 차단이나 dashboard에는 연결하지 않았다.
  - `tests/test_kis_http_clients.py`에 KIS 일별 주문/체결 응답의 대체 필드명 fixture를 추가했다.
  - `app/storage/sqlite_store.py`에 `insert_live_fill_if_absent()`, `fetch_live_fill()`, `fetch_live_fill_totals()`, `sum_live_fill_qty()`, `fetch_live_orders_for_trading_day()`를 추가했다.
  - `app/storage/runtime_writer.py`에 `write_live_fill_if_absent()`를 추가했다.
  - `app/services/live_order_manager.py`에 `blocked` terminal 재시도 정책 docstring과 Phase 2 pre-submit 정책을 추가했다. 위반 시 broker 호출 없이 `pre_submit_policy_blocked` 이벤트와 함께 `blocked`로 남긴다.
  - Phase 2 pre-submit 정책에 live fill mismatch 신규 intent 차단을 추가했다. 같은 거래일의 `live_orders.filled_qty`와 `live_fills` 합계가 어긋나면 새 intent는 broker 호출 전 `blocked`가 된다.
  - `tests/test_live_execution_sync.py`, `tests/test_live_order_manager.py`를 보강했다.
  - `app/services/dashboard.py`에 `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)` 정합성 read-only 카드(`실전 fill 정합성`, `실전 fill 불일치 상세`)와 mismatch status alert를 추가했다. 포지션/회계/주문 전송에는 연결하지 않는다.
  - `app/services/live_order_monitoring.py`를 추가해 거래일 단위 `unknown`/`stuck` 미해결 주문 수, 열린 주문 수, 최장 경과 시간을 read-only로 요약한다.
  - `app/services/dashboard.py`에 `실전 미해결 주문`, `실전 미해결 주문 상세` 카드와 `실전 주문 상태 확인 필요` status alert를 추가했다.
  - `tests/test_dashboard.py`에 live fill mismatch가 dashboard payload와 HTML에 표시되는지 검증하는 fixture를 추가했다.
  - `app/services/reporting.py`가 같은 live fill 정합성과 미해결 주문 요약을 `latest-runtime-report.json`과 `latest-runtime-report.md`에 기록하도록 보강했다.
  - `tests/test_reporting.py`에 runtime report가 live fill mismatch와 `unknown` 미해결 주문을 JSON/Markdown에 표시하는지 검증하는 fixture를 추가했다.
  - `tests/test_kis_http_clients.py`에 KIS 일별 주문/체결 조회 연속 조회(`tr_cont=M`) fixture를 추가해 여러 페이지의 주문/체결 응답을 이어 붙이는 동작을 잠갔다.
  - `app/services/live_position_accounting.py`를 추가해 기록된 `live_fills`에서 long-only 평균단가 position을 순수 계산한다. 자동 position 저장, portfolio snapshot, 세금/결제 정산에는 아직 연결하지 않았다.
  - `SQLiteRuntimeStore.fetch_live_fills_for_trading_day()`를 추가해 position 계산 helper가 거래일별 fill을 read-only로 가져올 수 있게 했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_execution_sync` 통과, 9개.
  - `python -m unittest tests.test_live_execution_sync tests.test_kis_http_clients` 통과, 16개.
  - `python -m unittest tests.test_sqlite_store` 통과, 9개.
  - `python -m unittest tests.test_live_order_manager` 통과, 8개.
  - `python -m unittest tests.test_live_execution_sync tests.test_dashboard` 통과, 25개.
  - `python -m unittest tests.test_reporting tests.test_dashboard tests.test_live_execution_sync` 통과, 26개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_execution_sync tests.test_reporting tests.test_dashboard` 통과, 35개.
  - `python -m unittest tests.test_dashboard tests.test_live_order_manager tests.test_reporting` 통과, 25개.
  - `python -m py_compile app/services/live_order_monitoring.py app/services/dashboard.py app/services/reporting.py` 통과.
  - `python -m unittest tests.test_dashboard tests.test_reporting` 통과, 17개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_execution_sync tests.test_kis_http_clients tests.test_dashboard tests.test_reporting` 통과, 42개.
  - `python -m unittest tests.test_kis_http_clients` 통과, 7개.
  - `python -m py_compile app/services/live_position_accounting.py app/storage/sqlite_store.py` 통과.
  - `python -m unittest tests.test_live_position_accounting tests.test_live_storage tests.test_live_execution_sync` 통과, 20개.
  - `python -m unittest tests.test_live_storage tests.test_live_order_guard tests.test_live_phase_readiness` 통과, 21개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 220개.
  - `python -m app --build-runtime-report` 통과. 최신 runtime report 생성: `runtime-data/reports/runtime/latest-runtime-report.md`, `runtime-data/reports/runtime/latest-runtime-report.json` (`live_fill_mismatches=0`).
  - `python -m app --build-dashboard` 통과. 최신 dashboard snapshot 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json` (`generated_at=2026-05-17T01:39:36.806128+09:00`).
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실제 KIS live 주문 API 호출 없음.
  - 실제 KIS REST 조회 호출 없음.
  - 운영 DB schema apply 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.
- cowork 전달:
  - `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-work_ver_10.md`에 `review_ver_9` 반영 요약과 다음 리뷰 질문을 남겼다.

## [2026-05-16] Codex -> Slice 5-2 live execution sync mapper/status apply 구현

- 목적:
  - cowork 회복 전까지 Slice 5에서 독립적으로 진행 가능한 live execution sync의 순수 parser/mapper를 먼저 구현했다.
  - 실제 KIS REST 호출 없이 KIS daily order/fill record를 live 상태와 delta fill로 해석하고, `live_orders` 상태/수량과 event만 반영하는 단위를 테스트로 잠갔다.
- 변경:
  - `app/services/live_execution_sync.py`를 추가했다.
  - `snapshot_from_kis_daily_order_fill(record)`는 `KisDailyOrderFillRecord` 또는 같은 attribute/key를 가진 입력을 `LiveBrokerOrderSnapshot`으로 정규화한다.
  - `derive_live_order_status(snapshot)`는 `accepted`, `open`, `partially_filled`, `filled`, `cancelled`, `cancelled_partial`, `expired`, `rejected`, `unknown`을 계산한다.
  - live unmatched 상태는 paper sync의 `pending_lookup` 대신 fail-closed 성격의 `unknown`으로 둔다.
  - `build_live_order_sync_decision(snapshot, previous_applied_fill_qty)`는 이전 적용 수량 이후의 delta fill만 계산하고 음수 delta는 0으로 고정한다.
  - `LiveExecutionSync.apply_order_snapshot()`은 `live_orders` status/filled/remaining/avg_fill과 `live_order_events`만 반영한다.
  - `SQLiteRuntimeStore.update_live_order_transition()`은 선택적으로 filled/remaining/avg fill을 함께 업데이트할 수 있게 확장했다.
  - `tests/test_live_execution_sync.py`를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_execution_sync` 통과, 4개.
  - `python -m unittest tests.test_live_execution_sync tests.test_broker_paper_sync tests.test_live_order_manager tests.test_live_storage` 통과, 20개.
  - `python -m unittest tests.test_live_execution_sync tests.test_live_order_manager tests.test_live_storage` 통과, 18개.
  - `python -m unittest tests.test_live_execution_sync tests.test_broker_paper_sync tests.test_live_order_manager tests.test_live_storage tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script` 통과, 30개.
  - `bash -n scripts/script_dispatch.sh scripts/set_live_kill_switch.sh scripts/run_codex_ops_job.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 205개.
  - `python -m app --build-dashboard` 통과. 최신 dashboard snapshot 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실제 KIS live 주문 API 호출 없음.
  - 실제 KIS REST 조회 호출 없음.
  - 운영 DB write/apply 없음. DB 반영 검증은 `.tmp-tests/` 아래 SQLite에서만 수행.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.
- cowork 전달:
  - `docs/cowork-reports/2026-05-16-production-architecture-implementation-blueprint-work_ver_9-2.md`에 `work_ver_9`와 `work_ver_9-1`을 합친 토큰 절약용 통합본을 남겼다.

## [2026-05-16] Codex -> review_ver_8 반영: Slice 5 live order manager 1차 구현

- 목적:
  - cowork `review_ver_8`의 결론인 Slice 5 live order manager 진입 권고를 반영했다.
  - live 주문 intent, idempotency, 상태 전이, guard 호출, broker 주입형 제출/취소, 재시작 복구의 1차 골격을 만들었다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-16-production-architecture-implementation-blueprint-review_ver_8.md` 확인.
- 변경:
  - `scripts/run_codex_ops_job.sh --job-type premarket-readiness`에 `--database-timeout-seconds` 옵션을 추가했다. 기본값은 2초다.
  - SQLite read-only smoke에서 `locked`/`busy`는 실제 손상과 구분해 `unknown`으로 분류한다.
  - `app/services/live_phase_readiness.py` docstring에 새 3개 readiness check는 `checks_json`에 보관하고 SQL column 승격은 별도 schema migration으로 남긴다는 결정을 명시했다.
  - `scripts/set_live_kill_switch.sh`를 추가했다. 기본은 status/dry-run이고 실제 ON/OFF 파일 기록은 `--apply`가 있을 때만 한다. OFF 해제는 `--confirm-disable`이 필요하다.
  - `app/services/live_order_manager.py`를 추가했다. 실제 KIS client를 생성하지 않고 broker protocol을 외부에서 주입받는다.
  - `LiveOrderManager.create_intent()`는 deterministic idempotency key를 생성하고 중복 intent를 재사용한다.
  - `LiveOrderManager.submit_intent()`는 `LiveOrderGuard`를 통과한 뒤 broker를 호출한다. guard 차단 시 broker 호출 없이 `blocked`, broker 예외 또는 불명확 응답은 `unknown`으로 기록한다.
  - `LiveOrderManager.request_cancel()`은 cancel-only guard를 통과한 뒤 `cancel_requested`로 전이한다.
  - `LiveOrderManager.recover_open_orders()`는 재시작 시 open 계열 주문을 `unknown`으로 잠그고 broker reconcile을 요구한다.
  - `SQLiteRuntimeStore`에 `fetch_live_order`, `fetch_live_order_by_idempotency_key`, `update_live_order_transition`을 추가하고 `cancel_requested`를 open 계열 상태에 포함했다.
  - `tests/test_live_order_manager.py`, `tests/test_live_kill_switch_cli_script.py`를 추가하고 관련 테스트를 보강했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 갱신했다.
- 실행 산출물:
  - `./scripts/set_live_kill_switch.sh --enable --reason dry_run_validation --actor test` 실행: `status=dry_run`, `applied=false`, 실제 kill switch 파일 기록 없음.
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness --database-timeout-seconds 2.0` 실행: `status=ok`, `database=status ok`, `timeout_seconds=2.0`.
  - `./scripts/run_live_readiness_dry_run.sh` 실행: fixture가 없으므로 `status=blocked`, 9개 check 모두 `not_verified`.
- 검증:
  - `bash -n scripts/script_dispatch.sh scripts/set_live_kill_switch.sh scripts/run_codex_ops_job.sh` 통과.
  - `python -m unittest tests.test_codex_ops_job_script tests.test_live_kill_switch_cli_script tests.test_live_kill_switch` 통과, 13개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_storage tests.test_live_order_guard tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script` 통과, 27개.
  - `python -m unittest tests.test_live_order_manager tests.test_live_storage tests.test_live_order_guard tests.test_live_kill_switch tests.test_live_kill_switch_cli_script tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 48개.
  - `bash -n scripts/script_dispatch.sh scripts/set_live_kill_switch.sh scripts/run_codex_ops_job.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 199개.
  - `python -m app --build-dashboard` 통과. 최신 dashboard snapshot 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실제 KIS live 주문 API 호출 없음.
  - 실제 KIS live client 생성 없음.
  - kill switch CLI 검증은 dry-run으로만 실행.
  - 운영 DB schema apply 없음.
  - readiness DB `--record` 실행 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-16] Codex -> review_ver_7 반영: database read-only smoke 분리

- 목적:
  - cowork `review_ver_7`의 최우선 권고인 `database` check와 `storage_migration_state` 의미 분리를 반영했다.
  - 운영 DB에 write 없이 SQLite 연결성만 확인하는 read-only smoke를 premarket-readiness report에 추가했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-16-production-architecture-implementation-blueprint-review_ver_7.md` 확인.
- 변경:
  - `app/services/codex_ops.py`의 `PREMARKET_READINESS_CHECK_KEYS`에 `database`를 추가하고, `build_premarket_readiness_report()`가 `database_smoke`를 별도 check로 받게 했다.
  - `scripts/run_codex_ops_job.sh --job-type premarket-readiness` 경로에서 SQLite를 `mode=ro` URI로 열어 `SELECT 1`, `sqlite_master`, `PRAGMA schema_version`, `PRAGMA journal_mode`만 확인한다.
  - 처음에는 `PRAGMA quick_check`를 넣었으나 실제 `runtime-data/dev.db`에서 60초 timeout 위험이 확인되어 제거했다. 장중 안전 기준에 맞춰 가벼운 read-only smoke만 남겼다.
  - `app/services/live_phase_readiness.py`의 premarket adapter는 이제 `database`를 `storage_migration_state`가 아니라 premarket report의 `database` check에서 가져온다.
  - `LiveReadinessRun`의 전용 SQL column은 기존 6개만 유지하고, `disk_space`, `dashboard`, `storage_migration_state`는 `checks_json`에 보관한다는 주석을 추가했다. SQL column 승격은 별도 schema migration 결정으로 남긴다.
  - `tests/test_codex_ops.py`, `tests/test_codex_ops_job_script.py`, `tests/test_live_phase_readiness.py`, `tests/test_live_readiness_dry_run_script.py`를 보강했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 database/storage 분리 기준을 반영했다.
- 실행 산출물:
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness` 실행: `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json` 재생성, `database=status ok`, blockers/warnings 없음.
  - `./scripts/run_live_readiness_dry_run.sh` 실행: fixture가 없으므로 `status=blocked`, 9개 check 모두 `not_verified`.
- 검증:
  - `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 33개.
  - `bash -n scripts/script_dispatch.sh scripts/run_codex_ops_job.sh` 통과.
  - `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_dashboard` 통과, 47개.
  - `python -m app --build-dashboard` 통과. 최신 dashboard snapshot 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 188개.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - SQLite smoke는 read-only 연결만 수행한다.
  - 운영 DB insert/apply 없음.
  - 실제 장애 주입 없음.
  - Codex CLI 실제 호출 없음.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-16] Codex -> live readiness 명시 DB 기록 옵션 추가

- 목적:
  - readiness dry-run의 기본 동작은 JSON only로 유지하면서, 필요할 때만 `live_readiness_runs` 테이블에 명시 기록할 수 있는 좁은 연결부를 추가했다.
- 변경:
  - `scripts/run_live_readiness_dry_run.sh`에 `--record`와 `--database-path` 옵션을 추가했다.
  - `--record`는 `--database-path`가 없으면 실패한다.
  - `database_path`는 저장소 내부 경로만 허용한다.
  - `--record` 대상 DB 파일은 이미 존재해야 하며, wrapper가 새 SQLite 파일을 조용히 만들지 않는다.
  - DB 기록은 이미 schema가 준비된 SQLite DB에만 insert를 시도하며, script 기본 실행은 계속 `runtime-data/reports/live-readiness/latest-readiness.json` 생성만 수행한다.
  - dashboard `실전 전환 readiness dry-run` 카드에 DB 기록 여부와 DB 경로 표시를 추가했다.
  - `tests/test_live_readiness_dry_run_script.py`에 명시 DB 기록, DB 경로 제한, `--record` 단독 실행 차단 검증을 추가했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 기본 JSON only / 명시 DB 기록 분리 기준을 반영했다.
- 검증:
  - `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh` 통과.
  - `python -m unittest tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness` 통과, 16개.
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_dashboard tests.test_codex_ops tests.test_codex_ops_job_script` 통과, 46개.
  - `python -m app --build-dashboard` 통과. 최신 dashboard snapshot 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 187개.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 이번 검증은 `.tmp-tests/` 아래 임시 DB만 사용했다.
  - 운영 DB insert/apply 실행 없음.
  - 실제 장애 주입 없음.
  - Codex CLI 실제 호출 없음.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-16] Codex -> live readiness dry-run 점검 키 확장

- 목적:
  - cowork `review_ver_6`의 추가 후보였던 disk space, dashboard, storage migration state를 Phase readiness dry-run의 명시 check로 승격했다.
  - fixture가 없는 항목을 통과로 보지 않는 보수 정책을 9개 check 전체로 확장했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰는 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`이고, 이후 새 review는 없었다.
- 변경:
  - `app/services/live_phase_readiness.py`의 readiness check key를 `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `kill_switch`, `database`, `disk_space`, `dashboard`, `storage_migration_state` 9개로 확장했다.
  - `create_readiness_run_from_premarket_report()`는 premarket report에서 확인 가능한 dashboard/disk/storage 상태를 check에 반영하되, WebSocket 복구/계좌 snapshot/market status/kill switch는 계속 별도 fixture 또는 override가 있어야 통과시킨다.
  - `build_fault_injection_dry_run_report()`와 `scripts/run_live_readiness_dry_run.sh`는 9개 check 모두 fixture가 명시되지 않으면 `not_verified`로 차단한다.
  - dashboard의 `실전 전환 readiness dry-run` 카드에 disk space, dashboard, storage migration 표시를 추가했다.
  - `tests/test_live_phase_readiness.py`, `tests/test_live_readiness_dry_run_script.py`, `tests/test_dashboard.py`를 보강했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 9개 check 기준을 반영했다.
- 실행 산출물:
  - `./scripts/run_live_readiness_dry_run.sh` 실행: `runtime-data/reports/live-readiness/latest-readiness.json` 재생성.
  - fixture를 주지 않았으므로 결과는 의도대로 `status=blocked`, 9개 check 모두 `not_verified`.
- 검증:
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_dashboard` 통과, 26개.
- 주의:
  - 실제 장애 주입 없음.
  - Codex CLI 실제 호출 없음.
  - 운영 DB insert/apply 없음.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-16] Codex -> dashboard readiness dry-run 카드 추가

- 목적:
  - `premarket-readiness`와 `live-readiness` dry-run 산출물을 운영자가 dashboard에서 바로 볼 수 있게 했다.
- 변경:
  - `app/services/dashboard.py`가 `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`과 `runtime-data/reports/live-readiness/latest-readiness.json`을 읽도록 추가했다.
  - `상태 및 설정 > 현재 프로그램 상태` 하위에 `실전 전환 readiness dry-run` 카드를 추가했다.
  - 이 카드는 JSON read-only이며 운영 DB insert, schema apply, 실전 주문, Codex CLI 호출을 하지 않는다.
  - `tests/test_dashboard.py` fixture와 assertion을 보강했다.
- 검증:
  - `python -m unittest tests.test_dashboard tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 26개.
  - `python -m unittest tests.test_dashboard tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_codex_ops tests.test_codex_ops_job_script` 통과, 42개.
  - `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh scripts/run_codex_ops_job.sh` 통과.
  - `python -m app --build-dashboard` 통과. 최신 dashboard snapshot 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`.
- 주의:
  - 실제 장애 주입 없음.
  - Codex CLI 실제 호출 없음.
  - 운영 DB insert/apply 없음.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-16] Codex -> fixture 기반 live readiness dry-run 구현

- 목적:
  - cowork 토큰 대기 중 추가로 진행 가능한 안전 slice를 구현했다.
  - 실제 장애를 만들지 않고 fixture 결과만으로 Phase readiness record를 생성하는 dry-run runner를 추가했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰는 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`이고, 이후 새 review는 없었다.
- 변경:
  - `app/services/live_phase_readiness.py`에 `build_fault_injection_dry_run_report()`를 추가했다.
  - `scripts/run_live_readiness_dry_run.sh`를 추가하고 `scripts/script_dispatch.sh`에 dry-run 전용 runner를 연결했다.
  - fixture가 `ok/passed/healthy/ready`를 명시한 항목만 readiness check 통과로 본다.
  - fixture가 없는 항목은 `not_verified`로 남기며 Phase readiness를 통과시키지 않는다.
  - `tests/test_live_readiness_dry_run_script.py`를 추가하고 `tests/test_live_phase_readiness.py`를 보강했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 현재 구현 상태를 반영했다.
- 실행 산출물:
  - `./scripts/run_live_readiness_dry_run.sh` 실행: `runtime-data/reports/live-readiness/latest-readiness.json` 생성.
  - 실제 fixture를 주지 않았으므로 결과는 의도대로 `status=blocked`, 모든 readiness check는 `not_verified`.
- 검증:
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script` 통과, 12개.
  - `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh scripts/run_codex_ops_job.sh` 통과.
- 주의:
  - 실제 장애 주입 없음.
  - Codex CLI 실제 호출 없음.
  - 운영 DB insert/apply 없음.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-16] Codex -> premarket-readiness dry-run wrapper 구현

- 목적:
  - cowork 토큰 여유가 부족한 상태에서 `review_ver_6` 이후 다음 안전 슬라이스를 자율 진행했다.
  - Codex CLI를 실제 호출하기 전에 `premarket-readiness` job의 JSON report schema와 dry-run wrapper를 코드와 테스트로 먼저 잠갔다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰는 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`이고, 이후 새 review는 없었다.
- 변경:
  - `app/services/codex_ops.py`에 `PREMARKET_READINESS_CHECK_KEYS`와 `build_premarket_readiness_report()`를 추가했다.
  - readiness check는 live runtime, runtime watchdog, dashboard, KIS quote credential, storage migration state, disk space, manifest policy를 본다.
  - `scripts/run_codex_ops_job.sh`를 추가하고 `scripts/script_dispatch.sh`에 dry-run 전용 `premarket-readiness` job을 연결했다.
  - wrapper는 Codex CLI를 호출하지 않고 상태 파일과 status script 결과를 읽어 `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`만 생성한다.
  - `scripts/run_storage_migration_dry_run.sh`의 필수 table/index 점검을 Slice 2b 전체 live 원장 기준으로 맞췄다.
  - `app/services/live_phase_readiness.py`에 `create_readiness_run_from_premarket_report()` adapter를 추가했다. 이 adapter는 premarket report만으로 readiness를 통과시키지 않고, WebSocket 복구/계좌 snapshot/market status/kill switch는 별도 override가 있어야 통과시킨다.
  - `tests/test_codex_ops.py`, `tests/test_codex_ops_job_script.py`, `tests/test_storage_migration_dry_run_script.py`를 보강했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 wrapper 구현 상태를 반영했다.
- 실행 산출물:
  - `./scripts/apply_storage_migration.sh` plan 모드 실행: `status=planned`, `apply=false`, 운영 DB 변경 없음.
  - `./scripts/run_storage_migration_dry_run.sh` 실행: 임시 DB 대상 `status=ok`.
  - `./scripts/run_codex_ops_job.sh --job-type premarket-readiness` 실행: `status=ok`, blockers/warnings 없음.
- 검증:
  - `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script` 통과, 16개.
  - `python -m unittest tests.test_codex_ops tests.test_codex_ops_job_script tests.test_storage_migration_dry_run_script tests.test_storage_migration_apply_script` 통과, 22개.
  - `python -m unittest tests.test_live_phase_readiness tests.test_codex_ops tests.test_codex_ops_job_script` 통과, 22개.
  - `python -m unittest tests.test_live_phase_readiness tests.test_codex_ops tests.test_codex_ops_job_script tests.test_storage_migration_dry_run_script tests.test_storage_migration_apply_script` 통과, 28개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 177개.
  - `bash -n scripts/script_dispatch.sh scripts/run_codex_ops_job.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh` 통과.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 최종 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
- 주의:
  - Codex CLI 실제 호출 없음.
  - 운영 DB schema apply 없음. `apply_storage_migration.sh`는 plan 모드만 실행했다.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> review_ver_6 반영과 codex_ops manifest 구현

- 목적:
  - cowork `review_ver_6` 권고에 따라 Codex CLI 운영 자동화 실행 wrapper 전에 job manifest와 장 상태별 권한 모델을 순수 함수로 먼저 잠갔다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=post-close`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md` 확인.
- 변경:
  - `app/services/codex_ops.py`를 추가해 premarket-readiness, postclose-research, intraday-incident-triage, postclose-maintenance-review, cowork-handoff job manifest를 정의했다.
  - 장중 보호 상태에서는 heavy action, root patch 적용, runtime restart, 운영 DB schema apply, 실전 주문 관련 flag 변경, gate 기준값 변경, 실전 주문 전송을 자동 차단한다.
  - `runtime-data/reports/codex/ops/` report root, `.tmp-tests/codex-ops/` patch draft root, patch draft cleanup 보호, backup include/exclude 정책을 코드로 판정하게 했다.
  - `tests/test_codex_ops.py`를 추가해 protected session 판정, job별 허용/차단 action, path 제한, backup/cleanup 정책, unknown action 차단을 검증했다.
  - `AGENTS.md`, `README.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`에 Codex ops 산출물과 manifest 구현 상태를 반영했다.
- 검증:
  - `python -m unittest tests.test_codex_ops` 통과, 10개.
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_order_guard` 통과, 10개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 168개.
  - `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh` 통과.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
- 최종 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=weekend`, `live_runtime_should_run=false`, watchdog 실행 중.
- 주의:
  - `scripts/run_codex_ops_job.sh` wrapper는 아직 구현하지 않았다.
  - Codex CLI 실제 호출 없음.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> Codex CLI 운영 자동화 통합 리포트 작성

- 목적:
  - 장전 준비, 장후 학습, 장중 incident triage에서 Codex CLI를 운영 보조로 호출할 수 있는 구조를 기존 실전 전환 리포트와 통합했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=post-close`, `live_runtime_should_run=false`, watchdog 실행 중.
- 변경:
  - cowork 전달용 통합 리포트 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-work_ver_6-3.md`를 추가했다.
  - 리포트에는 `work_ver_6`, `work_ver_6-1`, `work_ver_6-2` 구현 요약과 Codex CLI 운영 자동화 설계를 함께 정리했다.
  - `docs/cowork-reports/README.md`에 `work_ver_6-3` 참조를 추가했다.
- 설계 요약:
  - Codex CLI는 자동매매 판단자나 주문 실행자가 아니라 운영 보조 에이전트로 격리한다.
  - 장전 `premarket-readiness`, 장후 `postclose-research`, 장중 `intraday-incident-triage` job을 제안한다.
  - 장중에는 읽기 전용 분석과 격리 patch 초안만 허용하고, root 코드 수정/DB migration/runtime restart/실전 주문 관련 flag 변경은 금지한다.
- 검증:
  - 문서/리포트만 추가했으며 최종 `git diff --check` 대상이다.
- 주의:
  - Codex CLI wrapper 구현은 아직 하지 않았다.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> phase approval/readiness record service 구현

- 목적:
  - Phase 1/2 승인과 readiness 결과를 수동 메모가 아니라 해시가 있는 record로 남길 수 있게 했다.
- 변경:
  - `app/services/live_phase_readiness.py`를 추가해 `LivePhaseApproval`과 `LiveReadinessRun` 생성 helper를 구현했다.
  - approval hash와 readiness hash는 정렬된 JSON payload의 SHA-256으로 계산한다.
  - `app/storage/sqlite_store.py`에 active live phase approval 조회 메서드를 추가했다.
  - `tests/test_live_phase_readiness.py`를 추가해 approval hash 안정성, active/expired approval 조회, readiness blocked 상태, 필수 check key 검증을 잠갔다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`를 phase approval/readiness record 구현 상태로 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_phase_readiness tests.test_live_storage tests.test_storage_migration_apply_script` 통과, 13개.
  - `python -m unittest tests.test_live_order_guard tests.test_live_kill_switch tests.test_market_status` 통과, 20개.
  - `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 158개.
- 주의:
  - fault injection 실행기, dashboard 연결, 운영 승인 CLI/UI는 아직 구현하지 않았다.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> Slice 2b live 체결/포지션/감사 원장 구현

- 목적:
  - 실전 주문 전송 없이, 향후 live execution sync와 order manager가 사용할 체결/포지션/감사/승인/readiness 저장 원장을 먼저 추가했다.
- 시작 전 상태:
  - review_ver_5 반영 보강 직후 이어서 진행했다.
  - 운영 DB `runtime-data/dev.db`에는 migration apply를 실행하지 않았다.
- 변경:
  - `app/storage/contracts.py`에 `LiveFill`, `LivePosition`, `LivePortfolioSnapshot`, `LiveAuditEvent`, `LivePhaseApproval`, `LiveReadinessRun` dataclass를 추가했다.
  - `app/storage/sqlite_store.py`에 `live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs` 테이블과 index를 추가했다.
  - `app/storage/runtime_writer.py`에 live fill/position/portfolio/audit/approval/readiness write 메서드를 추가했다.
  - `scripts/script_dispatch.sh`의 storage migration apply 필수 table/index와 sample insert/read/delete smoke check를 Slice 2b 테이블까지 확장했다.
  - `tests/test_live_storage.py`, `tests/test_storage_migration_apply_script.py`를 Slice 2b schema/writer/smoke 기준으로 보강했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`를 Slice 2b 구현 상태로 갱신했다.
- 검증:
  - `python -m unittest tests.test_live_storage tests.test_storage_migration_apply_script tests.test_storage_migration_dry_run_script tests.test_sqlite_store` 통과, 21개.
  - `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 155개.
- 주의:
  - 아직 live execution sync, order manager, dashboard에는 연결하지 않았다.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> review_ver_5 반영과 마이그레이션 안전 보강

- 목적:
  - cowork `review_ver_5`의 즉시 보강 권고를 반영해 운영 DB schema 적용과 live order guard의 silent bypass 위험을 줄였다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=post-close`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_5.md` 확인.
- 변경:
  - `app/storage/sqlite_store.py`의 `backup_database()`를 `shutil.copy2` 기반 파일 복사에서 SQLite native backup API로 바꿔 committed WAL page까지 일관된 snapshot으로 백업하게 했다.
  - `scripts/script_dispatch.sh`의 `storage_migration_apply()` 서비스 정지 확인에 runtime watchdog을 추가했다.
  - `storage_migration_apply()` smoke check를 table/index 존재 확인에서 sample insert/read/delete까지 확장하고, 실패 시 복구도 SQLite native restore로 맞췄다.
  - `app/services/live_order_guard.py`에 phase 정규화와 known phase 검증을 추가해 오타나 미등록 phase를 `phase_unknown`으로 차단했다.
  - `app/services/live_kill_switch.py`에 `stale_after` 미지정 시 24시간 기본값이라는 docstring을 추가했다.
  - `tests/test_sqlite_store.py`, `tests/test_storage_migration_apply_script.py`, `tests/test_live_order_guard.py`에 회귀 테스트를 추가했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`를 현재 구현 상태와 `ALLOW_LIVE_ORDERS=false` cancel-only 권장 의미에 맞게 갱신했다.
- 검증:
  - `python -m unittest tests.test_sqlite_store tests.test_storage_migration_apply_script tests.test_live_order_guard tests.test_live_kill_switch` 통과, 25개.
  - `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 154개.
- 주의:
  - 운영 DB `runtime-data/dev.db`에 apply는 실행하지 않았다.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> storage migration apply wrapper 보강

- 목적:
  - cowork `review_ver_4` 이후 추가 리뷰 왕복 없이, Slice 2b 진입 전 운영 DB 적용 안전 절차를 스크립트와 테스트로 먼저 잠갔다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=post-close`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 새 `review_ver_5`는 없어서 이번 전달 리포트는 `work_ver_5-1`로 작성한다.
- 변경:
  - `scripts/apply_storage_migration.sh`를 추가했다.
  - `scripts/script_dispatch.sh`에 `storage_migration_apply()`를 추가했다.
  - wrapper는 기본 plan 모드에서는 DB를 바꾸지 않고, `--apply`가 있을 때만 schema 적용을 수행한다.
  - 기본 `runtime-data/dev.db`에는 `--skip-service-check`를 허용하지 않는다.
  - 실제 apply 경로는 live runtime/dashboard 상태 확인, backup 생성, schema 초기화, 필수 live table/index smoke query, 실패 시 backup restore 절차를 포함한다.
  - `tests/test_storage_migration_apply_script.py`를 추가해 plan mode 비변경, 임시 DB apply/backup/smoke, 저장소 밖 DB 경로 거부, runtime DB service check skip 거부를 검증했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 현재 구현 상태와 다음 권장 순서에 맞게 갱신했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-work_ver_5-1.md`를 추가했다.
- 검증:
  - `python -m unittest tests.test_storage_migration_apply_script tests.test_storage_migration_dry_run_script` 통과, 6개.
  - `bash -n scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh scripts/script_dispatch.sh` 통과.
  - `python -m unittest tests.test_storage_migration_apply_script tests.test_storage_migration_dry_run_script tests.test_live_kill_switch tests.test_live_order_guard` 통과, 17개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 152개.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 운영 DB `runtime-data/dev.db`에 apply는 실행하지 않았다.
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> review_ver_4 반영과 Slice 4 live order guard 구현

- 목적:
  - 장 종료 후 live runtime이 멈춘 상태에서 cowork `review_ver_4`의 운영 안전 권고를 반영하고, 실전 주문 호출 직전 이중 안전장치의 순수 로직을 구현했다.
- 시작 전 상태:
  - `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`.
  - `./scripts/get_runtime_watchdog_status.sh`: `market_session_status=post-close`, `live_runtime_should_run=false`, watchdog 실행 중.
  - 최신 cowork 리뷰 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-review_ver_4.md` 확인.
- 변경:
  - `app/storage/contracts.py`에서 `LiveOrderEvent.actor` 후보의 `codex`를 제거하고 `test`를 추가했다.
  - `LiveOrder.__post_init__`에서 `order_id`, `trading_day`, `phase`, `symbol`, `side`, `order_type`, `status`, prediction/signal/target/gate/market/model/rule id 같은 필수 문자열의 빈 값을 거부하도록 보강했다.
  - `tests/test_live_storage.py`에 `codex` actor 거부, `test` actor 허용, 필수 문자열 빈 값 거부 테스트를 추가했다.
  - `app/services/live_kill_switch.py`를 추가해 `runtime-data/reports/live-risk/kill-switch.json` 후보 파일을 fail-closed로 읽고 atomic write로 저장하게 했다.
  - `app/services/live_order_guard.py`를 추가해 read-only, submit, cancel-only guard를 분리했다. submit은 live mode, `ALLOW_LIVE_ORDERS=true`, live profile, phase approval, 지정가 주문, kill switch off, market status allowed를 모두 요구한다.
  - `tests/test_live_kill_switch.py`, `tests/test_live_order_guard.py`를 추가했다.
  - `app/services/market_status.py`의 boolean flag 판정을 `True`뿐 아니라 `1`, `true`, `yes`, `on` 문자열도 처리하도록 보강했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 Slice 4 구현 상태로 갱신했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-work_ver_5.md`를 추가했다.
- 검증:
  - `python -m unittest tests.test_live_kill_switch tests.test_live_order_guard tests.test_live_storage tests.test_market_status` 통과, 24개.
  - `python -m unittest tests.test_live_kill_switch tests.test_live_order_guard tests.test_live_storage tests.test_market_status tests.test_storage_migration_dry_run_script` 통과, 26개.
  - `bash -n scripts/run_storage_migration_dry_run.sh scripts/script_dispatch.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 146개.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
  - `git diff -- app/risk VERSION config` 출력 없음.
- 주의:
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - `live_order_guard`는 아직 브로커 주문 경로에 연결하지 않은 순수 가드다.
  - 자동 commit/push 없음.

## [2026-05-15] Codex -> review_ver_3 반영과 Slice 3 market status 구현

- 목적:
  - cowork `review_ver_3`에서 권장한 Slice 1/2a 보강을 반영하고, Phase 1/2 실전 전환 전 필요한 market status 순수 판정 로직과 storage migration dry-run wrapper를 구현했다.
- 변경:
  - `app/brokers/kis_readonly.py`의 `_client`가 private delegate이며 주문 메서드 우회 용도가 아니라는 설명을 보강했다.
  - `tests/test_live_readonly_guard.py`에 `describe()` signature/delegate 검증과 `get_kis_live_readonly_client()` call-time network side effect 0건 검증을 추가했다.
  - `app/storage/contracts.py`에서 live storage JSON sub-field type, 빈 `idempotency_key`, `LiveOrderEvent.actor` 의미를 더 엄격하게 검증했다.
  - `tests/test_live_storage.py`에 잘못된 JSON 타입과 빈 idempotency key 회귀 테스트를 추가했다.
  - `app/services/market_status.py`와 `tests/test_market_status.py`를 추가해 stale snapshot, 장 구간, 거래정지/관리/투자유의, 가격제한, VI, 단일가, 기업행위 차단 사유를 외부 API 없이 판정하게 했다.
  - `scripts/run_storage_migration_dry_run.sh`와 `tests/test_storage_migration_dry_run_script.py`를 추가해 운영 DB 사본 또는 빈 임시 DB에서 live table/index 초기화 여부를 확인할 수 있게 했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/README.md`를 현재 구현 상태와 다음 권장 순서에 맞게 갱신했다.
  - cowork 전달용 `docs/cowork-reports/2026-05-15-production-architecture-implementation-blueprint-work_ver_4.md`를 추가했다.
  - `AGENTS.md`에 작업 시작 전 장 진행 상태와 최신 cowork review 확인, 장중 수집 보호 모드, 사용자 존댓말 기본 응답 규칙을 추가했다.
- 검증:
  - `python -m unittest tests.test_storage_migration_dry_run_script` 통과, 2개.
  - `python -m unittest tests.test_market_status tests.test_live_storage tests.test_live_readonly_guard tests.test_storage_migration_dry_run_script` 통과, 21개.
  - `bash -n scripts/run_storage_migration_dry_run.sh scripts/script_dispatch.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 134개.
  - `git diff --check` 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됐다.
- 주의:
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-14] Codex -> Slice 2a live storage 원장 구현

- 목적:
  - 실전 주문을 전송하지 않고도 Phase 2 준비에 필요한 market status, live order, live order event 초기 원장을 SQLite/JSONL에 기록할 수 있게 했다.
- 변경:
  - `app/storage/contracts.py`에 `MarketStatusSnapshot`, `LiveOrder`, `LiveOrderEvent` dataclass를 추가했다.
  - `MarketStatusSnapshot.status_json`, `LiveOrder.detail_json`, `LiveOrderEvent.detail_json`의 최소 JSON key를 생성 시점에 검증한다.
  - `LiveOrderEvent.actor`는 `system`, `account_owner`, `recovery`, `kill_switch`, `codex` 후보만 허용한다.
  - `app/storage/sqlite_store.py`에 `market_status_snapshots`, `live_orders`, `live_order_events` 테이블과 관련 index를 추가했다.
  - `live_orders.idempotency_key`는 `UNIQUE`로 두고, duplicate insert가 실패하도록 `INSERT`를 사용한다.
  - `fetch_open_live_orders()`를 추가해 open 계열 상태 조회를 준비했다.
  - `app/storage/runtime_writer.py`에 `write_market_status_snapshot`, `write_live_order`, `write_live_order_event`를 추가했다.
  - `tests/test_live_storage.py`를 추가해 dataclass 직렬화, JSON 최소 key, actor 표준값, schema/index, dataclass-schema 정합성, idempotency unique, open order 조회, JSONL/SQLite fan-out을 검증했다.
  - `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, cowork 히스토리 파일을 Slice 2a 구현 상태로 갱신했다.
  - cowork 히스토리 파일 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-work_ver_3-2.md`를 추가했다.
- 검증:
  - `python -m unittest tests.test_live_storage` 통과, 5개.
  - `python -m unittest tests.test_live_storage tests.test_sqlite_store tests.test_broker_paper_sync tests.test_paper_reconciliation` 통과, 21개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 124개.
- 주의:
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
  - live 체결/포지션/감사 원장은 Slice 2b로 남겼다.
  - 자동 commit/push 없음.

## [2026-05-14] Codex -> Slice 1 live read-only client 구현

- 목적:
  - Phase 1 실전 계좌 read-only 연결 전제인 구조적 주문 차단을 첫 코드 slice로 구현했다.
- 변경:
  - `app/brokers/kis_readonly.py`를 추가해 `KisRestQuoteClient`를 composition으로 감싸는 `KisReadOnlyClient`를 만들었다.
  - read-only wrapper는 `get_current_price`, `get_orderbook`, `get_intraday_minute_chart`, `get_account_balance`, `get_daily_order_fills`만 노출하고 `submit_cash_order`, `cancel_order`는 노출하지 않는다.
  - `get_kis_live_readonly_client(settings, mode="live")` factory는 `live` 모드만 허용하고 `paper` 등 다른 모드는 `ValueError`로 거부한다.
  - `tests/test_live_readonly_guard.py`를 추가해 주문 메서드 미노출, 조회 메서드 signature 동등성, delegate 호출, live-only factory, import-time network side effect 없음을 검증했다.
  - `tests/test_live_client_isolation.py`를 추가해 기존 `KisRestQuoteClient(` 직접 생성 경로 allowlist와 paper mirroring의 paper profile 사용을 잠갔다.
  - `docs/Production-Implementation-Blueprint.md`와 계좌 소유자/실전 운용 승인권자 결정 기록에 Slice 1 구현 결과를 반영했다.
  - `docs/Production-Architecture.md` 상단에 `운영자` 의미를 계좌 소유자 또는 실전 운용 승인권자로 고정하고, Phase 2 손실/슬리피지/VI/주문타입 결정과 Slice 1 구현 상태를 반영했다.
  - cowork 히스토리 파일 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-work_ver_3-1.md`를 추가했다.
- 검증:
  - `python -m unittest tests.test_live_readonly_guard tests.test_live_client_isolation tests.test_kis_http_clients tests.test_settings` 통과, 19개.
  - `python -m unittest discover -s tests -p "test_*.py"` 통과, 119개.
- 주의:
  - 실전 주문 API 호출 없음.
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-14] Codex -> 실전 전환 구현 청사진 구체화

- 목적:
  - claude cowork 토큰 제약으로 추가 왕복이 어려운 상태에서, 2026-05-14 08:00 KST 전까지 코드 작업이 가능한 수준으로 실전 전환 구조를 더 구체화한다.
- 변경:
  - `docs/Production-Implementation-Blueprint.md`를 추가해 Phase 1 read-only, live enable guard, market status/VI, live order state machine, idempotency, SQLite schema 초안, service interface, dashboard/report, 테스트, 구현 slice를 정리했다.
  - 다음 코드 작업의 첫 순서로 Slice 1 read-only client, Slice 2 storage schema, Slice 3 market status, Slice 4 live order guard 체크리스트를 추가했다.
  - Claude cowork 전달 이력 관리를 위해 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-report.md`와 폴더 `README.md`를 추가했다.
  - cowork 리뷰 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-cowork-review.md`를 반영해 Slice 2를 2a/2b로 분할하고, kill switch schema, live client 우회 검사, `expired` 상태, Phase 2 정정 금지, live schema 누락 필드, migration/report-slice 매핑을 보강했다.
  - `docs/cowork-reports/README.md`에 report/review/followup/decision 파일 명명 규칙을 추가했다.
  - 반영 이력 파일 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-codex-followup.md`를 추가했다.
  - 계좌 소유자/실전 운용 승인권자 결정 기록 템플릿 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision-template.md`를 추가했다.
  - cowork 추가 왕복 없이 Slice 1 read-only wrapper 공개 메서드, allowlist 기반 isolation 기준, Slice 1 acceptance criteria, Slice 2a dataclass 필드, Slice 2a acceptance criteria/smoke query, Slice 1 go/no-go 기준을 보강했다.
  - cowork에게 전달할 통합 리포트 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-work_ver_2.md`를 추가했다.
  - `docs/cowork-reports/README.md`의 명명 규칙을 `work_ver_N` / `review_ver_N` / `work_ver_N-M` 형식으로 갱신했다.
  - cowork `review_ver_2`를 확인하고 `docs/Production-Implementation-Blueprint.md`에 signature 동등성/factory negative/import-time side effect 테스트 후보, `KisRestQuoteClient(` allowlist 6개 경로 분석, nullable schema 조정, JSON 최소 키, actor 표준값, migration dry-run 자동화 후보, Slice 1 go/no-go 보강을 반영했다.
  - 반영 리포트 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-work_ver_3.md`를 추가했다.
  - 계좌 소유자/실전 운용 승인권자 결정 기록 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision.md`를 추가했다. Slice 1 시작 승인, Phase 2 보수/기본 손실 한도, tick-aware 슬리피지 budget, 비상 청산 시장가 예외 권장안, VI open 주문 처리 권장안을 기록했다.
  - `README.md`와 `AGENTS.md`에 `docs/cowork-reports/` 역할을 추가했다.
  - `README.md` 핵심 문서 목록과 `AGENTS.md` 문서 역할에 새 청사진 문서를 추가했다.
  - `docs/Production-Architecture.md`에서 구현 청사진 문서를 실제 작업 순서 기준으로 참조하도록 연결했다.
- 문서 기준:
  - 새 청사진은 코드 변경 없이 제안 신규 모듈과 테이블을 명시한다.
  - 코드 변경 제안은 변경 전 / 변경 후 / 영향 범위 / 회귀 위험 형식으로 정리했다.
  - `app/risk/` 변경과 gate 기준값 확정은 운영자 승인 전 보류로 남겼다.
- 검증:
  - `git diff --check` 통과.
  - 금지된 코드 경로, `app/risk/`, gate 기준값, `VERSION` 변경이 없음을 확인했다.
  - 새 문서 참조와 기존 경로 존재 여부를 self-review 했다.
- 주의:
  - 이번 작업은 문서만 변경했다.
  - `VERSION` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-14] Codex -> Production Architecture cowork v2 보강

- 목적:
  - claude cowork v2 리뷰에서 남은 실전 운용 안전 누락과 단정조 위험을 추가 반영했다.
- 변경:
  - `docs/Production-Architecture.md` 4장 제목을 `안전 invariants와 정책 슬롯`으로 바꾸고, 현재 확인 사실 / invariant 후보 / 수치 정책 슬롯을 분리했다.
  - Phase 1 P0 기준은 별도 read-only client 또는 주문 메서드 hard fail 같은 구조적 차단을 기본 후보로 명시했다.
  - VI(변동성완화장치), 지정가/시장가 주문 타입 정책, 단주 잔량, fault injection 기준, 다양한 장 상황 후보를 추가했다.
  - 장애 시나리오 표를 `신규 주문 자동 동작`과 `진행 중 주문 운명`으로 나눠, 취소 시도/조회 보류/유지/보호성 청산 후보를 구분했다.
  - Phase 0 누적 정합성 자동 집계와 shadow/canary 모드 표현을 현재 구현 단정이 아니라 제안/운영 정책 단계로 약화했다.
- 검증:
  - `git diff --check` 통과.
  - 새 문서의 목차와 각 절 `관련 문서/코드 경로` 줄을 확인했다.
  - 금지된 코드, `app/risk/`, gate 기준값, `VERSION` 변경이 없음을 확인했다.
  - 문서에 단정적으로 쓴 기존 경로가 실제 저장소에 존재하는지 self-review 했다.
  - cowork v2 핵심 반영 항목인 VI, 지정가/시장가 정책, read-only client, fault injection, 진행 중 주문 운명 칼럼을 확인했다.
- 주의:
  - 이번 작업은 문서와 cowork 전달용 runtime report만 변경한다.
  - `VERSION` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-14] Codex -> Production Architecture cowork 리뷰 반영

- 목적:
  - cowork 리뷰에서 지적된 실전 운용 안전 누락, 과장 표현, 위험한 가정을 `docs/Production-Architecture.md`에 반영했다.
- 변경:
  - 실전 enable 플래그 시행 지점을 현재 확인된 코드 사실과 목표 구조로 분리했다.
  - `ALLOW_LIVE_ORDERS`는 현재 `app/config/settings.py`의 설정 일관성 검증까지만 확인되며, `app/brokers/kis_quote_rest.py` 주문 함수 직전 차단은 아직 없다는 점을 명시했다.
  - 값이 비어 있던 손실/노출/슬리피지 hard limit을 invariant가 아니라 운영자 결정 대기 슬롯으로 낮춰 적었다.
  - 상한가/하한가, 거래정지, 관리/투자유의, 동시호가, T+2, 기업행위, 부분 체결, kill switch 청산과 슬리피지 충돌, 운영자 단일 장애점, 승인 기록 무결성, paper-vs-live metric을 보강했다.
- 검증:
  - `git diff --check` 통과.
  - 새로 추가된 `docs/Production-Architecture.md`의 trailing whitespace 별도 확인.
  - 새 문서가 `README.md`, `AGENTS.md`, `docs/logbook.md`에서 일관되게 참조되는지 확인했다.
  - 문서에 단정적으로 쓴 기존 경로가 실제 저장소에 존재하는지 self-review 했다.
- 주의:
  - 이번 작업은 문서만 변경했다.
  - `VERSION` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-14] Codex -> 실전 운용 아키텍처 설계 문서 작성

- 목적:
  - 학습/연구 단계 이후 실제 자금 자동매매로 넘어갈 때 필요한 목표 구조, 안전 invariant, 단계적 전환, 장애 대응, 감사 로그, 검증 기준을 코드 변경 없이 문서화했다.
- 변경:
  - `docs/Production-Architecture.md`를 새 기준 문서로 추가했다.
  - `README.md` 핵심 문서 목록에 `docs/Production-Architecture.md` 참조를 추가했다.
  - `AGENTS.md` 문서 역할 섹션에 `docs/Production-Architecture.md` 참조를 추가했다.
- 문서 기준:
  - 현재 구현은 `paper`와 KIS 모의계좌 mirroring 중심이며, 실전 주문은 기본 비활성 상태로 정리했다.
  - 실전 주문 lifecycle, idempotency, 일일 손실/최대 낙폭 kill switch, 노출 한도, 슬리피지 추적, 알림 채널, 감사 로그 연결, active model 교체 안전성은 실전 전환 전 보강 대상으로 분리했다.
  - 현재 코드에 없는 제안 경로는 `제안 신규` 또는 `확인 필요`로 표시했다.
- 검증:
  - `git diff --check` 통과.
  - `README.md`, `AGENTS.md`에서 새 문서 참조 확인.
  - 새 문서에서 단정조로 참조한 주요 기존 경로 존재 확인.
- 주의:
  - 이번 작업은 문서만 변경했다.
  - `VERSION` 변경 없음.
  - 자동 commit/push 없음.

## [2026-05-13] Codex → 장후 label rebuild, dashboard 갱신, paper cash 기준 점검

- 후속 보강:
  - quick maintenance 성공 뒤 라벨이 아직 닫히지 않는 반복 문제를 줄이기 위해 `scripts/run_post_close_label_refresh.sh`를 추가했다.
  - quick 경로는 계속 10분 목표의 가벼운 진단으로 두고, 새 label refresh 경로가 `python -m app --build-feature-dataset` 후 KIS live 품질, source drift, KIS live feature diagnostics, runtime report, dashboard 를 갱신한다.
  - 상태 파일은 `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`에 남긴다.
  - 검증: `bash -n scripts/script_dispatch.sh`, `bash -n scripts/run_post_close_label_refresh.sh`, dry-run 2종, `python -m unittest tests.test_post_close_maintenance_script tests.test_post_close_label_refresh_script` 통과.
  - 실제 확인: `./scripts/run_post_close_label_refresh.sh --skip-build` 실행 완료, `status=ok`, dashboard generated_at `2026-05-13T23:15:10+09:00`.
  - 전체 검증: `python -m unittest discover -s tests -p "test_*.py"` 111개 통과, `git diff --check` 통과, `./scripts/check_local_setup.sh` `ok=true`.
  - 대시보드 `머신러닝 현황` 탭에 `장후 label refresh 상태` 카드를 추가해 최신 label refresh 상태 파일을 화면에서 확인할 수 있게 했다.
  - 대시보드 보강 검증: `python -m unittest tests.test_dashboard tests.test_post_close_label_refresh_script tests.test_post_close_maintenance_script` 17개 통과, `python -m app --build-dashboard` generated_at `2026-05-13T23:34:31+09:00`.
  - `paper_alignment` baseline snapshot 이 보유 종목 0개일 때만 raw cash 를 쓰던 조건을 수정했다.
  - 이제 보유 종목 유무와 관계없이 KIS `total_asset_amount - stock_evaluation_amount` 로 계산한 유효현금을 로컬 cash baseline 으로 쓴다.
  - 회귀 테스트 `test_align_local_paper_to_broker_uses_effective_cash_without_positions`를 추가했다.
  - 수정 후 `./scripts/verify_paper_dual_account_match.sh -AlignToBroker -RefreshDashboard -AsJson` 재실행 결과 `ok=true`, `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`, `raw_cash_gap=588,554`가 됐다.
  - 해석: KIS raw cash 와 total asset 기반 유효현금의 차이는 raw_cash_gap 으로만 남기고, 브로커 기준 로컬 paper baseline 은 유효현금 기준으로 일치한다.
- 장마감 후 상태:
  - live runtime 은 `15:30:16 +0900`에 post-close 상태로 정상 중지됐다.
  - dashboard 와 runtime watchdog 은 running 이며, 최종 `./scripts/check_local_setup.sh`는 `ok=true`, blockers 없음.
  - post-close quick maintenance 는 `2026-05-13 16:03:08 +0900`에 `status=ok`로 완료되어 있었다.
- feature/label 닫힘:
  - quick 완료 직후 2026-05-13 h15/h60 labels 가 `0`으로 남아 있어 장후 label rebuild 를 실행했다.
  - `python -m app --build-feature-dataset`: `features_written=6,401,292`, `labels_written=11,571,293`, horizons `[15, 60]`.
  - 갱신된 2026-05-13 KIS live 품질: minute bars/features `3,770`, h15 labels `3,620`, h60 labels `3,170`.
  - h15 label distribution: down `668`, flat `2,080`, up `872`.
  - latest raw minute 은 `2026-05-13T15:30:00+09:00`, closed feature coverage 는 `96.67%`, assessment 는 `ok`.
- 장후 리포트와 대시보드:
  - `python scripts/summarize_kis_live_data_quality.py --recent-days 10`: `assessment=ok`.
  - `python scripts/summarize_feature_source_drift.py`: `source_drift_detected` 유지.
  - `python scripts/summarize_kis_live_feature_diagnostics.py`: `no_clear_single_feature_signal`, strongest feature `mid_price`, Pearson `0.046725`.
  - `python -m app --build-runtime-report`와 `python -m app --build-dashboard` 실행 완료. dashboard generated_at `2026-05-13T20:54:44+09:00`.
- paper 계좌 정합성:
  - 최초 `./scripts/verify_paper_dual_account_match.sh -AsJson` 결과는 `initial_cash_mismatch`였다. 브로커/로컬 모두 보유 종목은 없었지만, root `.env`의 `PAPER_INITIAL_CASH=10000000`과 브로커 raw cash `9,201,233`이 달랐다.
  - 열린 포지션이 없어서 `./scripts/verify_paper_dual_account_match.sh -SyncInitialCash -AlignToBroker -RefreshDashboard -AsJson`를 실행했다.
  - root `.env`의 `PAPER_INITIAL_CASH`는 `9,201,233`으로 갱신됐다.
  - 최종 보유 수량과 total asset 은 일치하고 mismatch row 는 없지만, KIS 응답에서 `raw cash=9,201,233`, `effective cash/total asset=9,789,787`로 현금성 값이 갈라져 `balance_match=false`, status `waiting_first_submission`으로 남았다.
- 판단:
  - 2026-05-13 장중 데이터는 라벨까지 닫힌 학습 가능 상태다.
  - KIS live 단일 피처 신호는 여전히 약해 모델 승격은 보류한다.
  - 다음 작업 후보는 KIS 모의계좌의 raw cash 와 effective cash 차이 원인, 즉 미정산금/예수금 해석을 paper 정합성 리포트에서 더 명확히 표시하는 것이다.

## [2026-05-12] Codex → 장후 label rebuild, KIS 품질 갱신, paper 정합성 정렬

- 장마감 후 상태:
  - live runtime 은 `15:30:45 +0900`에 post-close 상태로 정상 중지됐다.
  - dashboard/watchdog 은 stale 로 확인되어 재기동했고, 최종 `./scripts/check_local_setup.sh`는 `ok=true`, blockers 없음으로 회복됐다.
  - post-close quick maintenance 는 watchdog 에 의해 이미 `2026-05-12 16:03:54 +0900`에 `status=ok`로 완료되어 있었다.
- feature/label 닫힘:
  - quick 완료 직후 대시보드는 오늘 `labels=0`으로 보였고, KIS 품질 리포트도 2026-05-12 h15/h60 labels `0`이었다.
  - `python -m app --build-feature-dataset` 실행 후 `features_written=6,397,522`, `labels_written=11,564,503`, horizons `[15, 60]`.
  - 갱신된 2026-05-12 KIS live 품질: minute bars/features `3,760`, h15 labels `3,610`, h60 labels `3,160`.
  - h15 label distribution: down `1,259`, flat `1,545`, up `806`.
  - latest raw minute 은 `2026-05-12T15:30:00+09:00`, closed feature coverage 는 `96.41%`, assessment 는 `ok`.
- 장후 리포트와 대시보드:
  - `python scripts/summarize_kis_live_data_quality.py --recent-days 10`: `assessment=ok`.
  - `python scripts/summarize_feature_source_drift.py`: `source_drift_detected` 유지.
  - `python scripts/summarize_kis_live_feature_diagnostics.py`: `no_clear_single_feature_signal`, strongest feature `avg_trade_size`, Pearson `0.045198`.
  - `python -m app --build-runtime-report`와 `python -m app --build-dashboard` 실행 완료. dashboard generated_at `2026-05-12T21:27:54+09:00`.
- paper 계좌 정합성:
  - 최초 `./scripts/verify_paper_dual_account_match.sh -AsJson`에서 로컬에만 `247540` 3주가 남아 `needs_review`가 나왔다.
  - 브로커 모의계좌를 기준으로 `./scripts/verify_paper_dual_account_match.sh -AlignToBroker -RefreshDashboard -AsJson` 실행.
  - 최종 `ok=true`, `status=matched_waiting_first_submission`, mismatch `0`, cash gap `0`, total asset gap `0`.
  - 현재 브로커/로컬 기준: `105560` 4주, effective cash `9,201,233`, total asset `9,815,633`.
- 판단:
  - 2026-05-12 장중 데이터는 라벨까지 닫힌 학습 가능 상태로 복구됐다.
  - KIS live 단일 피처 신호는 아직 약하므로 모델 승격은 보류한다.
  - 다음 거래일에는 장중 09:30 수집률과 장후 h15/h60 label 닫힘을 계속 확인한다.

## [2026-05-11] Codex → broker paper align wrapper cowork 검토 후 테스트 보강

- cowork read-only 검토를 반영해 `scripts/wsl_ops.py`의 `verify-paper-dual-account-match` 주변 회귀 테스트를 보강했다.
- 추가로 잠근 분기:
  - `-AlignToBroker` 실행 실패 시 `CalledProcessError`가 전파되고 sync/reconcile 로 넘어가지 않는다.
  - root `.env` 누락 시 KIS 호출 전에 fail-loud 한다.
  - KIS account snapshot 누락, `-SyncInitialCash` 현금 0/누락, `-FailOnMismatch` mismatch exit 을 확인한다.
  - `-SyncInitialCash`, `-AlignToBroker`, `-RefreshDashboard`, `-FailOnMismatch`, `-AsJson` argparse 별칭이 유지되는지 확인한다.
  - align → sync-broker-paper-orders → reconcile 순서를 확인한다.
- 검증:
  - `python -m py_compile scripts/wsl_ops.py tests/test_wsl_ops.py`
  - `python -m unittest tests.test_wsl_ops`: 10개 통과.
  - `python scripts/wsl_ops.py verify-paper-dual-account-match --help`: PowerShell 스타일 별칭 확인.
  - `python -m unittest discover -s tests -p "test_*.py"`: 108개 통과.
  - `git diff --check`: 통과.

## [2026-05-11] Codex → 장후 quick maintenance, label rebuild, paper 정합성 복구

- 장 종료 후 quick maintenance 를 실행했다.
  - `./scripts/run_post_close_ml_maintenance.sh --quick`: `status=ok`, completed_at `2026-05-11 22:16:58 +0900`.
  - runtime report, local setup check, KIS live 품질, source drift, KIS live feature diagnostics, dashboard rebuild 가 갱신됐다.
- 오늘 Cybos/KIS 누적 DB 기준 feature/label 을 다시 닫았다.
  - `python -m app --build-feature-dataset`: `features_written=6,393,762`, `labels_written=11,557,733`.
  - 2026-05-11 KIS live: features `3,463`, h15 labels `3,313`, h60 labels `2,863`.
  - h15 label distribution: down `595`, flat `2,191`, up `527`.
  - assessment 는 재부팅/DB lock 공백이 누적되어 `watch` 유지지만, latest raw minute 은 `15:30`까지 도달했다.
- feature 진단:
  - KIS live feature diagnostics 는 `no_clear_single_feature_signal`.
  - source drift 는 `source_drift_detected`; Cybos historical 은 live 호가 feature 직접 대리값으로 쓰지 않는다.
- 모의계좌 정합성:
  - WSL bash 포팅 과정에서 `verify_paper_dual_account_match.sh -AlignToBroker`가 실제 `python -m app --align-local-paper-to-broker`를 호출하지 않는 누락을 확인했다.
  - `scripts/wsl_ops.py`를 수정해 `-AlignToBroker`는 실제 align 을 수행하고, 열린 브로커 포지션이 있으면 `-SyncInitialCash`는 거부하도록 legacy 동작을 복원했다.
  - `./scripts/verify_paper_dual_account_match.sh -AlignToBroker -RefreshDashboard -AsJson`: `ok=true`, `status=matched_waiting_first_submission`, mismatch/cash gap/total asset gap 모두 `0`.
  - 현재 기준: 브로커/로컬 모두 `005930` 1주, cash `9,638,723`, total asset `9,924,223`.
- 검증:
  - `python -m py_compile scripts/wsl_ops.py tests/test_wsl_ops.py`
  - `python -m unittest tests.test_wsl_ops tests.test_paper_alignment tests.test_paper_reconciliation tests.test_broker_paper_sync`: 14개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 101개 통과.
  - `git diff --check`: 통과.

## [2026-05-11] Codex → 주말 자율 점검 마감

- 14:13 KST 기준 주말 자율 연구/품질개선 follow-up 종료 시각에 도달했다.
- 최종 상태:
  - `./scripts/check_local_setup.sh`: `ok=true`, blockers 없음.
  - dashboard/watchdog/live runtime 모두 running.
  - latest raw minute: `2026-05-11T14:13:00+09:00`, lag `67s`.
  - 당일 coverage watch 는 12:30~13:03 재부팅/DB 잠금 공백이 누적된 결과이며, 현재 live 수집 흐름은 정상이다.
- 후속 heartbeat 자동화는 종료 대상으로 처리한다.

## [2026-05-11] Codex → 재부팅 후 runtime 복구와 autoboot 장중 fast-start 보강

- 12:56 KST 재부팅 후 점검에서 startup launcher 는 설치/정상 경로였지만 dashboard, watchdog, live runtime 프로세스가 stale/stopped 상태였다.
- dashboard/watchdog 을 재기동했고 watchdog 이 live runtime 을 다시 올려 최종 `./scripts/check_local_setup.sh`는 `ok=true`, blockers 없음으로 회복됐다.
- live runtime 은 KIS WebSocket 연결 후 `database is locked`로 몇 차례 종료됐고, 장중에 떠 있던 `python -m app --cleanup-runtime-test-data`가 DB 쓰기를 막는 원인으로 확인되어 종료했다.
- 이후 latest raw minute 은 `2026-05-11T13:05:00+09:00`, lag `31s`로 회복됐다. 당일 전체 coverage watch 는 재부팅/잠금 구간 공백이 반영된 정상 주의 상태다.
- `scripts/script_dispatch.sh`의 `runtime_autoboot`는 장전/장중(`pre-open`, `regular-session`)에는 account refresh, cleanup, dashboard build 를 건너뛰고 dashboard/live runtime/watchdog 기동을 우선하는 fast-start 로 보강했다.
- 검증:
  - `bash -n scripts/script_dispatch.sh`
  - `timeout 30s ./scripts/start_runtime_autoboot.sh` → `live_window_fast_start=true`
  - `./scripts/check_local_setup.sh` → `ok=true`

## [2026-05-10] Codex → 월요일 09:30 점검 false alarm 보정

- cowork 검토를 반영해 KIS live coverage 와 readiness 카드의 장중 점검 오해 가능성을 줄였다.
- `scripts/summarize_kis_live_data_quality.py`가 `latest_raw_minute_lag_seconds`와 닫힌 분 기준 `minute_bar_closed_coverage_ratio`, `feature_closed_coverage_ratio`를 출력한다.
- 분봉/특징 coverage assessment 는 아직 닫히지 않은 마지막 1분을 제외해 09:30 직후 자연 지연이 false watch 로 보이지 않게 했다.
- 대시보드 `KIS live 데이터 품질` 카드에 raw minute 지연, 닫힌 분 기준 coverage, raw coverage 100% 초과 caveat 를 표시한다.
- 대시보드 `장전 readiness` 카드에 점검 신선도와 KIS 시세 자격정보 준비 여부를 추가했다.
- quick post-close maintenance 는 `check_local_setup.sh`를 warning-only 로 실행해 readiness 입력도 갱신한다.
- `./scripts/run_post_close_ml_maintenance.sh --quick` 검증 결과 tasks 에 `check-local-setup`이 포함되고 `status=ok`로 완료됐다.

## [2026-05-10] Codex → runtime readiness 대시보드 표시

- `./scripts/check_local_setup.sh` 최신 결과는 `ok=true`, blockers 없음으로 확인했다.
- 대시보드 `상태 및 설정 > 현재 프로그램 상태`에 `장전 readiness` 카드를 추가했다.
- 이 카드는 `runtime-data/reports/recovery/latest-local-setup-check.json`을 읽어 dashboard, watchdog, live runtime, startup launcher, websockets, lightgbm 상태를 보여준다.
- 현재는 주말이라 live runtime 은 `stopped`, `live_runtime_should_run=false`가 정상이다.

## [2026-05-10] Codex → 월요일 장전 runtime readiness 점검

- `./scripts/check_local_setup.sh` 첫 실행에서 dashboard/watchdog stale 로 `ok=false`를 확인했다.
- dashboard 와 runtime watchdog 을 재기동했고, watchdog 이 stale dashboard 를 다시 살려 최종 점검은 `ok=true`가 됐다.
- 현재 dashboard 는 `running`, runtime watchdog 은 `running`, live runtime 은 주말 session status 때문에 `stopped`가 정상이다.
- 월요일에는 09:00~09:30 사이 watchdog 이 live runtime 을 켜고 KIS symbol-minute 가 증가하는지 확인한다.

## [2026-05-10] Codex → KIS live 장중 coverage 눈금 추가

- `scripts/summarize_kis_live_data_quality.py`에 최신 거래일 기준 `latest_intraday_coverage`를 추가했다.
- 기준은 watchlist 종목 수와 정규장 시작 이후 최신 raw minute 까지의 기대 symbol-minute 다.
- 대시보드 `KIS live 데이터 품질` 카드에 기대 symbol-minute, 시장 체결/호가/분봉/특징 coverage 를 표시한다.
- 현재 2026-05-08 기준 market `97.7%`, feature `96.9%`로 계산된다. orderbook 은 장전 호가 포함 때문에 `103.8%`로 1을 넘을 수 있다.
- coverage 가 `95%` 미만이면 `watch`, `80%` 미만이면 `needs_attention`으로 assessment 를 올리도록 보강했다.

## [2026-05-10] Codex → quick post-close 데이터 품질 진단 자동 갱신

- 목적:
  - 장후 대시보드가 최신 KIS live 데이터 품질, KIS-Cybos feature drift, KIS live feature-label 진단을 자동으로 반영하도록 quick maintenance 를 보강했다.
- 변경:
  - `scripts/script_dispatch.sh`의 quick post-close 경로에 아래 warning-only 진단을 추가했다.
    - `scripts/summarize_kis_live_data_quality.py --recent-days 10`
    - `scripts/summarize_feature_source_drift.py`
    - `scripts/summarize_kis_live_feature_diagnostics.py`
  - quick 상태 파일의 tasks 목록에 진단 3종을 포함하도록 했다.
- 안전 기준:
  - heavy research, feature dataset 전체 재생성, active model 교체, `app/risk/` 변경은 하지 않았다.
  - 진단 실패는 stderr warning 으로만 남기고 quick dashboard 갱신 흐름을 계속 진행한다.
- 회귀 테스트:
  - `tests/test_post_close_maintenance_script.py`를 추가해 quick 경로의 진단 명령과 상태 파일 task 목록을 확인한다.

## [2026-05-10] Codex → KIS live feature-label 진단

- 목적:
  - 실제 KIS live 표본 안에서 현재 피처가 h15 label/future return 과 어떤 관계를 보이는지 확인했다.
- 구현:
  - `scripts/summarize_kis_live_feature_diagnostics.py` 추가.
  - `tests/test_kis_live_feature_diagnostics.py` 추가.
  - 출력 리포트: `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.{json,md}`.
- 결과:
  - 표본 rows `6,420`, symbols `10`, labeled trade_dates `2`.
  - h15 label distribution: down `1,041`, flat `3,997`, up `1,382`.
  - strongest by absolute Pearson: `return_1m_pct`, Pearson `-0.039879`, top-bottom future_return delta `-0.068962`.
  - `hl_range_pct`는 Pearson `0.015360`으로 약하지만 top-bottom up-ratio delta `0.217290`이 관찰됐다.
  - `bid_ask_imbalance`, `spread_bps`의 단일 피처 상관은 아직 매우 약하다.
- 판단:
  - posture: `sample_too_small`.
  - 현재 KIS live 데이터는 피처 후보를 관찰하는 정도로만 쓰고, 모델 승격 근거로 쓰지 않는다. 월요일 이후 더 쌓인 live 데이터로 같은 리포트를 재확인한다.
- 대시보드:
  - `머신러닝 현황 > 현재 운용`에 `KIS live feature-label 진단` 카드를 추가해 표본 크기, strongest feature, Pearson, 상하위 구간 차이를 바로 볼 수 있게 했다.

## [2026-05-10] Codex → KIS live vs Cybos historical feature source drift 진단

- 목적:
  - Cybos 5년치 15분봉 후보를 실제 KIS live 데이터의 직접 대리값으로 볼 수 있는지 feature 분포 기준으로 확인했다.
- 구현:
  - `scripts/summarize_feature_source_drift.py` 추가.
  - `tests/test_feature_source_drift_summary.py` 추가.
  - 출력 리포트: `runtime-data/reports/data-quality/latest-feature-source-drift.{json,md}`.
  - KIS 표본은 Cybos 마지막 일자 이후 live 날짜를 우선 사용해 같은 feature row가 양쪽 표본에 섞이지 않게 했다.
- 결과:
  - KIS 표본: `6,590` rows, `10` symbols, `3` trade dates, `2026-05-06..2026-05-08`.
  - Cybos 표본: `100,000` rows, `199` symbols, `20` trade dates, `2026-04-06..2026-05-04`.
  - `spread_bps`: KIS mean `12.546763`, zero_ratio `0.006070`; Cybos mean `0.0`, zero_ratio `1.0`.
  - `bid_ask_imbalance`: KIS mean `0.038760`, zero_ratio `0.007436`; Cybos mean `0.0`, zero_ratio `1.0`.
  - `avg_trade_size`도 KIS mean `400.831744` vs Cybos mean `1054.741933`으로 차이가 컸다.
- 판단:
  - posture: `source_drift_detected`.
  - Cybos historical 은 live 호가 feature 분포를 담지 못하므로, Cybos-only 연구 후보는 구조 탐색용으로만 보고 실제 KIS live 성능의 직접 대리값으로 승격 판단하지 않는다.
- 대시보드:
  - `머신러닝 현황 > 현재 운용`에 `KIS-Cybos feature drift` 카드를 추가해 위 진단 결과를 바로 확인할 수 있게 했다.

## [2026-05-10] Codex → KIS live 데이터 품질 요약과 label 닫힘 보정

- 목적:
  - 다음 모델 개선 전에 KIS 실시간 체결/호가 데이터가 feature/label 까지 닫히는지 정본 DB 기준으로 확인했다.
- 구현:
  - `scripts/summarize_kis_live_data_quality.py` 추가.
  - `tests/test_kis_live_data_quality_summary.py` 추가.
  - 출력 리포트: `runtime-data/reports/data-quality/latest-kis-live-data-quality.{json,md}`.
  - 첫 구현은 SQLite 임시 actual-minute 조인이 10분을 넘겨 중단했고, 반복 조인을 제거해 정본 DB 기준 약 10초 안에 완료되도록 바꿨다.
- 실행:
  - 첫 리포트에서 2026-05-08 feature `3,790` symbol-minute 대비 h15/h60 label 이 `0`으로 확인됐다.
  - `python -m app --build-feature-dataset` 실행 완료: `features_written=6,390,299`, `labels_written=11,551,557`, horizons `[15, 60]`.
  - 재실행한 품질 리포트 assessment 는 `ok`.
- 최신 2026-05-08 품질:
  - market symbol-minutes `3,821`
  - orderbook symbol-minutes `4,060`
  - minute bars `3,790`
  - features `3,790`
  - h15 labels `3,640`
  - h60 labels `3,200`
  - h15 label distribution: down `614`, flat `2,208`, up `818`
- 판단:
  - 최신 KIS live 데이터는 feature/label 기준으로 학습 가능한 상태까지 닫혔다.
  - 2026-05-07은 live runtime 늦은 재기동으로 인한 부분 수집일로 유지한다.
  - 월요일에는 장전/09:30 수집률 확인을 먼저 하고, 모델 튜닝은 그 이후 KIS 누적 품질을 보고 진행한다.

## [2026-05-10] Codex → dashboard KIS live 데이터 품질 카드 추가

- 목적:
  - 월요일 장전/장중 점검 때 대시보드만 보고도 KIS live 데이터가 feature/label까지 닫혔는지 확인할 수 있게 했다.
- 구현:
  - `app/services/dashboard.py`가 `latest-kis-live-data-quality.json`을 dashboard payload에 포함한다.
  - 머신러닝 현황의 현재 운용 탭에 `KIS live 데이터 품질` 카드를 추가했다.
- 확인:
  - `python -m app --build-runtime-report` 실행 완료.
  - `python -m app --build-dashboard` 실행 완료: `generated_at=2026-05-10T06:05:14.388332+09:00`.
  - HTML에서 `KIS 품질: ok`, `KIS 최신일: 2026-05-08`, h15 labels `3,640`, h60 labels `3,200` 표시 확인.

## [2026-05-10] Codex → Cybos 연구 suite 통합 요약

- 목적:
  - 주말 연구 두 번째 라운드로 기존 Cybos 리포트를 한곳에 모아 다음 의사결정 기준을 명확히 했다.
  - 새 대형 학습 없이 기존 결과를 재해석하는 안전한 작업으로 진행했다.
- 구현:
  - `scripts/summarize_cybos_research_suite.py` 추가.
  - `tests/test_cybos_research_suite_summary.py` 추가.
  - 출력 리포트: `runtime-data/reports/backtests/latest-cybos-research-suite-summary.{json,md}`.
- 결과:
  - posture: `hold_all_current_cybos_candidates`.
  - `bar_only`는 hit_rate `0.383333`이지만 net `-3.785540%`로 비용을 넘지 못했다.
  - `bar_context`, `bar_context_momentum`, `F-1 cybos bar-only`도 모두 비용 반영 net 음수다.
  - expected-value는 낮은 비용 `0.10%`, `0.108%`에서만 headline 양수이고 bootstrap CI 하단은 음수다.
  - rule challenger 최선인 `quiet_breakout`도 hit_rate `0.070254`, net `-106.838776%`로 승격 후보가 아니다.
  - label sensitivity/reproducibility는 각각 과최적화 의심, 재현성 부족으로 정리됐다.
- 판단:
  - 현재 Cybos 15분 과거봉 기반 후보는 자동 승격할 후보가 없다.
  - 다음 모델 방향은 신규 grid 튜닝보다 KIS 실시간 호가/체결 데이터 품질 누적, 비용 `0.13%` 이상에서 CI 하단 양수인 후보 탐색, regime/시장상태 피처 설계가 우선이다.

## [2026-05-10] Codex → dashboard profile 재측정

- 명령:
  - `./scripts/profile_dashboard_build.sh`
- 결과:
  - profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-030930/`
  - elapsed `0:25.65`, max RSS `459,068KB`.
- 판단:
  - 10분 자동 갱신 기준으로는 안정권이다.
  - 주 병목은 raw KIS source minute 집계로 재확인됐다.
  - 추가 expression index 는 dashboard 조회를 줄일 수 있으나 raw tick 쓰기 비용을 키울 수 있어, 월요일 장중 수집 안정성을 먼저 본 뒤 적용 여부를 판단한다.

## [2026-05-10] Codex → 주말 연구 배치: EV 비용 sweep 과 dashboard raw-source 인덱스

- 목적:
  - 월요일 장전 전까지 주말/저부하 시간에 할 수 있는 모델 품질·운영 품질 작업을 진행했다.
  - app/risk gate 는 건드리지 않고, 기존 리포트 재분석과 대시보드 병목 완화를 우선했다.
- expected-value 안정성:
  - `scripts/summarize_expected_value_stability.py`에 `--cost-sweep-pct` 옵션을 추가했다.
  - 기존 expected-value fold 선택을 재학습 없이 비용별로 재가격해 fold 분포와 bootstrap CI를 함께 기록한다.
  - 결과 리포트: `runtime-data/reports/backtests/latest-cybos-expected-value-stability-bar-context-momentum-h15.{json,md}`.
  - 비용 `0.10%`, `0.108%`에서는 trade-sum headline 이 양수지만 CI가 0을 가로질러 안정성이 부족하다.
  - 비용 `0.13%`, `0.16%`, `0.20%`에서는 비용 반영 trade-sum 이 음수다.
  - 판단: 현재 `bar_context_momentum` expected-value 후보는 비용 초과 알파가 안정적이지 않으므로 승격 보류를 유지한다.
- dashboard 성능:
  - 사전 profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-014912/`, elapsed `0:26.51`, max RSS `459,980KB`.
  - `raw_market_ticks(source, symbol, event_time)`, `raw_orderbook_ticks(source, symbol, event_time)` 인덱스를 스키마와 정본 DB에 반영했다.
  - source count 조회는 `lower(source)` 계산을 피하고 `source IN (...)`로 인덱스를 사용하도록 바꿨다.
  - 사후 profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-015234/`, elapsed `0:18.17`, max RSS `458,832KB`.
  - 판단: dashboard build 는 10분 갱신 기준 안정권이며, 직전 profile 대비 약 `31%` 단축됐다.
- 검증:
  - `python -m py_compile app/storage/sqlite_store.py scripts/summarize_expected_value_stability.py` 통과.
  - `python -m unittest tests.test_expected_value_stability tests.test_runtime_scope tests.test_dashboard`: 16개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 93개 통과.

## [2026-05-09] Codex → challenger 독립 holdout 보강

- 목적:
  - LightGBM 학습 validation tail과 challenger 평가 tail이 사실상 같은 기간이던 문제를 줄였다.
  - 이제 challenger는 마지막 tail `10%`를 reserved holdout으로 떼어내고, 학습/validation은 그 이전 development 구간에서만 수행한다.
- 구현:
  - `app/services/research.py`에 challenger holdout split을 추가했다.
  - 학습 summary에 `challenger_holdout_split`을 기록한다.
  - challenger report와 candidate별 결과에 `dataset_scope`, `evaluation_split`, `evaluation_independence_status`를 기록한다.
  - 최신 LightGBM 학습 summary가 reserved holdout과 맞지 않으면 해당 LightGBM은 promotable 후보로 보지 않도록 했다.
  - cowork 리뷰 반영으로 holdout 경계/validation overlap 비교는 ISO 문자열 비교가 아니라 `datetime.fromisoformat` 비교로 보강했다.
  - legacy/mismatch/overlap/fallback 가드 분기와 split key 비중복을 단위 테스트로 고정했다.
- 실제 재실행:
  - `python -m app --train-lightgbm --horizon-min 15`
    - `training_run_id=train-lightgbm-h15-20260509030957756047`
    - `train_rows=4,295,040`, `validation_rows=1,183,354`, `validation_accuracy=0.571482`
  - `python -m app --run-challengers --horizon-min 15`
    - `dataset_scope=challenger_holdout_tail_10pct`
    - holdout rows `662,401`, start `2025-10-24T09:00:00+09:00`
    - best `latest_lightgbm`: accuracy `0.504269`, trade_hit_rate `0.202465`, net `-30.697069%`, trades `568`
    - `recommended_action=review_required`, active model은 `baseline-h15-v1` 유지
  - `python -m app --build-dashboard`: `generated_at=2026-05-09T03:26:29.971728+09:00`
- 판단:
  - challenger 평가 독립성은 개선됐지만, 독립 holdout 기준 비용 반영 성과가 음수라 모델 승격은 보류한다.
  - `0.92` validation 과열 자체는 이번 변경으로 직접 설명된 것이 아니며, 이번 변경은 해당 validation 구간을 challenger 승격 근거로 재사용하지 않게 한 조치다.
  - LightGBM 승격 검토는 재학습 직후 같은 데이터 경계에서 challenger를 이어 실행해야 한다. live 데이터가 추가되어 holdout 경계가 바뀌면 fail-safe로 promotable이 막힌다.
  - cowork 리뷰의 남은 위험인 artifact/DB 불일치 복구 시나리오도 보강했다. 새 LightGBM artifact는 `training_run_id`, `trained_at`, `dataset_scope`, `challenger_holdout_first_event_time`를 payload에 저장하고, challenger는 DB 최신 training row와 artifact의 `training_run_id`가 다르면 승격 후보에서 제외한다.
  - 정본 전체 `python -m app --train-lightgbm --horizon-min 15`와 `python -m app --run-challengers --horizon-min 15`는 각각 15분/10분 제한에서 완료되지 않고 메모리 95% 안팎까지 사용해 중단했다. 기존 artifact 시각은 `2026-05-09 03:09`로 partial overwrite는 확인되지 않았다.
  - 판단: 전체 LightGBM/challenger는 quick 작업이 아니라 D드라이브 snapshot 기반 heavy research 또는 bounded 평가 경로로 분리해야 한다.
  - 대시보드 표기도 점검했다. 기존 화면은 LightGBM `검증 정확도`를 학습 validation `57.15%`가 아니라 challenger holdout `50.43%`로 보여 혼동 여지가 있었고, 예전 challenger report의 `promotable=true`도 새 artifact lineage guard 기준과 맞지 않았다.
  - dashboard는 학습 validation split만 찾아 `학습 validation 정확도`로 표시하고, 현재 artifact lineage guard를 적용해 legacy metadata 없는 LightGBM 후보를 `승격 가능=아니오`로 표시하도록 바꿨다.
  - `python -m app --build-dashboard`로 `generated_at=2026-05-09T14:44:36.689019+09:00` snapshot을 만들고 dashboard server를 PID `439371`로 재시작했다.
- 검증:
  - `python -m py_compile app/models/lightgbm_model.py app/services/research.py` 통과.
  - `python -m unittest tests.test_research_pipeline`: 8개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 91개 통과.

## [2026-05-08] Codex → cowork 의견 반영: post-close quick 분리, dashboard 병목 제거, EV 안정성 진단

- 판단:
  - cowork 의견 중 모델 승격 보류, portfolio proxy 해석 주의, fold 분포/CI 필요, quick/heavy 트랙 분리는 타당하다고 봤다.
  - 비용 sweep 전체 재학습은 장시간 작업이므로 먼저 기존 `0.13%` expected-value 결과를 재학습 없이 안정성 리포트로 요약했다.
- post-close 운영:
  - watchdog 기본 post-close 모드를 `quick-live-report`로 변경했다.
  - quick 경로는 `build-runtime-report`, `build-dashboard`만 수행하고, snapshot DB와 `--rebuild-actual-ml`을 쓰는 heavy research 는 `--heavy-research --use-snapshot` 명시 실행으로 분리했다.
  - `run_post_close_ml_maintenance.sh --quick` 직접 실행 결과 `status=ok`, `completed_at=2026-05-08 22:10:23 +0900`.
  - watchdog을 재기동해 `post_close_ml_mode=quick-live-report`를 새 기본값으로 반영했다.
- dashboard 병목:
  - profile 산출물: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260508-215838/`.
  - cProfile에서 `runtime_scope.build_runtime_scope`가 Cybos 5년치 raw row까지 actual runtime 판정에 넣는 것이 병목으로 확인됐다.
  - `fetch_raw_symbol_minute_source_counts(..., sources=...)`를 추가하고 actual scope 에서는 `kis-rest`, `kis-ws`만 SQL에서 먼저 읽도록 바꿨다.
  - 장 시간 판정은 minute 단위 캐시를 사용한다.
  - 재측정: `python -m app --build-dashboard`가 `0:35.04`, max RSS `453,960KB`로 완료됐다.
- expected-value 안정성:
  - 리포트: `runtime-data/reports/backtests/latest-cybos-expected-value-stability-bar-context-momentum-h15.{json,md}`.
  - fold 분포: 양수 `5`, 음수 `2`, no-trade `5`.
  - bootstrap 95% fold-sum net CI: `-203.859408..42.553578`.
  - 결론: 비용 반영 거래합산 수익률이 음수이고 fold 안정성도 낮으므로 모델 승격 보류를 유지한다.
- 검증:
  - `python -m py_compile app/services/runtime_scope.py app/storage/sqlite_store.py scripts/wsl_ops.py scripts/summarize_expected_value_stability.py` 통과.
  - `bash -n scripts/script_dispatch.sh scripts/profile_dashboard_build.sh scripts/run_post_close_ml_maintenance.sh` 통과.
  - `python scripts/wsl_ops.py run-watchdog-loop --single-pass` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.

## [2026-05-08] Codex → 0.13% expected-value 재검증, 포트폴리오 프록시, dashboard 최적화

- expected-value 0.13% 비용 재검증:
  - 입력 DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260508-160019.db`.
  - 출력 runtime: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/expected-value-20260508-h15-cost013/runtime-data`.
  - source=`cybos-historical`, feature set=`bar_context_momentum`, horizon=`15`, trade cost=`0.13%`.
  - 결과: `folds=12`, `rows_evaluated=600,000`, `trades_taken=2,599`, `overall_accuracy=0.534130`, `trade_hit_rate=0.300500`, `win_rate=0.497114`.
  - 거래합산: `trade_sum_net_return_pct=-51.251310`, `average_net_return_pct=-0.019720`.
  - 포트폴리오 프록시: `portfolio_return_pct=-1.802245`, `allocation=5%`, `max_gross_exposure=100%`, `executed=2,006`, `skipped_exposure=593`.
  - 판단: 0.108% 비용에서는 양수였지만 0.13% 보수 비용에서는 다시 음수다. hit rate는 문턱만 넘었고 비용 초과 기대값은 아직 부족하므로 모델 승격은 보류한다.
- 구현:
  - expected-value walk-forward에 `fixed_fraction_per_signal_horizon_proxy` 포트폴리오 프록시 수익률을 추가했다.
  - 이 값은 실제 paper 계좌 수익률이 아니라, 거래별 수익률 합산을 덜 과장해서 보기 위한 진단값이다.
- 대시보드:
  - `python -m app --build-dashboard` 기존 측정: `8분 03초`, max RSS 약 `7.9GB`.
  - 기본 `오늘` 화면에서 대형 테이블 전체를 읽지 않도록 기간 SQL 조회를 우선 사용하게 바꿨다.
  - 재측정: `3분 27초`, max RSS 약 `5.4GB`.
  - dashboard server와 watchdog은 둘 다 running 상태다.

## [2026-05-08] Codex → 장후 maintenance 중단, expected-value review 완료

- 장후 운영 상태:
  - 확인 시각: `2026-05-08 18:07 KST`.
  - live runtime은 `2026-05-08 15:30:33 +0900`에 정상 정지했고, watchdog은 post-close 상태에서 running 이다.
  - 09:00 이후 정본 DB 누적: `raw_market_ticks=1,170,143`, `raw_orderbook_ticks=647,201`, `curated_minute_bars=3,770`, `feature_model_inputs=3,770`, `serving_predictions=7,540`, `serving_trade_signals=3,770`.
- post-close maintenance:
  - 자동 post-close maintenance는 D드라이브 snapshot `post-close-h15-20260508-160019.db`를 만든 뒤 `--rebuild-actual-ml` 단계에서 2시간 가까이 진행됐다.
  - main DB가 아니라 snapshot/runtime 격리 경로에서 실행 중이었으나, 더 진행하면 같은 heavy job이 반복될 가능성이 커서 중단했다.
  - `latest-post-close-ml.json`은 `failed`로 표시했다.
  - watchdog이 `failed` 상태를 보고 같은 날짜 maintenance를 계속 재시작하는 문제가 있어, 오늘 날짜에 status 값이 있으면 `already_<status>`로 보고 재시작하지 않도록 `scripts/wsl_ops.py`를 수정했다.
  - 중단 중 생긴 불완전한 D드라이브 snapshot `post-close-h15-20260508-181250*`, `post-close-h15-20260508-181459*`는 삭제했다.
- expected-value review:
  - 실행 경로: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/expected-value-20260508-h15/runtime-data`.
  - 입력 DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260508-160019.db`.
  - 명령은 도구 1시간 제한에서 timeout 됐지만 리포트 생성은 완료됐다.
  - 결과: `folds=12`, `rows_evaluated=600,000`, `trades_taken=3,008`, `overall_accuracy=0.534130`, `trade_hit_rate=0.304854`, `win_rate=0.523271`, `average_net_return_pct=0.006320`, `trade_sum_net_return_pct=+19.012036`, `estimated_cost_drag_pct=324.864`.
  - fold 안정성: 양수 fold 7개, 음수 fold 2개, no-trade fold 3개.
  - 판단: 비용 `0.108%` 기준에서는 train-only expected-value 선별이 처음으로 양수 거래합산 순수익과 0.3 이상 hit rate를 만들었다. 다만 0.13% 보수 비용 재검증과 portfolio-level 수익률 환산 전까지 자동 승격하지 않는다.
- 대시보드:
  - expected-value 리포트는 정본 `runtime-data/reports/backtests/`에도 복사했다.
  - `python -m app --build-dashboard`는 5분 제한에서 끝나지 않아 중단했다.
  - dashboard server는 `http://127.0.0.1:8765`에서 running, API responding 상태이며 최신 snapshot은 `2026-05-08 18:48` 파일이다.

## [2026-05-08] Codex → 장중 broker paper 체결 조회 rate-limit 완화

- 관찰:
  - 확인 시각: `2026-05-08 14:56 KST`.
  - live runtime은 `running`, `current_session_status=regular-session`, `trading_mode=paper` 상태다.
  - 09:00 이후 정본 DB 누적: `curated_minute_bars=3,550`, `feature_model_inputs=3,550`, `serving_predictions=7,100`, `serving_trade_signals=3,550`.
  - `live-runtime.stderr.log`에서 `KIS broker paper order-fill query rate-limited` 경고가 누적 231회 확인됐다.
- 조치:
  - 수동 `sync_broker_paper_orders`는 기존처럼 짧은 재시도를 유지한다.
  - 장중 `OnlinePipelineProcessor`의 브로커 체결 동기화는 rate-limit 발생 시 같은 호출 안에서 즉시 재시도하지 않고, 기존 5분 cooldown 으로 빠지도록 바꿨다.
  - 목적은 KIS 호출 제한 충돌, live loop 지연, 로그 폭증을 줄이는 것이다.
  - watchdog이 `2026-05-08 15:00:34 +0900`에 live runtime을 다시 올려 현재 실행 중인 프로세스에는 이번 변경이 적용된 상태다.
  - 15:00 재기동 직후 tail 기준으로는 broker paper 체결 조회 즉시 재시도 로그가 추가로 보이지 않았다.
- 검증:
  - `python -m py_compile app/services/broker_paper.py app/services/broker_paper_sync.py app/services/streaming.py` 통과.
  - `python -m unittest tests.test_broker_paper_sync tests.test_streaming_pipeline`: 11개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.
  - `git diff --check` 통과.

## [2026-05-08] Codex → 장중 수집 확인과 train-only expected-value 실험 경로 추가

- 장중 수집 상태:
  - 확인 시각: `2026-05-08 12:14 KST`.
  - live runtime은 `2026-05-08 08:00:59 +0900`부터 `running`, `current_session_status=regular-session`, `trading_mode=paper` 상태다.
  - runtime watchdog은 `running`, `live_runtime_should_run=true`, 오류 없음이다.
  - 09:00 이후 정본 DB 누적: `curated_minute_bars=1,940`, `feature_model_inputs=1,946`, `serving_predictions=3,900`, `serving_trade_signals=1,950`.
  - 판단: 2026-05-08 장중 수집/추론 축은 살아 있다.
- 장중 heavy snapshot 중단:
  - `run_research_on_snapshot.sh --prefix intraday-metrics-gate -- python -m app --run-gate-walk-forward --horizon-min 15`는 live DB backup 단계가 1시간 이상 끝나지 않아 중단했다.
  - 미완성 D드라이브 snapshot 파일은 삭제했다.
  - 판단: 장중에는 live DB 전체 snapshot/gate 재생성을 직접 밀지 않고, 장후 maintenance에서 snapshot 기반으로 실행한다.
- 모델 개선 경로:
  - `python -m app --run-cybos-expected-value-review`를 추가했다.
  - 이 경로는 각 fold의 train tail calibration 구간에서만 `probability_up` threshold를 고르고 test 구간에 적용한다.
  - 선택 기준은 비용 차감 평균 기대값 양수 여부이며, test 결과를 보고 threshold를 다시 맞추지 않는다.
  - 장후 후속 heartbeat는 16:20 KST에 gate/challenger 재생성과 expected-value review를 이어서 확인하도록 갱신했다.
- 검증:
  - `python -m py_compile app/__main__.py app/services/research.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_research_pipeline tests.test_dashboard`: 18개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.
  - `git diff --check` 통과.

## [2026-05-08] Codex → 수익률 지표 의미 분리와 장전 자동 기동 확인

- 장전 자동 기동 확인:
  - `2026-05-08 08:37 KST` 기준 runtime watchdog은 `running`, `live_runtime_should_run=true`, 오류 없음.
  - live runtime은 `2026-05-08 08:00:59 +0900`에 시작됐고 `running`, `trading_mode=paper`, `credentials_ready_for_quotes=true` 상태다.
  - 판단: 2026-05-08 장전 자동 기동은 정상 작동했다. 실제 09:00 이후 분봉/feature 누적은 09:35 heartbeat에서 확인한다.
- 수익률 지표 정리:
  - 기존 `cumulative_net_return_pct`가 실제 계좌 수익률처럼 오해될 수 있어, research metric에 집계 방식 필드를 추가했다.
  - 추가 필드: `return_aggregation=sum_of_trade_pct_not_portfolio`, `trade_sum_gross_return_pct`, `trade_sum_net_return_pct`, `estimated_cost_drag_pct`, `portfolio_return_pct=null`, `portfolio_return_unavailable_reason`.
  - 기존 `cumulative_*` 필드는 하위 호환을 위해 유지한다.
  - 대시보드 문구는 `누적 순수익률` 대신 `거래합산 순수익률`, `비용 차감 합계`, `수익률 집계 방식`을 보여주도록 바꿨다.
- 판단:
  - `net=-170736%` 같은 값은 데이터 병합 오류의 직접 증거가 아니라, 거래별 퍼센트 손익을 다수 거래에 단순 합산한 진단값이다.
  - 다음 실험에서는 거래합산 수익률보다 비용 초과 평균 기대값과 거래 선별 능력을 우선한다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_research_pipeline tests.test_dashboard`: 17개 통과.

## [2026-05-08] Codex → 장전 운영 복구, gate reference 재생성, Cybos momentum 실험

- 운영 상태:
  - 확인 시각은 `2026-05-08 02:29 KST`였고 시장 상태는 `pre-open`이었다.
  - live runtime은 꺼져 있었지만 정규장 시작 60분 전이 아니므로 정상 범위로 판단했다.
  - runtime watchdog이 stale 상태여서 `./scripts/start_runtime_watchdog_background.sh`로 재기동했다.
  - 대시보드 서버도 stale 상태였으나 watchdog 재시작 뒤 `running`, `dashboard_responding=true`, `dashboard_api_responding=true`로 복구됐다.
  - 09:35 장중 수집 확인 heartbeat를 등록했다.
- 대시보드:
  - `python -m app --build-dashboard`를 실행해 최신 dashboard snapshot을 `2026-05-08T03:27:23.027323+09:00`로 갱신했다.
- 정본 gate walk-forward:
  - `python -m app --run-gate-walk-forward --horizon-min 15` 실행.
  - `parameter_profile=gate_reference_v1`, `command_source=cli_run_gate_walk_forward`, `feature_market_source=cybos-historical`.
  - 결과: `folds=118`, `rows_evaluated=5900000`, `trades_taken=1572715`, `overall_accuracy=0.416342`, `trade_hit_rate=0.125765`, `cumulative_net_return_pct=-170736.127782`.
  - 설정 provenance와 Cybos source 분리는 정상화됐지만, gate 성능 조건은 통과하지 못했다.
- challenger 재평가:
  - `python -m app --run-challengers --horizon-min 15` 실행.
  - `recommended_action=keep_active`, `walk_forward_gate_status=needs_review`.
  - 최신 LightGBM 후보는 `overall_accuracy=0.343409`, `trade_hit_rate=0.170136`, `cumulative_net_return_pct=-46489.671791`.
  - 이전의 LightGBM 0.92 수준 validation 과열은 사라졌고, 현재 challenger와 gate reference는 모두 부정적 방향으로 일관된다.
- 모델 개선 실험:
  - `bar_context_momentum` 피처셋으로 Cybos LightGBM 실험을 실행했다.
  - walk-forward 결과: `folds=12`, `rows_evaluated=600000`, `trades_taken=6666`, `overall_accuracy=0.535122`, `trade_hit_rate=0.282628`, `cumulative_gross_return_pct=529.484167`, `cumulative_net_return_pct=-190.443833`.
  - 판단: gross 기준 방향성은 일부 있으나 거래비용 `0.108%`를 넘지 못한다. 현재 병목은 비용을 초과하는 거래 선별 능력 부족이다.
- 다음:
  - 모델 승격은 보류한다.
  - 장중 수집이 실제로 09:00 이후 누적되는지 09:35 heartbeat에서 확인한다.
  - 다음 모델 실험은 비용 초과 기대값을 직접 기준으로 삼는 평가/학습 구조 또는 거래 빈도 억제 방향을 우선한다.

## [2026-05-08] Codex → WSL/D드라이브 경로 정리

- 환경 확인:
  - `C:` 여유 공간이 약 0.8GB, `D:` 여유 공간이 약 970GB로 확인됐다.
  - Ubuntu WSL2 배포판 BasePath가 `C:\Users\Keios\AppData\Local\wsl\{5043514c-aa32-4220-928c-802d47b0f90b}`로 확인됐다.
  - Windows Machine PATH에 오래된 `J:\Program Files\Git\Git\cmd`가 남아 있고, User PATH에는 없음을 확인했다.
- 조치:
  - `wsl --manage Ubuntu --move D:\WSL\Ubuntu`로 Ubuntu WSL2 배포판을 D드라이브로 이동했다.
  - 이동 후 BasePath가 `D:\WSL\Ubuntu`로 바뀐 것을 확인했고, WSL 기동 smoke test가 성공했다.
  - Machine PATH의 `J:\Program Files\Git\Git\cmd`는 사용자 관리자 PowerShell 조치 후 제거된 것으로 확인했다.
  - 현재 Codex 앱 프로세스는 제거 전 PATH를 물고 있어 이 세션 일부 `wsl` 실행에는 경고가 남을 수 있다. 새 PowerShell 또는 Codex 재시작 후에는 사라지는 상태로 판단한다.
  - 앞으로 Cybos 수집 임시 DB도 C드라이브가 아니라 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\cybos_collect.db`를 기본값으로 사용하도록 바꿨다.
  - `AGENTS.md`에 D드라이브 우선 정책을 명시했다. 2026-05-24 최신 기준에서는 캐시까지 포함해 Codex가 경로를 지정할 수 있는 모든 새 데이터 저장을 D드라이브로 제한한다.
- 변경:
  - `AGENTS.md`: WSL 배포판 위치 `D:\WSL\Ubuntu`, 대용량 작업 D드라이브 우선, `C:\Temp` 기본 사용 금지 규칙 추가.
  - `scripts/collect_cybos_historical.py`: 기본 `--db-path`를 D드라이브 데이터 경로로 변경.
  - `scripts/merge_cybos_to_main.sh`, `README.md`: 병합 예시를 `/mnt/d/CodexData/.../cybos_collect.db` 기준으로 갱신.
- 검증:
  - 이동 후 `C:` 여유 공간이 약 17GB로 회복됐다.
  - `python -m py_compile scripts/collect_cybos_historical.py` 통과.
  - `bash -n scripts/merge_cybos_to_main.sh scripts/run_gate_walk_forward_backtest.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 87개 통과.
  - `python -m app --build-dashboard`: `runtime-data/reports/dashboard/latest-dashboard.html`, `latest-dashboard.json` 생성 성공.

## [2026-05-07] Codex → WSL 자동 시작, Cybos feature 재빌드, gate reference 분리

- WSL 정본 자동 시작:
  - Windows 시작프로그램의 `RealTimeStockRuntime.cmd`, `GitAutoPushWatcher.cmd`가 예전 `D:\GitHub\Real-time-stock-price-prediction-program` 경로를 가리키던 것을 확인했다.
  - 두 런처를 현재 WSL 정본 저장소 `/home/keios/projects/Real-time-stock-price-prediction-program` 기준 `wsl.exe -d Ubuntu --cd ...` 명령으로 갱신했다.
  - WSL systemd user service는 이 환경에서 WSL 세션 불안정을 일으킬 수 있어 비활성화/삭제했다.
  - `install_runtime_startup_launcher.sh`, `install_git_autopush_startup_launcher.sh`는 Windows 시작프로그램을 사용할 수 있으면 systemd user service를 만들지 않고 Windows 런처만 갱신하도록 바꿨다.
  - 검증: `get_runtime_startup_launcher_status.sh` 결과 `installed=true`, `ok=true`, `windows_startup_launcher.ok=true`, systemd service `not-found`.
- Cybos feature/label:
  - 원인: 기존 feature builder가 호가 snapshot이 있는 분봉만 feature를 생성해, 호가가 없는 `cybos-historical` 15분봉 대부분이 학습 feature에 들어오지 못했다.
  - 조치: `source=cybos-historical` 분봉은 내부 synthetic orderbook으로 feature row를 만들고, 학습에서는 `mid_price`, `spread_bps`, `bid_ask_imbalance`를 제외한다.
  - `python -m app --build-feature-dataset` 실행 완료: `features_written=6386509`, `labels_written=11544717`.
  - 재확인: `feature_model_inputs=6386509`, `feature_labels=11544717`, labeled feature source 샘플은 `cybos-historical`.
- Gate reference:
  - walk-forward 리포트에 `parameter_profile`, `command_source`, `feature_market_source` provenance 를 남기도록 변경했다.
  - 정본 gate reference 전용 명령 `python -m app --run-gate-walk-forward --horizon-min 15`와 `scripts/run_gate_walk_forward_backtest.sh`를 추가했다.
  - gate 전용 경로는 `feature_market_source=cybos-historical`, `parameter_profile=gate_reference_v1`로 기록한다.
- 복구 메모:
  - 대용량 feature 재빌드 직후 WSL이 일시적으로 `Wsl/Service/E_UNEXPECTED` 상태가 되었고, Windows 재부팅 후 복구됐다.
  - 이후 systemd user service 대신 Windows 시작프로그램 런처를 주 자동 기동 경로로 둔다.

## [2026-05-07] Codex → walk-forward 생성 경로, challenger split, live 공백 원인 진단

- 정본 walk-forward 생성 경로:
  - `runtime-data/reports/backtests/latest-walk-forward-h15.json`은 `2026-05-06T20:08:51.772212+09:00`에 평가되고 `20:08:58 +0900`에 파일이 갱신됐다.
  - 현재 설정은 `min_train_rows=30`, `test_window_rows=10`, `step_rows=10`, `gap_rows=15`, `max_train_rows=200`이다.
  - `scripts/run_walk_forward_backtest.sh` 기본 경로는 `max_train_rows`를 넘기지 않고, `--rebuild-actual-ml` 경로는 `max_train_rows=40`을 쓴다.
  - 따라서 현재 정본 gate reference는 자동 post-close 산출물이 아니라, 2026-05-06 실험 E의 수동 명령 `--walk-forward-gap-rows 15 --walk-forward-max-train-rows 200`이 안정 경로를 덮어쓴 결과로 판단한다.
  - 후속 후보: walk-forward JSON에 생성 명령/parameter profile을 남기고, gate reference 전용 생성 경로를 분리한다.
- challenger 누수 진단:
  - 현재 코드의 split은 거래일 기준 tail 20% validation + horizon purge 구조다.
  - 정본 DB 기준 현재 15분 labeled dataset은 `343807` rows이며, train `262178` rows(`2021-01-04..2025-04-08`), validation `81629` rows(`2025-04-09..2026-05-06`)로 나뉜다.
  - train/validation `(symbol,event_time)` overlap은 `0`, 날짜 overlap도 `0`이다.
  - 최신 LightGBM candidate의 학습 run `train-lightgbm-h15-20260506200645749446`도 last train `2025-04-08T15:00:00+09:00`, first validation `2025-04-09T09:00:00+09:00`로 기록되어 직접 row leakage 증거는 없다.
  - 다만 LightGBM 학습 시 validation으로 쓰인 tail 구간과 challenger evaluation 구간이 사실상 같은 기간이라, challenger metric은 독립 out-of-sample 평가가 아니라 validation 재사용 평가로 취급한다.
  - 추가로 canonical labeled dataset source resolve 결과 `pykrx-daily-proxy=328429`, `cybos-historical=152`라서, 5년치 Cybos 병합 이후 기대한 `cybos-historical only` feature/label 상태가 아니다. 기준선 재측정 전 feature 재생성과 source resolve 점검이 필요하다.
- 2026-05-07 live runtime 공백:
  - 정본 DB의 2026-05-07 분봉/특징은 15:17~15:18의 20건뿐이다.
  - WSL 정본 로그에서 2026-05-07 첫 live runtime 연결은 `15:17:48`, KIS WebSocket 연결 성공은 `15:17:50`이다.
  - 현재 watchdog state의 `started_at`은 `2026-05-07 16:53:13 +0900`이라 장전/장중 자동 기동을 담당했다는 증거가 없다.
  - `get_runtime_startup_launcher_status.sh` 결과는 `installed=false`, `systemctl --user is-enabled stock-runtime-autoboot.service`는 `not-found`다.
  - 반면 오래된 local setup check에는 Windows 시작프로그램 런처가 `D:\GitHub\Real-time-stock-price-prediction-program`을 가리키던 기록이 남아 있다.
  - 결론: 저장소 이전 뒤 WSL 정본 기준 자동 시작 런처가 재설치되지 않은 것이 5/7 장중 공백의 1차 원인이다. 다음 조치는 WSL 정본을 대상으로 한 시작 런처 재설치/검증이다.

## [2026-05-07] Codex → 정본 gate reference와 장중 수집 공백 점검

- Cowork 검토 내용을 WSL2 정본 저장소 기준으로 다시 확인했다.
- 정본 `runtime-data/reports/backtests/latest-walk-forward-h15.json`은 `2026-05-06T20:08:51.772212+09:00`에 생성된 결과이며, 설정은 `min_train_rows=30`, `test_window_rows=10`, `step_rows=10`, `gap_rows=15`, `max_train_rows=200`이다.
- 해당 walk-forward 결과는 `folds=33284`, `overall_accuracy=0.380246`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`로 gate를 통과하지 못한다.
- 문제 해석:
  - 현재 gate 미통과는 맞다.
  - 다만 정본 gate reference가 5년치 데이터 승격 판단용으로는 지나치게 작은 학습창/검증창으로 만들어져 있어, 다음 조치는 gate 우회가 아니라 의미 있는 학습창의 정본 walk-forward를 다시 만드는 방향이어야 한다.
- 변경 전 challenger 정본 리포트의 `latest_lightgbm`은 accuracy `0.921672`, net `+2026.652123`로 보였지만, 같은 정본의 walk-forward와 격차가 커서 승격 근거로 쓰지 않는다. tail validation 평가 편향 또는 데이터 누수 의심 대상으로 기록한다.
- 코드 변경 뒤 `python -m app --run-challengers --horizon-min 15`를 재실행해 최신 challenger 리포트를 `2026-05-07T20:30:09.309909+09:00`로 갱신했다.
  - best candidate: `linear_score_builtin`
  - accuracy `0.510456`, trade_hit_rate `0.491738`, net `+359.201116`, trades `1755`
  - `latest_lightgbm`: accuracy `0.534479`, trade_hit_rate `0.244785`, net `-723.208906`, trades `18265`
  - recommended_action: `review_required`
  - decision_reason: `Walk-forward setup needs review (...)`
- 2026-05-07 장중 데이터:
  - 정본 DB 기준 분봉/특징은 15:17~15:18의 20건뿐이다.
  - label 0건은 해당 시각의 15분 horizon이 장마감 이후로 넘어가므로 정상이다.
  - 실제 문제는 live runtime이 09:00~15:16에 켜져 있지 않았던 공백이다.
- 변경:
  - walk-forward gate 판정에 설정 점검 사유를 추가했다. 작은 학습창/검증창 또는 과도한 fold 수는 기준 완화 없이 `needs_review`로 표시된다.
  - 대시보드에 `게이트 기준 워크포워드` 카드를 추가해 정본 gate reference와 post-close snapshot 산출물을 분리해서 볼 수 있게 했다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py`
  - `python -m unittest tests.test_dashboard`: 13개 통과
  - `python -m unittest tests.test_research_pipeline`: 3개 통과
  - `python -m app --run-challengers --horizon-min 15`
  - `python -m app --build-dashboard`: `2026-05-07T20:33:54.440248+09:00`

## [2026-05-07] Codex → post-close snapshot ML 완료 확인과 wide walk-forward 재측정

- 확인 내용:
  - `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json` 상태가 `ok`로 바뀐 것을 확인했다.
  - 완료 시각은 `2026-05-07 19:14:42 +0900`이다.
  - snapshot DB는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260507-165315.db`이고, snapshot runtime 은 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/post-close-20260507-h15/runtime-data`이다.
- 대시보드:
  - `python -m app --build-dashboard`를 다시 실행해 `runtime-data/reports/dashboard/latest-dashboard.html`과 `.json`을 갱신했다.
  - 생성 시각은 `2026-05-07T19:21:42.344608+09:00`이다.
  - `장후 자동 학습 상태` 카드에 `status=ok`, 완료 시각, snapshot DB/runtime 경로가 표시되는 것을 확인했다.
- 데이터 진단:
  - snapshot DB에는 KIS WebSocket 기반 raw market ticks `2,194,180`, raw orderbook ticks `1,703,559`, curated minute bars/features `10,655`가 있다.
  - 15분 라벨은 `10,246`, 60분 라벨은 `9,016`이다.
  - `2026-05-07` 데이터는 15:17~15:18의 20개 분봉뿐이라 아직 15분 라벨로 닫히지 않았다.
- 모델 개선 실험:
  - 기본 post-close walk-forward 는 `min_train_rows=30`, `max_train_rows=40`이라 승격 판단용으로 너무 짧다.
  - 별도 runtime 에서 wide walk-forward sanity 를 실행했다.
  - 명령 설정: `min_train_rows=3000`, `test_rows=500`, `step_rows=500`, `gap_rows=15`, `max_train_rows=8000`
  - 결과: `folds=14`, `rows_evaluated=7000`, `trades_taken=1495`, `overall_accuracy=0.266857`, `trade_hit_rate=0.138462`, `cumulative_net_return_pct=-262.298425`
- 판단:
  - 오늘 post-close 실제 KIS 데이터 기반 모델은 승격하지 않는다.
  - 다음 개선은 단순 파라미터 조정보다 장중 데이터 누적, 라벨 닫힘률 개선, snapshot actual-ML 지표를 대시보드에 별도 표시하는 작업이 우선이다.

## [2026-05-07] Codex → 대시보드 장후 자동 학습 상태 표시

- 변경 파일:
  - `app/services/dashboard.py`
  - `tests/test_dashboard.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - 대시보드 `머신러닝 현황 > 현재 운용` 화면에 `장후 자동 학습 상태` 카드를 추가했다.
  - 이 카드는 `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`의 상태, 기준일, 시작/완료 시각, 실행 모드, horizon, pid, snapshot DB, snapshot runtime, stdout/stderr 로그, 오류 메시지를 보여준다.
  - 장중 수집과 연구/학습 snapshot 트랙이 분리되어 있으므로, 사용자가 터미널 로그를 직접 열지 않아도 장후 자동 학습 진행 여부를 대시보드에서 확인할 수 있다.
- 모델 개선 병행:
  - watchdog 이 시작한 post-close snapshot 재학습을 유지한다.
  - 현재 실행 중인 무거운 재학습과 DB snapshot 작업을 방해하지 않기 위해 추가 중복 학습은 시작하지 않고, 완료 상태와 산출물 확인을 다음 연결점으로 둔다.
- 검증:
  - `python -m py_compile app/services/dashboard.py`
  - `python -m unittest tests.test_dashboard`: 13개 통과
  - `python -m unittest discover -s tests -p "test_*.py"`: 86개 통과
  - `git diff --check`
  - `python -m app --build-dashboard`: post-close snapshot 재학습 진행 중 180초 제한 내 미완료. 재학습 완료 후 실제 dashboard snapshot 재생성을 다시 확인한다.

## [2026-05-07] Codex → 장마감 후 자동 snapshot ML maintenance 연결

- 변경 파일:
  - `AGENTS.md`
  - `scripts/script_dispatch.sh`
  - `scripts/wsl_ops.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - 사용자 수동 작업은 Codex가 물리적으로 처리할 수 없는 필수 작업만 안내한다는 원칙을 `AGENTS.md`에 기록했다.
  - `run_post_close_ml_maintenance.sh` 기본 실행을 snapshot DB 기준으로 바꿨다.
  - snapshot DB에서 `--rebuild-actual-ml`, runtime report, dashboard build 를 실행하고, main state 파일에는 snapshot 경로와 별도 runtime output 경로를 남긴다.
  - runtime watchdog 이 post-close 상태에서 장마감 후 기본 30분이 지나면 하루 한 번 장후 ML maintenance 를 백그라운드로 시작하도록 했다.
  - 자동 학습은 active model 자동 교체와 실전 주문 승격을 하지 않는다.
- 검증:
  - `python -m py_compile scripts/wsl_ops.py`
  - `bash -n scripts/script_dispatch.sh`
  - `bash -n scripts/run_post_close_ml_maintenance.sh`
  - `python scripts/wsl_ops.py run-watchdog-loop --single-pass --disable-post-close-ml`
  - `python -m unittest discover -s tests -p "test_*.py"`: 86개 통과
- 운영 참고:
  - 검증 중 임시 runtime 으로 뜬 dashboard 프로세스는 중지했다.
  - 실제 watchdog 재시작은 검증과 커밋 뒤 현재 WSL2 저장소 기준으로 다시 수행한다.

## [2026-05-07] Codex → 투트랙 장중 수집 + 연구 스냅샷 운영

- 변경 파일:
  - `scripts/create_research_db_snapshot.sh`
  - `scripts/run_research_on_snapshot.sh`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - 장중 `수집 트랙`과 오프라인 `연구 트랙`을 명시적으로 분리했다.
  - live runtime/watchdog 은 계속 `runtime-data/dev.db`에 장중 KIS 체결/호가를 적재한다.
  - 연구/학습은 SQLite backup API로 만든 snapshot DB를 `DATABASE_URL`로 지정해 실행한다.
  - 기본 snapshot / research run 보관 위치는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 아래로 둔다. 2026-05-24 최신 기준에서는 D드라이브 경로를 사용할 수 없으면 새 다운로드, 캐시, 대용량 실험을 시작하지 않는다.
  - `scripts/run_research_on_snapshot.sh -- python -m app ...` 형태로 기존 연구 명령을 live DB lock 없이 실행할 수 있게 했다.
- 검증:
  - `bash -n scripts/create_research_db_snapshot.sh`
  - `bash -n scripts/run_research_on_snapshot.sh`
  - `.tmp-tests/two-track/live.db` 기준 snapshot smoke test
  - snapshot runner의 `DATABASE_URL` / `RUNTIME_DATA_DIR` 환경 주입 smoke test
- 판단:
  - 앞으로 장중에는 수집 안정성을 우선하고, 무거운 ML/룰 실험은 snapshot DB와 격리된 runtime output에서 실행한다.
  - 수집 트랙을 끄고 실험하는 방식은 기본 운영 방식에서 제외한다.

## [2026-05-07] Codex → 궁극 운영 목표 문서화와 G-1 룰 기반 challenger

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `scripts/wsl_ops.py`
  - `tests/test_research_pipeline.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - README와 Current Implementation에 궁극 운영 목표를 명시했다.
  - 목표는 `데이터 수집 -> 전략 후보 생성 -> 비용/슬리피지/세금 반영 검증 -> walk-forward 검증 -> paper 운용 -> 소액 실전 검증 -> 리스크 제한 운용 -> 일일 분석 -> 승격/폐기`가 반복되는 로컬 투자 연구·운영 시스템으로 정리했다.
  - 월 누적 `+50%`는 장기 stretch target 으로 기록하되, 보장 수익률이나 즉시 실전 운용 기준은 아니라고 명시했다.
  - 장중 데이터 수집은 ML/룰 실험과 분리된 background live runtime/watchdog 축으로 유지하고, 코스피200 Cybos 갱신은 장후 Windows 배치 + WSL 병합 흐름으로 분리한다고 문서화했다.
  - `--run-cybos-rule-challengers` CLI를 추가해 고정 long-only 룰 후보 5개를 비용 반영 walk-forward로 비교하도록 했다.
  - watchdog 상태 조회가 실제 `wsl_ops.py run-watchdog-loop` 프로세스를 `stale`로 오판하지 않도록 보강했다.
- 장중 수집 점검:
  - `2026-05-07 15:17` 현재 WSL2 저장소 기준으로 live runtime과 runtime watchdog을 재기동했다.
  - KIS WebSocket 연결 로그를 확인했다.
  - `15:30` 장마감 이후 상태는 `post-close`이며 watchdog의 `off_session_hold_post-close`가 정상 동작이다.
- G-1 실행 결과:
  - 실행 명령: `python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13`
  - `quiet_breakout`: `trades=669`, `trade_hit_rate=0.070254`, `net=-106.838776`
  - `opening_momentum`: `trades=1884`, `trade_hit_rate=0.242569`, `net=-201.657683`
  - `pullback_bounce`: `trades=6144`, `trade_hit_rate=0.148438`, `net=-855.823355`
  - `momentum_follow`: `trades=8607`, `trade_hit_rate=0.149065`, `net=-1174.643028`
  - `range_expansion`: `trades=11810`, `trade_hit_rate=0.168417`, `net=-1642.290757`
- 판단:
  - 고정 룰 challenger 5개 모두 비용 반영 기준에서 음수이므로 자동 승격하지 않는다.
  - 다음 연구 방향은 KIS 호가 데이터 누적 기반 피처 검증 또는 더 엄격한 기간 분리/시장상태 기준 실험으로 분리한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-rule-challengers-review.json`
  - `runtime-data/reports/backtests/latest-cybos-rule-challengers-review.md`

## [2026-05-07] Codex → F-6b threshold 0.20 재현성 검증

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 연구 경로에 `--run-cybos-label-reproducibility-review` CLI를 추가했다.
  - F-6에서 유일하게 양수였던 `threshold=0.20`을 자동 채택하지 않고, fold 설계와 기간 샘플을 바꿔 재현성을 확인하도록 했다.
  - 기본 F-6 fold, 더 촘촘한 step, 짧은 학습창, 2021~2023 샘플, 2024~2026 샘플을 같은 비용 0.13% 기준으로 비교했다.
- 실행 결과:
  - `f6_baseline`: `trades=44`, `trade_hit_rate=0.545455`, `net=+3.577014%`
  - `denser_step`: `trades=46`, `trade_hit_rate=0.565217`, `net=+3.706487%`
  - `shorter_train`: `trades=109`, `trade_hit_rate=0.339450`, `net=-11.557602%`
  - `early_2021_2023_sample`: `trades=78`, `trade_hit_rate=0.269231`, `net=-5.929057%`
  - `recent_2024_2026_sample`: `trades=70`, `trade_hit_rate=0.442857`, `net=-2.350204%`
- 거래 원장 참고:
  - baseline 맞춘 거래 평균 gross `0.754928%`
  - baseline 틀린 거래 평균 gross `-0.441063%`
  - 양수 결과는 fold 설계 일부에서만 나타나며 기간 샘플 분리에서는 재현되지 않았다.
- 판단:
  - `threshold=0.20`은 재현성 부족으로 채택하지 않는다.
  - Cybos 15분 bar-only ML의 threshold 튜닝은 우선순위를 낮추고, 다음은 룰 기반 challenger 또는 KIS 호가 데이터 누적 후 호가 피처 검증으로 분리한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-label-reproducibility-review.json`
  - `runtime-data/reports/backtests/latest-cybos-label-reproducibility-review.md`

## [2026-05-07] Codex → F-6 라벨 민감도 진단

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 연구 경로에 `--run-cybos-label-sensitivity-review` CLI를 추가했다.
  - F-6은 threshold 선택/승격 실험이 아니라 라벨 민감도 진단으로 구현했다.
  - threshold grid는 실행 전 고정값 `[0.13, 0.20, 0.35, 0.50]`로 두고, 현재 설정값 `0.35`를 포함했다.
  - threshold별 전체 up/down 라벨 수, walk-forward 거래 수, hit-rate, 비용 0.13% 반영 순수익률, `trades < 30` 신뢰 낮음 표시를 리포트에 남겼다.
- 사전 확인:
  - 실제 로딩된 `label_threshold_15=0.35%`
  - 왕복 비용 기준 `0.13%`
  - 현재 threshold는 비용보다 높아, 현 설정 자체가 비용 미만 움직임을 학습하는 구조라고 보기는 어렵다.
- 실행 결과:
  - threshold `0.13`: `trades=25`, `trade_hit_rate=0.480000`, `net=-1.724058%`, `신뢰 낮음`
  - threshold `0.20`: `trades=44`, `trade_hit_rate=0.545455`, `net=+3.577014%`
  - threshold `0.35`: `trades=57`, `trade_hit_rate=0.333333`, `net=-1.413583%`
  - threshold `0.50`: `trades=77`, `trade_hit_rate=0.181818`, `net=-18.729151%`
- 판단:
  - `0.20` 하나만 양수이고 여러 threshold에서 일관된 양수 패턴이 아니다.
  - threshold를 자동 채택하지 않고 `채택 보류, 과최적화 의심`으로 기록한다.
  - 다음 검증은 별도 기간/다른 fold 설계 또는 룰 기반 challenger와 비교하는 방식으로 분리한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-label-sensitivity-review.json`
  - `runtime-data/reports/backtests/latest-cybos-label-sensitivity-review.md`

## [2026-05-07] Codex → F-5 손익 진단과 비용 반영 재평가

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 연구 경로에 `--run-cybos-profitability-review` CLI를 추가했다.
  - F-5 walk-forward 거래 원장, 종목/시간대/confidence 구간별 손익 진단, 비용 재계산, train-only confidence threshold, H60 bar-only 비교를 한 번에 남기도록 했다.
  - threshold 실험은 사전 고정 grid `[0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.75, 0.80]`만 사용하고, 각 fold의 train calibration 구간에서만 선택한 뒤 test에 적용했다.
  - 수동 시간대/종목 제외 필터는 과최적화 위험 때문에 만들지 않았다.
- 실행 결과:
  - F-5 재현: `trades=57`, `overall_accuracy=0.580310`, `trade_hit_rate=0.333333`, `gross=+5.996417%`
  - F-5 기존 비용 0.108% net: `-0.159583%`
  - F-5 요청 비용 0.13% net: `-1.413583%`
  - F-5 구조 가설: 소수 거래와 비용 민감도가 핵심이며, confidence가 수익 거래를 안정적으로 분리하지 못함.
  - train-only threshold: `trades=55`, `trade_hit_rate=0.327273`, `net=-2.295251%`
  - H60 bar-only walk-forward: `trades=112`, `overall_accuracy=0.587108`, `trade_hit_rate=0.187500`, `net=-60.233578%`
- 판단:
  - F-5는 실전 비용 기준으로 손익분기라 보기 어렵다.
  - threshold 보정과 60분 horizon 전환 모두 개선이 아니었다.
  - 다음 실험은 단순 confidence 조정보다 새로운 정보가 있는 피처 또는 데이터 품질 개선 쪽이 필요하다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-profitability-review.json`
  - `runtime-data/reports/backtests/latest-cybos-profitability-review.md`

## [2026-05-07] Codex → F-5 이후 수익 양수화 실험

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 실험 CLI에 `--cybos-experiment-feature-set`을 추가해 `bar_only`, `bar_context`, `bar_context_momentum` 피처 세트를 선택할 수 있게 했다.
  - `bar_context`는 `close_position_pct`, `minute_slot_pct`, `log_volume`을 추가한다.
  - `bar_context_momentum`은 여기에 `prev_return_pct`, `prev_hl_range_pct`, `log_volume_delta`를 추가한다.
  - 기존 F-1/F-5 계열 `bar_only` 피처는 유지했다.
- 실험 결과:
  - F-2 `bar_context`, `train_rows=20000`: walk-forward accuracy `0.559345`, trade_hit_rate `0.240113`, net `-84.717904`
  - F-3 `bar_context_momentum`, `train_rows=20000`: walk-forward accuracy `0.569643`, trade_hit_rate `0.255112`, net `-113.966154`
  - F-4 `bar_only`, `train_rows=50000`: walk-forward accuracy `0.575857`, trade_hit_rate `0.303030`, net `-16.066645`
  - F-5 `bar_only`, `train_rows=100000`: walk-forward accuracy `0.580310`, trade_hit_rate `0.333333`, net `-0.159583`
  - F-6 `bar_only`, `train_rows=200000`: walk-forward accuracy `0.575893`, trade_hit_rate `0.208333`, net `-4.788923`
  - F-7 `bar_only`, `train_rows=100000`, `LABEL_THRESHOLD_15=0.40`: walk-forward accuracy `0.615464`, trade_hit_rate `0.204082`, net `-8.857048`
  - F-8 `bar_only`, `train_rows=100000`, `LABEL_THRESHOLD_15=0.33`: walk-forward accuracy `0.564798`, trade_hit_rate `0.383333`, net `-3.785540`
- 판단:
  - 완료 조건인 `trade_hit_rate >= 0.3`과 `cumulative_net_return_pct > 0`을 동시에 만족한 실험은 아직 없다.
  - F-5가 현재 최고 후보이며 순수익률은 손익분기 근처지만 여전히 음수다.
  - F-6/F-7/F-8이 모두 F-5 수익률을 넘지 못해 `3회 연속 개선 없음` 조건에 도달했다.
  - 자율 진행을 멈추고 운영자 판단을 요청한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-bar-only-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-bar-context-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-bar-context-momentum-h15.json`
  - `runtime-data/ml/models/lightgbm-cybos-bar-only-h15-v1.joblib`
  - `runtime-data/ml/models/lightgbm-cybos-bar-context-h15-v1.joblib`
  - `runtime-data/ml/models/lightgbm-cybos-bar-context-momentum-h15-v1.joblib`

## [2026-05-07] Codex → ML 실험 자율 범위 추가와 Cybos bar-only F-1 기준선

- 변경 파일:
  - `AGENTS.md`
  - `app/__main__.py`
  - `app/services/research.py`
  - `app/storage/sqlite_store.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `AGENTS.md`의 `7. 운영 안전 규칙` 아래에 `7-1. ML 실험 자율 범위`를 추가했다.
  - ML 실험에 한해 피처 조합, split, 학습 파라미터, 하이퍼파라미터, 재실험 방향을 Codex가 자율 판단할 수 있도록 기준을 명시했다.
  - 운영자 판단이 필요한 조건은 `3회 연속 개선 없음`, 완료 조건 충족, 데이터 소스 추가/변경, 스프린트 목표 변경, `app/risk/` 변경, `scripts/` 구조 변경으로 구분했다.
  - `source=cybos-historical`만 조회하는 SQLite helper와 Cybos bar-only LightGBM 실험 CLI `--run-cybos-bar-only-experiment`를 추가했다.
  - Cybos 과거 데이터에는 호가가 없으므로 `mid_price`, `spread_bps`, `bid_ask_imbalance`는 제외하고 `avg_trade_size`, `hl_range_pct`, `return_1m_pct`만 사용했다.
  - `pykrx-daily-proxy`, `kis-ws`, `kis-rest-historical`, `synthetic` 데이터는 F-1 학습/평가에서 제외했다.
- 데이터셋:
  - source: `cybos-historical`
  - symbols: `199`
  - source_rows: `6283279`
  - labeled_rows: `6040981`
  - 기간: `2021-03-30T09:15:00+09:00..2026-05-04T15:15:00+09:00`
  - label distribution: `flat=4437376`, `down=805811`, `up=797794`
- 실험 결과:
  - F-1 `train_rows=2000`: validation `0.473329`, walk-forward accuracy `0.546787`, trade_hit_rate `0.217913`, net `-1041.554842`
  - F-1b `train_rows=10000`: validation `0.487424`, walk-forward accuracy `0.563363`, trade_hit_rate `0.282515`, net `-27.799564`
  - F-1c `train_rows=20000`: validation `0.506736`, walk-forward accuracy `0.576262`, trade_hit_rate `0.284987`, net `-25.134498`
  - F-1c feature importance: `avg_trade_size=2795`, `hl_range_pct=2401`, `return_1m_pct=2015`
- 판단:
  - validation accuracy가 `0.6` 이하로 내려와 proxy 누수성 과대평가는 해소된 상태로 본다.
  - walk-forward `trade_hit_rate`가 최고 `0.284987`로 완료 기준 `0.3`에는 아직 못 미친다.
  - F-1 -> F-1b -> F-1c 순서로 개선이 있어 `3회 연속 개선 없음` 보고 조건은 아니다.
  - 다음 자율 실험 방향은 데이터 소스나 risk/gate 변경 없이 `close_position_pct`, `minute_slot`, `log_volume` 같은 bar-context 피처를 추가하는 것이다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.md`
  - `runtime-data/ml/models/lightgbm-cybos-bar-only-h15-v1.joblib`

## [2026-05-07] Codex → 스프린트 04 재시작 전 Cybos 학습 가능성 점검

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 5년치 실제 15분봉 병합 후 `python -m app --build-feature-dataset`를 재실행했다.
  - feature 재생성 결과는 `features_written=356970`, `labels_written=647510`, horizons `15, 60` 이었다.
  - main DB의 `raw_market_ticks` 기준 `cybos-historical`은 199종목 `6283279`행, `kis-ws`는 10종목 `3054451`행이다.
  - `raw_orderbook_ticks` 기준 `cybos-historical`은 0행이고, `kis-ws`는 `2245513`행, `pykrx-daily-proxy`는 `332228`행이다.
  - H15 labeled feature row는 전체 `343807`행이고, market source 기준 `cybos-historical` row는 `243993`행이지만 호가 source는 대부분 proxy다.
  - 실험 F의 조건인 `spread_bps`, `bid_ask_imbalance`를 Cybos 실제 호가 피처로 포함하는 조건이 현재 DB로 충족되지 않아 학습/챌린저/walk-forward 실행은 보류했다.
- 실행 명령:
  ```bash
  python -m app --build-feature-dataset
  git diff --check -- docs/STATUS.md docs/logbook.md
  ```
- 확인 결과:
  - H15 label distribution: `flat=258339`, `up=42591`, `down=42877`
  - `git diff --check`: `ok`

## [2026-05-07] Codex → 외부 수집 데이터 D드라이브 보관 기준 정리

- 변경 파일:
  - `AGENTS.md`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - 앞으로 이 저장소 작업 중 새로 내려받거나 수집하는 대용량 외부 데이터는 기존 `D:\GitHub\Real-time-stock-price-prediction-program` 폴더가 아니라 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래에 보관하도록 기준을 추가했다.
  - WSL2 접근 경로는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 로 기록했다.
  - `C:\Temp\cybos_collect.db`는 병합 스크립트가 `--src` DB를 삭제하므로, 병합용 원본은 유지하고 보관본을 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\cybos_collect_20260507.db`로 복사했다.
  - `C:\Temp\cybos_collect.db`와 D드라이브 보관본 크기가 모두 `1373368320` bytes 임을 확인했다.
  - `C:\Temp\cybos_collect.db` 내용 확인 결과 `source=cybos-historical`, 유효 종목 `199`개, `raw_market_ticks=6283279`, `curated_minute_bars=6283279`, 범위 `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00` 로 수집되어 있었다.
  - 종목별 row 수는 최소 `7826`, 최대 `32451`, 평균 `31574.27`개였다. 일부 신규상장/편입 종목은 시작일이 늦어 row 수가 짧다.
  - main DB는 아직 기존 삼성전자 병합분만 반영된 상태로, `raw_market_ticks WHERE source='cybos-historical'` 기준 `1`종목 `32451`행이다.
  - Cybos 병합 명령은 현재 작업 위치와 무관하게 실행되도록 절대 스크립트 경로 형태를 기준으로 정리했다.
- 기준 병합 명령:
  ```bash
  bash ~/projects/Real-time-stock-price-prediction-program/scripts/merge_cybos_to_main.sh \
    --src /mnt/c/Temp/cybos_collect.db \
    --dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db
  ```
- 검증:
  - `git diff --check`: `ok`

## [2026-05-07] Codex → Cybos 코스피200 코드 필터 보강

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - `CpUtil.CpCodeMgr.GetGroupCodeList(180)` 결과에 `A0126Z0` 같은 비주식 코드가 섞일 때 수집기가 fatal 로 중단되는 문제를 수정했다.
  - Cybos 그룹 조회 결과는 `A` 접두어를 제거한 뒤 정규식 `^[0-9]{6}$`에 맞는 종목 코드만 사용한다.
  - 필터링 후 `코스피200 유효 종목: N개`를 출력하고, 제외한 잘못된 코드는 개수와 일부 샘플만 출력한 뒤 계속 진행한다.
- 실행 명령:
  ```bash
  python -m py_compile scripts/collect_cybos_historical.py
  python - <<'PY'
  from scripts.collect_cybos_historical import load_kospi200_symbols
  class CodeMgr:
      def GetGroupCodeList(self, group_code):
          return ["A005930", "A0126Z0", "000660", "101S12", "005930"]
  print(load_kospi200_symbols(CodeMgr(), group_code=180))
  PY
  git diff --check
  python -m unittest discover -s tests -p "test_*.py"
  ```
- 확인 결과:
  - 문법 검사: `ok`
  - 필터 smoke test: `A005930`, `000660`, 중복 `005930`은 유효 종목 2개로 정규화하고 `A0126Z0`, `101S12`는 제외
  - 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 18.052s`, `OK`

## [2026-05-07] Codex → Cybos 삼성전자 15분봉 실제 수집과 병합

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - 실제 실행에서 기본 365일 chunk 요청이 Cybos `StockChart` 행 수 제한에 걸려 앞구간이 잘리는 것을 확인했다.
  - 수집기 기본 `--chunk-days`를 60일로 낮춰 긴 기간 요청 시 row cap에 걸릴 가능성을 줄였다.
  - 삼성전자 실제 수집/병합 결과와 Cybos가 반환하지 않은 초기 구간을 문서화했다.
- 실행 명령:
  ```powershell
  E:\Users\Keios\AppData\Local\Programs\Python\Python311-32\python.exe `
    scripts\collect_cybos_historical.py `
    --symbols 005930 --start 2021-01-04 --chunk-days 60 --force
  ```
  ```bash
  bash scripts/merge_cybos_to_main.sh \
    --src /mnt/c/Temp/cybos_collect.db \
    --dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db
  ```
- 확인 결과:
  - 관리자 권한 PowerShell 실행: `status=ok`, `bars_written=32451`, `requests=33`
  - 수집 범위: `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00`
  - 병합 결과: `raw_market_ticks_merged=32451`, `curated_minute_bars_merged=32451`
  - main DB 확인: `source=cybos-historical`, `symbol=005930`, `rows=32451`
  - `C:\Temp\cybos_collect.db`와 sidecar 파일 삭제 확인
  - `2021-01-04..2021-03-29` 구간은 15일 단위로 재시도했지만 Cybos가 모두 `raw_rows=0`을 반환했다.
  - 문법 검사, bash 파싱 검사, 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 12.883s`, `OK`

## [2026-05-07] Codex → Cybos 수집 DB 로컬화와 WSL 병합 스크립트

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `scripts/merge_cybos_to_main.sh`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - Windows 에서 WSL2 UNC 경로 SQLite DB를 직접 열 때 `database is locked`가 날 수 있어, Cybos 수집 기본 DB를 `C:\Temp\cybos_collect.db`로 바꿨다.
  - 수집 DB의 parent 폴더가 없으면 자동 생성하도록 했다.
  - 수집 완료 후 WSL2에서 main runtime DB로 병합하는 `scripts/merge_cybos_to_main.sh`를 추가했다.
  - 병합 스크립트는 `raw_market_ticks`의 동일 `(symbol,event_time,source)` 행을 교체하고, `curated_minute_bars`는 기존 기본키로 upsert 한다.
  - 병합 성공 뒤 `/mnt/c/Temp/cybos_collect.db` 같은 source DB 파일을 삭제한다.
- 실행 명령:
  ```bash
  python -m py_compile scripts/collect_cybos_historical.py
  bash -n scripts/merge_cybos_to_main.sh
  bash scripts/merge_cybos_to_main.sh --src .tmp-tests/cybos-merge/src.db --dst .tmp-tests/cybos-merge/dst.db
  git diff --check
  python -m unittest discover -s tests -p "test_*.py"
  ```
- 확인 결과:
  - 문법 검사: `ok`
  - bash 파싱 검사: `ok`
  - 병합 smoke test: `merge_smoke_ok`, `raw_rows=1`, `bar_rows=1`, source DB와 sidecar 삭제 확인
  - 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 12.671s`, `OK`

## [2026-05-06] Codex → Cybos Plus 15분봉 수집 스크립트 추가

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - Windows 32bit Python 전용 Cybos Plus `CpSysDib.StockChart` 15분봉 수집 스크립트를 추가했다.
  - 코스피200 전체 수집 시 `CpUtil.CpCodeMgr.GetGroupCodeList(180)`로 구성 종목을 동적으로 조회하도록 했다.
  - `raw_market_ticks`에는 `source=cybos-historical`로 저장하고, `curated_minute_bars`에는 기존 `(symbol, bar_time)` 기본키 구조 그대로 `INSERT OR REPLACE`로 적재한다.
  - Cybos 조회 제한을 초당 15회 이하로 맞추고, 종목별 실패는 다음 종목으로 넘어가도록 했다.
  - 재실행 시 `raw_market_ticks`의 기존 `cybos-historical` 범위가 요청 구간을 이미 덮으면 해당 종목을 skip한다.
- 실행 명령:
  ```bash
  python -m py_compile scripts/collect_cybos_historical.py
  git diff --check
  python -m unittest discover -s tests -p "test_*.py"
  ```
  ```powershell
  E:\Users\Keios\AppData\Local\Programs\Python\Python311-32\python.exe `
    scripts\collect_cybos_historical.py `
    --symbols 005930 --start 2021-01-04
  ```
- 확인 결과:
  - 문법 검사: `ok`
  - 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 18.452s`, `OK`
  - Windows 32bit Python 실행: 스크립트 진입은 확인했으나 `CpCybos.IsConnect == 0`으로 실패
  - 오류 메시지: `fatal: Cybos Plus is not connected. Log in to Cybos Plus, then rerun this script.`
  - Cybos Plus가 로그인/연결되지 않아 삼성전자 `bars_written`과 기간 범위는 아직 확인하지 못했다.

## [2026-05-06] Codex → WSL2 git-autopush watcher 전환

- 변경 파일:
  - `scripts/wsl_ops.py`
  - `README.md`
  - `docs/Versioning.md`
  - `docs/logbook.md`
- 변경 내용:
  - WSL2 watcher의 push 단계에서 WSL `git push`가 GitHub HTTPS 인증 실패로 멈추지 않도록 `GIT_TERMINAL_PROMPT=0`을 적용했다.
  - WSL push가 실패하면 Windows GitHub Desktop의 `git.exe`와 저장된 자격 증명으로 같은 WSL 작업 폴더를 push하는 fallback을 추가했다.
  - watcher 기준 `ScanRoot`를 현재 WSL2 저장소 root로 실행하는 기준을 문서화했다.
  - 이전 WSL 인증 실패로 남아 있던 `git push origin main` 잔여 프로세스를 종료했다.
- 실행 명령:
  ```bash
  # git_push fallback smoke test는 scripts/wsl_ops.py의 git_push()를 직접 호출
  python -m py_compile scripts/wsl_ops.py
  python -m unittest discover -s tests -p "test_*.py"
  ./scripts/test_git_autopush_watcher.sh
  ```
- 확인 결과:
  - Windows GitHub Desktop Git fallback smoke test: `git_push_ok`
  - 단위 테스트: `Ran 85 tests in 12.860s`, `OK`
  - autopush watcher 자체 테스트: `git autopush watcher test passed`
  - watcher 상태: `healthy=true`, `watcher_pids=[92294]`, `managed_repo_count=1`
  - 상태 파일 기준 `scan_root=/home/keios/projects/Real-time-stock-price-prediction-program`
  - 자동 커밋/푸쉬 watcher는 더 이상 `D:\GitHub`가 아니라 현재 WSL2 저장소 기준 상태 파일을 갱신한다.
  - 자동화 정책은 기존처럼 `VERSION` 변경을 트리거로 사용한다.

## [2026-05-06] Codex → 스프린트 04 실험 E 일봉 단위 split

- 변경 파일:
  - `app/services/research.py`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - train/validation split을 행 단위 tail 80/20에서 거래일 단위 tail 80/20로 변경했다.
  - 같은 날짜 row가 train과 validation에 동시에 들어가지 않도록 했고, horizon purge는 validation 시작 시각 기준으로 유지했다.
  - 작은 synthetic fixture에서 날짜 split 또는 purge 후 `down/flat/up` 라벨 구성이 깨질 때만 row-level fallback을 사용하도록 했다.
  - proxy 포함 학습셋 feature list는 실험 B/D 상태 그대로 `avg_trade_size`, `hl_range_pct`, `return_1m_pct`를 유지했다.
- 실행 명령:
  ```bash
  python -m py_compile app/services/research.py
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
  python -m app --run-challengers --horizon-min 15
  ```
- 확인 결과:
  - 단위 테스트: `Ran 85 tests in 11.904s`, `OK`
  - split: `trade_date_tail_20pct`, train `2025-04-08`까지, validation `2025-04-09`부터, 날짜 overlap `0`
  - LightGBM: `train_rows=254350`, `validation_rows=78542`, `validation_accuracy=0.921672`, `trades_taken=5911`, `trade_hit_rate=0.870919`, `cumulative_net_return_pct=2026.652123`
  - walk-forward: `folds=33284`, `rows_evaluated=332840`, `overall_accuracy=0.380246`, `trades_taken=111223`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`
  - challenger 최종 판단: `review_required`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
- 판단:
  - validation_accuracy가 `0.7` 이하로 떨어지지 않았으므로, 기존 `0.912`가 같은 날짜 train/validation 혼입 때문이었다는 가설은 확인되지 않았다.
  - walk-forward trade_hit_rate가 `0.3` 이상으로 오르지 않아 실전 방향성 개선도 확인되지 않았다.
  - 다음 단계는 proxy 15분 라벨 자체를 제외하거나 실제 KIS 분봉 기반 검증을 분리하는 쪽이 우선이다.

## [2026-05-06] Codex → 스프린트 04 긴급 누수 점검과 실험 B/D

- 변경 파일:
  - `app/services/research.py`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `pykrx-daily-proxy` 라벨이 같은 일봉 OHLC에서 보간된 현재 proxy close와 미래 proxy close의 차이로 만들어지는지 확인했다.
  - 기존 train/validation split이 tail 80/20만 수행하고 horizon purge를 적용하지 않던 점을 확인하고, validation 시작 시각 기준 `train.event_time + horizon < validation_start_time` purge를 추가했다.
  - proxy 포함 학습셋에서 `spread_bps`, `bid_ask_imbalance`에 더해 `mid_price`도 학습 feature list에서 제외했다.
  - 작은 synthetic fixture에서는 purge 후 `down/flat/up` 라벨 구성이 깨질 때 기존 split을 유지해 테스트 안정성을 보존했다.
- 실행 명령:
  ```bash
  python -m py_compile app/services/research.py
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
  python -m app --run-challengers --horizon-min 15
  ```
- 확인 결과:
  - 단위 테스트: `Ran 85 tests in 12.835s`, `OK`
  - 실험 B/D feature_names: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`
  - LightGBM: `train_rows=266300`, `validation_rows=66582`, `validation_accuracy=0.911793`, `trades_taken=5113`, `trade_hit_rate=0.889693`, `cumulative_net_return_pct=1816.829656`
  - walk-forward: `folds=33284`, `rows_evaluated=332840`, `overall_accuracy=0.380246`, `trades_taken=111223`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`
  - challenger 최종 판단: `review_required`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
- 판단:
  - `mid_price` 제거 후에도 validation이 `0.6` 이하로 떨어지지 않았으므로 `mid_price` 단독 누수 가설은 지지되지 않는다.
  - walk-forward trade_hit_rate도 `0.3` 이상으로 개선되지 않아, 다음 단계는 proxy 15분 라벨 자체를 제외하거나 일봉 단위 split/검증으로 바꾸는 방향이 우선이다.

## [2026-05-06] Codex → 스프린트 04 C-1 재실험과 KIS REST 수집 경로

- 변경 파일:
  - `app/services/research.py`
  - `app/storage/sqlite_store.py`
  - `app/brokers/kis_quote_rest.py`
  - `app/collectors/historical.py`
  - `app/__main__.py`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `pykrx-daily-proxy` row가 포함된 학습셋에서는 `spread_bps`, `bid_ask_imbalance`를 학습 feature list에서 제외하도록 변경했다.
  - LightGBM C-1 설정으로 `class_weight="balanced"`를 적용했다.
  - source lookup 성능을 위해 raw tick/orderbook의 `(symbol,event_time)` index를 추가했다.
  - KIS REST `FHKST03010200` 분봉 수집 CLI `--collect-kis-historical`을 추가하고 `source=kis-rest-historical`로 기존 DB에 적재하도록 했다.
- 실행 명령:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
  python -m app --run-challengers --horizon-min 15
  python -m app --collect-kis-historical --start 2025-05-06 --end 2026-05-06
  ```
- 확인 결과:
  - 전체 단위 테스트: `Ran 85 tests in 13.796s`, `OK`
  - C-1 LightGBM: `train_rows=266313`, `validation_rows=66579`, `validation_accuracy=0.911699`, `trades_taken=5328`, `trade_hit_rate=0.863176`, `cumulative_net_return_pct=1807.293048`
  - C-1 전체 라벨: `down=22656`, `flat=286577`, `up=23659`
  - walk-forward: `folds=33284`, `rows_evaluated=332840`, `overall_accuracy=0.412748`, `trades_taken=104327`, `trade_hit_rate=0.101259`, `cumulative_net_return_pct=-10384.138893`
  - challenger 최종 판단: `review_required`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
  - KIS REST 수집: 요청 기간 `2025-05-06~2026-05-06`, 실제 적재 `4200` bars, 범위 `2026-05-04T15:02:00+09:00~2026-05-06T15:30:00+09:00`
- 제한 사항:
  - 공식 KIS 샘플 기준 `FHKST03010200`은 당일 분봉 성격이라, 이번 실행도 1년 전체가 아니라 최근 일부 구간만 반환됐다.
  - 1년 실제 분봉 백필은 다른 장기 분봉 TR 또는 별도 실제 분봉 소스 검토가 필요하다.

## [2026-05-06] Codex → 스프린트 04 전 데이터 품질 점검

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `pykrx-daily-proxy` 일봉 기반 15분 프록시 분봉 생성 방식을 점검했다.
  - 프록시 호가는 `bid=close-tick`, `ask=close+tick`, `bid_size=ask_size` 구조라 `mid_price`는 프록시 close와 같고, `spread_bps`는 tick size 기반 기계값이며, raw 기준 `bid_ask_imbalance`는 항상 `0.0`임을 확인했다.
  - `runtime-data/dev.db`에서 `kis-ws`와 `pykrx-daily-proxy`의 호가 기반 피처 분포를 비교해 `spread_bps`와 `bid_ask_imbalance`의 source 간 차이가 큰 위험을 `docs/STATUS.md` 상단에 기록했다.
- 확인 결과:
  - raw orderbook rows: `kis-ws=2245513`, `pykrx-daily-proxy=332228`
  - exact feature samples: `kis-ws=12521`, `pykrx-daily-proxy=332228`
  - `spread_bps` median/mean: `kis-ws=12.83/14.74`, `pykrx-daily-proxy=37.92/42.31`
  - `bid_ask_imbalance`: `kis-ws`는 p05 `-0.8056`, p95 `0.8500` 분산이 있으나, 순수 proxy 구간은 `0.0` 고정
- 검증:
  - `git diff --check`: `ok`

## [2026-05-06] Codex → 스프린트 03 과거 데이터 수집 파이프라인

- 변경 파일:
  - `app/collectors/historical.py`
  - `app/storage/sqlite_store.py`
  - `app/__main__.py`
  - `scripts/collect_historical_data.sh`
  - `requirements.txt`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/logbook.md`
- 변경 내용:
  - KIS 공식 샘플의 `주식일별분봉조회`는 과거 분봉 조회가 가능하지만 최대 1년 보관으로 안내되어 5년치에는 부적합하다고 판단하고 B안으로 진행.
  - pykrx 일봉 OHLCV를 거래일당 26개 15분 proxy bar 로 변환해 기존 `curated_minute_bars`에 적재.
  - feature 생성을 위해 같은 시각의 proxy orderbook 을 `raw_orderbook_ticks`에 `pykrx-daily-proxy` source 로 적재.
  - 기존 DB 스키마는 변경하지 않고 SQLite batch upsert/insert helper 만 추가.
  - `./scripts/collect_historical_data.sh --start-date 2021-01-01` 실행 경로와 품질 리포트를 추가.
- 실행 명령:
  ```bash
  pip install --break-system-packages -r requirements.txt
  ./scripts/collect_historical_data.sh --start-date 2021-01-01
  ```
- 확인 결과:
  - 수집 방식: `B: pykrx daily OHLCV to 15-minute proxy bars`
  - 수집 기간: `2021-01-01` ~ `2026-05-06`
  - 실제 적재 시작일: `2021-01-04`
  - 대상 종목: watchlist 10개
  - proxy bars written: `332228`
  - proxy orderbooks written: `332228`
  - feature rows written: `345877`
  - label rows written: `625990`
  - 학습 가능 15분 row: `332892`
  - 품질: `expected_complete_symbol_dates=12778`, `complete_symbol_dates=12778`, `missing_or_partial_symbol_dates=0`
  - 리포트: `runtime-data/reports/historical/latest-historical-collection.{json,md}`
- 검증:
  - Python 컴파일: `ok`
  - bash 파싱 검사: `ok`
  - `git diff --check`: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 13.164s`, `OK`

## [2026-05-06] Codex → WSL2 스프린트 02 완료

- 변경 파일:
  - `requirements.txt`
  - `docs/logbook.md`
- 변경 내용:
  - WSL2 환경에 `pip` 이 없어 `python3-pip` 을 설치한 뒤, Ubuntu externally-managed 환경 제한에 따라 `pip install --break-system-packages -r requirements.txt` 로 Python 의존성을 설치했다.
  - 저장소에 없던 `requirements.txt` 를 추가해 WSL2 테스트와 Synthetic 실행에 필요한 `joblib`, `lightgbm`, `numpy`, `scikit-learn`, `scipy`, `websockets` 를 명시했다.
  - runtime-data 복사 후 Synthetic 30분 사이클을 재실행해 통과를 확인했다.
- 실행 명령:
  ```bash
  pip install -r requirements.txt
  pip install --break-system-packages -r requirements.txt
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
  ```
- 확인 결과:
  - 단위 테스트: `Ran 85 tests in 32.458s`, `OK`
  - Synthetic 30분: `exit 0`
  - Synthetic 학습: `train_rows=11336`, `validation_rows=2834`, `validation_accuracy=0.655963`
  - Synthetic walk-forward: `folds=1412`, `rows_evaluated=14120`, `overall_accuracy=0.272309`
  - Challenger 판단: `recommended_action=review_required`, `best_model_version=lightgbm-h15-v1`, `active_model_version_after_run=baseline-h15-v1`
- 예상 결과:
  - WSL2 이전 후 작업 4, 5 기준 검증은 통과 상태다.
  - LightGBM은 후보 1위지만 walk-forward gate 가 `needs_review` 이므로 자동 승격하지 않는다.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - DB의 `feature_model_inputs`, `feature_labels`, raw tick/source 현황을 확인해 데이터 기간, row 수, 종목 목록, 실제 KIS 수집일과 synthetic/sample 혼입일을 정리.
  - walk-forward `max_train_rows`를 40, 120, 500, 2000으로 바꿔 각각 실행하고 folds, accuracy, cumulative_net_return_pct, trades_taken을 `docs/STATUS.md` 상단에 기록.
  - 현재 코드 기준 과거 시세 일괄 backfill 명령과 pykrx/KIS 과거 시세 REST 수집 구현이 없음을 확인.
  - 주의: 직전 중단된 C-3의 LightGBM 수동 `class_weight` 변경은 작업트리에 남아 있다. 이번 walk-forward는 centroid 기반이라 해당 변경이 수치에 영향을 주지 않지만, 다음 LightGBM 학습 전 유지/철회 판단이 필요하다.
- 실행 요청 명령:
  ```powershell
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 120
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 500
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 2000
  ```
- 확인할 수치:
  - feature rows: 첫 row `2026-04-11T09:15:00+09:00`, 마지막 row `2026-05-06T13:14:00+09:00`, 전체 `14258`, 종목 10개.
  - 15분 라벨 결합 row: `13246`, 마지막 row `2026-05-06T11:53:00+09:00`.
  - max_train_rows 40/120/500/2000 결과: accuracy `0.420303 / 0.366970 / 0.331667 / 0.279697`, 수익률 `-60.569747% / -310.370998% / -454.176316% / -487.896584%`.
- 예상 결과 (성공 기준):
  - 데이터가 아직 실제 KIS 기준 5일치뿐이어서 60거래일 학습창 가정과 맞지 않는다.
  - 현재 `max_train_rows=40`은 4~5거래일이 아니라 10종목 합산 row 기준 약 0.02거래일에 불과하다.
  - 과거 데이터 backfill이 없으므로 학습 데이터 확장은 장중 WebSocket 축적 또는 별도 과거 시세 수집 기능 추가가 필요하다.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `app/services/research.py`
  - `tests/test_research_pipeline.py`
  - `config/strategy.toml`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `_split_dataset()`에 horizon purge를 적용해 train 라벨 horizon이 validation 시작 구간과 겹치지 않도록 수정.
  - purge 동작을 확인하는 단위 테스트를 추가.
  - 실험 C-1은 LightGBM `class_weight="balanced"`만 적용해 실행 후, C-2 독립성을 위해 해당 코드는 되돌림. 결과는 `docs/STATUS.md`에 기록.
  - 실험 C-2는 `label_threshold_15=0.25`만 적용. `mid_price`와 walk-forward gate 기준은 수정하지 않음.
  - 현재 실행 환경에서 threshold override 가능성이 있어 C-2 실행 명령에는 `LABEL_THRESHOLD_15=0.25`를 명시.
- 실행 요청 명령:
  ```powershell
  python -m unittest discover -s tests -p "test_*.py"
  $env:LABEL_THRESHOLD_15='0.25'; python -m app --build-feature-dataset
  $env:LABEL_THRESHOLD_15='0.25'; python -m app --train-lightgbm --horizon-min 15
  $env:LABEL_THRESHOLD_15='0.25'; python -m app --run-challengers --horizon-min 15
  $env:LABEL_THRESHOLD_15='0.25'; python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
  $env:LABEL_THRESHOLD_15='0.25'; python -m app --run-challengers --horizon-min 15
  ```
- 확인할 수치:
  - 검증: `python -m unittest discover -s tests -p "test_*.py"` → `Ran 86 tests in 31.500s`, `OK`. `git diff -- app/risk` 결과 없음.
  - C-1(class_weight only): validation_accuracy=0.508569, predicted labels `flat=1163, up=321, down=850`, trades_taken=56, LightGBM cumulative_net_return_pct=81.654830%, walk-forward overall_accuracy=0.437866, walk-forward cumulative_net_return_pct=21.594597%.
  - C-2(threshold only): 전체 라벨 분포 `flat=8151, up=2511, down=2584`, validation_accuracy=0.573962, predicted labels `flat=2330, up=73, down=247`, trades_taken=18, LightGBM cumulative_net_return_pct=67.457440%, walk-forward overall_accuracy=0.420303, walk-forward cumulative_net_return_pct=-60.569747%.
- 예상 결과 (성공 기준):
  - C-1은 `trades_taken > 50`을 만족하고 up 예측 비율도 개선됐지만 validation accuracy가 크게 하락.
  - C-2는 라벨 분포를 60:20:20에 가깝게 조정했지만 LightGBM 거래 수는 18건으로 성공 기준 미달.
  - 다음 우선순위는 운영자 판단 필요. 단독 실험 기준으로는 C-1이 거래 수 회복에 더 직접적이며, C-2는 라벨 기반 정상화 효과가 있으나 단독으로는 flat 예측 편향 해소가 부족하다.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `docs/logbook.md`
- 변경 내용:
  - `docs/STATUS.md`의 Phase 1 수치를 기준으로 Phase 2 원인 분석을 수행.
  - 데이터 누수 점검: `mid_price`는 `app/features/minute_bars.py`에서 현재 시점 호가의 bid/ask 평균으로 생성되고, 라벨은 `app/services/research.py`에서 현재 bar 이후 horizon의 future bar close로 별도 계산된다. 따라서 `mid_price` 자체가 미래 가격을 직접 참조하는 lookahead는 아니다.
  - 단, 현재 검증 구조에는 누수/과대평가 위험이 있다. `_split_dataset()`은 단순 80/20 시간 분할이며 horizon purge가 없어 train 마지막 row의 라벨 계산 구간이 validation 시작 시각과 겹친다. 현재 DB 기준 train 끝과 validation 시작이 모두 `2026-05-04T11:35:00+09:00`이고, train row 155건의 라벨 horizon이 validation 시작 이후와 겹친다.
  - `mid_price`는 절대 가격 수준이라 종목 식별 대리변수로 작동할 수 있다. 종목별 가격대와 라벨 분포가 함께 학습되면 실시간 예측 일반화보다 종목/구간 암기가 쉬워지므로 Phase 3에서 제거 또는 정규화 실험이 필요하다.
  - LightGBM 거래 3건 원인: 거래 판정은 `app/services/research.py::_evaluate_rows_with_model()`에서 `predicted_label == "up"`이고 `probability_up >= settings.strategy.min_signal_confidence`일 때만 카운트한다. 기본 임계값은 `config/strategy.toml`의 `min_signal_confidence = 0.58`이며 `.env`의 `MIN_SIGNAL_CONFIDENCE`로 override 가능하다.
  - Phase 1 LightGBM 검증은 실제 라벨이 `flat=1889, up=240, down=174`이고 예측은 `flat=2260, up=11, down=32`였다. accuracy 0.816761은 대부분 `flat` 다수 클래스 적중에서 온 값이며, up 예측 11건 중 0.58 신뢰도 통과가 3건뿐이라 거래가 3건으로 줄었다. 임계값만 낮춰도 최대 up 예측 후보가 11건 수준이므로 핵심 원인은 임계값보다 라벨 불균형/flat 편향이다.
  - walk-forward gate 검토: gate는 `app/services/research.py::_build_walk_forward_gate()`의 하드코딩 기준 `overall_accuracy < 0.55`와 `cumulative_net_return_pct <= 0.0`로 판단한다. Phase 1 walk-forward는 `overall_accuracy=0.438710`, `cumulative_net_return_pct=-14.115270%`라 gate 실패가 정상이다.
  - 다만 현재 walk-forward 명령은 `LightGBM`이 아니라 `walk-forward-centroid-h15-v1`을 매 fold 학습한다. 이 gate를 LightGBM 승격 판단에 그대로 쓰면 "LightGBM의 walk-forward 성능"이 아니라 centroid 참조 성능으로 막는 구조가 된다.
  - 0.55 accuracy 기준은 주가 방향 예측에서 단독 절대 기준으로 쓰기엔 거칠다. 현재 라벨은 flat 다수 클래스가 70~80%대라, overall accuracy는 majority-flat baseline과 trade 수익성/거래 커버리지보다 덜 유용하다.
- 실행 요청 명령:
  ```powershell
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  ```
- 확인할 수치:
  - Phase 1 STATUS: LightGBM `validation_accuracy=0.816761`, `trades_taken=3`, predicted labels `flat=2260, up=11, down=32`, actual labels `flat=1889, up=240, down=174`.
  - Phase 1 walk-forward: `overall_accuracy=0.438710`, `trades_taken=3126`, `cumulative_net_return_pct=-14.115270%`, `max_train_rows=40`.
  - 현재 코드 gate: `overall_accuracy < 0.55`이면 `needs_review`.
- 예상 결과 (성공 기준):
  - Phase 3 첫 실험은 **실험 C: 라벨 기준 재정의**를 우선 권장한다. `label_threshold_15=0.35`로 인해 flat 편향이 강하므로 threshold 조정 또는 class_weight/balanced 학습을 한 가지씩만 적용해 up/down 커버리지를 먼저 회복한다.
  - 두 번째 후보는 `mid_price` 제거 또는 `bar.close` 대비 상대값/수익률형 피처로 정규화하는 **피처 축소 실험 B**다.
  - gate 개선은 이후 실험으로 분리한다. LightGBM 전용 walk-forward를 만들거나, hard 0.55 accuracy보다 baseline 대비 초과수익, trade_hit_rate, 거래 수 최소치, majority-class 대비 개선폭을 함께 보는 기준으로 바꾸는 것이 타당하다.

## [2026-05-06] Cowork — SQLite fix 2차 검증 실패 (1c1aa04 적용 후)

- 트리거: Codex 커밋 `1c1aa04 fix(storage): add sqlite journal memory fallback [sprint-01]` pull 후 사용자 지시("SQLite fix 검증") 수행.
- 환경: Cowork Linux 샌드박스(Ubuntu 22.04, Python 3.10.12). 저장소는 `fuse`/virtiofs 마운트.
- 사전 조치:
  - 작업트리의 일부 파일이 또 FUSE 동기화 중 절단되어 도착(`app/storage/sqlite_store.py`가 1006줄로 잘려 있고 HEAD blob은 974줄). `git show HEAD:` 로 `app/storage/sqlite_store.py`, `tests/test_sqlite_store.py`, `docs/logbook.md`, `AGENTS.md` 정본을 추출해 `cp` 로 작업트리 복원(코드 수정 아님, 정본 복원).
  - `SQLITE_JOURNAL_MODE_FALLBACKS = ('WAL', 'DELETE', 'MEMORY')` 확인 — Codex 의도대로 도입됨.
  - `select_sqlite_journal_mode(Path('runtime-data/dev.db').resolve())` → `WAL` (FUSE 경로인데도 WAL 선호로 후퇴 — 1차 패치의 FUSE→DELETE 감지가 사라진 듯)
- 단위 테스트: `python -m unittest discover -s tests -p "test_*.py"` (PYTHONPYCACHEPREFIX=/tmp/pyc)
  - `Ran 85 tests in 2.861s` — 테스트 개수 일치
  - `FAILED (errors=39)` — 39건 모두 `sqlite3.OperationalError: disk I/O error` (스택은 `_initialize_schema_with_journal_mode → CREATE TABLE`)
  - 재현 단일 케이스(test_synthetic_seed):
    ```
    WARNING ... SQLite startup journal_mode=WAL failed for database=.../test.db error=disk I/O error; falling back to DELETE
    WARNING ... SQLite startup journal_mode=DELETE failed for database=.../test.db error=disk I/O error; falling back to MEMORY
    ERROR   ... SQLite startup failed with all journal modes for database=.../test.db last_mode=MEMORY error=disk I/O error
    ```
  - **MEMORY까지 fallback이 진행됐음에도 최종 실패**.
- ⚠️ 중단 조건(단위 테스트 1개 이상 실패) 발동으로 Synthetic 미실행.
- 원인 좁힘 — 핵심 진단:
  - WAL → DELETE 시도 단계에서 SQLite가 `<dbname>-journal` 사이드카 파일을 만든다.
  - virtiofs FUSE에서 이 사이드카는 한 번 만들어지면 `unlink`이 `Operation not permitted` 으로 거부된다(파일 자체는 존재).
  - 결과적으로 마지막 단계인 MEMORY 시도 시에도 SQLite가 기존 `-journal` 을 발견해 rollback/recovery 시도 → disk I/O error.
  - 직접 재현 결과:
    | 시나리오 | 결과 |
    |---|---|
    | 신선한 경로에 `MEMORY` 단독 | OK |
    | 신선한 경로에 `WAL→DELETE→MEMORY` 체인 | FAIL at MEMORY (disk I/O error) |
    | 신선한 경로에 `DELETE→MEMORY` | FAIL at MEMORY |
    | DELETE 실패 후 `.db` 삭제 + `-journal` 삭제 시도 | `-journal` 삭제 실패 (Operation not permitted) |
    | DELETE 실패 후 `.db` 만 삭제 + MEMORY 재시도 | FAIL (남은 `-journal`이 방해) |
- 결론: 이 환경에서 `WAL`이나 `DELETE`를 한 번이라도 **시도하면** journal 사이드카가 영구적으로 남아 모든 후속 시도를 막는다. **사이드카가 만들어지지 않게** 하는 것이 유일한 해법.
- Codex 권장 후속 조치(Cowork 의견):
  1. `select_sqlite_journal_mode` 가 마운트된 Windows 폴더(virtiofs/fuse)에 대해 **`MEMORY` 를 preferred 로 직접 반환**하게 수정. WAL/DELETE를 아예 시도하지 않도록 fallback 체인을 `(MEMORY,)` 로 단축.
  2. 또는 `select_sqlite_journal_mode` 가 FUSE를 감지하면 fallback 체인을 `(MEMORY, OFF)` 로 시작.
  3. Codex 1차 패치(`eb3949f`) 의 FUSE→DELETE 감지 로직이 이번 2차 패치(`1c1aa04`)에 누락된 것으로 보이므로, 그 감지 로직을 살리되 결과를 `MEMORY` 로 매핑하도록 결합.
- 추가 환경 메모(반복 보고):
  - 프로젝트 `requires-python = ">=3.12"` 이지만 Cowork 샌드박스 Python은 3.10.12. `tomli` → `tomllib` shim 적용 중.
  - `pip install --break-system-packages lightgbm scikit-learn websockets joblib tomli scipy threadpoolctl` 적용 중.
  - `PYTHONPYCACHEPREFIX=/tmp/pyc` 로 stale `.pyc` 우회 중.
  - 작업트리 파일이 FUSE 동기화 중 잘려 도착하는 일이 반복됨 — Codex 커밋 후 첫 Cowork 세션에서 `git show HEAD:` 로 정본 강제 동기화가 매번 필요할 수 있음.

## 🔴 [2026-05-06] 운영자 판단 필요 — SQLite fix 검증 실패 (단위 테스트 단계)

- 상황: SQLite fix 검증 실패 — 단위 테스트 단계에서 39/85 disk I/O error. WAL→DELETE→MEMORY 체인이 들어왔지만, 실패한 시도에서 남는 `-journal` 사이드카를 FUSE에서 삭제할 수 없어 MEMORY 단계까지 오염됨.
- 가져갈 파일: `docs/logbook.md` (위 "Cowork — SQLite fix 2차 검증 실패" 섹션, pragma 시나리오 표 포함)
- 질문: 추가 조치 방향 결정 필요. Codex 권장안 ① `select_sqlite_journal_mode` 가 FUSE 경로에 대해 처음부터 `MEMORY` 를 반환하도록 수정 / ② Phase 1 Windows 결과로 갈음하고 Cowork 환경 검증 자체 보류 / ③ 다른 방향 지정.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Windows 로컬 환경에서 Phase 1 명령을 직접 실행하고 결과를 `docs/STATUS.md` 상단에 기록.
  - 전체 단위 테스트 85개 통과 후 walk-forward, LightGBM 학습, challenger 비교를 순서대로 실행.
  - LightGBM 피처 중요도 상위 5개와 baseline 대비 핵심 판단을 함께 기록.
  - MDD와 샤프지수는 현재 리포트에 원 필드가 없어 거래별/폴드별 순수익률 단순누적 기준 참고값으로 계산해 명시.
- 실행 요청 명령:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  ```
- 확인할 수치:
  - 단위 테스트: `Ran 85 tests in 25.449s`, `OK`
  - walk-forward: `folds=1147`, `rows_evaluated=11470`, `trades_taken=3126`, `overall_accuracy=0.438710`, `cumulative_net_return_pct=-14.115270`
  - LightGBM 학습: `train_rows=9212`, `validation_rows=2303`, `validation_accuracy=0.816761`
  - challenger: `recommended_action=keep_active`, `walk_forward_gate_status=needs_review`, `active_model_version_after_run=baseline-h15-v1`
  - LightGBM latest: `trades_taken=3`, `cumulative_net_return_pct=-0.113131`, `overall_accuracy=0.816761`
  - baseline active: `trades_taken=1013`, `cumulative_net_return_pct=-51.599478`, `overall_accuracy=0.108120`
  - 피처 중요도 top5: `mid_price=1450`, `spread_bps=1110`, `bid_ask_imbalance=1077`, `avg_trade_size=986`, `hl_range_pct=853`
- 예상 결과 (성공 기준):
  - 운영자는 `docs/STATUS.md` 상단의 Phase 1 Windows 직접 실행 결과를 보고 Phase 2 원인 분석 착수 여부를 판단한다.
  - 현재 자동 승격은 하지 않는다. LightGBM은 정확도는 높지만 거래 수가 3건뿐이라 `keep_active`가 정상 판단이다.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `app/storage/sqlite_store.py`
  - `tests/test_sqlite_store.py`
  - `docs/logbook.md`
- 변경 내용:
  - SQLite 시작 초기화를 `WAL → DELETE → MEMORY` 3단계 fallback으로 변경.
  - `PRAGMA journal_mode` 호출만이 아니라 `journal mode 설정 + synchronous 설정 + schema 생성 + commit` 전체를 한 단계로 보고, 어느 지점에서든 `sqlite3.OperationalError`가 나면 다음 journal mode로 재시도하도록 수정.
  - `DELETE`에서 `CREATE TABLE` 중 `disk I/O error`가 나는 Cowork FUSE/virtiofs 환경은 다음 단계인 `MEMORY`로 넘어가도록 처리.
  - 성공 시 시작 로그에 `SQLite startup using journal_mode=<MODE> for database=<path>` 형식으로 실제 동작 모드를 남김.
  - fallback 실패 로그는 `SQLite startup journal_mode=<MODE> failed ... falling back to <NEXT>` 형식으로 남김.
  - fallback 순서와 `MEMORY`까지의 재시도, 시작 로그 출력 단위 테스트를 기존 SQLite 테스트 안에서 갱신.
- 실행 요청 명령:
  ```bash
  git pull origin main
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
  ```
- 확인할 수치:
  - 로컬 전체 단위 테스트: `Ran 85 tests in 25.305s`, `OK`
  - 로컬 Synthetic 30분: `exit 0`
  - Synthetic 학습: `train_rows=9212`, `validation_rows=2303`, `validation_accuracy=0.818498`
  - Synthetic walk-forward: `folds=1147`, `rows_evaluated=11470`, `overall_accuracy=0.282127`
  - 로컬 시작 로그: `SQLite startup using journal_mode=WAL ...`
- 예상 결과 (성공 기준):
  - Cowork FUSE/virtiofs 환경에서 `WAL` 실패 후 `DELETE`를 시도하고, `DELETE`가 schema 생성 중 `disk I/O error`를 내면 `MEMORY`로 자동 전환되어 단위 테스트와 Synthetic Step 1이 통과해야 한다.
  - Cowork 로그에는 최종적으로 `SQLite startup using journal_mode=MEMORY ...`가 보여야 한다.

## [2026-05-06] Cowork 후속 검증 — Codex 패치 적용 후에도 SQLite "disk I/O error" 잔존

- 트리거: Codex `eb3949f fix(storage): fallback sqlite journal on mounted paths` pull 후 가이드 명령 재실행
- 환경: Cowork Linux 샌드박스(Ubuntu 22.04, Python 3.10.12). 저장소는 `fuse`/virtiofs로 마운트(`fstype=fuse, source=/mnt/.virtiofs-root/shared/d/...`).
- 사전 조치:
  - 작업트리 `app/storage/sqlite_store.py`가 1074줄 → 964줄(BOM+CRLF, `query = """`에서 잘림)으로 도착해 SyntaxError. FUSE 동기화 중 절단으로 추정. `git show HEAD:app/storage/sqlite_store.py` 로 정본 추출 후 `cp` 로 작업트리 덮어써서 1074줄 정본 복원.
  - `select_sqlite_journal_mode(Path('runtime-data/dev.db').resolve())` → `DELETE` (Codex 의도대로 동작)
- 단위 테스트: `python -m unittest discover -s tests -p "test_*.py"`
  - `Ran 85 tests in 2.031s` — 테스트 개수는 Codex 인수인계 기대치(85)와 일치
  - `FAILED (errors=40)` — 40건 모두 `sqlite3.OperationalError: disk I/O error` (`connection.execute(statement)` for CREATE TABLE)
- 핵심 진단(샌드박스에서 직접 SQLite pragma 조합 실험 결과):
  | 조합 | 결과 |
  |---|---|
  | `journal_mode=DELETE` | FAIL: disk I/O error |
  | `journal_mode=DELETE` + `synchronous=NORMAL` | FAIL: disk I/O error |
  | `journal_mode=DELETE` + `synchronous=OFF` | FAIL: disk I/O error |
  | `journal_mode=DELETE` + `locking_mode=EXCLUSIVE` | OK |
  | `journal_mode=MEMORY` | OK |
  | `journal_mode=OFF` | OK |
  fcntl flock·F_SETLK은 정상 동작. SQLite 자체의 journal 파일 생성/동기화 syscall이 이 virtiofs FUSE에서 실패함.
- 결론: Codex 패치는 의도대로 `DELETE`를 선택했으나, virtiofs 환경에서는 `DELETE` 단독으로는 부족함. `DELETE` 선택 시 `PRAGMA locking_mode=EXCLUSIVE` 를 함께 설정하거나, mount 감지가 `DELETE` 트리거되는 경로에 대해 `journal_mode=MEMORY` 로 한 단계 더 fallback 필요.
- Cowork 조치: 가이드의 "Synthetic 통과 전 Step 2 보류" 규칙대로 Step 2~5 미실행. 운영자 호출 양식 갱신.
- 추가 환경 메모(다음 세션 가속용):
  - 프로젝트 `requires-python = ">=3.12"` 이지만 Cowork 샌드박스 Python은 3.10.12. `tomllib` 백포트 shim(`~/.local/lib/python3.10/site-packages/tomllib.py`) 적용 후 `app.config.settings` 로딩 가능.
  - `pip install --break-system-packages lightgbm scikit-learn websockets joblib tomli scipy threadpoolctl` 완료.
  - `PYTHONPYCACHEPREFIX=/tmp/pyc` 사용해 마운트된 `__pycache__` 의 stale `.pyc` 우회 필요.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `app/storage/sqlite_store.py`
  - `tests/test_sqlite_store.py`
  - `docs/logbook.md`
- 변경 내용:
  - SQLite 스키마 초기화 전에 DB 경로 환경을 감지해 journal mode를 선택하도록 수정.
  - 정상 로컬 디스크는 기존처럼 `WAL`을 사용하고, UNC 경로·Windows 원격 드라이브·Windows reparse/mount 폴더·Linux/WSL 계열 마운트/네트워크 파일시스템(`drvfs`, `9p`, `cifs`, `nfs`, `virtiofs`, `fuse.*` 등)은 `DELETE` 모드로 자동 전환.
  - 감지 누락으로 `WAL` 설정이 실패해도 `DELETE`로 한 번 fallback 하도록 보강.
  - `DELETE` 모드 DB에서는 `wal_checkpoint`를 no-op 처리해 백업 경로가 WAL 전용 pragma에 묶이지 않도록 수정.
  - 네트워크/마운트 환경 선택과 WAL 실패 fallback 단위 테스트 추가.
- 실행 요청 명령:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
  ```
- 확인할 수치:
  - 전체 단위 테스트: `85 tests OK`
  - Synthetic 30분 재실행: `exit 0`
  - Synthetic 학습: `train_rows=9212`, `validation_rows=2303`, `validation_accuracy=0.818498`
  - Synthetic walk-forward: `folds=1147`, `rows_evaluated=11470`, `overall_accuracy=0.282127`
  - Challenger 판단: `recommended_action=keep_active`, `active_model_version_after_run=baseline-h15-v1`, `walk_forward_gate_status=needs_review`
  - 참고: 처음 Synthetic 실행은 120초 도구 제한으로 timeout 되었고, 600초 제한 재실행에서 정상 통과.
- 예상 결과 (성공 기준):
  - Cowork Linux 샌드박스에서 Windows 폴더를 마운트한 경로는 WAL을 시도하기 전에 `DELETE` journal mode로 열려 Synthetic Step 1이 통과해야 한다.
  - Windows 로컬 디스크 실행은 기존 WAL 모드를 유지해야 한다.

## [2026-05-06] Cowork 스프린트 01 Phase 1 시도 — Synthetic 실행 환경 오류

- 트리거: COWORK_GUIDE.md 세션 시작 순서에 따른 스프린트 01 Phase 1 진단 시도
- 환경: Cowork Linux 샌드박스(Ubuntu 22.04, Python 3.10.12), 저장소는 Windows `~/projects/Real-time-stock-price-prediction-program` 폴더 마운트
- 사전 준비:
  - Python 3.12 사용 불가 → `tomllib` 누락 → `tomli` 백포트를 `tomllib`로 별칭 처리(`~/.local/lib/python3.10/site-packages/tomllib.py`)
  - 패키지 설치: `lightgbm 4.6.0`, `scikit-learn 1.7.2`, `websockets 16.0`, `joblib 1.5.3`, `tomli 2.4.1`, `scipy 1.15.3`, `threadpoolctl 3.6.0`
  - `app.config.settings.load_settings()` 호출 성공
- 실행: `python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15`
- 결과: `exit 1`. 핵심 traceback:
  ```
  File "app/storage/sqlite_store.py", line 312, in _initialize_schema
      connection.execute("PRAGMA journal_mode=WAL")
  sqlite3.OperationalError: unable to open database file
  ```
- 추가 검증: 표준 sqlite3로도 동일 오류 — `python -c "sqlite3.connect('runtime-data/dev.db').execute('PRAGMA journal_mode=WAL')"` → `unable to open database file`
- 해석: WAL 모드는 공유 메모리 매핑(`-shm`, `-wal`)을 요구하는데, Cowork에서 Windows 폴더를 Linux 샌드박스에 마운트한 가상 파일시스템이 이 매핑을 지원하지 않는 것으로 보임. 코드베이스가 깨진 것은 아님.
- 조치: 가이드의 "Synthetic 실패 시 Step 2 보류" 규칙에 따라 Step 2~5 실행 중단. `docs/STATUS.md` 상단에 운영자 판단 필요 양식 기록.
- 운영자 질문: ① Phase 1 진단을 운영자가 Windows에서 직접 실행할지, ② Codex에 환경 fallback 코드 수정을 지시할지, ③ Phase 1 자체를 보류할지

## 현재 스냅샷

- 날짜: `2026-05-05`
- 현재 버전: `0.2.0`
- 최근 릴리스 커밋: `8f601ba`
- 감시기 방식: `VERSION` 변경 감지
- 저장소 자동 점검 참여: 켜짐
- 기준 문서 동기화: 예
- 실행 자동시작 실행기 설치: 예

## 현재 상태

- Python 기반 로컬 연구, 수집, 예측, 모의운용 흐름이 구현되어 있다.
- KIS REST 현재가/호가 조회, KIS WebSocket 파서와 수신기, 재연결 처리가 준비되어 있다.
- SQLite와 JSONL 기반 실행 저장소에 원시 체결, 호가, 분봉, 특징, 라벨, 예측, 신호, 주문, 체결, 평가를 기록한다.
- 15분과 60분 예측을 기록하되, 신호와 주문 판단은 15분 기준으로 수행한다.
- 현재 15분 활성 모델은 `baseline-h15-v1` 이고, LightGBM은 장후 재학습과 도전자 모델 비교에 사용한다.
- LightGBM은 정상 학습되지만 워크포워드 기준이 약하면 자동 승격하지 않는다.
- 운영 학습창은 `최근 60거래일 + 오늘 데이터` 기준이며, 오래된 데이터는 삭제하지 않고 비교와 회귀 검증에 보관한다.
- 로컬 대시보드는 `http://127.0.0.1:8765` 에서 실행되며, 기본 자동 새로고침 주기는 10분이다.
- 대시보드는 기본 화면과 `/api/dashboard.json` 에서 최신 캐시 스냅샷을 우선 사용하고, 수동 갱신과 자동 새로고침 때 `/api/refresh` 로 다시 생성한다.
- 대시보드는 실제 운용 데이터만 기본 표시하고 `sample`, `synthetic`, `demo`, 재생 전용 행, 정규장 밖 스냅샷 분봉을 제외한다.
- 대시보드는 원시 체결/호가 행 전체를 메모리에 올리지 않고 분 단위 집계 카운트로 요약해 생성 시간을 줄인다.
- 예측 상세 탭은 선택 기간의 전체 예측을 보여준다.
- 장마감 뒤 같은 거래일의 후속 분봉이 더 생길 수 없는 예측은 `대기 중`이 아니라 `결과 없음`으로 닫는다.
- 로컬 가상 계좌와 KIS 모의계좌는 시작 예수금 동기화와 브로커 기준 정렬을 통해 비교한다.
- KIS 모의계좌 상품코드는 화면에 없으면 `.env` 에 빈 값으로 두고, 앱 내부에서 모의투자 기본값을 적용한다.
- 브로커 모의계좌 주문 미러링은 `ENABLE_BROKER_PAPER_MIRRORING=true` 일 때 켜진다.
- 브로커 주문/체결 조회가 KIS 호출 제한에 걸리면 재시도하고, 계속 막히면 안전하게 `rate_limited` 리포트를 남긴다.
- 실시간 수집 중 브로커 체결 동기화는 분 단위로 제한하고, KIS rate-limit 발생 뒤 5분 냉각 시간을 둔다.
- 실행 감시기와 자동 시작 스크립트는 정규장에는 대시보드와 실시간 수집기를 복구하고, 장외와 설정된 휴장일에는 실시간 수집기를 다시 켜지 않아 CPU 재연결 루프를 줄인다.
- 정규장 시작 60분 전부터는 장전 준비 단계로 실시간 수집기를 미리 켠다.
- PC 로그인 후 자동 복구용 실행 자동시작과 시작프로그램 실행기가 준비되어 있다.
- 매시간 저장소 점검 자동화는 git 추적 파일을 직접 수정하지 않고 `runtime-data/reports/codex/automation/` 아래에만 산출물을 남긴다.

## 활성 체크리스트

- [x] KIS REST 수집 구현
- [x] SQLite 적재와 실행 기록기 구현
- [x] 분봉 / 특징 / 라벨 생성 구현
- [x] 기준 모델 학습 구현
- [x] 검증 꼬리구간 백테스트 구현
- [x] 워크포워드 백테스트 구현
- [x] 실행 리포트 구현
- [x] VERSION 기반 감시기 참여 설정 정리
- [x] 다중 모델 도전자 비교 구조
- [x] LightGBM 학습 파이프라인 추가
- [x] 로컬 모니터링 대시보드 추가
- [x] 대시보드 10탭 구조와 한글 UI
- [x] 대시보드 기본 새로고침 10분과 수동 갱신 경로
- [x] 대시보드 예측 상세 전체 표시
- [x] 실제 KIS WebSocket 장중 수신 검증
- [x] KIS 브로커 모의계좌 잔고 조회와 대시보드 반영
- [x] 브로커 모의계좌 주문 제출 미러링
- [x] 로컬 가상투자와 KIS 모의투자의 시작 예수금 동기화
- [x] 실행 감시기 백그라운드 제어 스크립트
- [x] 장중 유휴 WebSocket 수집 상태 감지와 복구
- [x] 장외 실시간 수집기 재기동 제한으로 CPU 사용 절감
- [x] 설정 휴장일 실시간 수집기와 자동 시작 차단
- [x] git 추적 Markdown 문서의 사람이 읽는 본문 한글 정리
- [x] 저장소 맞춤형 `AGENTS.md` 재구성

## 버전과 감시기

- 감시기가 보는 기준 파일은 root `VERSION` 이다.
- 저장소 참여 설정 파일은 root `autopush.json` 이다.
- 현재 설정은 `enabled=true`, `trigger=version-change`, `branch=main` 이다.
- 버전을 바꾸는 명령은 `scripts/bump_version.sh` 를 사용한다.
- 감시기 확인 위치:
- `runtime-data/autopush/git-autopush.log`
- `runtime-data/autopush/git-autopush-state.json`

## 최신 검증 결과

- `2026-05-05 01시대` 저장소 점검과 개선:
- 현재 시각 `2026-05-05 01:47 +09:00` 기준 dashboard 는 `127.0.0.1:8765` 로 정상 응답했고, runtime watchdog 은 `running`, `heartbeat_stale=false` 였다.
- 실시간 수집기는 `pre-open` 장전 준비 시작 전이라 `stopped` 가 정상 상태였고, `check_local_setup.sh -AsJson` 은 `ok=true`, KIS paper 자격정보와 LightGBM 사용 가능 상태를 확인했다.
- 문제점: `config/market_calendar.toml`이 2026-05-05 어린이날 휴장을 몰라 현재 장 상태를 `pre-open`으로 계산했다. 이 상태면 08:00 이후 감시기가 불필요하게 실시간 수집기를 시작할 수 있다.
- 조치: 2026년 KRX 전일 휴장일을 `holidays`에 확장해 2026-05-05와 연말 휴장 등을 반영했다.
- 문제점: 전일 live runtime 로그에서 KIS 브로커 모의계좌 체결 조회가 주문 제출 직후 반복 실행되어 `EGW00201` rate-limit 재시도가 다수 발생했다.
- 조치: 실시간 브로커 체결 동기화를 분당 1회로 제한하고, rate-limit 발생 시 5분 냉각 시간을 두도록 변경했다. 주문 제출 직후 강제 체결 조회는 제거하고 다음 분 단위 동기화에서 반영한다.
- 문제점: 대시보드 수동 생성이 원시 체결/호가 대량 행을 여러 번 메모리에 올려 120초 제한 안에 끝나지 않았고, 기존 대시보드 서버 `/api/refresh`도 watchdog timeout 경고를 낼 수 있었다.
- 조치: runtime scope 에 원시 체결/호가 분 단위 카운트를 보관하고 대시보드는 이 집계값을 사용하도록 바꿔 원시 행 전체 로딩을 제거했다.
- 부분 검증 `python -m unittest tests.test_dashboard tests.test_runtime_scope`: `14 tests OK`
- 브로커 동기화 관련 부분 검증 `python -m unittest tests.test_settings tests.test_kis_ws_verification tests.test_streaming_pipeline tests.test_broker_paper_sync`: `20 tests OK`
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `81 tests OK`
- 공백 오류 검사 `git diff --check`: `ok`
- 대시보드 생성 시간 재측정 `python -m app --build-dashboard`: `ok`, `23.27초`
- 새 대시보드 서버 `/api/refresh`: `ok`, `19.41초`
- 대시보드 서버 재시작 뒤 상태: `running`, `http://127.0.0.1:8765`, 실시간 수집기 `stopped`, 장 상태 `holiday`
- 실행 감시기 상태: `running`, `heartbeat_stale=false`, `market_session_status=holiday`, `live_runtime_should_run=false`, `live_runtime_action=off_session_hold_holiday`

- `2026-05-04 17시대` 동작 구조 점검과 감시기 보강:
- 저장소 목적 대비 구조는 `brokers/collectors -> features/labels -> models/services -> paper_trading/portfolio/risk -> reporting` 흐름으로 맞게 분리되어 있고, 기본 운용도 `paper` 검증 중심으로 유지 중이다.
- 실제 상태 점검에서 dashboard 는 `127.0.0.1:8765` 로 정상 응답했고, 장마감 뒤 live runtime 은 중지 상태가 정상임을 확인했다.
- 문제점: runtime watchdog 프로세스는 살아 있었지만 `watchdog-state.json`의 `last_checked_at`이 오래 멈춘 상태를 `running`으로 표시했다. 이 경우 내일 장전 자동 복구가 살아 있는 것처럼 보일 수 있다.
- `get_runtime_watchdog_status.sh`가 심박 나이와 stale 기준을 표시하고, 프로세스가 살아 있어도 기본 10분 이상 심박이 멈추면 `stale` 로 판정하도록 수정했다.
- `start_runtime_watchdog_background.sh`가 stale 심박을 가진 기존 감시기 프로세스를 재사용하지 않고 중지 후 새로 시작하도록 수정했다.
- `run_runtime_watchdog_loop.sh`는 장마감 ML 정비 시작 직전 상태 파일에 `post_close_ml_rebuild_starting`을 먼저 기록하고, live runtime 이 최신 분봉을 쓰는 정규장에는 별도 KIS 검증 WebSocket 을 중복 실행하지 않도록 수정했다.
- 확인 결과: stale 감시기 프로세스를 새 기준으로 감지했고, 감시기 재시작 후 `status=running`, `heartbeat_stale=false`, `last_checked_at=2026-05-04 17:53:33 +09:00`, 장 상태 `post-close`, live runtime `stopped` 로 정리했다.
- bash 파싱 검사: 감시기 관련 3개 스크립트 모두 `parse ok`
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `80 tests OK`
- 대시보드 스냅샷 생성 `python -m app --build-dashboard`: `ok`, `generated_at=2026-05-04T17:53:17.750250+09:00`
- 공백 오류 검사 `git diff --check`: `ok`

- `2026-05-04 15시대` 보안 점검:
- git 추적 파일과 git 기록에서 실제 root `.env` 추적은 발견되지 않았고, `.env.example`만 추적 중인 것을 확인했다.
- 로컬 `.env`는 존재하지만 `.gitignore`에 의해 ignore 처리되어 있다.
- 대시보드 프로세스는 `127.0.0.1:8765`에만 바인딩되어 외부 인터페이스로 열려 있지 않다.
- 치명 후보로 NAS 복구 스냅샷이 root `.env*`, `runtime-data/cache/kis/access_token.json`, runtime 로그를 포함할 수 있는 구조를 확인했다.
- `scripts/export_recovery_snapshot.sh`가 root `.env*`, KIS 토큰 캐시, runtime 로그, private key 계열 파일을 제외하도록 수정했다.
- RECOVERY.md, README.md, AGENTS.md, 주간/강제 NAS 백업 wrapper에 비밀값 제외 백업 원칙을 반영했다.
- 로컬 `.env`와 `runtime-data/cache/kis/paper/access_token.json`의 Windows ACL에서 일반 `Users`/`Authenticated Users` 상속 권한을 제거하고 현재 사용자, Administrators, SYSTEM만 접근하도록 좁혔다.
- bash 파싱 검사: NAS 백업 관련 4개 스크립트 모두 `parse ok`
- 임시 로컬 백업 패키지 생성 검증: `.env`, `.env.local`, `runtime-data/cache/kis`, `runtime-data/logs`, `access_token.json`, private key 패턴 파일 모두 스냅샷에 없음
- 공백 오류 검사 `git diff --check`: `ok`

- `2026-05-01 10시대` 휴장일 전체 점검:
- 오늘 `2026-05-01`은 휴장일로 운용해야 하므로 `config/market_calendar.toml`의 `holidays`에 추가했다.
- 기존 bash 장 상태 계산이 주말과 시간만 보고 오늘을 `regular-session`으로 오판해 watchdog 이 live runtime 을 재기동한 것을 확인했다.
- `get_live_runtime_status.sh`, `check_local_setup.sh`, `run_runtime_watchdog_loop.sh`, `run_post_close_ml_maintenance.sh`, `run_hourly_repo_audit_iteration.sh`가 `holidays`를 읽어 `holiday`로 해석하도록 보강했다.
- 추가 점검에서 `start_runtime_autoboot.sh`, `start_monday_runtime.sh`도 실시간 수집기를 직접 시작할 수 있어 같은 휴장일 차단 조건을 적용했다.
- 휴장일 자동 부팅 시뮬레이션 `start_runtime_autoboot.sh -SkipDashboard -SkipAccountRefresh -SkipRuntimeCleanup -SkipDashboardBuild -SkipWatchdog`: `market_session_status=holiday`, `live_runtime_should_run=false`, `live_runtime=stopped`
- Python 설정, KIS 검증, runtime scope, 대시보드도 같은 휴장일 설정을 사용하도록 맞췄다.
- 즉시 `stop_runtime_watchdog.sh`와 `stop_live_runtime.sh`를 실행해 휴장일 불필요한 WebSocket 재연결을 중지했다.
- 부분 검증 `python -m unittest tests.test_settings tests.test_runtime_scope tests.test_kis_ws_verification`: `10 tests OK`
- 전체 검증 `python -m unittest discover -s tests -p "test_*.py"`: `80 tests OK`
- 실행 리포트 생성 `python -m app --build-runtime-report`: `ok`
- 대시보드 스냅샷 생성 `python -m app --build-dashboard`: `ok`, `session_status=holiday`, `live_runtime=stopped`
- bash 파싱 검사: 휴장일 관련 5개 스크립트와 자동 시작 2개 스크립트 모두 `parse ok`
- `scripts/get_live_runtime_status.sh`: `current_session_status=holiday`, `status=stopped`

- `2026-05-01 00시대` 전체 점검과 복구:
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `79 tests OK`
- 공백 오류 검사 `git diff --check`: `ok`
- 대시보드 스냅샷 생성 `python -m app --build-dashboard`: `ok`
- 실행 리포트 생성 `python -m app --build-runtime-report`: `ok`
- 실행 리포트 행 수: `raw_market_ticks=1523101`, `raw_orderbook_ticks=1244192`, `minute_bars=7614`, `feature_rows=7614`, `labels=13889`, `predictions=13041`, `signals=6521`, `orders=1165`, `fills=114`, `broker_order_submissions=46`
- 대시보드 서버 시작 지연 원인은 서버가 포트를 열기 전에 무거운 스냅샷 재생성을 먼저 수행하던 구조였다. 기존 캐시 스냅샷이 있으면 서버를 먼저 열도록 수정했다.
- 대시보드 스냅샷 저장 중 상태 점검이 같은 JSON 파일을 읽어 Windows 파일 잠금 충돌이 1회 발생한 로그를 확인했다. 스냅샷 저장을 임시 파일 교체와 짧은 재시도 방식으로 보강했다.
- 보강 뒤 `python -m unittest tests.test_dashboard`, `python -m unittest discover -s tests -p "test_*.py"`, `python -m app --build-dashboard`, `git diff --check` 를 다시 통과했다.
- 실시간 수집기 상태가 오래된 KIS 검증 파일의 `regular-session` 값을 현재 장 상태처럼 보여주던 문제를 수정했다. 이제 현재 장 상태와 마지막 KIS 검증 당시 장 상태를 분리해서 보여준다.
- 로컬 setup 점검은 현재 장 상태와 장전 준비 시간을 계산해, 장외나 장전 준비 전 실시간 수집기 중지를 정상으로 해석한다.
- SQLite 연결을 명시적으로 닫도록 수정해 테스트 중 반복되던 `unclosed database` 경고를 제거했다.
- bash 파싱 검사: `scripts/get_live_runtime_status.sh`, `scripts/check_local_setup.sh` 모두 `parse ok`
- 대시보드 단위 테스트 `python -m unittest tests.test_dashboard`: `13 tests OK`
- 로컬 setup 점검 `scripts/check_local_setup.sh -AsJson`: `ok=true`
- 대시보드 상태: `running`, `http://127.0.0.1:8765`, `/health`와 `/api/dashboard.json` 응답 `ok`
- 실행 감시기 상태: `running`, 장 상태 `pre-open`, `live_runtime_should_run=false`
- 실시간 수집기 상태: `stopped`, 현재 장 상태 `pre-open`, 장전 준비 시작 전이므로 정상 대기
- 로컬 가상투자와 KIS 모의투자 정합성 `scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`
- `2026-04-30` 로컬 `AGENTS.md` 재구성:
- `D:/GitHub/ref_AGENTS.md`는 공통 설계 기준서로만 참고하고, 현재 저장소의 실제 구조와 기준 문서를 먼저 확인한 뒤 `AGENTS.md`를 다시 작성했다.
- 현재 존재하는 `app/`, `scripts/`, `tests/`, `runtime-data/`, `docs/` 기준으로 작업 순서, 운영 안전 규칙, 주요 명령, 검증 기준을 구체화했다.
- KIS 모의계좌, 로컬 가상투자 비교, 장외 CPU 절감, 대시보드 10분 새로고침, 감시기, NAS 백업 기준을 로컬 예외로 반영했다.
- `AGENTS.md`에 적은 주요 디렉터리, 파일, bash 스크립트 경로 존재 확인: 모두 `True`
- 공백 오류 검사 `git diff --check`: `ok`
- `2026-04-30` 문서 한글화 정리:
- git 추적 중인 Markdown 문서의 사람이 읽는 제목과 설명을 한글 기준으로 정리했다.
- 명령어, 파일 경로, 환경변수, API 이름, 모델명, 상태 키는 실행 정확성을 위해 원문 식별자를 유지했다.
- `docs/logbook.md` 는 오래된 누적 로그 대신 현재 상태와 최신 결과 중심으로 압축했다.
- git 추적 Markdown 본문 스캔: 영어-only 설명 문장 `0건`
- 공백 오류 검사 `git diff --check`: `ok`
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `79 tests OK`
- 테스트가 만든 `.tmp-tests` 임시 산출물은 워크스페이스 내부 경로 확인 뒤 삭제했다.
- `2026-04-30` 장마감 실행 검토:
- 실제 실행 행: `raw_market_ticks=619669`, `raw_orderbook_ticks=612546`, `minute_bars=3725`, `feature_rows=3725`, `labels=6700`, `predictions=7450`, `signals=3725`, `orders=1036`, `fills=5`, `broker_order_submissions=10`
- 예측 요약: `total=7450`, `evaluated=6700`, `pending=0`, `no_result=750`, `success_rate=0.110149`
- 장후 머신러닝 관리: `status=ok`, `features_written=7613`, `labels_written=13889`, LightGBM `train_rows=5912`, `validation_rows=1478`, `validation_accuracy=0.751691`
- 최신 백테스트: `rows_evaluated=1478`, `trades_taken=777`, `overall_accuracy=0.104871`, `cumulative_net_return_pct=-150.552985`
- 최신 워크포워드: `folds=734`, `rows_evaluated=7340`, `overall_accuracy=0.440054`, `cumulative_net_return_pct=-96.657339`
- 최신 도전자 모델 비교: `recommended_action=review_required`, `best_candidate=latest_lightgbm`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
- 브로커 기준 정렬 뒤 모의계좌 정합성: `ok=true`, `status=aligned_waiting_first_submission`, `mismatch_count=0`, `cash_gap=0`, `total_asset_gap=0`
- 대시보드 계좌 동기화: `account_sync.status=일치`, `cash_gap=0`, `raw_cash_gap=88045`
- 전체 테스트: `python -m unittest discover -s tests -p "test_*.py"` 기준 `79 tests OK`
- 실행 리포트 생성: `python -m app --build-runtime-report` 기준 `ok`
- 대시보드 생성: `python -m app --build-dashboard` 기준 `ok`

## 다음 명령

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
python -m app --train-lightgbm --horizon-min 15
./scripts/run_ml_shadow_cycle.sh
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
python -m app --build-runtime-report
python -m app --build-dashboard
./scripts/run_dashboard.sh
./scripts/start_dashboard_background.sh
./scripts/get_dashboard_status.sh
./scripts/stop_dashboard.sh
./scripts/start_live_runtime_background.sh
./scripts/get_live_runtime_status.sh
./scripts/stop_live_runtime.sh
./scripts/start_runtime_watchdog_background.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/stop_runtime_watchdog.sh
./scripts/check_local_setup.sh
./scripts/connect_kis_paper_account_interactive.sh
./scripts/reconcile_paper_accounts.sh
./scripts/start_hourly_repo_audit_background.sh
./scripts/get_hourly_repo_audit_status.sh
./scripts/bump_version.sh -Version 0.2.1
```
