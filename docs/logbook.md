# 작업 기록

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
