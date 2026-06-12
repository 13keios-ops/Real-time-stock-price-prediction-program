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
- `docs/Production-Architecture.md`: 실제 자금 자동매매 전환 목표 구조와 안전 기준
- `docs/Production-Implementation-Blueprint.md`: 실전 전환 구현 순서, 상태머신, schema 초안
- `docs/Production-Transition-Progress.md`: 실전 전환 단계별 목표와 현재 진행상태
- `docs/Execution-Plan.md`: 현재 상태 기준 다음 작업 순서, 방법, 이유를 정리한 실행 계획판
- `docs/Manual-Market-Status-Runbook.md`: 자동 원천 전 repo-local 수동 market status snapshot 운영 절차
- `docs/KIS-Connection-Runbook.md`: KIS REST rate limit, WebSocket reconnect, 모의계좌 정합성 장애 대응 절차
- `docs/Codex-Operating-Feedback.md`: 사용자의 반복 지적을 작업 전후 체크리스트와 skill 후보로 정리한 보조 기준
- `.agents/skills/daily-ops-check/SKILL.md`: 장전/장후 자동화 상태 확인과 조치 절차
- `docs/cowork-reports/`: Codex와 Claude cowork 사이의 전달/리뷰/후속 보강 이력
- `RECOVERY.md`: GitHub + NAS 복구 기준
- `runtime-data/`: 실행 로그, 리포트, 캐시, 모델 산출물

현재 사실 기준은 기준 문서에만 남긴다.
같은 내용을 여러 문서에 길게 반복하지 않는다.

## 4. 기본 작업 흐름

1. 현재 상태를 대화 맥락이 아니라 파일, 로그, 상태 명령으로 확인한다.
2. 작업 시작 전 장 진행 상태와 실행 중인 수집기를 먼저 확인한다. 기본 확인 명령은 `./scripts/get_live_runtime_status.sh`와 `./scripts/get_runtime_watchdog_status.sh`다.
3. 같은 주제의 cowork ping-pong이 진행 중이면 `docs/cowork-reports/`에서 최신 `review_ver_*` 파일을 먼저 확인하고, 이미 반영한 리뷰인지 최신 `work_ver_*`와 비교한다.
4. 변경 범위를 작게 잡고, 실제 저장소 구조와 맞지 않는 공통 문구는 넣지 않는다.
5. 코드 변경이 있으면 관련 문서도 같은 작업 안에서 갱신한다.
6. 검증 명령을 실제로 실행하고 결과를 확인한다.
7. 산출물 경로, 삭제한 임시 자산, 다음 연결점이 있으면 `docs/logbook.md`에 남긴다.
8. 변경 파일이 있으면 가능한 한 같은 턴에서 commit과 push까지 마친다.
9. 사용자가 직접 해야 하는 작업은 Cybos Plus 로그인처럼 Codex가 물리적으로 처리할 수 없는 필수 작업만 안내하고, 그 외 구현·검증·문서화·커밋·푸시는 Codex가 자율적으로 처리한다.
10. 사용자가 장전/장후 상태체크, daily ops, 운영상태 자동화 확인과 조치를 요청하면 `.agents/skills/daily-ops-check/SKILL.md`를 먼저 읽고 따른다.

반복 지적 방지 체크:

- 사용자가 이미 승인한 같은 작업 범위의 commit/push는 반복해서 묻지 않고 진행한다. 도구 안전정책이 막으면 우회하지 않고 차단 사유와 남은 상태를 보고한다.
- 판단 요청에는 가능한 한 권장안을 함께 제시한다. 사용자가 직접 결정해야 하는 항목은 이유와 기본 권장안을 같이 둔다.
- 최종 답변은 최근 한 문장에만 좁히지 않고, 이번 큰 작업 흐름에서 확인한 상태, 조치, 검증, 남은 위험을 함께 요약한다.
- 운영자는 Codex나 Claude cowork가 아니라 계좌 소유자 또는 실전 운용 승인권자를 뜻한다.
- 반복 누락이 다시 나오면 `docs/Codex-Operating-Feedback.md`에 체크 항목 또는 skill 후보로 반영한다.

장중 수집 보호:

