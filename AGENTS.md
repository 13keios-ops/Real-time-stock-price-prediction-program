# 작업 지침

> 이 파일은 이 저장소에서 Codex가 따라야 할 로컬 실행 지침이다.
> `D:/GitHub/ref_AGENTS.md`는 공통 설계 기준서일 뿐이며, 이 파일에는 현재 저장소에 실제로 존재하는 경로와 명령만 둔다.

## 1. 미션

- 이 저장소는 국내 주식 실시간 데이터 수집, 특징 생성, 15분/60분 예측, 로컬 가상 모의운용, KIS 모의계좌 검증, 대시보드 리포트를 안정화하는 연구용 프로그램이다.
- 현재 기본 운영은 실전 자동매매가 아니라 `paper` 기준 검증이다.
- Codex의 우선순위는 실제 상태 확인, 안전한 변경, 검증 가능한 실행, 기준 문서 동기화다.

## 2. 작업 시작 전 읽을 문서

비사소한 작업, 코드/문서 수정, 장시간 실행, 커밋, 푸시 전에는 아래 순서로 다시 읽는다.

1. `AGENTS.md`
2. `README.md`
3. `docs/logbook.md`
4. 최신 `docs/logbook_archive/logbook_*.md` 1개
5. `docs/Current-Implementation.md`
6. `docs/Versioning.md`
7. 작업 범위와 직접 관련된 `docs/*.md`

새 기능 위치나 레이어 경계가 관련되면 `README.md`의 `새 기능을 어디에 둘까` 섹션을 다시 확인한다.
자격정보, 비공개 원격, 외부 미러, 백업 정책이 관련되면 형제 폴더 `../secrets/README.local.md`가 있을 때 함께 읽는다.

## 3. 문서 역할

- `AGENTS.md`: Codex 로컬 작업 규칙
- `README.md`: 프로젝트 개요, 저장소 구조, 주요 실행 방법
- `docs/logbook.md`: 현재 상태, 활성 체크리스트, 최신 검증 결과
- `docs/Current-Implementation.md`: 실제 구현 범위와 운영 기준
- `docs/Versioning.md`: `VERSION`, watcher, 자동 commit/push 기준
- `RECOVERY.md`: GitHub + NAS 복구 기준
- `runtime-data/`: 실행 로그, 리포트, 캐시, 모델 산출물

현재 사실 기준은 기준 문서에만 남긴다.
같은 내용을 여러 문서에 길게 반복하지 않는다.

## 4. 기본 작업 흐름

1. 현재 상태를 대화 맥락이 아니라 파일, 로그, 상태 명령으로 확인한다.
2. 변경 범위를 작게 잡고, 실제 저장소 구조와 맞지 않는 공통 문구는 넣지 않는다.
3. 코드 변경이 있으면 관련 문서도 같은 작업 안에서 갱신한다.
4. 검증 명령을 실제로 실행하고 결과를 확인한다.
5. 산출물 경로, 삭제한 임시 자산, 다음 연결점이 있으면 `docs/logbook.md`에 남긴다.
6. 변경 파일이 있으면 가능한 한 같은 턴에서 commit과 push까지 마친다.
7. 사용자가 직접 해야 하는 작업은 Cybos Plus 로그인처럼 Codex가 물리적으로 처리할 수 없는 필수 작업만 안내하고, 그 외 구현·검증·문서화·커밋·푸시는 Codex가 자율적으로 처리한다.

답변은 쉬운 한국어를 먼저 쓴다.
영어 개발 용어와 약어는 필요할 때만 쓰고, 처음에는 풀어서 설명한다.
최종 답변 전에는 `현재 작업 모드`, `답변 접두어`, `활성 체크리스트 갱신 여부`, `기준 문서 반영 여부`를 한 줄 체크포인트로 확인한다.

## 5. 저장소 구조와 배치 기준

- `app/brokers/`: KIS 인증, REST 조회, WebSocket 연결
- `app/collectors/`: 외부 응답을 내부 이벤트로 변환
- `app/features/`, `app/labels/`: 분봉, 특징, 라벨 생성
- `app/models/`, `app/services/research.py`: 모델 학습, 평가, 백테스트
- `app/services/streaming.py`: 실시간 예측, 재생, 온라인 처리 흐름
- `app/paper_trading/`, `app/portfolio/`: 모의주문, 포지션, 포트폴리오
- `app/risk/`: 리스크 게이트
- `app/services/reporting.py`: 실행 리포트 생성
- `config/`: 설정, watchlist, autopush 설정
- `scripts/`: 반복 실행 bash 스크립트
- `tests/`: `unittest` 기반 검증

