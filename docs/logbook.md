# Logbook

## Current Snapshot

- date: `2026-04-12`
- current version: `0.2.0`
- latest release commit: `8f601ba`
- watcher mode: `VERSION` change trigger
- watcher repo opt-in: enabled
- canonical docs synced: yes

## Current State

- Python 기반 로컬 연구, 수집, 예측 골격이 구현되어 있다.
- KIS REST 현재가와 호가 조회가 구현되어 있다.
- KIS WebSocket 파서와 listener 준비가 되어 있고 reconnect 인자가 추가되어 있다.
- KIS WebSocket readiness / verification report 경로가 추가되어 있다.
- KIS 브로커 모의계좌 잔고 조회와 캐시 리포트 생성이 된다.
- SQLite 기반 raw tick, orderbook, minute bar, feature, label, prediction, paper trading, evaluation 저장이 된다.
- centroid baseline 학습, validation-tail backtest, walk-forward backtest가 된다.
- LightGBM 학습 artifact 저장이 된다.
- gap_rows / max_train_rows 를 받는 walk-forward backtest가 된다.
- baseline / linear-score / centroid를 비교하는 challenger 구조가 추가되었다.
- latest LightGBM challenger 비교가 추가되었다.
- challenger 추천 action, walk-forward gate, leaderboard 기록이 추가되었다.
- active model은 registry로만 명시하고, registry가 없으면 baseline builtin으로 fallback 한다.
- runtime report와 backtest report가 `runtime-data/reports/` 아래에 생성된다.
- 로컬 운영용 dashboard snapshot과 HTTP serving이 추가되었다.
- KIS REST collector는 짧은 rate-limit burst에 대해 retry/backoff를 한다.
- synthetic 데이터는 이제 `up/down/flat`이 섞이도록 조정되어 연구 지표가 더 의미 있게 나온다.
- Hourly Repo Audit 자동화 스크립트와 상태 파일 구조가 추가되었다.
- audit progress 상태 파일의 배열 정합성 방어가 추가되었다.
- 다음 ML 운영 기준은 `최근 60거래일 + 오늘 데이터`, `장중 추론`, `장후 재학습`, `메인 모델 LightGBM` 으로 확정됐다.
- 과거 데이터는 학습창 밖으로 밀리더라도 삭제하지 않고 warm/cold 비교 자산으로 보관한다.

## Active Checklist

- [x] KIS REST 수집 구현
- [x] SQLite 적재와 runtime writer 구현
- [x] minute bar / feature / label 생성 구현
- [x] baseline 학습 구현
- [x] validation-tail backtest 구현
- [x] walk-forward backtest 구현
- [x] runtime report 구현
- [x] VERSION 기반 watcher opt-in 정리
- [x] README와 logbook 기준으로 오래된 주제 문서 역할 재정리
- [x] 다중 모델 challenger 비교 구조
- [x] challenger 추천과 실제 승격 상태 분리
- [x] challenger walk-forward gate
- [x] Hourly Repo Audit 자동화 기본 구조
- [x] Hourly Repo Audit 상태 이어받기 재실행 검증
- [x] Hourly Repo Audit 백그라운드 runner 시작
- [x] Hourly Repo Audit progress 배열 정합성 보강
- [x] LightGBM 학습 파이프라인 추가
- [x] 로컬 모니터링 dashboard 추가
- [x] dashboard background start/status/stop 스크립트 추가
- [x] monday runtime starter 스크립트 추가
- [x] dashboard 실제 운용 데이터 전용 필터와 test runtime cleanup
- [x] replay 데이터를 실제 운용 데이터와 분리하고 old dashboard port-owner 추적 보강
- [x] dashboard 한글 기본 UI와 3탭 전환 구조
- [x] dashboard 학습 탭의 오프라인 연구 결과 / 실운용 데이터 해석 구분
- [x] dashboard 학습 탭의 실운용 학습 상태 / 오프라인 연구 결과 구조 분리
- [x] 실제 KIS WebSocket 장중 수신 검증
- [x] KIS 브로커 모의계좌 잔고 조회와 dashboard 반영

## Version And Watcher

- watcher가 보는 기준 파일은 root `VERSION` 이다.
- 저장소 opt-in 파일은 root `autopush.json` 이다.
- 현재 설정은 `enabled=true`, `trigger=version-change`, `branch=main` 이다.
- 버전을 바꾸는 명령은 `scripts/bump_version.ps1` 를 사용한다.
- watcher 확인 위치
  - `runtime-data/autopush/git-autopush.log`
  - `runtime-data/autopush/git-autopush-state.json`