- `get_live_runtime_status` 또는 `get_runtime_watchdog_status`에서 `regular-session`, 실제 장전 워밍업 구간인 `pre-open`, `live_runtime_should_run=true`, live runtime 실행 중 상태가 확인되면 장중 수집 보호 모드로 본다. `overnight`는 장전 워밍업 전 야간 대기 상태이며, live runtime 실행 중 또는 `live_runtime_should_run=true`가 아니면 장중 수집 보호 모드로 보지 않는다.
- 장중 수집 보호 모드에서는 사용자 명시 승인 없이 루트 코드 파일 변경, 전체 테스트, `python -m app ...`, dashboard/runtime 재생성, `runtime-data/dev.db` 접근 가능성이 있는 명령을 실행하지 않는다.
- 장중에도 가능한 작업은 읽기 전용 상태 확인, 문서/리포트 정리, `git diff --check`, `bash -n`, 그리고 `.tmp-tests/` 아래로 완전히 격리된 좁은 단위 테스트로 제한한다.
- 코드 구현이 필요하면 격리 작업공간이나 별도 worktree에서 초안을 준비하고, 장 종료 후 또는 사용자 승인 후 루트 저장소에 적용한다.

답변은 쉬운 한국어를 먼저 쓴다.
영어 개발 용어와 약어는 필요할 때만 쓰고, 처음에는 풀어서 설명한다.
사용자에게는 존댓말을 기본으로 사용한다.
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

