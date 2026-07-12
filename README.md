# 실시간 주가 예측 프로그램

국내 주식의 실시간 시세, 호가, 공시, 뉴스, 반응 데이터를 바탕으로 주가 변동을 연구하고 예측하는 로컬 연구용 프로그램이다.
현재 목표는 자동 실전 매매가 아니라 `실시간 수집 -> 특징 생성 -> 예측 -> 모의투자 검증 -> 리포트` 흐름을 안정적으로 만드는 것이다.

## 궁극 운영 목표

이 프로그램의 궁극적인 목표는 단일 모델이 바로 돈을 버는 구조가 아니라, `데이터 수집 -> 전략 후보 생성 -> 비용/슬리피지/세금 반영 검증 -> walk-forward 검증 -> paper 운용 -> 소액 실전 검증 -> 리스크 제한 운용 -> 일일 분석 -> 승격/폐기`가 반복되는 로컬 투자 연구·운영 시스템이다.

수익 목표는 과도한 일간 고정 수익률을 약속하는 방향이 아니라, 손실일을 작게 제한하고 유리한 장세에서 수익 기회를 키우는 방향으로 둔다. 1차 검증 목표는 비용 반영 후 양수 기대값, 구간 분리 재현성, 최대 낙폭 제한, 연속 손실 제한, paper 운용 안정성을 실제 리포트로 확인하는 것이다. 월 누적 `+50%`는 장기 stretch target 으로만 남기며, 보장 수익률·즉시 운용 기준·승격 조건으로 쓰지 않는다. 전략 승격은 검증 가능한 1차 목표를 통과한 경우에만 검토한다.

장중 데이터 수집은 연구 실험과 분리된 백그라운드 운영 축으로 유지한다. 일반 거래일에는 `runtime watchdog`이 정규장 시작 전부터 live runtime 을 켜고, 장중 KIS WebSocket 체결/호가 데이터를 계속 쌓는다. 오프라인 ML/룰 실험은 이 수집기를 끄지 않고 기존 DB와 리포트를 읽는 방식으로 실행한다. 코스피200 Cybos 갱신은 Windows COM API 제약 때문에 장후 배치 수집과 WSL 병합 흐름으로 분리한다.

## 투트랙 운영 원칙

장중 운영은 `수집 트랙`과 `연구 트랙`을 분리한다. 수집 트랙은 live runtime 과 runtime watchdog 이 `runtime-data/dev.db`에 장중 KIS 데이터를 계속 저장하는 흐름이다. 연구 트랙은 같은 DB를 직접 무겁게 읽고 쓰지 않고, `scripts/create_research_db_snapshot.sh`로 SQLite backup 스냅샷을 만든 뒤 `DATABASE_URL`을 스냅샷 DB로 바꿔 실험한다.

연구 스냅샷 기본 보관 위치는 WSL 기준 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/` 이다. 연구 실행 산출물은 기본적으로 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/` 아래에 격리한다. D드라이브 경로를 사용할 수 없으면 새 다운로드, 캐시, 대용량 실험을 시작하지 않고 경로 문제를 먼저 해결한다.

장마감 후 자동 관리는 runtime watchdog 이 담당한다. 정규장이 끝나고 기본 30분이 지나면 하루 한 번 `run_post_close_ml_maintenance.sh --quick`를 백그라운드로 시작한다. quick 경로는 live DB를 무겁게 재학습하지 않고 runtime report, KIS live 데이터 품질, KIS-Cybos feature drift, KIS live feature-label 진단, dashboard snapshot 만 갱신한다. 이 진단들은 대시보드 갱신용 warning-only 작업이라 실패해도 heavy research 를 자동 시작하지 않는다. 결과 상태는 `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`에 남긴다. Cybos 5년치, snapshot DB, `--rebuild-actual-ml` 같은 heavy research 는 watchdog 기본 자동 트리거에서 제외하고 명시 명령으로만 실행한다. active model 자동 교체와 실전 주문 승격은 하지 않는다.

quick 경로는 10분 안쪽의 운영 점검을 목표로 하므로 전체 feature/label 재생성은 포함하지 않는다. 장마감 뒤 h15/h60 라벨까지 닫아 학습 가능한 상태로 만들 때는 `./scripts/run_post_close_label_refresh.sh`를 별도로 실행한다. 이 경로는 `--recent-days` 값에 맞춰 `python -m app --build-feature-dataset --feature-dataset-recent-days N`으로 최근 구간만 갱신한 뒤 KIS live 품질, source drift, KIS live feature diagnostics, runtime report, dashboard 를 갱신하고 상태를 `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`에 남긴다. 전체 이력 feature/label 재생성은 연구/복구용 명시 작업으로만 실행한다.

## 로컬 데이터 저장 원칙

작업 중 새로 생기는 캐시, 다운로드, 임시 데이터, 수집 데이터, 모델 산출물, 리포트, 스냅샷은 모두 D드라이브에만 둔다. WSL 저장소 자체가 `D:\WSL\Ubuntu` 아래에 있으므로 저장소 내부 `runtime-data/`와 `.tmp-tests/`도 물리적으로 D드라이브 기준이다.