## Latest Verified Results

- dashboard/runtime cleanup targeted tests: `6 tests OK`
- streaming replay isolation tests: `3 tests OK`
- dashboard korean tab UI tests: `4 tests OK`
- 최신 synthetic dev cycle:
  - training accuracy: `0.866667`
  - backtest trades: `13`
  - backtest cumulative net return pct: `25.870005`
  - walk-forward folds: `3`
  - walk-forward gap rows: `15`
  - walk-forward max train rows: `40`
  - walk-forward trades: `26`
  - walk-forward cumulative net return pct: `30.874830`
- 최신 challenger review:
  - active model version: `baseline-h15-v1`
  - best candidate: `active_model`
  - best model version: `baseline-h15-v1`
  - recommended action: `keep_active`
  - walk-forward gate status: `needs_review`
  - decision reason: `The top challenger matches the current active model.`
  - candidates compared: `5`
- 최신 LightGBM training:
  - model version: `lightgbm-h15-v1`
  - validation accuracy: `0.0`
  - activation applied: `false`
- 최신 KIS verification:
  - `connection_ready=true`
  - `market_data_flow_ok=true`
  - `session_status=regular-session`
  - `frames_received=20`
  - `control_frames=2`
- 최신 KIS broker account:
  - `ok=true`
  - `cash_balance=10000000`
  - `total_evaluation_amount=10000000`
  - `position_row_count=0`
- 최신 KIS REST preflight:
  - current price 조회: `ok`
  - orderbook 조회: `ok`
  - single-symbol KIS dev cycle: `success_events=1`, `failure_events=0`

## Recent Log

- `2026-04-11`
  - v0.2.0 release commit and push completed.
  - watcher가 이 저장소의 `VERSION=0.2.0` 변화를 감지하고 push 상태를 갱신했다.
  - walk-forward backtest와 KIS WebSocket reconnect 준비를 추가했다.
  - SQLite `paper_positions.opened_at` 호환성 보강을 넣었다.
  - canonical 운영 문서 세트를 `AGENTS / README / logbook / Versioning` 기준으로 재정리했다.
  - 깨진 legacy `docs/*.md`를 UTF-8 기준의 reference 문서로 전면 정리했다.
  - root `.env` 자동 로딩을 추가했다.
  - challenger review CLI와 report 경로를 추가했다.
  - KIS WebSocket verification CLI와 report 경로를 추가했다.
  - 실제 장중 검증은 현재 환경에 `.env`와 `websockets`가 없어 아직 미완료 상태다.