- 작업 중 Codex가 경로를 지정할 수 있는 모든 캐시, 다운로드, 임시 데이터, 수집 데이터, 모델 산출물, 리포트, 스냅샷은 D드라이브에만 저장한다. 캐시도 산출물로 취급하며, 새 작업에서 C드라이브나 OS 기본 임시 폴더를 저장 위치로 쓰지 않는다.
- 현재 Ubuntu WSL2 배포판은 `D:\WSL\Ubuntu` 아래에 둔다. 따라서 WSL 저장소 내부의 `runtime-data/`, `.tmp-tests/`, 모델 산출물도 물리적으로 D드라이브에 위치하는 것을 기준으로 한다.
- 이 저장소 작업에서 새 데이터 수집, 다운로드, 캐시, 스냅샷, 장기 보관, 대용량 임시 파일은 D드라이브만 사용한다. 도구가 내부적으로 강제하는 숨은 캐시도 경로를 지정할 수 있으면 `D:\CodexData\Real-time-stock-price-prediction-program\` 또는 WSL 저장소 내부 경로로 돌린다.
- 누적 실행 산출물은 `runtime-data/` 아래에 둔다.
- 새로 내려받거나 수집하는 대용량 외부 데이터는 WSL 저장소나 기존 `D:\GitHub\Real-time-stock-price-prediction-program` 폴더가 아니라 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래에 보관한다. WSL에서는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 로 접근한다.
- Windows 전용 수집 스크립트가 임시 DB나 중간 파일을 만들 때도 기본값은 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래로 둔다. `C:\Temp`는 이 저장소 기본 경로로 사용하지 않는다.
- root `results/`는 만들지 않는다.
- 임시 테스트 산출물은 `.tmp-tests/` 아래에 둘 수 있고, 검증 뒤 삭제 가능하다.
- 모델 산출물은 `runtime-data/ml/` 아래에 둔다.
- 대시보드와 실행 리포트는 `runtime-data/reports/` 아래에 둔다.
- Codex 운영 자동화 report는 `runtime-data/reports/codex/ops/` 아래에 둔다. Codex 장중 incident patch 초안은 `.tmp-tests/codex-ops/` 아래에만 두고, 이 경로는 자동 cleanup 대상에서 제외한다.
- `scripts/run_codex_ops_job.sh --job-type premarket-readiness`는 dry-run 전용 readiness report wrapper다. 이 wrapper는 Codex CLI를 호출하지 않고 상태 파일을 읽어 JSON report만 생성한다.
- `scripts/run_live_readiness_dry_run.sh`는 실제 장애를 만들지 않는 fixture 기반 readiness wrapper다. fixture가 없는 항목은 `not_verified`로 남기고 Phase readiness를 통과시키지 않는다. 현재 fixture check key는 `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `system_clock`, `kill_switch`, `database`, `disk_space`, `dashboard`, `storage_migration_state`다. 기본은 JSON only이며, SQLite 저장은 `--record --database-path <repo 내부 경로>`를 명시한 경우에만 시도한다. `database` check는 premarket report에서 SQLite read-only smoke(`SELECT 1`, `sqlite_master`, `schema_version`, `journal_mode`)로 확인하고, `storage_migration_state`는 schema 적용 상태와 분리해서 본다. `token_refresh` check는 `scripts/probe_kis_token_refresh.sh`가 token 원문 없이 생성한 sanitized JSON을 사용한다. `account_snapshot` check는 `scripts/probe_kis_account_snapshot.sh`가 계좌번호 없이 생성한 sanitized JSON을 사용한다. `ws_recovery` check는 `scripts/probe_kis_ws_recovery.sh`가 실제 WebSocket 네트워크를 열지 않는 synthetic fault injection 결과를 만든 경우에만 통과 후보가 된다. 실제 KIS WebSocket 복구 관측은 Phase 1 read-only 진입 뒤 별도로 수집한다. `market_status` check는 `scripts/probe_market_status_snapshot.sh`가 repo 내부 수동 snapshot에서 생성한 sanitized JSON을 사용한다. KIS/거래소 자동 원천은 아직 연결하지 않는다. `system_clock` check는 fixture/dry-run 결과 또는 `scripts/probe_kis_clock_reference.sh`가 read-only 현재가 조회 1회로 생성한 sanitized check JSON을 `--system-clock-check-path`로 넘긴 경우에만 통과 후보가 된다. `scripts/build_live_readiness_fixture_snapshot.sh`는 premarket report, token refresh check, account snapshot check, synthetic WS recovery check, market status check, system clock check, kill switch 상태 파일을 읽어 로컬로 증명 가능한 항목만 fixture로 묶고, market status check 파일이 없으면 자동으로 통과시키지 않는다.
- `token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `system_clock`의 timestamped readiness 증거는 `app/services/live_phase_readiness.py`에서 key별 freshness 기준 초과 시 `stale_evidence`로 차단한다. 현재 기준은 `system_clock/ws_recovery=30분`, `account_snapshot/market_status=1시간`, `token_refresh=4시간`이다. Phase 2/3 readiness와 live submit guard는 synthetic `ws_recovery`를 실전 제출 증거로 인정하지 않고, `app/services/ws_recovery_evidence.py`의 real evidence type이 없으면 broker 호출 전에 차단한다. Dashboard live readiness 카드는 `ws_recovery` evidence type, 실제 증거 여부, freshness, stable frame, reconnect storm 여부를 read-only로 표시한다. HTTP `Date` 기반 `system_clock` skew는 초 단위 header 한계 때문에 밀리초 정밀도가 아니라 대략 1초 이내 여부를 보는 증거다. `scripts/probe_kis_clock_reference.sh --compare-paper-live`는 주문 메서드 없는 read-only quote로 paper/live HTTP `Date` reference를 비교하는 sanitized 진단 JSON을 만든다.
- `account_snapshot` check는 `position_row_count`, `summary_row_count`, `cash_balance`, `stock_evaluation_amount`, `total_asset_amount` shape와 값 타입이 모두 맞아야 통과 후보가 된다. 누락되거나 타입이 바뀌면 계좌번호/raw response 없이 shape drift로 차단한다.
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
- Codex 운영 job 산출물은 `runtime-data/reports/codex/ops/` 아래에 남긴다. 장중 운영 job은 `app/services/codex_ops.py`의 manifest/권한 모델을 통과해야 하며, root 코드 적용, 운영 DB schema apply, runtime restart, 실전 주문 관련 flag 변경은 자동 실행하지 않는다. 현재 구현된 wrapper는 `scripts/run_codex_ops_job.sh --job-type premarket-readiness` dry-run report 생성, `scripts/run_live_readiness_dry_run.sh` fixture 기반 10개 check readiness report 생성, `scripts/probe_kis_clock_reference.sh` read-only KIS quote 기반 system_clock check 및 `--compare-paper-live` paper/live reference 비교 생성, `scripts/probe_kis_token_refresh.sh` KIS auth-only token_refresh check 생성, `scripts/probe_kis_account_snapshot.sh` KIS read-only account_snapshot check 생성, `scripts/probe_kis_ws_recovery.sh` synthetic WS recovery check 생성, `scripts/probe_market_status_snapshot.sh` repo-local manual market_status check 생성, `scripts/build_live_readiness_fixture_snapshot.sh` 로컬 증적 fixture snapshot 생성까지다. readiness DB 기록은 기본값이 아니며 `--record`와 repo 내부 `--database-path`가 함께 있어야 한다. `scripts/set_live_kill_switch.sh`는 기본 dry-run/status이고, 실제 kill switch ON/OFF 파일 기록은 `--apply`가 있을 때만 수행한다. OFF 해제는 `--disable --apply --confirm-disable` 조합을 요구한다.
- Phase 2/3 live submit caller는 `LiveOrderGuard.assert_can_submit()` 또는 `LiveOrderManager.submit_intent()`에 실제 WS 복구 관측 evidence type을 넘겨야 한다. 넘기지 않거나 synthetic 값이면 `ws_recovery_real_evidence_required`로 차단한다.

## 11. 완료 기준

- 변경 내용이 현재 저장소 구조와 맞는지 확인한다.
- 없는 경로, 없는 명령, 공통 기준서의 예시 문구를 남기지 않는다.
- 필요한 검증을 실제로 실행한다.
- 관련 기준 문서와 `docs/logbook.md`를 갱신한다.
- 작업 트리에 의도하지 않은 변경이 없는지 확인한다.
- 불필요한 백그라운드 프로세스를 남기지 않는다.

<!-- NAS_BACKUP_START -->
## NAS 백업 운영

- 이 저장소의 NAS 백업은 두 종류로 구분한다.
- 재난 복구용 NAS 전체 백업은 이전 저장소 유실 사고 대응을 위한 이중 보관이며, 접근 권한이 제한된 NAS 안에서 전체 작업 트리와 로컬 복구 자산을 보존할 수 있다. 이 백업은 cowork 전달, 감사 증적 공유, 실전 전환 readiness 통과 증거로 직접 쓰지 않는다.
- 실전 전환 검증용 sanitized recovery export는 root `.env*`, KIS 토큰 캐시, runtime 로그, private key 계열 파일을 포함하지 않는다. `tests/test_wsl_ops.py`와 저장소 export wrapper가 잠그는 포함/제외 정책은 이 sanitized export 기준이다.
- 기본 보관 정책은 최신 3개 보관과 주 1회 정기 백업 명령 제공이다.
- 현재 NAS 공유 루트 기준은 \\192.168.0.2\backup 이다.
- 정책이 바뀌면 RECOVERY.md, README.md, AGENTS.md, scripts/run_weekly_nas_backup.sh, scripts/run_forced_nas_backup.sh, scripts/run_weekly_nas_backup.ps1, scripts/run_forced_nas_backup.ps1을 함께 맞춘다.
- 2026-05-28 사용자 변경 기준: NAS 백업은 용량과 소요 시간이 크므로 Codex가 자율 실행하지 않는다. 주간/강제 NAS 백업 모두 사용자가 해당 작업에서 명시적으로 지시했을 때만 실행한다.
- 코드/운영 자동화 변경, 장후 마감 조치, Phase readiness 증거 생성, release/복구 직전 같은 중요 체크포인트여도 Codex가 forced NAS backup을 자동 실행하지 않는다. 필요하면 "NAS 백업 실행" 같은 명시 지시를 받은 뒤에만 실행한다.
- 실전 주문 flag 변경, 비밀값 본문 기록, root `.env*`를 cowork/검증 산출물로 공유하는 행위는 계속 금지한다.

주간 백업:

```bash
./scripts/run_weekly_nas_backup.sh --backup-share-root /mnt/backup
```

강제 백업:

```bash
./scripts/run_forced_nas_backup.sh --backup-share-root /mnt/backup --backup-reason "before-release"
```
<!-- NAS_BACKUP_END -->

