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
- SQLite 기반 raw tick, orderbook, minute bar, feature, label, prediction, paper trading, evaluation 저장이 된다.
- centroid baseline 학습, validation-tail backtest, walk-forward backtest가 된다.
- LightGBM 학습 artifact 저장이 된다.
- gap_rows / max_train_rows 를 받는 walk-forward backtest가 된다.
- baseline / linear-score / centroid를 비교하는 challenger 구조가 추가되었다.
- latest LightGBM challenger 비교가 추가되었다.
- challenger 추천 action, walk-forward gate, leaderboard 기록이 추가되었다.
- active model은 registry로만 명시하고, registry가 없으면 baseline builtin으로 fallback 한다.
- runtime report와 backtest report가 `runtime-data/reports/` 아래에 생성된다.
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
- [ ] 실제 KIS WebSocket 장중 수신 검증

## Version And Watcher

- watcher가 보는 기준 파일은 root `VERSION` 이다.
- 저장소 opt-in 파일은 root `autopush.json` 이다.
- 현재 설정은 `enabled=true`, `trigger=version-change`, `branch=main` 이다.
- 버전을 바꾸는 명령은 `scripts/bump_version.ps1` 를 사용한다.
- watcher 확인 위치
  - `runtime-data/autopush/git-autopush.log`
  - `runtime-data/autopush/git-autopush-state.json`

## Latest Verified Results

- 전체 테스트: `37 tests OK`
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
  - `market_data_flow_ok=false`
  - `session_status=weekend`
  - `frames_received=10`
  - `control_frames=10`
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
.\scripts\start_hourly_repo_audit_background.ps1
.\scripts\get_hourly_repo_audit_status.ps1
.\scripts\bump_version.ps1 -Version 0.2.1
```
