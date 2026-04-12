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
- baseline / linear-score / centroid를 비교하는 challenger 구조가 추가되었다.
- challenger 추천 action과 leaderboard 기록이 추가되었다.
- runtime report와 backtest report가 `runtime-data/reports/` 아래에 생성된다.
- synthetic 데이터는 이제 `up/down/flat`이 섞이도록 조정되어 연구 지표가 더 의미 있게 나온다.
- Hourly Repo Audit 자동화 스크립트와 상태 파일 구조가 추가되었다.

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
- [x] Hourly Repo Audit 자동화 기본 구조
- [x] Hourly Repo Audit 상태 이어받기 재실행 검증
- [x] Hourly Repo Audit 백그라운드 runner 시작
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

- 전체 테스트: `36 tests OK`
- 최신 synthetic dev cycle:
  - training accuracy: `0.866667`
  - backtest trades: `13`
  - backtest cumulative net return pct: `25.870005`
  - walk-forward folds: `4`
  - walk-forward trades: `21`
  - walk-forward cumulative net return pct: `16.040505`
- 최신 challenger review:
  - best candidate: `baseline_builtin`
  - best model version: `baseline-h15-v1`
  - recommended action: `promote`
  - candidates compared: `4`
- 최신 KIS verification:
  - `connection_ready=true`
  - `market_data_flow_ok=false`
  - `session_status=weekend`
  - `frames_received=5`
  - `control_frames=5`

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

## Next Commands

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
python -m app --build-runtime-report
.\scripts\start_hourly_repo_audit_background.ps1
.\scripts\get_hourly_repo_audit_status.ps1
.\scripts\bump_version.ps1 -Version 0.2.1
```
