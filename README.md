# Real-time Stock Price Prediction Program

국내 주식의 실시간 시세, 호가, 공시, 뉴스, 반응 데이터를 바탕으로 주가 변동을 연구하고 예측하는 로컬 연구용 프로그램이다.
현재 목표는 자동 실전 매매가 아니라 `실시간 수집 -> 특징 생성 -> 예측 -> 모의투자 검증 -> 리포트` 흐름을 안정적으로 만드는 것이다.

## 핵심 문서

- `AGENTS.md`: 저장소 운영 규칙의 단일 기준
- `docs/logbook.md`: 현재 상태, 활성 체크리스트, 최근 기록
- `docs/Current-Implementation.md`: 실제 구현 범위와 실행 방법
- `docs/Versioning.md`: `VERSION` 기반 버전 관리와 watcher 기준
- `docs/Repo-Audit-Automation.md`: 매시간 저장소 전체 점검 자동화 기준
- `docs/*.md`: 주제별 상세 설계와 참고 문서

## 현재 구현 상태

현재 저장소는 아래 기능까지 구현되어 있다.

- KIS REST 현재가/호가 조회
- KIS WebSocket 파서와 listener 준비
- SQLite / JSONL runtime 저장
- minute bar 생성
- feature / label 생성
- centroid baseline 학습
- LightGBM 학습 artifact 저장
- validation-tail backtest
- gap/max-train 제어가 가능한 walk-forward backtest
- walk-forward gate를 반영하는 challenger model 비교 보고서
- active model 명시 registry와 builtin baseline fallback
- LightGBM shadow challenger 비교
- online replay 기반 paper trading 상태 기록
- KIS WebSocket readiness / verification report
- runtime / backtest / walk-forward report 생성
- 로컬 모니터링 대시보드 snapshot 생성과 HTTP serving
- 대시보드 기본 언어 한글화와 상단 상태 영역 + 10탭 전환 UI
- 대시보드 기본 자동 새로고침 5분과 수동 `상태 업데이트` 버튼
- 대시보드에서 `모의투자(가상) / 모의계좌(실제) / 실 운용계좌 / 머신러닝 현황 / 상태 및 설정 / 예측현황 / 신호 & 주문현황 / 체결과 분봉 / 오늘의 리포트 / 기타` 탭 제공
- 대시보드 상단에서 `조회 범위`와 `기준 날짜`로 특정일 / 최근 기간 / 전체 누적 데이터 조회
- 학습 탭에서 `실운용 학습 상태`와 `오프라인 연구 결과`를 분리해 보여주는 구조
- 최근 예측에 기준가 대비 `예상 변동 금액`과 `실제 결과` 표시
- 예측현황 탭에서 선택 기간 기준 `예측 건수 / 확정 건수 / 성공률 / 수평선별 집계` 제공
- 신호 & 주문현황 탭에서 신호, 주문, 체결을 묶어서 확인하고 `매도 신호 차단 이유`를 함께 설명
- 오늘의 리포트 탭에서 계좌 결과, 예측 성공률, 체결 수, 분석과 고찰, 다음 접근 방향 자동 요약
- `모의투자(가상)` 탭은 `상태 설명 / 보유 종목 / 매수·매도 및 체결현황` 세로 하위 탭으로 다시 나뉜다.
- `모의투자(가상)` 탭의 보유 종목 화면은 열린 포지션이 없을 때도 `최근 종료 포지션`을 함께 보여준다.
- 대시보드의 실제 운용 데이터 전용 필터와 테스트 운용 흔적 정리 명령
- KIS 브로커 모의계좌 잔고 조회와 대시보드 반영
- 실시간 수집기 background 실행과 상태 확인 스크립트
- 장중에는 15분·60분 예측을 함께 기록하고, 신호와 주문은 15분 기준으로만 생성
- 샘플 WebSocket replay 데이터를 `kis-ws-replay` 출처와 `*-replay-*` ID로 분리
- 오염된 분(minute)을 대시보드 actual runtime 범위에서 제외하는 stricter filter
- 정규장 밖 KIS REST snapshot 분과 raw 집계를 대시보드 actual runtime 범위에서 제외
- 대시보드 start/status/stop 스크립트의 포트 점유 프로세스 추적 보강
- 대시보드 탭 선택 상태를 새로고침 뒤에도 유지하는 localStorage 처리
- paper 계좌번호만 8자리일 때 상품코드 `01` 기본 처리
- `.env`의 `여기에_상품코드` 같은 placeholder 값 자동 무시
- KIS REST rate-limit backoff 재시도
- 매시간 저장소 전체 점검 자동화와 상태 이어받기 구조
- audit progress JSON 배열 정합성 보강