저장소 밖에 둘 필요가 있는 대용량 외부 데이터, 연구 스냅샷, 장기 캐시는 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래를 기본 위치로 쓴다. WSL에서는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/`로 접근한다. 새 작업에서 `C:\Temp`, 사용자 홈의 기본 다운로드 폴더, OS 기본 임시 폴더를 저장 위치로 쓰지 않는다.

## 핵심 문서

- `AGENTS.md`: 저장소 운영 규칙의 단일 기준
- `docs/STATUS.md`: 짧은 현재 상태와 blocker
- `docs/SPRINT_CURRENT.md`: 현재 작업 기간과 동결 범위
- `docs/Repository-Structure.md`: 실제 레이어, 문서 역할, 구조 부채
- `WORKFLOW.md`, `COWORK_GUIDE.md`: 현재 Codex/cowork 협업 절차
- `docs/logbook.md`: 현재 상태, 활성 체크리스트, 최근 기록
- `docs/Current-Implementation.md`: 실제 구현 범위와 실행 방법
- `docs/Versioning.md`: `VERSION` 기반 버전 관리와 watcher 기준
- `docs/Production-Architecture.md`: 실제 자금 자동매매 전환을 위한 목표 구조와 안전 기준
- `docs/Production-Implementation-Blueprint.md`: 실전 전환을 코드 작업 단위로 나눈 구현 청사진
- `docs/Production-Transition-Progress.md`: 실전 전환 단계별 목표와 현재 진행상태
- `docs/Execution-Plan.md`: 현재 상태에서 다음 작업을 어떤 순서와 방법으로 진행할지 정리한 실행 계획판
- `docs/Model-Research-PreRegistration.md`: Cybos-KIS 격차, orderbook 피처 가설, h60 트랙 사전등록 기준
- `docs/Social-Signal-Shadow-Plan.md`: SNS/공개 영향력 이벤트를 Phase 1 shadow 로 관측·평가하는 기준
- `docs/Manual-Market-Status-Runbook.md`: 자동 원천 전 repo-local 수동 market status snapshot 운영 절차
- `docs/KIS-Connection-Runbook.md`: KIS REST rate limit, WebSocket reconnect, 모의계좌 정합성 장애 대응 절차
- `docs/Codex-Operating-Feedback.md`: 반복 지적 방지 체크리스트와 저장소 전용 skill 후보 관리
- `.agents/skills/daily-ops-check/SKILL.md`: 장전/장후 자동화 상태 확인과 조치 절차
- `docs/cowork-reports/`: Codex와 Claude cowork 사이의 전달/리뷰/후속 보강 이력
- `docs/Repo-Audit-Automation.md`: 매시간 저장소 전체 점검 자동화 기준
- `docs/archive/`, `docs/logbook_archive/`: 퇴역 원문과 기간별 작업 요약
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
- 검증 꼬리구간 백테스트
- gap/max-train 제어가 가능한 walk-forward backtest
- walk-forward gate를 반영하는 challenger model 비교 보고서
- 활성 모델 명시 등록부와 내장 기준 모델 예비 처리
- LightGBM shadow challenger 비교
- LightGBM 성능 진단, feature source, feature profile, label band, label band 재현성, probability calibration 연구 리포트
- LightGBM 하락/회피 방어 신호 후보 요약 리포트
- LightGBM 하락/회피 신호의 baseline 매수 회피 / 조기청산 shadow 비교 리포트
- 모델 공통 meta-policy shadow 후보 요약 리포트
- SNS/공개 영향력 이벤트 shadow 평가 계획과 read-only 사후평가 리포트
- paper/KIS mismatch trace 리포트와 gate walk-forward 극단 fold 요약/장세 분석 리포트
- online replay 기반 paper trading 상태 기록
- KIS WebSocket 연결 준비와 검증 리포트
- 실행 / 백테스트 / 워크포워드 리포트 생성
- 로컬 모니터링 대시보드 snapshot 생성과 HTTP serving
- 대시보드 기본 언어 한글화와 상단 상태 영역 + 10탭 전환 UI
- 대시보드 기본 자동 새로고침 10분과 수동 `상태 업데이트` 버튼
- 대시보드에서 `모의투자(가상) / 모의계좌(실제) / 실 운용계좌 / 머신러닝 현황 / 상태 및 설정 / 예측현황 / 신호 & 주문현황 / 체결과 분봉 / 오늘의 리포트 / 기타` 탭 제공
- 각 상위 탭 내부는 `상태 설명 / 상세 표 / 해석 또는 안내` 방식의 세로 보조탭 구조로 통일
- 표와 목록이 긴 영역은 내부 스크롤 패널로 바뀌어 화면을 바꾸지 않고 위아래로 누적 데이터를 볼 수 있음
- 대시보드 상단에서 `조회 범위`와 `기준 날짜`로 특정일 / 최근 기간 / 전체 누적 데이터 조회
- 학습 탭에서 `실운용 학습 상태`와 `검증 및 비교 결과`를 분리해 실제 데이터 기반 결과만 해석하는 구조
- 머신러닝 현황 탭에서 `게이트 기준 워크포워드`와 `장후 자동 학습 상태`를 별도 카드로 표시해 정본 승격 게이트가 보는 보고서와 post-close snapshot 산출물을 구분해서 확인
- 머신러닝 현황 탭에서 `KIS live 데이터 품질` 카드를 표시해 최신 KIS 체결/호가 symbol-minute, feature, h15/h60 label coverage 를 확인
- 최근 예측에 기준가 대비 `예상 변동 금액`과 `실제 결과` 표시
- 최근 예측의 `실제 결과`는 예측 시각에서 정확히 `+15분/+60분` 분봉이 없어도, 같은 거래일 안에서 목표 시각 이후 가장 가까운 실제 분봉을 사용해 계산
- 장마감 뒤 같은 거래일의 후속 분봉이 더 생길 수 없는 예측은 `대기 중`으로 남기지 않고 `결과 없음`으로 닫는다.
- 예측현황 탭에서 선택 기간 기준 `예측 건수 / 확정 건수 / 성공률 / 수평선별 집계` 제공
- 예측현황 탭에서 `오전/오후`, `시간대별`, `상승/하락` 통계를 함께 제공
- 예측현황 탭에서 예측 정확도, 신호 replay(과거 신호 재생) 기준 가상 수익률, 실제 paper 체결 기준 FIFO 청산손익을 분리해서 표시
- 최근 예측 리스트는 최신 기준 최대 `100개`까지 표시하고, 예측상세 탭은 선택 기간의 예측 전체를 표시
- 신호 & 주문현황 탭에서 신호, 주문, 체결을 묶어서 확인하고 `매도 신호 차단 이유`를 함께 설명
- 오늘의 리포트 탭에서 계좌 결과, 예측 성공률, 체결 수, 분석과 고찰, 다음 접근 방향 자동 요약
- `모의투자(가상)` 탭은 `상태 설명 / 보유 종목 / 매수·매도 및 체결현황` 세로 하위 탭으로 다시 나뉜다.
- `모의투자(가상)` 탭의 보유 종목 화면은 열린 포지션이 없을 때도 `최근 종료 포지션`을 함께 보여준다.
- 같은 세로 하위 탭 패턴을 `모의계좌(실제) / 실 운용계좌 / 머신러닝 현황 / 상태 및 설정 / 예측현황 / 신호 & 주문현황 / 체결과 분봉 / 오늘의 리포트 / 기타`에도 적용했다.
- 대시보드의 실제 운용 데이터 전용 필터와 테스트 운용 흔적 정리 명령
- KIS 브로커 모의계좌 잔고 조회와 대시보드 반영
- 로컬 가상 주문의 브로커 모의계좌 주문 제출 미러링과 제출 이력 저장
- 로컬 가상 계좌와 브로커 모의계좌를 비교하는 paper-account reconciliation 리포트
- 브로커 모의계좌 기준으로 로컬 가상 계좌 현재 상태를 맞추는 marker 기반 paper alignment
- paper alignment marker 이후의 주문/체결/브로커 제출 수만 `현재 로컬 계좌 요약`에 집계해서, 오래된 누적 이력이 현재 상태처럼 보이지 않도록 정리
- live runtime 재시작 뒤에도 주문/체결 ID가 겹치지 않도록 실행별 고유 namespace를 사용
- broker paper sync 는 alignment marker 이전 제출 주문을 새 baseline 에 다시 적용하지 않음
- 런타임 재시작 시 기존 로컬 가상 포트폴리오 상태 복원
- 런타임과 broker paper sync 는 alignment baseline 이후 체결이 있으나 최신 스냅샷이 오래된 경우, 기준 현금에 이후 체결 현금흐름을 반영해 복원한다.
- actual-only cleanup 은 실제 브로커 체결 시각에 생성된 포트폴리오 스냅샷을 실제 운용 데이터로 보존한다.
- 실제 운용 데이터만 남기기 위한 runtime test-data 정리와 actual-only ML 재구축 경로
- pykrx 일봉 기반 10종목 장기 과거 데이터 backfill 과 15분 proxy 분봉 적재 경로
- Cybos 실제 15분봉 기반 bar-only LightGBM 연구 실험 경로
- 실시간 수집기 background 실행과 상태 확인 스크립트
- KIS WebSocket listener 는 구독 뒤 프레임이 들어오지 않으면 timeout 후 reconnect 해서 connected-but-idle 상태를 줄인다.
- 장중에는 15분·60분 예측을 함께 기록하고, 신호와 주문은 15분 기준으로만 생성
- 샘플 WebSocket replay 데이터를 `kis-ws-replay` 출처와 `*-replay-*` ID로 분리
- 오염된 분(minute)을 대시보드 actual runtime 범위에서 제외하는 stricter filter
- 정규장 밖 KIS REST snapshot 분과 raw 집계를 대시보드 actual runtime 범위에서 제외
- 대시보드 start/status/stop 스크립트의 포트 점유 프로세스 추적 보강
- 대시보드 SQLite 읽기 경로는 스키마 초기화를 건드리지 않도록 분리하고, busy-timeout / read retry 로 잠금 충돌에 더 강하게 조정
- 대시보드 HTTP 응답은 SQLite 잠금이 잠시 발생해도 연결이 바로 끊기지 않고 `일시 점검` 안내 응답으로 돌아오도록 보강
- 대시보드 기본 화면과 기본 JSON API는 최신 cached snapshot 을 우선 사용하도록 바뀌었다.
- 대시보드 `상태 업데이트` 버튼과 10분 자동 새로고침은 `/api/refresh` 로 새 snapshot 을 만든 뒤 화면을 갱신한다.
- 대시보드는 `KIS 검증 / 최근 분봉 / 최근 예측 / 최근 신호 / 최근 학습 / 최근 평가 / 대시보드 생성` 신선도를 함께 계산해 상태 탭에 표시한다.
- 대시보드 상단 상태 경고 카드는 이제 `정규장 실시간 지연` 과 `장외 안내`를 구분해서 보여준다. 정규장에는 `실시간 분봉 지연`, `최근 예측 기록 정지`, `KIS 실시간 검증 실패`를 바로 경고하고, 장외에는 `KIS 검증은 장외 기준으로 기록되었습니다` 같은 안내형 메시지로 낮춰 보여준다.
- 머신러닝 현황 탭은 오늘 학습이 없더라도 최신 전체 `backtest / walk-forward / challenger` 결과를 계속 보여줘서 공백처럼 보이지 않게 바뀌었다.
- 대시보드 상단 경고는 이제 `오늘 학습 부재`를 무조건 띄우지 않고, 최신 학습이나 평가 기록이 실제로 `없음` 또는 `지연` 상태일 때만 올린다.
- 대시보드의 기본 조회 범위가 `오늘`일 때 현재 달력 날짜에 장중 기록이 없으면, 마지막 실제 장중 날짜를 자동으로 골라 `최근 장중` 기준으로 보여준다.
- 장마감 후 자동 quick maintenance 는 `run_post_close_ml_maintenance.sh --quick` 로 runtime report, 품질 진단, 제한 LightGBM 학습, challenger 평가, dashboard snapshot 을 10분 안에 갱신하는 것을 목표로 한다.
- heavy research 는 `run_post_close_ml_maintenance.sh --heavy-research --use-snapshot` 처럼 명시적으로 실행할 때만 snapshot DB에서 feature / label / LightGBM / backtest / walk-forward / challenger / dashboard 재구축을 수행한다.
- post-close maintenance 는 최신 상태를 `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json` 에 남기고, heavy research 의 실제 재구축 상세는 `runtime-data/reports/actual-ml/latest-rebuild.json` 에 남긴다.
- post-close ML maintenance 와 runtime watchdog 은 장외와 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 live runtime 을 다시 켜지 않아 WebSocket 재연결 루프가 CPU를 계속 쓰지 않도록 하되, 일반 거래일에는 정규장 시작 60분 전부터 `pre-open` warmup 으로 live runtime 을 미리 켠다. post-close ML maintenance 와 post-close label refresh wrapper 는 weekend/holiday 상태에서 기본 실행하면 `skipped` 상태 파일만 남기고 학습/라벨/대시보드 재생성 작업을 수행하지 않는다. 그보다 이른 거래일 새벽/야간 시간은 `overnight`로 구분해 live runtime 이 꺼진 상태를 정상으로 본다.
- runtime watchdog 의 정규장 stale 복구는 검증용 단일 종목이 아니라 설정된 watchlist 로 live runtime 을 다시 시작한다.
- runtime watchdog 상태 조회는 프로세스 존재뿐 아니라 `last_checked_at` 심박 나이도 확인한다. 기본 10분 이상 심박이 멈추면 `stale` 로 보고, 시작 스크립트는 같은 watchdog 프로세스를 재사용하지 않고 재시작한다.
- 정규장에 live runtime 이 이미 최신 분봉을 쓰고 있으면 watchdog 은 별도 KIS 검증 WebSocket 을 중복으로 열지 않고, live runtime 의 실제 데이터 흐름을 우선 신뢰한다.
- `scripts/get_dashboard_status.sh` 는 이제 실제 포트와 HTTP 응답을 다시 확인한 뒤 상태 파일도 함께 정규화해서 `starting` 이 오래 남는 문제를 줄인다.
- dashboard foreground/background 시작 스크립트는 WSL2의 실제 Python 실행 파일을 우선 찾아 사용한다.
- PC 재부팅 후 자동 시작을 위한 runtime autoboot 스크립트와 시작프로그램 launcher 설치/삭제 스크립트
- runtime watchdog background 시작 / 상태 / 중지 스크립트가 추가되었다.
- `scripts/get_live_runtime_status.sh` 와 runtime watchdog 은 serializer 기반 파일 읽기를 써서, cached dashboard snapshot 의 한글/긴 JSON 도 안정적으로 읽는다.
- live runtime 상태 스크립트는 이제 실제 `python -m app --kis-ws-listen` 프로세스인지까지 확인해 stale pid 재사용 오판을 줄이고, root `.env` 또는 KIS 자격정보가 없을 때는 blocked 이유를 함께 남긴다.
- root `.env` 가 나중에 복구되면, live runtime 상태 스크립트는 예전 `missing_kis_credentials` 실패를 그대로 붙잡지 않고 현재 KIS app key/secret 준비 상태를 다시 읽어 stale blocked 상태를 자동 해제한다.
- live runtime 이 정상 중지된 상태에서는 마지막 INFO 로그를 실패 사유로 표시하지 않는다.
- dashboard / watchdog / repo review / hourly audit background helper 는 이제 저장된 pid 만 믿지 않고 실제 명령줄까지 확인해, pid 재사용으로 `running` 오판이나 잘못된 `Stop-Process` 가 나지 않도록 보강했다.
- `scripts/check_local_setup.sh` 는 복구 직후 root `.env`, Python module, dashboard, live runtime, watchdog, runtime startup launcher, NAS recovery root 상태를 한 번에 점검하고 recovery report를 남긴다.
- `scripts/restore_kis_env_interactive.sh` 는 WSL 터미널에서 기본적으로 `paper` 기준 KIS app key/secret 만 받아 root `.env` 를 저장한다. 계좌 값은 `-IncludeAccountFields` 로 함께 입력할 수 있다. Phase 1b용 live 자격정보만 준비할 때는 `--trading-mode live --include-account-fields --read-only-preparation`을 사용한다. 이 옵션은 현재 `TRADING_MODE=paper`를 보존하고 `ALLOW_LIVE_ORDERS=false`를 강제한다.
- `scripts/run_phase1b_readonly_observation.sh`는 기본적으로 네트워크 없는 Phase 1b 사전검사만 수행한다. `--execute`를 명시해야 제한된 live read-only 관측을 실행하며, 주문/취소 메서드는 노출하거나 호출하지 않는다.
- 대시보드 탭 선택 상태를 새로고침 뒤에도 유지하는 localStorage 처리
- paper 계좌번호만 8자리일 때 상품코드 `01` 기본 처리
- `.env`의 `여기에_상품코드` 같은 placeholder 값 자동 무시
- KIS REST rate-limit backoff 재시도
- 브로커 모의계좌 주문/체결 조회도 KIS `EGW00201` rate-limit 에 대해 재시도하고, 계속 막히면 기존 제출 주문을 pending 으로 유지한 채 `rate_limited` 리포트를 남긴다.
- runtime autoboot 와 Monday runtime 스크립트는 이제 내부 `python -m app ...` 실행이 실패하면 즉시 오류로 처리한다.
- paper-account reconciliation 기록은 live runtime 이 DB를 쓰는 중에도 더 오래 재시도하도록 보강했다.
- 매시간 저장소 전체 점검 자동화와 상태 이어받기 구조
- audit progress JSON 배열 정합성 보강
- `scripts/start_repo_review_until_deadline_background.sh` 로 특정 시각까지 저장소 전체점검을 반복 실행할 수 있다.
- bounded repo review runner 는 공백이 있는 workspace 경로에서도 하위 bash 호출이 끊기지 않도록 인자 인용과 iteration timeout 을 보강했다.
- 실전 전환 준비용 read-only client, live order guard, KIS live order guarded adapter, system clock skew helper, account snapshot probe, synthetic WS recovery probe, live 주문/체결/감사/알림 원장 골격, readiness dry-run, KIS paper fixture redaction/export helper 가 추가되었다. 현재는 runtime 실전 주문 경로에 연결하지 않은 안전 검증 골격이다.

현재 기준 버전은 `0.2.0` 이다.

## 확정된 ML 운영 방향

다음 구현 목표로 아래 방향을 확정했다.

- 학습 방식: `최근 60거래일 + 오늘 데이터`
- 운영 방식: `장중 추론`, `장후 재학습`
- 메인 모델: `LightGBM`
- 보조 모델: `baseline`, `centroid`, `linear-score`
- 검증 방식: `backtest + walk-forward + challenger 비교`
- 차트 분석: `이미지보다 수치 특징화 우선`

현재 실시간 주문 판단은 검증 완료 전까지 active `baseline` 모델이 담당한다. LightGBM은 최신 artifact가 있는 horizon 에 한해 장중 같은 종목/시각의 shadow serving 예측으로 추가 저장하고, 대시보드 `예측 흐름`에서 baseline 예측, 실제 결과, 신호, 주문, 체결과 나란히 비교한다. 이 shadow 예측은 active model 승격이나 주문 판단에 쓰지 않는다.

LightGBM 성능개선 트랙은 threshold 를 바로 낮추거나 active model 을 바꾸는 방식이 아니라, `성능 진단 -> 원천별 feature 실험 -> feature profile 후보 -> label band 재점검 -> label band 재현성 -> probability calibration -> 후보 shadow 고정 -> challenger / walk-forward 재검증` 순서로 진행한다. 현재 진단 기준으로 최신 LightGBM은 하락/회피 방향 연구 신호는 일부 있으나, 현물 매수 승격 근거는 부족하다. feature profile, label band, label band 재현성, probability calibration 실험은 모두 연구 전용 리포트이며 active model, gate 기준값, label threshold 를 자동 변경하지 않는다.

여기서 `최근 60거래일 + 오늘 데이터`는 과거 데이터를 삭제한다는 뜻이 아니다.
운영용 학습창은 최근 60거래일 중심으로 쓰되, 더 오래된 데이터는 drift 점검, 구간 비교, 재현, 회귀 검증, challenger 평가를 위해 보관하는 방향을 기본으로 한다.

## 계좌 값 해석

- `로컬 모의운용 계좌`
  - 프로그램 내부 모의주문 엔진이 기록한 가상 포트폴리오다.
  - 우리 전략이 어떤 신호, 주문, 체결을 만들었는지 확인하는 용도다.
- `브로커 모의계좌 잔고`
  - 한국투자 모의투자 계좌에서 직접 조회한 실제 잔고다.
  - 프로그램 내부 모의주문 기록과 별도로 존재하므로 값이 다를 수 있다.
- `KIS_PRODUCT_CODE_PAPER`
  - 모의투자 계좌 화면에 별도 상품코드가 없으면 root `.env` 에 빈 값으로 둔다.
  - 앱은 KIS 호출에 상품코드가 필요할 때 paper 기본값을 내부에서 적용한다.
  - 모의계좌 연결은 `scripts/connect_kis_paper_account_interactive.sh` 로 8자리 계좌번호만 입력하는 흐름을 기본으로 한다.
- `로컬 모의운용`과 `브로커 모의계좌`는 선택적으로 주문 제출을 함께 보낼 수 있다.
  - `ENABLE_BROKER_PAPER_MIRRORING=true` 이면 로컬 가상 주문을 브로커 모의계좌에도 함께 제출한다.
  - 다만 브로커 쪽 거절, 부분 체결, 체결 시차가 있으면 주문 직후에는 보유 수량과 예수금이 잠시 다를 수 있다.
  - 대시보드의 비교 카드와 `최근 브로커 제출 주문` 표에서 현재 동기화 상태를 확인한다.
- `로컬 시작 예수금 동기화`
  - 장 시작 전에는 `scripts/verify_paper_dual_account_match.sh -SyncInitialCash -AlignToBroker` 로 KIS 모의계좌 예수금을 root `.env` 의 `PAPER_INITIAL_CASH` 에 맞추고, 브로커 기준 marker 정렬까지 갱신한다.
  - 브로커 모의계좌에 이미 보유 종목이 있으면 현재 현금이 총 시작 예수금이 아니므로 `-SyncInitialCash`는 거부된다. 이때는 `scripts/verify_paper_dual_account_match.sh -AlignToBroker -AsJson` 으로 브로커 기준 marker 만 정렬한다.
  - 이후 수시 점검은 `scripts/verify_paper_dual_account_match.sh -AsJson` 으로 한다.
  - 최신 결과는 `runtime-data/reports/reconciliation/latest-paper-dual-account-match.{md,json}` 에 남는다.
- `paper-account reconciliation`
  - 로컬 가상 계좌와 브로커 모의계좌의 보유 수량, 예수금, 총자산을 비교하는 점검 리포트다.
  - 이 비교는 화면의 날짜 필터와 무관하게 `현재 로컬 가상 계좌 전체 상태`를 기준으로 계산한다.
  - 최신 결과는 `runtime-data/reports/reconciliation/latest-paper-account-sync.{md,json}` 에 남는다.
  - 미러링이 꺼져 있으면 `mirroring_disabled` 상태가 정상일 수 있다.
  - KIS 모의계좌의 원시 현금값은 체결 뒤에도 총 예수금처럼 남을 수 있어, 비교에는 `총자산 - 주식평가액` 으로 계산한 유효현금을 함께 사용한다.
- `paper baseline alignment`
  - 브로커 모의계좌 기준으로 로컬 가상 계좌의 현재 상태를 다시 맞추는 정렬 단계다.
  - 이 경로는 오래된 SQLite row 를 직접 지우지 않고 `runtime-data/reports/broker-paper/latest-alignment.json` marker 를 기준으로 현재 상태만 정렬한다.
  - 정렬 이후 대시보드의 `로컬 모의운용 계좌` 요약은 marker 이후 주문/체결/브로커 제출 수만 현재 상태로 집계한다.
  - marker 이후 새 체결이 일부 종목에만 생겨도 baseline 보유종목과 종목별로 병합해서 현재 보유수량을 비교한다.
  - 정렬 뒤에는 정합성 점검, 실행 리포트, 대시보드가 모두 브로커 기준 현재 상태를 우선 보여준다.
  - 현재 기본 해석 상태는 `aligned_waiting_first_submission` 이고, 뜻은 `브로커 기준 정렬은 끝났고 아직 브로커로 제출된 첫 주문이 없음` 이다.
- `모의주문 spread 게이트`
  - `MAX_SPREAD_BPS` 기본 운용값은 현재 `25.0` 이다.
  - 2026-04-29 실제 삼성전자 호가가 약 22bp 수준으로 들어와 기존 15bp 기준에서는 모든 주문 후보가 차단됐기 때문에, 모의운용 검증을 위해 25bp까지 허용한다.
  - 그래도 시간대, 신뢰도, 매수 전용 정책, 포지션 한도는 계속 적용된다.

## 저장소 구조

```text
app/                애플리케이션 코드
config/             TOML 설정, watchlist, autopush 설정
docs/               canonical 문서와 상세 설계 문서
docs/archive/       퇴역한 운영 문서 원문
docs/logbook_archive/ 기간별 작업 요약
migrations/         DB 스키마 초안
runtime-data/       로그, 리포트, 모델, 캐시, 실행 산출물
scripts/            반복 실행용 bash 스크립트
tests/              unittest 기반 검증
.agents/skills/     저장소 전용 skill 자리
templates/          새 저장소 시작용 운영 팩 자리
```

## 빠른 실행

전체 테스트:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

저장소 구조와 현재 Markdown 감사:

```bash
python scripts/audit_repository_structure.py
```

synthetic 전체 흐름:

```bash
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --build-runtime-report
```

10종목 과거 데이터 backfill:

```bash
./scripts/collect_historical_data.sh --start-date 2021-01-01
```

KIS `주식일별분봉조회`는 과거 분봉 조회가 가능하지만 공식 샘플 기준 최대 1년 보관으로 안내되어, 5년치 학습용 기본 backfill 은 pykrx 일봉을 15분 간격 26개 proxy bar 로 변환해 기존 `curated_minute_bars`, `raw_orderbook_ticks`, `feature_model_inputs`, `feature_labels` 구조에 적재한다.

Cybos Plus 15분봉 backfill 은 Windows 32bit Python 과 Cybos Plus COM 로그인이 필요하므로 Windows PowerShell 에서 직접 실행한다. 코스피200 전체 수집 시 종목 목록은 `CpUtil.CpCodeMgr`에서 동적으로 조회하되, ETF/인덱스 등 비주식 코드가 섞일 수 있어 숫자 6자리 종목 코드만 사용한다. Windows 에서 WSL2 UNC 경로의 SQLite DB를 직접 잠그지 않도록, 수집기는 기본적으로 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\cybos_collect.db`에 저장하고 WSL2 안에서 main runtime DB로 병합한다. Cybos `StockChart`는 긴 기간 요청에서 행 수가 잘릴 수 있어 기본 요청 단위는 60일이다.