- `2026-04-12`
  - challenger 승격 추천 규칙과 leaderboard 기록을 추가했다.
  - challenger 리포트는 이제 `recommended_model_version`, `promotion_requested`, `promotion_applied`, `promoted_model_version`, `active_model_version_after_run` 를 분리 기록한다.
  - root `.env`와 `websockets` 준비가 완료되어 KIS WebSocket 연결 준비 검증은 통과했다.
  - `2026-04-12 00:54 KST` 검증은 일요일 야간이라 control frame만 들어왔고 시장 데이터 수신 검증은 아직 남아 있다.
  - paper 계좌번호만 8자리일 때 상품코드 `01`을 기본값으로 쓰도록 설정 로더를 보강했다.
  - KIS verification report는 이제 `connection_ready` 와 `market_data_flow_ok` 를 분리해서 기록한다.
  - 매시간 저장소 전체 점검을 위한 Hourly Repo Audit 자동화 스크립트, 상태 스키마, 상태 파일 경로를 추가했다.
  - 자동화 산출물은 `runtime-data/reports/codex/automation/` 아래에만 쌓이도록 분리했다.
  - `2026-04-12 09:32 KST` 수동 재실행이 성공했고 `latest-progress.json` 과 backlog가 stable id 기반으로 이어받기 되는 것을 확인했다.
  - `AUD-001`은 현재 회차 기준 resolved로 내려갔고, 주요 open item은 `AUD-004`, `AUD-002`, `AUD-003`, `AUD-005` 순서로 정리되었다.
  - background 시작용 `scripts/start_hourly_repo_audit_background.ps1` 를 추가했고 runner 상태는 `runtime-data/reports/codex/automation/state/runner-state.json` 으로 확인한다.
  - `2026-04-12 09:40 KST` background runner를 실제로 시작했고 첫 즉시 실행이 진행 중이다.
  - 이후 확인 결과 자체 background runner는 `09:40` 회차까지만 완료했고 `10:00` 회차까지 유지되지 않았다. 앞으로는 Codex 자동화를 우선 스케줄러로 쓰고, 상태 스크립트는 죽은 pid 를 `stale` 로 해석한다.
  - walk-forward는 `gap_rows=15` 와 `max_train_rows` 를 지원하도록 확장했다.
  - `max_train_rows=30/40/50` 실험을 실제로 돌렸고, `30`은 성능이 크게 악화됐고 `40`은 현재 최고값과 같아 최신 기준선으로 유지했다.
  - 최신 challenger는 validation 성능이 좋아도 walk-forward gate가 약하면 `review_required` 로 남기도록 바뀌었다.
  - Hourly Repo Audit 재실행으로 `AUD-006` 은 resolved 로 내려갔고, 새 문서 동기화 항목 `AUD-007` 이 확인되었다.
  - ML 운영 방향을 `최근 60거래일 + 오늘 데이터`, `장중 추론`, `장후 재학습`, `메인 모델 LightGBM`, `보조 모델 baseline/centroid/linear-score` 로 확정했다.
  - `최근 60거래일 + 오늘 데이터` 는 운영용 학습창 기준이며, 더 오래된 데이터는 drift 점검, 구간 비교, 회귀 검증, challenger 평가용으로 계속 보관하는 방향으로 정리했다.
  - LightGBM 학습 파이프라인을 실제 코드로 추가했다.
  - LightGBM artifact는 이제 자동으로 active model이 되지 않고 shadow challenger로 남는다.
  - active runtime model을 명시적으로 `baseline-h15-v1` 로 되돌렸다.
  - challenger report는 이제 `latest_lightgbm` 후보를 함께 기록한다.
  - 현재 기준으로는 월요일 runtime/paper 운용은 `baseline active + LightGBM shadow` 조합이 가장 안전하다.
  - 월요일 전 preflight로 `run_ml_shadow_cycle`, KIS WebSocket verification, KIS 현재가/호가 조회를 다시 실행했다.
  - KIS REST 연속 호출에서 보이던 `EGW00201` rate-limit 오류를 collector retry/backoff로 완화했고, 이후 single-symbol `run-kis-dev-cycle`이 `success=1 failure=0`으로 통과했다.
  - 월요일 운영 중 화면으로 볼 수 있도록 `latest-dashboard.html/json` 생성과 `run_dashboard.ps1` 기반 로컬 HTTP 대시보드를 추가했다.
  - dashboard는 active model, KIS readiness, 포트폴리오, 최근 예측/신호/주문/체결/분봉, audit backlog를 한 화면에서 보여준다.
  - dashboard는 이제 기본적으로 `sample`, `synthetic`, `demo` 데이터를 제외한 실제 KIS 기반 운용 데이터만 보여준다.
  - sample WebSocket replay는 이제 `kis-ws-replay` 출처와 `pred-replay-*`, `paper-order-replay-*` 같은 replay 전용 ID를 사용한다.
  - dashboard actual-runtime 필터는 실제 출처만 존재하는 minute만 허용하고, 실제/테스트 출처가 섞인 minute는 제외하도록 강화했다.
  - `scripts/cleanup_runtime_test_data.ps1` 와 `python -m app --cleanup-runtime-test-data` 를 추가해 기존 SQLite의 test serving/paper 흔적을 정리할 수 있게 했다.
  - 현재 root runtime 데이터 정리 결과 demo prediction/signal/order/fill/portfolio snapshot/reconciliation/replay 항목은 제거됐고, 실제 시간대와 맞는 항목만 남겼다.
  - replay/online legacy serving rows를 다시 정리했고, 최신 dashboard JSON/API 기준 최근 prediction/signal/order/fill은 `0` 건으로 확인됐다.
  - dashboard 전용 테스트 2건을 추가했고 전체 테스트는 `40 tests OK`로 다시 확인했다.
  - `run_dashboard.ps1`의 PowerShell 예약 변수 `$Host` 충돌을 수정해 기본 실행이 바로 되도록 보정했다.
  - dashboard background start/status/stop 스크립트를 추가해 장중에 서버를 따로 띄우고 상태를 확인하거나 중지할 수 있게 했다.
  - `start_monday_runtime.ps1`를 추가해 대시보드 시작, shadow ML 갱신, KIS 사전 점검, runtime/dashboard 리포트 갱신을 한 번에 묶었다.
  - `start_dashboard_background.ps1`의 공백 포함 경로 전달 방식을 `-File` 에서 `-Command` 호출로 바꿔, `J:\GitHub\Real-time stock price prediction program` 같은 경로에서도 dashboard server가 정상 시작되도록 수정했다.
  - 이후 남아 있던 오래된 dashboard port owner 문제를 정리했고, `start_dashboard_background.ps1`, `get_dashboard_status.ps1`, `stop_dashboard.ps1`가 이제 상태 파일 pid뿐 아니라 실제 `8765` 포트 점유 프로세스와 `/health` 응답을 함께 확인한다.
  - dashboard 기본 언어를 한글로 바꿨고, 본문을 `거래 현황`, `학습 현황`, `그 외` 3개 탭으로 나눠 클릭 시 화면 전환되도록 정리했다.
  - dashboard 학습 탭에 `학습 데이터 해석` 카드를 추가해, 실제 운용 라벨이 없을 때는 현재 값이 저장된 오프라인 연구 결과라는 점을 명확히 표시하도록 보강했다.
  - dashboard 학습 탭을 `실운용 학습 상태`와 `오프라인 연구 결과`로 다시 나눠, 활성 모델 상태와 연구용 챌린저 결과가 같은 종류의 값처럼 보이지 않도록 정리했다.
  - background dashboard 실행이 Windows `python.exe` 앱 별칭에 막히지 않도록 `run_dashboard.ps1` 가 실제 Python executable 경로를 먼저 찾게 수정했다.