현재 기준 버전은 `0.2.0` 이다.

## 확정된 ML 운영 방향

다음 구현 목표로 아래 방향을 확정했다.

- 학습 방식: `최근 60거래일 + 오늘 데이터`
- 운영 방식: `장중 추론`, `장후 재학습`
- 메인 모델: `LightGBM`
- 보조 모델: `baseline`, `centroid`, `linear-score`
- 검증 방식: `backtest + walk-forward + challenger 비교`
- 차트 분석: `이미지보다 수치 특징화 우선`

여기서 `최근 60거래일 + 오늘 데이터`는 과거 데이터를 삭제한다는 뜻이 아니다.
운영용 학습창은 최근 60거래일 중심으로 쓰되, 더 오래된 데이터는 drift 점검, 구간 비교, 재현, 회귀 검증, challenger 평가를 위해 보관하는 방향을 기본으로 한다.

## 계좌 값 해석

- `로컬 모의운용 계좌`
  - 프로그램 내부 모의주문 엔진이 기록한 가상 포트폴리오다.
  - 우리 전략이 어떤 신호, 주문, 체결을 만들었는지 확인하는 용도다.
- `브로커 모의계좌 잔고`
  - 한국투자 모의투자 계좌에서 직접 조회한 실제 잔고다.
  - 프로그램 내부 모의주문 기록과 별도로 존재하므로 값이 다를 수 있다.

## 저장소 구조

```text
app/                애플리케이션 코드
config/             TOML 설정, watchlist, autopush 설정
docs/               canonical 문서와 상세 설계 문서
migrations/         DB 스키마 초안
runtime-data/       로그, 리포트, 모델, 캐시, 실행 산출물
scripts/            반복 실행용 PowerShell 스크립트
tests/              unittest 기반 검증
.agents/skills/     저장소 전용 skill 자리
templates/          새 저장소 시작용 운영 팩 자리
```

## 빠른 실행

전체 테스트:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

synthetic 전체 흐름:

```powershell
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --build-runtime-report
```

단순 백테스트:

```powershell
python -m app --run-backtest --horizon-min 15
```

walk-forward 백테스트:

```powershell
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
```

최근 실험 기준 추천 조합:

```powershell
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
```

challenger 비교:

```powershell
python -m app --run-challengers --horizon-min 15
```

이제 challenger는 validation 구간 성능만 보지 않고 최신 walk-forward 결과를 함께 읽어 `promote`, `keep_active`, `review_required` 중 하나를 내린다.

active model을 안전하게 baseline으로 고정:

```powershell
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
```

LightGBM shadow 학습:

```powershell
python -m app --train-lightgbm --horizon-min 15
```

이 명령은 이제 artifact와 평가 기록만 만들고, active model을 자동으로 교체하지 않는다.

월요일 전 shadow ML 갱신 일괄 실행:

```powershell
.\scripts\run_ml_shadow_cycle.ps1
```

KIS WebSocket listener:

```powershell
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
```

KIS WebSocket 검증:

```powershell
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

이 검증은 이제 `연결 준비 완료`와 `실제 장중 데이터 수신 확인`을 분리해서 기록한다.

로컬 대시보드 snapshot 생성:

```powershell
python -m app --build-dashboard
```

로컬 대시보드 실행:

```powershell
.\scripts\run_dashboard.ps1
```

실행 후 브라우저에서 `http://127.0.0.1:8765` 를 열면 된다.
이 스크립트는 이제 background 실행 시에도 `py -3` 또는 실제 Python executable 경로를 먼저 찾아 사용한다.
기본 자동 새로고침 주기는 `5분`이고, 화면 우측 상단 `상태 업데이트` 버튼으로 수동 새로고침도 할 수 있다.