새로 내려받거나 수집하는 대용량 외부 데이터는 기존 `D:\GitHub\Real-time-stock-price-prediction-program` 폴더를 사용하지 않고 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래에 보관한다. WSL2에서는 같은 위치를 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 로 접근한다.

```powershell
E:\Users\Keios\AppData\Local\Programs\Python\Python311-32\python.exe `
  scripts\collect_cybos_historical.py `
  --start 2021-01-04

E:\Users\Keios\AppData\Local\Programs\Python\Python311-32\python.exe `
  scripts\collect_cybos_historical.py `
  --symbols 005930 --start 2021-01-04
```

```bash
bash ~/projects/Real-time-stock-price-prediction-program/scripts/merge_cybos_to_main.sh \
  --src /mnt/d/CodexData/Real-time-stock-price-prediction-program/cybos/cybos_collect.db \
  --dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db
```

병합이 성공하면 `source=cybos-historical` 행을 기존 `raw_market_ticks` 구조에 넣고, 15분봉은 기존 `curated_minute_bars` 기본키로 upsert 한 뒤 `--src`로 넘긴 DB를 삭제한다. 원본 수집 DB를 보관해야 하면 병합 전에 같은 D드라이브 보관 경로 안에서 복사본을 만들어 둔다.

2026-05-07 삼성전자 테스트 기준으로 `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00` 구간 32,451개 15분봉을 `source=cybos-historical`로 병합했다. `2021-01-04..2021-03-29` 구간은 15일 단위로 재시도했지만 Cybos가 0행을 반환했다.

