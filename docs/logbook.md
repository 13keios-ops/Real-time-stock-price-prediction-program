# 작업 기록

## 현재 스냅샷

- 날짜: `2026-04-30`
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
- 예측 상세 탭은 선택 기간의 전체 예측을 보여준다.
- 장마감 뒤 같은 거래일의 후속 분봉이 더 생길 수 없는 예측은 `대기 중`이 아니라 `결과 없음`으로 닫는다.
- 로컬 가상 계좌와 KIS 모의계좌는 시작 예수금 동기화와 브로커 기준 정렬을 통해 비교한다.
- KIS 모의계좌 상품코드는 화면에 없으면 `.env` 에 빈 값으로 두고, 앱 내부에서 모의투자 기본값을 적용한다.
- 브로커 모의계좌 주문 미러링은 `ENABLE_BROKER_PAPER_MIRRORING=true` 일 때 켜진다.
- 브로커 주문/체결 조회가 KIS 호출 제한에 걸리면 재시도하고, 계속 막히면 안전하게 `rate_limited` 리포트를 남긴다.
- 실행 감시기는 정규장에는 대시보드와 실시간 수집기를 복구하고, 장외에는 실시간 수집기를 다시 켜지 않아 CPU 재연결 루프를 줄인다.
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
- [x] git 추적 Markdown 문서의 사람이 읽는 본문 한글 정리
- [x] 저장소 맞춤형 `AGENTS.md` 재구성

## 버전과 감시기

- 감시기가 보는 기준 파일은 root `VERSION` 이다.
- 저장소 참여 설정 파일은 root `autopush.json` 이다.
- 현재 설정은 `enabled=true`, `trigger=version-change`, `branch=main` 이다.
- 버전을 바꾸는 명령은 `scripts/bump_version.ps1` 를 사용한다.
- 감시기 확인 위치:
- `runtime-data/autopush/git-autopush.log`
- `runtime-data/autopush/git-autopush-state.json`

## 최신 검증 결과

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
- PowerShell 파싱 검사: `scripts/get_live_runtime_status.ps1`, `scripts/check_local_setup.ps1` 모두 `parse ok`
- 대시보드 단위 테스트 `python -m unittest tests.test_dashboard`: `13 tests OK`
- 로컬 setup 점검 `scripts/check_local_setup.ps1 -AsJson`: `ok=true`
- 대시보드 상태: `running`, `http://127.0.0.1:8765`, `/health`와 `/api/dashboard.json` 응답 `ok`
- 실행 감시기 상태: `running`, 장 상태 `pre-open`, `live_runtime_should_run=false`
- 실시간 수집기 상태: `stopped`, 현재 장 상태 `pre-open`, 장전 준비 시작 전이므로 정상 대기
- 로컬 가상투자와 KIS 모의투자 정합성 `scripts/verify_paper_dual_account_match.ps1 -AsJson`: `ok=true`, `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`
- `2026-04-30` 로컬 `AGENTS.md` 재구성:
- `D:/GitHub/ref_AGENTS.md`는 공통 설계 기준서로만 참고하고, 현재 저장소의 실제 구조와 기준 문서를 먼저 확인한 뒤 `AGENTS.md`를 다시 작성했다.
- 현재 존재하는 `app/`, `scripts/`, `tests/`, `runtime-data/`, `docs/` 기준으로 작업 순서, 운영 안전 규칙, 주요 명령, 검증 기준을 구체화했다.
- KIS 모의계좌, 로컬 가상투자 비교, 장외 CPU 절감, 대시보드 10분 새로고침, 감시기, NAS 백업 기준을 로컬 예외로 반영했다.
- `AGENTS.md`에 적은 주요 디렉터리, 파일, PowerShell 스크립트 경로 존재 확인: 모두 `True`
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

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
python -m app --train-lightgbm --horizon-min 15
.\scripts\run_ml_shadow_cycle.ps1
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
python -m app --build-runtime-report
python -m app --build-dashboard
.\scripts\run_dashboard.ps1
.\scripts\start_dashboard_background.ps1
.\scripts\get_dashboard_status.ps1
.\scripts\stop_dashboard.ps1
.\scripts\start_live_runtime_background.ps1
.\scripts\get_live_runtime_status.ps1
.\scripts\stop_live_runtime.ps1
.\scripts\start_runtime_watchdog_background.ps1
.\scripts\get_runtime_watchdog_status.ps1
.\scripts\stop_runtime_watchdog.ps1
.\scripts\check_local_setup.ps1
.\scripts\connect_kis_paper_account_interactive.ps1
.\scripts\reconcile_paper_accounts.ps1
.\scripts\start_hourly_repo_audit_background.ps1
.\scripts\get_hourly_repo_audit_status.ps1
.\scripts\bump_version.ps1 -Version 0.2.1
```
