# Logbook

## Current Snapshot

- date: `2026-04-11`
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
- runtime report와 backtest report가 `runtime-data/reports/` 아래에 생성된다.
- synthetic 데이터는 이제 `up/down/flat`이 섞이도록 조정되어 연구 지표가 더 의미 있게 나온다.

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

- 전체 테스트: `33 tests OK`
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
  - candidates compared: `4`
- 최신 KIS verification:
  - `ok=false`
  - missing requirements: `KIS credentials`, `python websockets package`

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

## Next Commands

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
python -m app --build-runtime-report
.\scripts\bump_version.ps1 -Version 0.2.1
```