단순 백테스트:

```bash
python -m app --run-backtest --horizon-min 15
```

walk-forward 백테스트:

```bash
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
```

정본 gate reference 워크포워드:

```bash
python -m app --run-gate-walk-forward --horizon-min 15
./scripts/run_gate_walk_forward_backtest.sh
```

이 명령은 `source=cybos-historical` 학습 행만 사용하고, 리포트 JSON에 `parameter_profile=gate_reference_v1`과 `command_source=cli_run_gate_walk_forward`를 남긴다.
일반 실험용 `--run-walk-forward`는 `parameter_profile=ad_hoc_cli`로 남아 정본 gate reference와 구분된다.

최근 실험 기준 추천 조합:

```bash
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
```

challenger 비교:

```bash
python -m app --run-challengers --horizon-min 15
```

기본 실행은 PC 안정성을 위해 최근 labeled feature row `250,000`건만 읽는다. 전체 이력으로 평가해야 할 때만 `--challenger-max-rows 0`을 명시한다.

이제 challenger는 학습 validation 구간을 다시 평가 구간으로 쓰지 않고 마지막 tail `10%`를 reserved holdout으로 분리해 평가한다. candidate별 `evaluation_independence_status`를 기록하고, 최신 walk-forward 결과도 함께 읽어 `promote`, `keep_active`, `review_required` 중 하나를 내린다. LightGBM artifact에는 `training_run_id`와 holdout metadata를 저장하며, DB 최신 training row와 artifact의 run id가 다르면 복구/복사 불일치로 보고 승격 후보에서 제외한다. 재학습 뒤 데이터가 추가되어 holdout 경계가 바뀌면 fail-safe로 promotable이 막히므로, 승격 검토는 재학습 직후 challenger를 이어서 실행한다.

