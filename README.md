# Real-time Stock Price Prediction Program

국내 주식의 실시간 시세, 호가, 공시, 뉴스, 반응 데이터를 바탕으로 주가 변동을 연구하고 예측하는 로컬 연구용 프로그램이다.
현재 목표는 자동 실전 매매가 아니라 `실시간 수집 -> 특징 생성 -> 예측 -> 모의투자 검증 -> 리포트` 흐름을 안정적으로 만드는 것이다.

## 핵심 문서

- `AGENTS.md`: 저장소 운영 규칙의 단일 기준
- `docs/logbook.md`: 현재 상태, 활성 체크리스트, 최근 기록
- `docs/Current-Implementation.md`: 실제 구현 범위와 실행 방법
- `docs/Versioning.md`: `VERSION` 기반 버전 관리와 watcher 기준
- `docs/*.md`: 주제별 상세 설계와 참고 문서

## 현재 구현 상태

현재 저장소는 아래 기능까지 구현되어 있다.

- KIS REST 현재가/호가 조회
- KIS WebSocket 파서와 listener 준비
- SQLite / JSONL runtime 저장
- minute bar 생성
- feature / label 생성
- centroid baseline 학습
- validation-tail backtest
- walk-forward backtest
- challenger model 비교 보고서
- online replay 기반 paper trading 상태 기록
- KIS WebSocket readiness / verification report
- runtime / backtest / walk-forward report 생성
- paper 계좌번호만 8자리일 때 상품코드 `01` 기본 처리

현재 기준 버전은 `0.2.0` 이다.

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

challenger 비교:

```powershell
python -m app --run-challengers --horizon-min 15
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
- watcher 설정: `autopush.json`
- watcher 상태: `runtime-data/autopush/git-autopush-state.json`
- watcher 로그: `runtime-data/autopush/git-autopush.log`
- 실행 설정은 root `.env`가 있으면 자동으로 함께 읽는다.

버전은 작업 마지막에 바꾸고, watcher가 그 변화를 감지해 자동 commit/push 또는 기존 release commit push를 수행한다.

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