대시보드는 이제 기본적으로 `sample`, `synthetic`, `demo` 데이터를 제외하고 실제 KIS 기반 운용 데이터만 보여준다.
샘플 WebSocket 재생 결과도 이제 `replay` 계열로 따로 저장되어 실제 운용 데이터 범위에 들어오지 않는다.
대시보드는 이제 상단 상태 영역과 `10개 탭` 구조를 사용한다.
탭은 `모의투자(가상)`, `모의계좌(실제)`, `실 운용계좌`, `머신러닝 현황`, `상태 및 설정`, `예측현황`, `신호 & 주문현황`, `체결과 분봉`, `오늘의 리포트`, `기타` 로 나뉜다.
브로커 계좌 잔고는 `runtime-data/reports/kis-account/latest-account-paper.json` 과 `latest-account-live.json` 캐시를 읽고, 캐시가 오래되면 KIS REST로 새로 갱신한다.
로컬 모의운용 계좌는 프로그램 내부 가상 포트폴리오이고, 브로커 계좌는 한국투자에서 직접 조회한 실제 계좌 상태다.
학습 탭은 `실운용 학습 상태`와 `오프라인 연구 결과`를 함께 보여주되 서로 다른 의미임을 분명히 구분한다.
예측 탭은 `기준가`, `예측 결과`, `예상 변동`, `실제 결과`, `성공 여부`를 함께 보여준다.
신호와 주문은 `신호 & 주문현황` 탭에서 묶어서 확인할 수 있다.
`오늘의 리포트` 탭은 현재 범위 기준 계좌 운용 결과와 고찰, 다음 접근 방향을 자동 요약한다.
화면 상단 `조회 범위`와 `기준 날짜`를 바꾸면 특정일, 최근 3일/7일/30일, 전체 누적 데이터를 선택해서 볼 수 있다.
상단 상태 영역은 현재 운영 모드, 15분/60분 활성 모델, 장 상태, 실시간 수집기 상태, 자동 새로고침 주기, 현재 선택 범위를 함께 보여준다.
`모의투자(가상)` 탭은 프로그램 내부 가상 장부 기준 운용 상태를, `모의계좌(실제)` 탭은 한국투자 모의투자 계좌 직접 조회 잔고를, `실 운용계좌` 탭은 실전 계좌 조회 상태를 분리해서 보여준다.
`모의투자(가상)` 탭의 `매수·매도 및 체결현황` 화면은 `매수 주문 / 매도 주문 / 체결 / 최근 신호` 확장 탭으로 펼쳐 볼 수 있다.
실제 장중 데이터가 충분히 쌓이기 전까지 backtest, walk-forward, challenger는 오프라인 연구 결과로 표시된다.
기존 테스트용 운용 흔적을 SQLite에서 정리하려면 아래를 사용한다.

```powershell
.\scripts\cleanup_runtime_test_data.ps1
```

브로커 모의계좌 잔고만 새로 갱신:

```powershell
.\scripts\refresh_kis_account.ps1
python -m app --kis-account-balance
```

로컬 대시보드 background 시작 / 상태 / 중지:

```powershell
.\scripts\start_dashboard_background.ps1
.\scripts\get_dashboard_status.ps1
.\scripts\stop_dashboard.ps1
```

이 background 시작 스크립트는 이제 wrapper PowerShell 대신 실제 Python 실행 파일을 직접 찾아 서버를 띄운다.
가능하면 `pythonw.exe`를 우선 사용해 콘솔 종료 영향 없이 더 안정적으로 유지한다.
또한 `/health` 응답이 올라올 때까지 잠깐 기다린 뒤 상태 파일을 `running` 으로 기록한다.

월요일 시작 루틴 1회 실행:

```powershell
.\scripts\start_monday_runtime.ps1
```

이 스크립트는 대시보드를 띄우고, shadow ML 갱신과 KIS 사전 점검을 순서대로 수행한 뒤 현재 active 모델과 주요 리포트 상태를 요약한다.
이제 여기에 `실시간 수집기 background 시작`, `KIS 브로커 모의계좌 잔고 갱신`도 포함된다.

실시간 수집기 background 시작 / 상태 / 중지:

```powershell
.\scripts\start_live_runtime_background.ps1
.\scripts\get_live_runtime_status.ps1
.\scripts\stop_live_runtime.ps1
```

실시간 수집기가 켜져 있으면:

- watchlist 종목을 계속 수집한다.
- 새 분이 닫힐 때마다 15분과 60분 예측을 함께 기록한다.
- 신호와 주문 판단은 15분 기준으로만 수행한다.
- 대시보드 상단 `현재 프로그램 상태`와 `로컬 모의운용 계좌`가 `운용 중`으로 바뀐다.
- 최근 예측 표에는 방향 문구 대신 기준가 대비 `예상 변동`과 수평선 도달 뒤 `실제 결과`가 표시된다.

Hourly Repo Audit 1회 실행:

```powershell
.\scripts\run_hourly_repo_audit_iteration.ps1
```

Hourly Repo Audit Codex 자동화 권장:

- Codex 자동화로 등록하면 앱 UI에서 바로 중지할 수 있다.
- 아래 PowerShell background runner는 Codex 자동화가 없을 때만 쓰는 fallback 이다.

Hourly Repo Audit 백그라운드 시작(fallback):

```powershell
.\scripts\start_hourly_repo_audit_background.ps1
```

Hourly Repo Audit 상태 확인:

```powershell
.\scripts\get_hourly_repo_audit_status.ps1
```

프로세스가 죽었는데 상태가 `waiting` 으로 남아 있으면 이 스크립트는 `stale` 로 해석해서 보여준다.

## 새 기능을 어디에 둘까

새 기능 위치는 아래 기준으로 판단한다.

- 증권사 인증, 시세 조회, WebSocket 연결은 `app/brokers/`
- 외부 응답을 내부 이벤트로 바꾸는 로직은 `app/collectors/`
- 분봉, 특징 생성은 `app/features/`
- 라벨 생성은 `app/labels/`
- 모델 학습, 평가, 백테스트는 `app/models/`, `app/services/research.py`
- 실시간 예측, replay, online 처리 흐름은 `app/services/streaming.py`
- 모의주문, 포지션, 포트폴리오 상태는 `app/paper_trading/`, `app/portfolio/`
- 리스크 게이트는 `app/risk/`
- 리포트 생성은 `app/services/reporting.py`
- 운영 문서는 `AGENTS.md`, `docs/logbook.md`, `docs/Versioning.md`, 주제별 `docs/*.md`

새 기능이 두 영역에 걸치면 먼저 `입력`, `가공`, `판단`, `기록` 중 어느 책임이 중심인지 확인하고 그 레이어에 둔다.

## 버전 관리와 watcher

이 저장소는 root `VERSION` 파일을 release-ready 신호로 사용한다.

- 버전 변경 스크립트: `scripts/bump_version.ps1`
- 자동 점검 스크립트: `scripts\run_hourly_repo_audit_iteration.ps1`, `scripts\start_hourly_repo_audit.ps1`, `scripts\start_hourly_repo_audit_background.ps1`
- watcher 설정: `autopush.json`
- watcher 상태: `runtime-data/autopush/git-autopush-state.json`
- watcher 로그: `runtime-data/autopush/git-autopush.log`
- 실행 설정은 root `.env`가 있으면 자동으로 함께 읽는다.

자동 점검 산출물은 `runtime-data/reports/codex/automation/` 아래에만 쌓이고 repo-tracked 파일은 건드리지 않는다.

버전은 작업 마지막에 바꾸고, watcher가 그 변화를 감지해 자동 commit/push 또는 기존 release commit push를 수행한다.

## 현재 ML 운용 기준

현재 `15분` 기준 active model은 builtin `baseline-h15-v1` 이다.

- 이유 1: 최근 synthetic/runtime 검증에서 active baseline이 가장 안정적이었다.
- 이유 2: 최신 LightGBM 학습은 정상 동작하지만, 현재 validation accuracy와 challenger 결과가 아직 약하다.
- 이유 3: 따라서 LightGBM은 월요일 전까지 `shadow challenger`로 계속 학습하고, 검증 통과 전에는 active model로 승격하지 않는다.

## Canonical 문서와 Reference 문서

이 저장소는 문서를 아래처럼 구분한다.

- canonical 문서
  - `AGENTS.md`
  - `README.md`
  - `docs/logbook.md`
  - `docs/Versioning.md`
  - `docs/Current-Implementation.md`
- reference 문서
  - `docs/Architecture.md`
  - `docs/Implementation-Blueprint.md`
  - `docs/KIS-Integration-Plan.md`
  - 그 외 주제별 상세 설계 문서

current truth는 canonical 문서에 남기고, 상세 설계와 배경 설명은 reference 문서에 둔다.