active model을 안전하게 baseline으로 고정:

```bash
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
```

LightGBM shadow 학습:

```bash
python -m app --train-lightgbm --horizon-min 15
```

이 명령은 이제 artifact와 평가 기록만 만들고, active model을 자동으로 교체하지 않는다. 기본 실행은 최근 labeled feature row `250,000`건으로 제한하며, 전체 이력 학습은 `--train-lightgbm-max-rows 0`을 명시했을 때만 수행한다.

Cybos 실제 15분봉만 사용하는 bar-only 기준선 실험:

```bash
./scripts/run_research_on_snapshot.sh -- \
  python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13

python -m app --run-cybos-bar-only-experiment --horizon-min 15
python -m app --run-cybos-bar-only-experiment --horizon-min 15 --cybos-experiment-feature-set bar_context
python -m app --run-cybos-profitability-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-label-sensitivity-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-label-reproducibility-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-expected-value-review --horizon-min 15 --cybos-experiment-feature-set bar_context_momentum --cybos-profitability-cost-pct 0.108
```

이 실험은 `source=cybos-historical`만 사용하고 `pykrx-daily-proxy`, `kis-ws`는 제외한다. Cybos 과거 데이터에는 호가가 없으므로 `mid_price`, `spread_bps`, `bid_ask_imbalance`도 제외한다. 지원 피처 세트는 `bar_only`, `bar_context`, `bar_context_momentum`이다. profitability review는 F-5 재현, 거래 원장 손익 진단, 왕복 비용 기준선, train-only confidence threshold, H60 bar-only 비교를 연구 리포트로 남긴다. label sensitivity review는 threshold를 자동 채택하지 않고 비용 기준 라벨 민감도만 진단한다. label reproducibility review는 민감도 진단에서 튄 threshold를 다른 fold 설계와 기간 샘플로 재검증한다. rule challenger review는 고정 long-only 룰 후보를 비용 반영 walk-forward로 비교하되, 최고 결과를 자동 승격하지 않는다.
expected-value review는 각 fold의 train tail calibration 구간에서만 `probability_up` threshold를 고르고 test 구간에 적용한다. 선택 기준은 비용 차감 평균 기대값이 양수인 후보이며, test 결과를 보고 threshold를 다시 맞추지 않는다. 이 리포트도 연구용 진단이며 active model 자동 승격에는 쓰지 않는다.

월요일 전 shadow ML 갱신 일괄 실행:

```bash
./scripts/run_ml_shadow_cycle.sh
```

장마감 후 quick maintenance 수동 재실행:

```bash
./scripts/run_post_close_ml_maintenance.sh --quick
```

장마감 후 snapshot 기반 heavy research 수동 재실행:

```bash
./scripts/run_post_close_ml_maintenance.sh --heavy-research --use-snapshot
```

KIS WebSocket 수신기:

```bash
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
```

KIS WebSocket 검증:

```bash
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

이 검증은 이제 `연결 준비 완료`와 `실제 장중 데이터 수신 확인`을 분리해서 기록한다.

로컬 대시보드 snapshot 생성:

```bash
python -m app --build-dashboard
```

로컬 대시보드 실행:

```bash
./scripts/run_dashboard.sh
```

실행 후 브라우저에서 `http://127.0.0.1:8765` 를 열면 된다.
이 스크립트는 이제 background 실행 시에도 `py -3` 또는 실제 Python executable 경로를 먼저 찾아 사용한다.
기본 자동 새로고침 주기는 `10분`이고, 화면 우측 상단 `상태 업데이트` 버튼으로 수동 새로고침도 할 수 있다.