- `2026-04-13`
  - `KIS 브로커 모의계좌 잔고 조회`를 추가했고 결과를 `runtime-data/reports/kis-account/latest-account.json` 과 `.md`로 남기도록 정리했다.
  - paper 계좌의 `KIS_PRODUCT_CODE_PAPER` 가 `.env.example` placeholder 문자열이어도 자동으로 빈값으로 간주하고 `01`을 적용하도록 설정 로더를 보강했다.
  - KIS REST 클라이언트는 이제 `EGW00121`, `EGW00123` 토큰 오류를 만나면 access token을 자동 재발급한 뒤 한 번 더 재시도한다.
  - 실제 장중 재검증 결과 `connection_ready=true`, `market_data_flow_ok=true`, `session_status=regular-session` 으로 확인됐다.
  - 실제 브로커 모의계좌 조회 결과 현재 예수금 `10,000,000원`, 보유 종목 `0건`이 확인됐다.
  - 대시보드 거래 탭은 이제 `로컬 모의운용 계좌`와 `브로커 모의계좌 잔고`를 분리해서 보여준다.
  - `start_monday_runtime.ps1` 는 이제 KIS 브로커 모의계좌 잔고를 함께 갱신하고 요약에 포함한다.
  - `start_dashboard_background.ps1` 는 이제 wrapper PowerShell 대신 실제 Python 실행 파일을 직접 background 로 띄운다.
  - 가능하면 `pythonw.exe` 를 우선 사용해 콘솔 종료 영향 없이 background 대시보드가 더 안정적으로 유지되도록 보강했다.
  - dashboard background 시작 후 `/health` 응답을 기다린 뒤 상태 파일을 `running` 으로 기록하도록 보강했다.
  - 장중 기준으로 `start_dashboard_background -> 25초 유지 -> get_dashboard_status -> /health -> /` 재검증이 성공했고, 포트 `8765`의 실제 소유 PID와 상태 파일 PID가 일치하는 것을 확인했다.

## Next Commands

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
python -m app --train-lightgbm --horizon-min 15
.\scripts\run_ml_shadow_cycle.ps1
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
python -m app --build-runtime-report
python -m app --build-dashboard
.\scripts\run_dashboard.ps1
.\scripts\start_dashboard_background.ps1
.\scripts\get_dashboard_status.ps1
.\scripts\stop_dashboard.ps1
.\scripts\start_monday_runtime.ps1
.\scripts\start_hourly_repo_audit_background.ps1
.\scripts\get_hourly_repo_audit_status.ps1
.\scripts\bump_version.ps1 -Version 0.2.1
```