기본 의존 방향은 `brokers/collectors -> features/labels -> models/services -> paper_trading/portfolio/risk -> reporting` 으로 유지한다.

## 6. 주요 명령

전체 테스트:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

합성 데이터 전체 흐름:

```bash
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
./scripts/run_full_synthetic_cycle.sh
```

리포트와 대시보드:

```bash
python -m app --build-runtime-report
python -m app --build-dashboard
./scripts/run_dashboard.sh
./scripts/start_dashboard_background.sh
./scripts/get_dashboard_status.sh
./scripts/stop_dashboard.sh
```

모델 검증:

```bash
python -m app --train-lightgbm --horizon-min 15
python -m app --run-backtest --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
python -m app --run-challengers --horizon-min 15
./scripts/run_ml_shadow_cycle.sh
./scripts/run_post_close_ml_maintenance.sh
./scripts/rebuild_actual_ml_state.sh
```

KIS와 모의계좌:

```bash
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
./scripts/verify_kis_ws.sh
./scripts/refresh_kis_account.sh
./scripts/reconcile_paper_accounts.sh
./scripts/verify_paper_dual_account_match.sh -AsJson
./scripts/verify_paper_dual_account_match.sh -SyncInitialCash -AlignToBroker -AsJson
```

실시간 수집기와 감시기:

```bash
./scripts/start_live_runtime_background.sh
./scripts/get_live_runtime_status.sh
./scripts/stop_live_runtime.sh
./scripts/start_runtime_watchdog_background.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/stop_runtime_watchdog.sh
```

복구와 자동 시작:

```bash
./scripts/check_local_setup.sh
./scripts/restore_kis_env_interactive.sh
./scripts/connect_kis_paper_account_interactive.sh
./scripts/start_runtime_autoboot.sh
./scripts/install_runtime_startup_launcher.sh
./scripts/get_runtime_startup_launcher_status.sh
./scripts/remove_runtime_startup_launcher.sh
```

버전 갱신:

```bash
./scripts/bump_version.sh -Version 0.2.1
```

## 7. 운영 안전 규칙

- 기본 거래 모드는 `paper`다.
- 실전 주문은 기본 비활성화 상태로 둔다.
- KIS 앱 키, 앱 시크릿, 계좌번호, 토큰, 원격 비공개 정보는 git 추적 파일에 쓰지 않는다.
- 저장소 루트 `.env`는 로컬 실행용이며 커밋하지 않는다.
- 모의투자 계좌 화면에 상품코드가 없으면 `KIS_PRODUCT_CODE_PAPER`는 빈 값으로 둘 수 있다.
- `ENABLE_BROKER_PAPER_MIRRORING=true` 일 때 로컬 가상 주문이 KIS 모의계좌에도 제출될 수 있다.
- 로컬 가상 계좌와 KIS 모의계좌 비교는 `총자산 - 주식평가액` 으로 계산한 브로커 유효현금을 기준으로 본다.
- 장외와 설정된 휴장일에는 실시간 수집기를 무리하게 재기동하지 않는다. 실행 감시기는 정규장 시작 60분 전부터 장전 준비로 켜되, `config/market_calendar.toml`의 `holidays` 날짜는 휴장으로 본다.
- 대시보드 전체 스냅샷 재생성은 기본 10분 간격으로 제한해 CPU 사용을 줄인다.
- 삭제나 정리 작업은 반드시 대상 경로가 저장소 내부인지 확인하고, 실제 브로커 체결 시각의 포트폴리오 스냅샷은 실제 운용 데이터로 보존한다.

## 7-1. ML 실험 자율 범위

ML 실험에 한해 Codex는 운영자 승인 없이 아래 범위 안에서 스스로 판단하고 실행한다.

자율 허용:

- 피처 조합 선택 및 변경
- 실험 방법 설계 (학습 파라미터, split 방식 등)
- 하이퍼파라미터 조정
- 실험 결과 해석 및 다음 실험 스스로 설계
- 중간 실패 시 대안 방법으로 전환
- 실험 결과가 좋지 않을 때 원인 분석 및 재실험

운영자 보고 필요 (자율 범위 밖):

- 3회 연속 실험에서 개선 없을 때
- 완료 조건 충족 시 (승격 승인 요청)
- 데이터 소스 추가/변경 필요 시
- 스프린트 목표 자체를 바꿔야 할 때
- app/risk/ 관련 변경이 필요할 때
- 운영 스크립트(scripts/) 구조 변경 시

보고 형식:
🔴 운영자 판단 필요 또는
🟢 완료 조건 충족 형식으로 출력 후 대기.

## 8. 산출물 규칙