대시보드는 이제 기본적으로 `sample`, `synthetic`, `demo` 데이터를 제외하고 실제 KIS 기반 운용 데이터만 보여준다.
샘플 WebSocket 재생 결과도 이제 `replay` 계열로 따로 저장되어 실제 운용 데이터 범위에 들어오지 않는다.
대시보드는 이제 상단 상태 영역과 `10개 탭` 구조를 사용한다.
탭은 `모의투자(가상)`, `모의계좌(실제)`, `실 운용계좌`, `머신러닝 현황`, `상태 및 설정`, `예측현황`, `신호 & 주문현황`, `체결과 분봉`, `오늘의 리포트`, `기타` 로 나뉜다.
각 탭은 내부적으로 같은 세로 보조탭 구조를 사용하고, 긴 표와 목록은 스크롤 패널 안에서 확인한다.
브로커 계좌 잔고는 `runtime-data/reports/kis-account/latest-account-paper.json` 과 `latest-account-live.json` 캐시를 읽고, 캐시가 오래되면 KIS REST로 새로 갱신한다.
로컬 모의운용 계좌는 프로그램 내부 가상 포트폴리오이고, 브로커 계좌는 한국투자에서 직접 조회한 실제 계좌 상태다.
학습 탭은 `실운용 학습 상태`와 `검증 및 비교 결과`를 함께 보여주되, 둘 다 실제 운용 데이터 기준 산출물만 사용한다.
실데이터 기반 결과가 없으면 연구용 예비 값을 대신 보여주지 않고, `실데이터 기반 결과 없음` 상태로 남긴다.
예측 탭은 `기준가`, `예측 결과`, `예상 변동`, `실제 결과`, `성공 여부`를 함께 보여준다.
예측현황 탭은 `오전/오후`, `시간대별`, `상승/하락` 통계를 함께 보여준다. 최근 예측 요약은 최대 `100개`까지 유지하고, 예측상세는 선택 기간 전체 예측을 최신 순으로 보여준다.
신호와 주문은 `신호 & 주문현황` 탭에서 묶어서 확인할 수 있다.
`오늘의 리포트` 탭은 현재 범위 기준 계좌 운용 결과와 고찰, 다음 접근 방향을 자동 요약한다.
화면 상단 `조회 범위`와 `기준 날짜`를 바꾸면 특정일, 최근 3일/7일/30일, 전체 누적 데이터를 선택해서 볼 수 있다.
상단 상태 영역은 현재 운영 모드, 15분/60분 활성 모델, 장 상태, 실시간 수집기 상태, 자동 새로고침 주기, 현재 선택 범위를 함께 보여준다.
`모의투자(가상)` 탭은 프로그램 내부 가상 장부 기준 운용 상태를, `모의계좌(실제)` 탭은 한국투자 모의투자 계좌 직접 조회 잔고를, `실 운용계좌` 탭은 실전 계좌 조회 상태를 분리해서 보여준다.
`모의투자(가상)` 탭의 `매수·매도 및 체결현황` 화면은 `매수 주문 / 매도 주문 / 체결 / 최근 신호` 확장 탭으로 펼쳐 볼 수 있다.
다른 상위 탭도 같은 방식으로 `상태 설명 / 보유 종목 또는 상세표 / 해석 또는 안내`를 왼쪽 세로 선택기로 전환한다.
실제 장중 데이터가 충분히 쌓이지 않았으면 백테스트, 워크포워드, 도전자 모델 결과는 예비 값을 대신 보여주지 않고 `실데이터 기반 결과 없음` 상태로 남긴다.
기존 테스트용 운용 흔적을 SQLite에서 정리하려면 아래를 사용한다.

```bash
./scripts/cleanup_runtime_test_data.sh
```

테스트 실행 뒤 생긴 `.tmp-tests` 산출물, Python `__pycache__`, PowerShell provider prefix 오염 디렉터리를 점검하려면 아래를 사용한다. 기본은 dry-run 이며, 실제 삭제는 `--apply`를 붙인다. `.tmp-tests/codex-ops/`는 장중 incident 초안 보존을 위해, `app/risk/` 아래 생성물은 리스크 모듈 작업 금지 정책 때문에 자동 정리 대상에서 제외한다.

```bash
./scripts/cleanup_repo_generated_artifacts.sh
./scripts/cleanup_repo_generated_artifacts.sh --apply
```

실데이터만 남기고 ML/검증 산출물을 다시 만들려면 아래를 사용한다.

```bash
./scripts/rebuild_actual_ml_state.sh
```

브로커 모의계좌 잔고만 새로 갱신:

```bash
./scripts/refresh_kis_account.sh
python -m app --kis-account-balance
```

로컬 가상 계좌와 브로커 모의계좌를 바로 비교:

```bash
./scripts/reconcile_paper_accounts.sh
python -m app --reconcile-paper-accounts
```

이 결과는 실행 리포트와 대시보드의 `최근 동기화 점검`, `차이 상세` 카드에도 함께 반영된다.
실제 reconciliation 실행은 계좌번호나 원문 응답 없이 최근 10개 유효 장후 거래일을 `runtime-data/reports/reconciliation/paper-account-history/`와 `latest-paper-account-history.json/.md`에 누적한다. 대시보드의 `10거래일 누적 정합성`, `거래일별 정합성` 카드에서 현재 `needs_review / insufficient_history / ready` 상태와 차이 종목을 확인할 수 있다.

브로커 기준으로 로컬 가상 계좌 현재 상태를 다시 맞추려면:

```bash
./scripts/align_local_paper_to_broker.sh
python -m app --align-local-paper-to-broker
```

이 정렬은 destructive delete 가 아니라 marker 기반 현재 상태 정렬이다.

브로커 모의계좌 주문 미러링을 켜고 실행:

```bash
$env:ENABLE_BROKER_PAPER_MIRRORING="true"
./scripts/start_runtime_autoboot.sh
```

현재 기본 전략 설정은 `true` 이고, 대시보드에는 현재 켜짐 여부와 브로커 제출 주문 수가 함께 표시된다.
실시간 수집 중 브로커 체결 조회가 KIS rate-limit 에 걸리면 즉시 재시도하지 않고 5분 cooldown 으로 빠진다. 수동 동기화 명령은 기존처럼 짧게 재시도한다.

로컬 대시보드 background 시작 / 상태 / 중지:

```bash
./scripts/start_dashboard_background.sh
./scripts/get_dashboard_status.sh
./scripts/stop_dashboard.sh
```

이 background 시작 스크립트는 이제 wrapper bash 대신 실제 Python 실행 파일을 직접 찾아 서버를 띄운다.
가능하면 `pythonw.exe`를 우선 사용해 콘솔 종료 영향 없이 더 안정적으로 유지한다.
또한 `/health` 응답이 올라올 때까지 잠깐 기다린 뒤 상태 파일을 `running` 으로 기록한다.
`get_dashboard_status.sh` 는 이제 `/health` 뿐 아니라 `/api/dashboard.json` 응답까지 확인해, 포트만 열려 있고 실제 payload 가 죽은 상태도 잡는다.
dashboard / watchdog helper 는 저장된 pid 가 다른 프로세스로 재사용돼도 실제 `python -m app --serve-dashboard` / watchdog script 가 아니면 `running` 으로 보거나 끄지 않는다.
이 dashboard / live-runtime / watchdog 계열 스크립트의 기본 `WorkspaceRoot` 는 이제 현재 shell 위치가 아니라 스크립트가 들어있는 저장소 root 를 기준으로 자동 계산한다.
기본 `today` 화면과 `/api/dashboard.json` 은 최신 snapshot cache 를 우선 내려 더 빠르게 응답하고, `상태 업데이트` 또는 10분 자동 새로고침 때는 `/api/refresh` 로 새 snapshot 을 다시 만든 뒤 reload 한다.

runtime watchdog background 시작 / 상태 / 중지:

```bash
./scripts/start_runtime_watchdog_background.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/stop_runtime_watchdog.sh
```

runtime watchdog 은 정규장에는 dashboard 와 live runtime 이 둘 다 살아 있는지 보고 꺼져 있으면 다시 올린다. 장외와 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 live runtime 을 새로 켜지 않고, 켜져 있으면 중지 상태로 둬서 WebSocket 재연결 루프를 막는다. 다만 일반 거래일의 정규장 시작 60분 전부터는 `pre-open` warmup 으로 live runtime 을 미리 켜서 장 시작 직후 수집 지연을 줄인다. 그보다 이른 시간은 `overnight` 상태로 표시한다.
다만 root `.env` 가 없거나 KIS 자격정보가 비어 있으면 live runtime 은 `blocked` 상태로 두고 무한 재시도를 멈춘다.
반대로 root `.env` 와 현재 trading mode 기준 KIS app key/secret 이 다시 준비되면, stale blocked 상태는 `stopped` 로 정리되고 다음 watchdog cycle 에서 재기동을 다시 시도할 수 있다.
상태 파일은 `runtime-data/reports/runtime-watchdog/state/watchdog-state.json` 에 남는다.
watchdog 은 dashboard `/api/refresh` 로 cached snapshot 을 갱신하고, 현재 장 시간과 최신 KIS verification 파일을 함께 기준으로 삼아 정규장 `missing/stale` 분봉 상태를 복구한다.
watchdog 상태 조회는 `last_checked_at` 기준 심박 나이를 함께 표시한다. 프로세스가 살아 있어도 기본 10분 이상 심박이 갱신되지 않으면 `stale` 로 보고, `start_runtime_watchdog_background.sh` 는 해당 stale 프로세스를 재시작한다.
정규장에 live runtime 이 실행 중이고 최신 분봉 상태가 `fresh` 이면 별도 KIS verification WebSocket 을 중복으로 열지 않는다.
대시보드 snapshot 전체 재생성은 기본 10분 간격으로 제한하고, 실시간 지연 판단은 우선 live runtime 상태값을 사용해 CPU를 계속 쓰는 refresh 루프를 줄인다.

PC 재부팅 후 자동 시작용 runtime autoboot:

```bash
./scripts/start_runtime_autoboot.sh
./scripts/install_runtime_startup_launcher.sh
./scripts/get_runtime_startup_launcher_status.sh
./scripts/remove_runtime_startup_launcher.sh
```

`start_runtime_autoboot.sh` 는 demo/sample SQLite 행 정리, 대시보드, 실시간 수집기, 브로커 모의계좌 잔고 갱신, runtime/dashboard 재생성을 한 번에 수행한다. 장외나 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기를 새로 켜지 않고 중지 상태로 맞춘다.
여기에 `sync-broker-paper-orders`, `paper-account reconciliation`, 필요 시 `paper baseline alignment` 도 포함되어, 재부팅 후 바로 브로커 기준 현재 상태를 다시 맞춘다.
이제 여기에 runtime watchdog 시작도 포함되어, 로그인 직후부터 dashboard 와 live runtime 이 다시 죽으면 자동 재기동할 수 있는 기반이 같이 올라온다.
이제 하위 `python -m app` 명령이 실제로 실패하면 성공처럼 지나가지 않고 바로 오류로 올린다.
`install_runtime_startup_launcher.sh` 는 WSL2/Windows 환경에서는 Windows 시작프로그램의 `RealTimeStockRuntime.cmd`를 현재 WSL 정본 저장소 경로로 설치한다. Windows launcher는 로그인 직후 짧게 대기한 뒤 `--skip-runtime-cleanup --skip-dashboard-build` 빠른 시작 경로로 실행하고, 결과를 `runtime-data/logs/automation/RealTimeStockRuntime.log`에 남긴다. Windows 시작프로그램을 사용할 수 없는 순수 Linux 환경에서만 systemd user service 로 fallback 한다.
`get_runtime_startup_launcher_status.sh` 는 Windows 시작프로그램 런처와 systemd user service 상태를 함께 보고, 현재 저장소 경로와 일치하는지도 확인한다.

복구 직후 로컬 setup 점검:

```bash
./scripts/check_local_setup.sh
```

이 스크립트는 root `.env`, `websockets`, dashboard, live runtime, watchdog, runtime startup launcher, NAS recovery root 접근 여부를 함께 확인하고 아래 보고서를 갱신한다.

- `runtime-data/reports/recovery/latest-local-setup-check.json`
- `runtime-data/reports/recovery/latest-local-setup-check.md`

보안 입력으로 root `.env` 복구:

```bash
./scripts/restore_kis_env_interactive.sh
```

계좌번호와 상품코드까지 함께 복구해야 하면:

```bash
./scripts/restore_kis_env_interactive.sh -IncludeAccountFields
```

Phase 1b 실전계좌 조회 준비 상태만 확인하면:

```bash
./scripts/run_phase1b_readonly_observation.sh
```

이 명령은 네트워크를 사용하지 않는다. live 조회 자격정보를 위의 `--read-only-preparation` 방식으로 준비하고 제한된 조회 증거를 만들 때만 `./scripts/run_phase1b_readonly_observation.sh --execute`를 사용한다.

Phase 1b 관측 결과를 기존 장전 fixture와 합쳐 전용 readiness로 판정할 때는 아래처럼 실행한다.

```bash
./scripts/run_live_readiness_dry_run.sh \
  --phase phase1b_live_readonly \
  --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json \
  --phase1b-observation-path runtime-data/reports/live-readiness/phase1b/latest-phase1b-readonly-observation.json \
  --report-path runtime-data/reports/live-readiness/phase1b/latest-readiness.json
```

`--phase1b-observation-path`를 주면 기존 paper fixture의 token/account/system clock 값 대신 해당 실계좌 read-only 관측값을 사용한다. 관측이 차단되거나 누락되면 paper 성공값으로 되돌아가지 않고 fail-closed로 차단한다. 관측 파일에 저장된 precomputed override는 판정 근거로 신뢰하지 않고 `execution_started`와 sanitized artifact에서 매번 다시 계산한다. `phase1b_live_readonly`에서는 `market_status`와 kill switch OFF가 주문 제출 전용 안전장치이므로 비차단 관측이며, WebSocket recovery와 나머지 운영 check는 필수다. 결과는 대시보드 `상태 및 설정 > 실전 전환 readiness dry-run`에서 별도 Phase 1b 행으로 확인한다.

위 단계를 한 번에 안전하게 실행하려면:

```bash
# 기본: 외부 KIS 네트워크 0회 preflight + local readiness
./scripts/run_phase1b_readiness_cycle.sh

# 실계좌 자격정보 준비 후 장외 bounded read-only 관측
./scripts/run_phase1b_readiness_cycle.sh --execute --refresh-dashboard
```

cycle은 `pre-open`과 `regular-session`에서 모든 단계를 시작 전에 차단한다. 기본 실행은 fresh local premarket/WS 증거를 만들지만 실제 관측 readiness를 덮지 않고 `latest-readiness-preflight.json`에 분리한다. `--execute`를 줬어도 실제 네트워크 시도가 0회이면 `latest-readiness-attempt.json`, bounded 관측이 1회 이상 시작된 경우에만 `latest-readiness.json`을 갱신한다.

2026-07-20 장후 사전등록 E1/E5 재측정은 아래 단일 명령으로 실행한다.

```bash
./scripts/run_preregistered_e1_e5_round.sh --execute
```

기본 실행은 dry-run이고, `2026-07-20 15:30 KST` 이전, 장중, 또는 2026-07-20 장후 label refresh 미완료 상태에는 `--execute`도 snapshot 생성 전에 차단된다. 허용 시 D드라이브 연구 snapshot에서 고정 구간 `2026-07-04~2026-07-18`만 read-only로 측정하며 학습·네트워크·주문·정책/model/gate 변경은 수행하지 않는다.

월요일 시작 루틴 1회 실행:

```bash
./scripts/start_monday_runtime.sh
```

이 스크립트는 대시보드를 띄우고, shadow ML 갱신과 KIS 사전 점검을 순서대로 수행한 뒤 현재 active 모델과 주요 리포트 상태를 요약한다.
이제 여기에 `demo/sample runtime cleanup`, `실시간 수집기 background 시작`, `runtime watchdog 시작`, `KIS 브로커 모의계좌 잔고 갱신`도 포함된다.

실시간 수집기 background 시작 / 상태 / 중지:

```bash
./scripts/start_live_runtime_background.sh
./scripts/get_live_runtime_status.sh
./scripts/stop_live_runtime.sh
```

실시간 수집기가 켜져 있으면:

- watchlist 종목을 계속 수집한다.
- 새 분이 닫힐 때마다 15분과 60분 예측을 함께 기록한다.
- 신호와 주문 판단은 15분 기준으로만 수행한다.
- 대시보드 상단 `현재 프로그램 상태`와 `로컬 모의운용 계좌`가 `운용 중`으로 바뀐다.
- 최근 예측 표에는 방향 문구 대신 기준가 대비 `예상 변동`과 수평선 도달 뒤 `실제 결과`가 표시된다.

매시간 저장소 점검 1회 실행:

```bash
./scripts/run_hourly_repo_audit_iteration.sh
```

매시간 저장소 점검 Codex 자동화 권장:

- Codex 자동화로 등록하면 앱 UI에서 바로 중지할 수 있다.
- 아래 bash 백그라운드 실행기는 Codex 자동화가 없을 때만 쓰는 예비 경로다.

매시간 저장소 점검 백그라운드 시작(예비 경로):

```bash
./scripts/start_hourly_repo_audit_background.sh
```

매시간 저장소 점검 상태 확인:

```bash
./scripts/get_hourly_repo_audit_status.sh
```

프로세스가 죽었는데 상태가 `waiting` 으로 남아 있으면 이 스크립트는 `stale` 로 해석해서 보여준다.
hourly audit 와 deadline review runner 상태/중지 스크립트도 이제 실제 bash script command line 을 확인해 stale pid 재사용 오판을 줄인다.
repo audit 스크립트는 WSL2의 `git` 을 기준으로 현재 저장소 상태를 점검한다.

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