- 현재 Ubuntu WSL2 배포판은 `D:\WSL\Ubuntu` 아래에 둔다. 따라서 WSL 저장소 내부의 `runtime-data/`, `.tmp-tests/`, 모델 산출물도 물리적으로 D드라이브에 위치하는 것을 기준으로 한다.
- 이 저장소 작업에서 새 데이터 수집, 다운로드, 스냅샷, 장기 보관, 대용량 임시 파일은 어쩔 수 없는 OS/도구 캐시를 제외하고 D드라이브만 사용한다.
- 누적 실행 산출물은 `runtime-data/` 아래에 둔다.
- 새로 내려받거나 수집하는 대용량 외부 데이터는 WSL 저장소나 기존 `D:\GitHub\Real-time-stock-price-prediction-program` 폴더가 아니라 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래에 보관한다. WSL에서는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 로 접근한다.
- Windows 전용 수집 스크립트가 임시 DB나 중간 파일을 만들 때도 기본값은 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래로 둔다. `C:\Temp`는 이 저장소 기본 경로로 사용하지 않는다.
- root `results/`는 만들지 않는다.
- 임시 테스트 산출물은 `.tmp-tests/` 아래에 둘 수 있고, 검증 뒤 삭제 가능하다.
- 모델 산출물은 `runtime-data/ml/` 아래에 둔다.
- 대시보드와 실행 리포트는 `runtime-data/reports/` 아래에 둔다.
- git으로 추적할 가치는 작고 재현에 필요한 문서, 설정 예시, 메타데이터에 한정한다.

## 9. 검증 기준

- 문서만 바꿨으면 최소 `git diff --check`를 실행한다.
- Python 코드, 앱 동작, 스크립트 동작이 바뀌면 `python -m unittest discover -s tests -p "test_*.py"`를 우선 실행한다.
- 대시보드 관련 변경은 `python -m unittest tests.test_dashboard`와 `python -m app --build-dashboard`를 함께 고려한다.
- 브로커 모의계좌 동기화 변경은 `python -m unittest tests.test_broker_paper_sync tests.test_paper_reconciliation`을 함께 고려한다.
- KIS WebSocket 변경은 `python -m unittest tests.test_kis_ws_parser tests.test_kis_ws_verification`을 함께 고려한다.
- bash 스크립트 변경은 최소 파싱 검사를 수행한다.
- 네트워크나 장 시간에 따라 실패할 수 있는 KIS 실시간 검증은 장 상태를 함께 기록한다.

## 10. 감시기와 자동화

- 이 저장소는 저장소 루트 `VERSION` 파일을 배포 준비 신호로 사용한다.
- 감시기 설정은 `autopush.json` 이고, 현재 기준 브랜치는 `main` 이다.
- 감시기 상태와 로그는 `runtime-data/autopush/` 아래에 있다.
- 버전은 작업 마지막에 바꾸고, 감시기 또는 수동 commit/push 흐름과 충돌하지 않게 한다.
- 매시간 저장소 점검 산출물은 `runtime-data/reports/codex/automation/` 아래에만 남기고 git 추적 파일을 직접 수정하지 않는다.

## 11. 완료 기준

- 변경 내용이 현재 저장소 구조와 맞는지 확인한다.
- 없는 경로, 없는 명령, 공통 기준서의 예시 문구를 남기지 않는다.
- 필요한 검증을 실제로 실행한다.
- 관련 기준 문서와 `docs/logbook.md`를 갱신한다.
- 작업 트리에 의도하지 않은 변경이 없는지 확인한다.
- 불필요한 백그라운드 프로세스를 남기지 않는다.

<!-- NAS_BACKUP_START -->
## NAS 백업 운영

- 이 저장소는 NAS 전체 백업 복구 패키지를 사용한다.
- 기본 정책은 비밀값 제외 전체 백업, 최신 3개 보관, 주 1회 정기 실행, 중요 기간 강제 백업이다.
- 백업 패키지는 root `.env*`, KIS 토큰 캐시, runtime 로그, private key 계열 파일을 포함하지 않는다.
- 현재 NAS 공유 루트 기준은 \\192.168.0.2\backup 이다.
- 정책이 바뀌면 RECOVERY.md, README.md, AGENTS.md, scripts/run_weekly_nas_backup.sh, scripts/run_forced_nas_backup.sh을 함께 맞춘다.

주간 백업:

```bash
./scripts/run_weekly_nas_backup.sh --backup-share-root /mnt/backup
```

강제 백업:

```bash
./scripts/run_forced_nas_backup.sh --backup-share-root /mnt/backup --backup-reason "before-release"
```
<!-- NAS_BACKUP_END -->