- 버전 변경 스크립트: `scripts/bump_version.sh`
- 자동 점검 스크립트: `scripts/run_hourly_repo_audit_iteration.sh`, `scripts/start_hourly_repo_audit.sh`, `scripts/start_hourly_repo_audit_background.sh`
- watcher 설정: `autopush.json`
- watcher 상태: `runtime-data/autopush/git-autopush-state.json`
- watcher 로그: `runtime-data/autopush/git-autopush.log`
- 실행 설정은 root `.env`가 있으면 자동으로 함께 읽는다.
- git-autopush 관련 `-ScanRoot` 기본값은 현재 저장소 root 이다.
- WSL `git push`가 GitHub HTTPS 인증에서 멈추면 watcher는 Windows GitHub Desktop의 Git 자격 증명을 사용한 push fallback을 시도한다.

자동 점검 산출물은 `runtime-data/reports/codex/automation/` 아래에만 쌓이고 repo-tracked 파일은 건드리지 않는다.

Codex 운영 보조 job 산출물은 `runtime-data/reports/codex/ops/` 아래에 둔다. 장중 incident patch 초안은 `.tmp-tests/codex-ops/` 아래에만 만들고 자동 cleanup 대상에서 제외한다. 실제 root 코드 적용, 운영 DB schema apply, runtime restart, 실전 주문 관련 flag 변경은 Codex 운영 job이 자동으로 수행하지 않는다. 현재 wrapper는 `scripts/run_codex_ops_job.sh --job-type premarket-readiness` dry-run report와 `scripts/run_live_readiness_dry_run.sh` fixture 기반 readiness report 생성까지 구현되어 있으며 Codex CLI를 호출하지 않는다. live readiness dry-run은 token refresh, WebSocket recovery, account snapshot, market status, system clock, kill switch, database, disk space, dashboard, storage migration state 10개 check를 요구한다. `token_refresh` check는 `scripts/probe_kis_token_refresh.sh`가 paper/live 인증 refresh 결과에서 token 원문 없이 sanitized JSON을 만든 경우에만 통과 후보가 된다. `account_snapshot` check는 `scripts/probe_kis_account_snapshot.sh`가 read-only 계좌 snapshot 조회 결과에서 계좌번호 없이 sanitized JSON을 만든 경우에만 통과 후보가 된다. `ws_recovery` check는 `scripts/probe_kis_ws_recovery.sh`가 실제 WebSocket 네트워크를 열지 않는 synthetic fault injection 결과를 만든 경우에만 통과 후보가 된다. 실제 KIS WebSocket 복구 관측은 Phase 1 read-only 진입 뒤 별도로 수집한다. `market_status` check는 `scripts/probe_market_status_snapshot.sh`가 repo 내부 수동 snapshot을 읽어 모든 요청 종목이 거래 가능하다고 판단한 경우에만 통과 후보가 된다. KIS/거래소 자동 원천은 아직 연결하지 않는다. `system_clock` check는 fixture/dry-run 결과 또는 `scripts/probe_kis_clock_reference.sh`가 read-only 현재가 조회 1회로 생성한 sanitized check JSON을 `--system-clock-check-path`로 넘긴 경우에만 통과 후보가 된다. `scripts/build_live_readiness_fixture_snapshot.sh`는 기존 premarket report, token refresh check, account snapshot check, synthetic WS recovery check, market status check, system clock check, kill switch 상태 파일을 읽어 로컬로 증명 가능한 check만 fixture JSON으로 묶는다. market status check 파일이 없으면 자동으로 통과시키지 않는다. `database` check는 premarket report에서 SQLite read-only smoke로 확인하며 storage migration state와 분리한다. 기본 실행은 JSON only이고, SQLite 기록은 `--record --database-path <repo 내부 경로>`를 명시한 경우에만 수행한다. `scripts/set_live_kill_switch.sh`는 기본 dry-run/status이며 실제 ON/OFF 파일 기록은 `--apply`가 있을 때만 수행한다. OFF 해제는 실수 방지를 위해 `--disable --apply --confirm-disable`을 요구한다.

2026-05-23 기준으로 timestamp가 있는 readiness 증거는 key별 freshness 기준을 넘으면 `stale_evidence`로 차단한다. 현재 기준은 `system_clock/ws_recovery=30분`, `account_snapshot/market_status=1시간`, `token_refresh=4시간`이다. `account_snapshot`은 row count뿐 아니라 `cash_balance`, `stock_evaluation_amount`, `total_asset_amount` shape 존재와 값 타입 drift까지 확인한다. Phase 2/3에서는 synthetic `ws_recovery`가 readiness와 live submit guard 양쪽에서 거부되며, 실제 KIS WebSocket 관측 evidence type이 있어야 broker 호출 전 가드를 통과할 수 있다. WS evidence type은 `app/services/ws_recovery_evidence.py`의 단일 정의를 사용한다. Dashboard의 live readiness 카드에는 `ws_recovery` evidence type, 실제 증거 여부, freshness, stable frame, reconnect storm 여부를 read-only로 표시한다. HTTP `Date` 기반 `system_clock` skew는 초 단위 header 한계 때문에 밀리초 정밀도가 아니라 대략 1초 이내 여부를 보는 증거다. `scripts/probe_kis_clock_reference.sh --compare-paper-live`는 주문 메서드 없는 read-only quote로 paper/live HTTP `Date` reference를 각각 1회 비교하는 sanitized 진단 JSON을 만들 수 있다.

버전은 작업 마지막에 바꾸고, watcher가 그 변화를 감지해 자동 commit/push 또는 기존 release commit push를 수행한다.

## 현재 ML 운용 기준

현재 `15분` 기준 active model은 builtin `baseline-h15-v1` 이다.

- 이유 1: 최근 synthetic/runtime 검증에서 active baseline이 가장 안정적이었다.
- 이유 2: 최신 LightGBM 학습은 정상 동작하지만, 현재 validation accuracy와 challenger 결과가 아직 약하다.
- 이유 3: 따라서 LightGBM은 `shadow challenger`로 계속 학습하고, 최신 artifact가 있는 horizon 은 장중 shadow serving 예측만 저장한다. 검증 통과 전에는 active model로 승격하지 않는다.

## 기준 문서와 참고 문서

이 저장소는 문서를 아래처럼 구분한다.

- 기준 문서
  - `AGENTS.md`
  - `README.md`
  - `docs/logbook.md`
  - `docs/Versioning.md`
  - `docs/Current-Implementation.md`
- 참고 문서
  - `docs/Architecture.md`
  - `docs/Implementation-Blueprint.md`
  - `docs/KIS-Integration-Plan.md`
  - 그 외 주제별 상세 설계 문서

현재 사실 기준은 기준 문서에 남기고, 상세 설계와 배경 설명은 참고 문서에 둔다.

<!-- NAS_BACKUP_START -->
## NAS Backup

- NAS 공유 루트: \\192.168.0.2\backup
- 저장소 백업 경로: \\192.168.0.2\backup\repos\real-time-stock-price-prediction-program\recovery-exports
- NAS 백업은 재난 복구용 전체 백업과 실전 전환 검증용 sanitized recovery export를 구분한다.
- 재난 복구용 전체 백업은 이전 저장소 유실 사고 대응을 위한 이중 보관이며, 접근 권한이 제한된 NAS 안에서 전체 작업 트리와 로컬 복구 자산을 보존할 수 있다.
- 실전 전환 검증용 sanitized recovery export는 root `.env*`, KIS 토큰 캐시(`runtime-data/cache/kis`), runtime 로그(`runtime-data/logs`), private key 계열 파일을 제외한다. cowork 전달이나 readiness 증거는 이 sanitized 기준만 사용한다.
- 정기 백업 명령은 주 1회 기준으로 제공하며, 최신 3개 package를 보관한다.
- NAS 백업은 용량과 소요 시간이 크므로 Codex가 자율 실행하지 않는다.
- 주간/강제 NAS 백업은 사용자가 해당 작업에서 명시적으로 지시했을 때만 실행한다.

Weekly backup:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_weekly_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup"
```

Forced backup:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_forced_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup" -Reason "before-release"
```

See [RECOVERY.md](./RECOVERY.md) for the full recovery scope.
<!-- NAS_BACKUP_END -->

