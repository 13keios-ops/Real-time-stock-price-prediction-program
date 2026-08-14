# 현재 구현 상태

## 현재 요약

### 2026-07-12 수익성 판정

- 현재 실제 수익 후보는 `0개`다. active `baseline-h15-v1`은 안전한 기준선 역할일 뿐 수익성이 입증된 모델이 아니다.
- challenger와 rescue/avoid는 3분류 정확도만 보지 않고 현행 왕복비용 `0.29%`, random control, 일별 재현성, 완전 lineage, 실제 portfolio replay를 함께 보도록 구현돼 있다.
- buy-avoid는 손실을 조금 줄였지만 절대 손익이 큰 음수이고 무작위보다 선별력이 나빠 기각됐다. buy-rescue KIS live no-trade 원장은 2026-08-02 기준 52,417행 중 eligible 25,726행이지만, LightGBM/linear-score/두 모델 동시 상승 진단이 모두 비용 후 음수라 후보가 아니다. hold-rescue도 현금손익을 악화시켜 후보가 아니다.
- 최신 walk-forward 산출물의 `0.108%` 비용 결과는 과거 진단이다. 정확도 gate도 실패했으며 현행 수익성 증거로 쓰지 않는다. 다음 생성물부터 `cost_model_version`을 기록한다.
- 2026-08-15 완결 E1/E5 라운드는 E1 후보 `0/3`, E5 second interval 미재현으로 기존 가설을 기각했다. 다음 수익 연구는 threshold 구제가 아니라 orderbook×regime/시간대/변동성/source/horizon의 새 사전등록 뒤 동일 비용·portfolio·random control·비중복 구간 비교다.

이 프로젝트는 국내 주식 실시간 데이터를 로컬에 저장하고, 분봉과 특징을 만들고, 15분/60분 예측과 모의운용 검증까지 이어지는 기본 운영 흐름을 갖췄다.
현재 목표는 실전 자동매매가 아니라 `수집 -> 특징 생성 -> 예측 -> 로컬 모의운용 + KIS 모의계좌 검증 -> 리포트` 흐름을 안정화하는 것이다.

궁극적인 동작 목표는 `데이터 수집 -> 전략 후보 생성 -> 비용/슬리피지/세금 반영 검증 -> walk-forward 검증 -> paper 운용 -> 소액 실전 검증 -> 리스크 제한 운용 -> 일일 분석 -> 승격/폐기`가 반복되는 로컬 투자 연구·운영 시스템이다. 수익 목표는 과도한 일간 고정 수익률이 아니라 손실일을 제한하고 유리한 장세에서 수익 기회를 키우는 구조로 둔다. 월 누적 `+50%`는 장기 stretch target 으로 기록하지만, 보장 수익률이나 즉시 실전 운용 기준은 아니다.

장중 데이터 수집은 실험과 분리된 백그라운드 축으로 유지한다. 일반 거래일에는 `runtime watchdog`이 live runtime 을 켜서 KIS WebSocket 체결/호가 데이터를 계속 쌓고, 오프라인 ML/룰 실험은 이 수집기를 끄지 않고 DB와 리포트를 읽는다. 코스피200 Cybos 갱신은 Windows COM API 제약 때문에 장후 배치 수집과 WSL 병합 흐름으로 분리한다.

장중에는 `수집 트랙`과 `연구 트랙`을 분리한다. 수집 트랙은 `runtime-data/dev.db`를 계속 쓰고, 연구 트랙은 `scripts/create_research_db_snapshot.sh`가 만든 SQLite backup 스냅샷을 `DATABASE_URL`로 지정해 실행한다. 기본 스냅샷과 연구 산출물 위치는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 아래지만, source DB가 8GiB 이상이고 `/mnt/d`가 WSL 9P 계열이면 snapshot만 repo-local `runtime-data/research-snapshots/`를 사용한다. WSL 배포판 자체가 D드라이브에 있으므로 D드라이브 전용 산출물 규칙은 유지된다.

장마감 후 자동 관리는 runtime watchdog 이 하루 한 번 시작한다. 기본 30분 지연 뒤 `run_post_close_ml_maintenance.sh --quick`를 백그라운드 실행하고, quick 경로는 live DB를 무겁게 재학습하지 않고 runtime report, local setup readiness, KIS live 데이터 품질, KIS-Cybos feature drift, KIS live feature-label 진단, dashboard snapshot 만 갱신한다. 이 진단들은 대시보드 갱신용 warning-only 작업이라 실패해도 heavy research 를 자동 시작하지 않는다. live DB는 장중 수집 원장으로 남긴다. snapshot DB와 `--rebuild-actual-ml`을 쓰는 heavy research 는 명시 명령이나 별도 저부하 시간대에서만 실행하며, 자동 학습은 active model 교체나 실전 주문 승격을 하지 않는다.

현재 기본 운영 자세는 아래와 같다.

- 기본 거래 모드: `paper`
- 실전 주문: 기본 비활성화
- 15분 활성 모델: `baseline-h15-v1`
- 60분 활성 모델: `baseline-h60-v1`
- LightGBM: 장후 재학습과 challenger 비교에 사용하되, 검증 통과 전 자동 승격하지 않음. 최신 artifact가 있는 horizon 은 장중 같은 종목/시각에 shadow serving 예측으로 추가 저장하지만, 주문 판단에는 쓰지 않음
- 대시보드 주소: 실행 시 `http://127.0.0.1:8765`
- runtime 데이터 루트: `runtime-data/`
- 장 상태 라벨: 일반 거래일의 정규장 시작 60분 전부터 `pre-open` warmup 으로 보고, 그보다 이른 새벽/야간 시간은 `overnight`로 구분한다. `overnight`에서는 live runtime 이 꺼져 있어도 정상일 수 있다.

## 구현 완료 범위

현재 구현된 큰 축은 아래와 같다.

- KIS REST 현재가/호가 조회
- KIS WebSocket 파서, 수신기, 재연결 처리
- KIS WebSocket 연결 준비와 장중 데이터 수신 검증 리포트
- SQLite 정본과 JSONL 보조본 기반 runtime 저장. feature JSONL은 SQLite primary key 기준으로 재생성할 수 있으며 오프라인 dataset 재구축은 SQLite만 upsert해 append-only JSONL 중복을 만들지 않는다. broker paper 상태는 local order별 최신 snapshot만 SQL에서 조회하고, 상태 변화가 있을 때만 새 snapshot을 기록해 분 단위 polling 복제를 막는다. 과거 raw JSONL과 SQLite 상태 이력은 자동 삭제하지 않는다.
- 원시 체결/호가 저장. 비정상 top-of-book 호가(bid 또는 ask 0 이하, crossed)는 raw 감사 원장에는 남기되 신호 상태, feature, 연구 입력에서 fail-closed로 제외한다.
- 1분봉 생성
- feature / label 생성
- baseline, centroid, linear-score, LightGBM 학습과 비교
- 검증 꼬리구간 백테스트
- gap/max-train 제어가 가능한 walk-forward backtest
- challenger 평가, 순위, walk-forward gate, 승격 판단
- 활성 모델 등록부와 내장 예비 모델
- 재생과 실시간 흐름의 모의운용 상태 기록
- 실행 리포트, 백테스트 리포트, 워크포워드 리포트, 도전자 모델 리포트
- 로컬 대시보드 스냅샷 생성과 HTTP 제공. 모의계좌 화면은 전체 정렬 원장의 현재 잔고와 포지션을 표시하고, 선택 기간 주문과 체결 지표는 별도 활동값으로 표시한다.
- 실시간 수집기 백그라운드 시작/상태/중지
- 실행 감시기 백그라운드 시작/상태/중지
- PC 로그인 후 자동 복구용 실행 자동시작과 시작프로그램 실행기
- KIS 브로커 모의계좌 잔고 조회
- 로컬 가상 계좌와 브로커 모의계좌 정합성 점검
- 로컬 가상 주문을 KIS 모의계좌로 함께 제출하는 브로커 모의계좌 미러링
- 브로커 기준 표시자 기반 모의계좌 기준선 정렬
- KIS 호출 제한 재시도와 안전 실패 처리
- pykrx 일봉 기반 장기 과거 데이터 backfill 과 기존 SQLite 구조 적재
- Cybos 실제 15분봉 기반 bar-only LightGBM 연구 실험 경로
- 실전 전환 준비용 read-only client, live order guard, KIS live order guarded adapter, system clock skew helper
- 현재가·호가·과거분봉·계좌 조회와 CLI 조회 경로의 read-only factory 고정, sanitized paper/live account shape 비교 wrapper
- Phase 1b live 자격정보 준비 시 paper 모드를 보존하고 `ALLOW_LIVE_ORDERS=false`를 강제하는 interactive helper 옵션
- KIS interactive env restore는 자격정보 입력 전과 저장 후 `.env` 권한을 모두 `0600`으로 강제한다. `.env`는 git ignore 상태이며 자격정보 값은 리포트와 로그에 포함하지 않는다.
- 기본 네트워크 0회 사전검사와 명시적 `--execute` 제한 조회를 분리한 Phase 1b read-only 관측 wrapper. live token 1회, paper/live account 각 최대 1페이지, live clock quote 1회만 허용하고 앞 단계 실패 시 fail-closed로 중단하고 `pre-open`/`regular-session` 실행을 코드에서 차단한다. system clock은 앞선 probe 시작 시각이 아니라 quote 직전 UTC 시각으로 판정한다.
- live 주문/체결/포지션/감사/승인/readiness 초기 원장과 순수 helper
- 실전 전환 readiness dry-run, fail-closed market_status 템플릿 helper, kill switch dry-run/status/apply helper, KIS paper fixture redaction/export helper
- Phase 1a 모의투자 read-only readiness 프로필.
  `phase1a_paper_readonly`는 token/account/system clock/database/dashboard를 필수로 보고,
  `market_status`와 `kill_switch`는 live submit 전용 안전장치로 비차단 관측한다.
- Phase 1b 실전계좌 read-only readiness 프로필.
  `phase1b_live_readonly`도 주문 제출 전용 `market_status`와 kill switch OFF는 비차단으로 두되, Phase 1b 관측 JSON의 live token/account/system clock 증거를 paper fixture보다 우선한다. 관측 누락·차단 시 paper 성공값으로 되돌아가지 않으며, 관측 파일의 precomputed override 대신 실행 여부와 sanitized artifact에서 다시 계산하고 WebSocket recovery와 운영 check를 포함해 fail-closed로 판정한다.
- 대시보드의 `실전 전환 readiness dry-run` 표는 범용 readiness와 `runtime-data/reports/live-readiness/phase1b/latest-readiness.json`을 분리해 표시한다.
- 장외 Phase 1b readiness cycle.
  `run_phase1b_readiness_cycle.sh` 기본 실행은 외부 KIS 네트워크 없이 local premarket/WS/preflight/fixture/readiness를 순서대로 갱신한다. 실제 live 조회는 `--execute`에서만 요청하고, `pre-open`/`regular-session`은 step 시작 전에 차단한다. preflight·실행 미시작·실제 실행 readiness 파일을 분리한다.
- review_ver_27 사전등록 E1/E5 단일 라운드.
  `run_preregistered_e1_e5_round.sh`는 기본 dry-run이며 `2026-07-20 15:30 KST` 이전, `pre-open`/`regular-session`, 또는 2026-07-20 장후 label refresh 미완료 상태에는 실제 계산을 fail-closed로 차단한다. `--execute`가 허용되는 장외에는 D드라이브 연구 스냅샷을 만들고 고정 구간 `2026-07-04~2026-07-18`만 읽어 E1 전체/분해 IC, 후보 3건 재현성, `105560` p_flat 및 p_down/p_up 일별 IC 관계, E5 threshold `0.40` random-control excess/z를 한 번에 기록한다. 이 라운드는 학습·네트워크·주문 호출과 정책/model/gate 변경을 하지 않는다. research snapshot은 기본 180초 timeout을 두고 partial SQLite에서 quick_check 뒤 final 파일을 atomic replace하며 partial SQLite의 journal/WAL/SHM sidecar도 종료 시 정리한다. 2026-08-15 승인 실행은 명시적 1800초 상한으로 26GB snapshot을 830.5초에 검증하고 라운드를 완결했다.

## 데이터 흐름

기본 흐름은 아래와 같다.

```text
KIS 체결/호가
-> raw tick / raw orderbook 저장
-> 1분봉 생성
-> feature / label 생성
-> 모델 학습과 평가
-> 장중 예측
-> 15분 신호 판단
-> 로컬 모의주문
-> 선택적으로 KIS 모의계좌 주문 제출
-> 체결/포지션/계좌 정합성 점검
-> runtime report와 dashboard
```

## 대시보드

대시보드 스냅샷 생성:

```bash
python -m app --build-dashboard
```

대시보드 서버 실행:

```bash
./scripts/run_dashboard.sh
```

백그라운드 시작/상태/중지:

```bash
./scripts/start_dashboard_background.sh
./scripts/get_dashboard_status.sh
./scripts/stop_dashboard.sh
```

대시보드는 아래 기준으로 동작한다.

- 기본 자동 새로고침 주기: 10분
- 수동 갱신 버튼: `상태 업데이트`
- 기본 화면과 `/api/dashboard.json` 은 최신 캐시 스냅샷을 먼저 내려 빠르게 응답한다.
- 수동 갱신과 10분 자동 새로고침은 `/api/refresh` 로 스냅샷을 다시 만든 뒤 화면을 갱신한다.
- 대시보드 서버 시작 시 기존 캐시 스냅샷이 있으면 무거운 스냅샷 재생성을 먼저 하지 않고 서버부터 열어 기동 지연을 줄인다.
- 원시 체결/호가 행은 화면에 직접 표시하지 않고 분 단위 집계 카운트만 사용해 대시보드 재생성 부하를 낮춘다.
- 원시 체결/호가의 actual source 분 단위 집계는 `source, symbol, event_time` 인덱스를 사용해 Cybos 5년치 데이터가 섞인 DB에서도 대시보드 재생성 시간을 낮춘다.
- 기본 날짜 조회처럼 기간 필터가 있는 대시보드 생성은 대형 테이블 전체를 읽지 않고 SQL 시간 범위로 먼저 좁힌 뒤 실제 runtime 필터를 적용한다.
- 기본 `오늘` 대시보드는 raw tick 전체를 직접 그룹화하지 않는다. `latest-kis-live-data-quality.json`의 `latest_trade_date`로 마지막 실제 거래일을 먼저 정하고, 대시보드용 runtime scope는 이미 압축된 `curated_minute_bars` 기간 범위로 만든다. raw tick coverage 는 별도 `KIS live 데이터 품질` 카드가 담당한다.
- 변경 전 / 변경 후 / 영향 범위 / 회귀 위험:
  변경 전에는 기본 대시보드 생성도 `raw_market_ticks`와 `raw_orderbook_ticks` 전체를 `symbol × minute × source`로 그룹화해 DB가 커진 뒤 WSL 명령 세션이 종료될 수 있었다.
  변경 후에는 기본 날짜를 data-quality 리포트에서 정하고, dashboard scope 는 선택 기간의 `curated_minute_bars`로 만든다.
  영향 범위는 dashboard payload 수집, runtime scope 생성, SQLite raw count helper 의 기간 조건에 한정된다.
  회귀 위험은 dashboard 의 raw tick 총량 숫자가 scope 기반 직접 집계 대신 data-quality 카드 중심 해석으로 분리되는 점이며, raw coverage 판단은 `latest-kis-live-data-quality.json`을 기준으로 계속 확인한다.
- `tests/test_runtime_scope.py`는 raw KIS 이벤트가 더 최신인데 `curated_minute_bars`만 멈춘 상황을 별도로 재현한다. 이 회귀 테스트는 분봉 생성 지연을 raw 수집 중단으로 오해하지 않도록, dashboard scope와 data-quality raw coverage의 역할 분리를 잠근다.
- `tests/test_dashboard.py`는 정규장 중 live runtime 이 실행 중인데 `latest_market_bar`가 stale 인 상황에서 dashboard status alert에 `실시간 분봉 갱신이 지연되고 있습니다` warning 이 노출되는지 잠근다. 이 테스트는 bar builder lag가 silent하게 지나가지 않도록 하는 운영 화면 회귀 잠금이다.
- 머신러닝 현황 탭의 `장후 자동 학습 상태` 카드는 post-close maintenance 상태, snapshot DB, snapshot runtime, stdout/stderr 로그 경로를 보여준다.
- 머신러닝 현황 탭의 `장후 label refresh 상태` 카드는 quick maintenance 뒤 live DB에서 feature/label rebuild 와 진단/대시보드 갱신을 수행한 최신 상태를 보여준다.
- 머신러닝 현황 탭의 `게이트 기준 워크포워드` 카드는 정본 저장소의 승격 게이트가 실제로 참조하는 `runtime-data/reports/backtests/latest-walk-forward-h15.json`의 시점, 학습창, fold 수, 수익률, 설정 점검 상태를 post-close snapshot 산출물과 분리해서 보여준다.
- 머신러닝 현황 탭의 `챌린저 및 워크포워드` 카드는 모델 자체 평가와 실행 제약을 분리해서 보여준다. 챌린저 표의 기본 정확도는 상승/보합/하락 전체를 보는 `3분류 정확도`이고, 기존 `trade_hit_rate`는 과거 호환 키로 유지하되 화면에서는 `매수 신호 적중률`로 표시한다. `가상 방향 거래`는 상승 예측을 가상 매수, 하락 예측을 가상 매도, 보합 예측을 거래 없음으로 계산하는 연구용 지표이며, 실제 현물 paper 주문·보유한도·강제청산 성과와 분리해서 본다. 이 수익률은 거래별 퍼센트 손익을 단순 합산한 값이며 복리 수익률, 포트폴리오 수익률, 실제 체결 가능 수익률이 아니다. 학습 자체는 이미 상승/보합/하락 3분류였고, 이번 기준은 평가/표시/거래지표 해석을 바로잡은 것이다.
- 머신러닝 현황 탭의 `챌린저 및 워크포워드` 카드는 LightGBM 성능 진단, feature source, feature profile, label band, label band 재현성, probability calibration 연구 리포트도 함께 보여준다. 이 카드들은 후보 탐색용이며 active model 승격, threshold 변경, 실전 주문 판단 변경을 의미하지 않는다.
- 머신러닝 현황 탭의 `KIS live 데이터 품질` 카드는 `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`을 읽어 최신 KIS 데이터의 feature/label 닫힘 상태를 보여준다.
- 이 카드는 최신 거래일 기준 watchlist × 정규장 시작 이후 최신 raw minute 의 기대 symbol-minute 대비 시장 체결, 호가, 분봉, 특징 coverage 도 보여준다. market coverage 는 최신 raw minute 기준, 분봉/특징 coverage 는 아직 닫히지 않은 마지막 1분을 제외한 닫힌 분 기준으로 평가한다. coverage 가 `95%` 미만이면 `watch`, `80%` 미만이면 `needs_attention`으로 assessment 를 올린다. 장전 호가나 REST snapshot 이 포함되면 raw coverage 는 100%를 넘을 수 있다.
- 같은 리포트는 raw market/orderbook의 watchlist 공통 누락 구간과 종목별 누락 분 수·범위를 별도 `raw_minute_gaps` 증거로 남긴다. WebSocket reconnect 객체와 공백 증거를 분리해 연결 이벤트와 실제 데이터 손실을 독립 판정한다.
- `--recent-days 10` 집계는 전체 관측 거래일 수와 source 총계는 유지하되, 가장 비싼 symbol×minute 원천 그룹화는 최근 10거래일로 제한한다. 26GB 운영 DB 실측은 약 439초에서 126초로 줄었고 결과 행·coverage·gap 판정은 동일했다.
- 과거 watch 사례는 feature/bar 비율과 시간대 공백을 함께 본다. 2026-06-05와 2026-06-09는 종가 동시호가 구간 공백 영향이 컸고, 2026-06-08은 raw market symbol-minute 가 약한 구간이 길었지만 orderbook 은 비교적 유지됐다. 따라서 같은 패턴이 재발하면 `watchdog` heartbeat, KIS WS frame, raw market/orderbook coverage 를 함께 비교한다.
- 머신러닝 현황 탭의 `KIS-Cybos feature drift` 카드는 `runtime-data/reports/data-quality/latest-feature-source-drift.json`을 읽어 Cybos historical 후보를 KIS live 대리값으로 볼 때의 source drift 판단을 보여준다.
- 머신러닝 현황 탭의 `KIS live feature-label 진단` 카드는 `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.json`을 읽어 KIS live 단일 피처와 h15 label/future return 의 약한 관계를 보여준다. 이 카드는 feature triage 용이며 모델 승격 근거가 아니다.
- 상태 및 설정 탭의 `장전 readiness` 카드는 `runtime-data/reports/recovery/latest-local-setup-check.json`을 읽어 dashboard, runtime watchdog, live runtime, startup launcher, websockets, lightgbm 상태, KIS 시세 자격정보 준비 여부, 점검 신선도, blockers 를 보여준다. `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, `ENABLE_BROKER_PAPER_MIRRORING=true` 조합은 Phase 0 KIS 모의계좌 검증용 `info` 상태로 표시하고, 이 조합을 벗어난 mirroring enabled 상태는 review 대상 warning 으로 남긴다.
- 정본 gate reference 워크포워드는 `python -m app --run-gate-walk-forward --horizon-min 15` 또는 `./scripts/run_gate_walk_forward_backtest.sh`로 생성하며, `source=cybos-historical`, `parameter_profile=gate_reference_v1` provenance 를 리포트에 남긴다.
- 스냅샷 파일 저장은 임시 파일 교체와 짧은 재시도를 사용해, 상태 점검이 같은 JSON 파일을 읽는 순간의 동시 읽기 충돌을 줄인다.
- SQLite 잠금이 잠깐 발생하면 연결을 끊지 않고 `일시 점검` 응답을 내려준다.
- 저장된 pid 만 믿지 않고 실제 명령줄과 포트 응답을 함께 확인한다.
- WSL2의 실제 Python 실행 파일을 우선 사용한다.
- 탭 선택 상태는 브라우저 localStorage에 저장해 새로고침 뒤에도 유지한다.

현재 대시보드 첫 화면은 `운영 콘솔`이다.
첫 화면은 Phase readiness, paper/KIS 계좌 정합성, 데이터 품질, 장후 파이프라인, 실전 주문 안전 상태를 먼저 보여준다.

현재 상위 탭은 아래 5개다.

- `운영 콘솔`
- `계좌`
- `ML/데이터`
- `예측/주문`
- `리포트/설정`

기존 상세 화면은 상위 탭 안에 묶어 보존한다.
`계좌` 탭은 `모의투자(가상)`, `모의계좌(실제)`, `실 운용계좌`를 함께 보여준다.
`ML/데이터` 탭은 머신러닝 현황과 데이터 품질/진단을 보여준다.
`예측/주문` 탭은 예측현황, 신호와 주문현황, 체결과 분봉을 함께 보여준다.
`리포트/설정` 탭은 오늘의 리포트, 상태 및 설정, 기타 자동 점검 이력을 함께 보여준다.
각 상세 묶음은 왼쪽 세로 보조탭 구조를 사용한다.
긴 표와 목록은 내부 스크롤 패널 안에서 확인한다.

대시보드 데이터 필터 기준은 아래와 같다.

- `sample`, `synthetic`, `demo` 실행 행은 기본 제외한다.
- 재생 전용 행은 실제 운용 범위에서 제외한다.
- 실제 출처와 테스트 출처가 섞인 오염 분봉은 제외한다.
- 정규장 밖 KIS REST 스냅샷 분봉과 원시 행은 실제 운용 집계에서 제외한다.
- 기본 `오늘` 조회에서 현재 날짜에 장중 기록이 없으면 마지막 실제 장중 날짜를 `최근 장중`으로 선택한다.

## 예측과 신호

- 장중에는 15분과 60분 예측을 함께 기록한다.
- 신호와 주문 판단은 15분 기준으로만 수행한다.
- 최근 예측은 기준가, 예상 변동, 실제 결과, 성공 여부를 함께 보여준다.
- 목표 시각의 정확한 분봉이 없어도 같은 거래일 안에서 목표 시각 이후 가장 가까운 분봉으로 실제 결과를 계산한다.
- 장마감 뒤 같은 거래일의 후속 분봉이 더 생길 수 없는 예측은 `대기 중`이 아니라 `결과 없음`으로 닫는다.
- 예측 상세 탭은 선택 기간의 전체 예측을 보여준다.
- 예측현황 탭은 예측 정확도, 신호 replay(과거 신호 재생) 기준 가상 수익률, 실제 paper 체결 기준 FIFO 청산손익을 분리해서 보여준다.
- 신호 replay 는 현물 매수 전용 운용을 기준으로 `미보유+매수 허용`은 진입, `보유+매도 신호`는 청산, `미보유+매도 신호`는 신규 숏이 아니라 진입 회피로 계산한다.
- 신호 & 주문현황 탭은 신호, 주문, 체결을 함께 보여주고 매도 신호 차단 이유를 설명한다.

## 머신러닝 운영

주요 명령:

```bash
python -m app --train-lightgbm --horizon-min 15
python -m app --run-backtest --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
python -m app --run-gate-walk-forward --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-lightgbm-buy-signal-diagnostics --horizon-min 15
python -m app --run-lightgbm-performance-diagnostics --horizon-min 15
python -m app --run-lightgbm-feature-source-experiment --horizon-min 15
python -m app --run-lightgbm-feature-profile-experiment --horizon-min 15
python -m app --run-lightgbm-label-band-experiment --horizon-min 15
python -m app --run-lightgbm-label-band-reproducibility-review --horizon-min 15
python -m app --run-lightgbm-calibration-experiment --horizon-min 15
python scripts/trace_paper_kis_mismatch.py
python scripts/summarize_walk_forward_extreme_folds.py
python scripts/analyze_walk_forward_extreme_fold_regimes.py
python scripts/summarize_lightgbm_defensive_signal_candidates.py
python scripts/summarize_lightgbm_defensive_shadow.py
python scripts/summarize_model_overlay_comparison.py --horizon-min 15
python scripts/summarize_cybos_kis_transfer_review.py --horizon-min 15
python scripts/summarize_meta_policy_shadow.py --horizon-min 15
python scripts/summarize_social_signal_shadow.py --horizon-min 15
python scripts/summarize_cybos_buy_avoid_proxy.py --trade-cost-pct 0.13
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
./scripts/create_research_db_snapshot.sh
./scripts/run_research_on_snapshot.sh -- python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-bar-only-experiment --horizon-min 15
python -m app --run-cybos-profitability-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-label-sensitivity-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-label-reproducibility-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-expected-value-review --horizon-min 15 --cybos-experiment-feature-set bar_context_momentum --cybos-profitability-cost-pct 0.29
python scripts/summarize_cybos_research_suite.py
python scripts/summarize_kis_live_data_quality.py --recent-days 10
python scripts/summarize_feature_source_drift.py
python scripts/summarize_kis_live_feature_diagnostics.py
```

- `--train-lightgbm`와 `--run-challengers`는 기본적으로 최근 labeled feature row `250,000`건만 읽는다. 전체 이력으로 실행해야 할 때만 각각 `--train-lightgbm-max-rows 0`, `--challenger-max-rows 0`을 명시한다.

현재 ML 기준은 아래와 같다.

### 2026-08-09 수익성 평가 정본

이 절은 아래의 과거 `promotable`, `defensive candidate`, rescue/avoid 기록보다 우선한다.

- 현재 비용·순방향 artifact lineage·decision episode portfolio replay·무작위 대조·일별 일관성을 모두 통과한 수익 후보는 `0개`다.
- LightGBM buy-avoid는 최신 하루 artifact만 택하지 않고, 각 거래일 예측 전에 학습이 완료된 완전 lineage 19개를 순방향 chain으로 묶는다. 2026-08-09 재평가의 threshold `0.40`은 baseline `-36.4241%`, policy `-34.3196%`, delta `+2.1045%p`다. 손실 완화는 있으나 절대 수익, 평균 거래 기대값, 비음수 거래일 비율이 모두 미달해 `rejected_no_absolute_portfolio_profit`이다.
- dashboard long-only signal replay는 공통 비용 helper의 `krx-common-stock-2026-v1`, 왕복 `0.29%`를 쓴다. 종전처럼 slippage `0.06%`만 차감하지 않는다. 합산 percent-point와 추정손익은 진단값이며 실제 계좌 수익률이 아니다.
- 장후 label refresh는 data quality와 feature diagnostics 뒤에 buy-avoid, model overlay, hold-rescue, meta-policy를 순서대로 갱신하고 runtime report/dashboard를 만든다. 수익성 근거가 과거 날짜에 멈춘 채 학습만 최신인 상태를 방지한다.
- 최신 buy-rescue serving decision ledger는 71,369행, eligible 35,573행이지만 LightGBM과 linear-score 결과가 모두 비용 후 음수다. hold-rescue도 161 lot 중 threshold 0.40 적용 37 lot, `delta_cash_sum=-26,387원`으로 기각된다.
- Phase 0이 matched `0/10`인 동안 로컬 누적 실현손익은 dashboard 표시용일 뿐 수익 증거로 사용하지 않는다. active `baseline-h15-v1`, gate, threshold, 주문 정책은 변경하지 않는다.

### 2026-07-12 평가 기반

아래 규칙은 2026-08-09 정본에서도 유지하는 공통 평가 기반이다.

- 겹치는 분 단위 신호의 수익률 합은 `sum_net_return_pct_points`로만 부르며 계좌 수익률로 해석하지 않는다.
- 수익 후보는 다음 분봉 시가, 동일 현금, 종목별 비중, 동시 보유 수, 수수료, 세금, 슬리피지를 적용한 decision-episode portfolio replay에서 절대 비용 후 수익과 평균 거래 기대값이 모두 양수여야 한다.
- 2026 국내 보통주 비용 정본은 `krx-common-stock-2026-v1`이다. [국가법령정보센터 2026 증권거래세 신고서 작성방법](https://law.go.kr/LSW/flDownload.do?bylClsCd=110202&flSeq=162621569)의 유가증권시장 증권거래세 5/10,000, 농어촌특별세 15/10,000, 코스닥시장 증권거래세 20/10,000을 기준으로 현재 10종목 보통주 watchlist는 매도 시 총 `0.20%`를 적용한다. 매수에는 거래세를 붙이지 않으며, 편도 수수료 `0.015%`와 편도 슬리피지 3bp를 합친 왕복 연구 비용은 `0.29%`다.
- 세금 `0.20%`와 달리 편도 수수료 `0.015%` 및 편도 슬리피지 3bp는 브로커 확정 수수료표나 실제 체결 관측값이 아니라 보수적 연구 가정이다. 모든 새 연구 리포트는 `cost_model_version`과 가정 상태를 기록하며, Phase 2 canary 전에 실제 계좌 현금 변화와 체결 미끄러짐으로 다시 보정한다.
- `PaperTradingEngine`, broker paper fill sync, LightGBM 연구 비용, portfolio replay가 같은 helper를 쓴다. 2026-07-12 이전 체결·snapshot은 소급 재작성하지 않아 비용 모델 단절이 있으며, KIS daily order/fill adapter에는 수수료·세금 분리 필드가 없으므로 Phase 2 전 canary에서 브로커 계좌 현금 변화와 다시 대조한다. ETF/ETN 등 상품별 과세는 현재 범위 밖이다.
- 2026-07-12 당시 LightGBM buy-avoid threshold `0.40`의 portfolio replay는 baseline `-38.1734%`, 필터 적용 `-36.3645%`였다. 이 값은 역사적 비교용이며 현재 판정은 위 2026-08-09 정본을 따른다. 구형 `-16.4010%/-15.3384%`는 잘못 낮은 매도세 `0.018%`를 사용한 결과다.
- `serving_decision_ledger`는 active/shadow 예측 lineage, 신호, 시간·spread gate, allocator, 현금·보유·pending 상태, 주문·체결 결과를 매 결정마다 기록한다. 과거 기간은 추정 backfill하지 않으며, 2026-08-09 최신 overlay 입력은 71,369행이다. 이 중 buy-rescue 정본 후보는 명시적 no-trade 조건을 만족한 행만 쓴다.
- buy-rescue는 안전 gate, 현금, 보유한도, pending, risk 차단을 뒤집지 않는다. 시간·spread gate 통과, 주문/체결 없음, baseline 비매수, `decision_stage=signal_blocked`인 최신 35,573행만 진단한다.
- hold-rescue threshold `0.40`의 최신 결과는 eligible `161`, 적용 `37`, 현금손익 차이 `-26,387원`, 개선 `13`, 악화 `22`로 현재 규칙을 기각한다.
- 모든 serving prediction은 `training_run_id`, `artifact_id`, `artifact_sha256`를 갖는다. lineage가 없는 LightGBM artifact는 loader가 거부하며, 기존 33,007개 lineage 없는 joined prediction은 진단 전용이다.
- 챌린저 `promotable=true`는 독립 holdout, 최소 30거래, 각 예측 클래스 비중 5% 이상, 다수 클래스 정확도 초과, 비용 후 평균·누적 수익 양수, 현금·보유한도 반영 portfolio replay 양수와 서로 겹치지 않는 평가구간 최소 2개 재현성을 모두 충족해야 한다. 같은 holdout 재실행은 시간 재현성으로 인정하지 않는다. 현재 temporal evidence 생성기는 없으므로 모든 후보는 fail-closed로 `promotable=false`다.
- meta-policy는 defensive random control, 입력 freshness, 데이터 종료일, lineage, 절대수익 양수 portfolio 후보를 필수로 확인한다. 현재 `blocked_evidence`이고 primary candidate는 없다.
- early-exit은 같은 bar close를 체결가로 쓰지 않고 다음 분봉 시가를 사용한다. 이 교정 전 결과와 직접 비교하지 않으며 미래 고정 구간 검증 전에는 진단으로만 둔다.

- 운영 학습창: 최근 60거래일 + 오늘 데이터
- 장중: 추론 중심
- 장후 quick: runtime report, 품질 진단, 제한 LightGBM 재학습, challenger 평가, dashboard snapshot 갱신
- 장후 heavy research: snapshot DB에서 특징 / 라벨 재생성, 백테스트, 워크포워드, 도전자 모델 비교
- 활성 모델 자동 교체 금지
- 도전자 모델이 워크포워드 관문을 통과하지 못하면 `review_required` 로 유지
- LightGBM 학습은 마지막 tail `10%`를 challenger 전용 holdout으로 예약하고, 학습/validation은 그 이전 development 구간에서 수행한다. challenger 평가는 최신 LightGBM artifact의 학습 시점 holdout 시작 시각을 우선 anchor 로 사용해 `challenger_holdout_training_anchor` 평가 구간을 만든다. 이렇게 하면 장후 label refresh 로 데이터가 추가되어도 LightGBM 학습 때 예약한 holdout 경계가 유지된다. candidate별 `evaluation_independence_status`를 리포트에 남기고, DB 최신 training row와 artifact run id가 다르면 복구/복사 불일치로 보고 승격 후보에서 제외한다.
- 최신 챌린저 리포트는 `three_class_accuracy`, `class_hit_rates`, `confusion_matrix`, `buy_signal_hit_rate`, `virtual_direction_*` 지표를 함께 기록한다. `promotable=true`는 2026-07-11 수익성 평가 정본의 표본·클래스·다수 기준·비용 후 수익·portfolio replay 조건을 모두 통과한 실제 승격 심사 자격을 뜻한다. 실제 활성 모델 교체는 `recommended_action`, 워크포워드 gate, 운영자 승인까지 추가로 필요하다.
- LightGBM 매수 신호 0건 원인은 `python -m app --run-lightgbm-buy-signal-diagnostics --horizon-min 15`로 진단한다. 이 명령은 threshold별 매수 신호 수, 적중률, 비용 차감 평균/누적 순수익률을 `runtime-data/reports/challengers/latest-lightgbm-buy-signal-diagnostics-h15.json`과 `.md`에 남기며, threshold 를 자동 채택하지 않는다.
- LightGBM 성능 진단은 `python -m app --run-lightgbm-performance-diagnostics --horizon-min 15`로 실행한다. 이 명령은 최신 LightGBM artifact 를 저장된 독립 holdout 경계로 평가하고, 3분류 정확도, 클래스별 적중률, 혼동행렬, 확률 분포, 가상 방향 threshold별 비용 차감 수익률을 `runtime-data/reports/challengers/latest-lightgbm-performance-diagnostics-h15.json`과 `.md`에 남긴다. 자동 승격과 threshold 자동 채택은 하지 않는다.
- 진단 threshold 중 비용 후 양수가 있더라도 기존 challenger 최소 표본인 30거래에 못 미치면 candidate라고 부르지 않고 `positive_*_small_sample_insufficient_evidence`로 표시한다. 2026-07-12 비용 정본 재평가에서는 기본 0.58이 53거래, 평균 `-0.348534%`, 누적 `-18.472324%p`이고 유일한 양수 threshold 0.66은 9거래뿐이라 이 상태다.
- LightGBM feature source 분리 실험은 `python -m app --run-lightgbm-feature-source-experiment --horizon-min 15`로 실행한다. 이 명령은 `mixed_recent`, `kis-ws`, `cybos-historical` 후보를 메모리 안에서만 학습/평가하고 artifact 를 덮어쓰지 않는다. 2026-06-12 기준 결과는 `mixed_recent`이 3개 피처로 소수 하락/회피 방향 양수 후보를 보였고, `kis-ws`는 6개 피처를 쓰지만 비용 차감 방향 기대값은 음수였다. 따라서 다음 단계는 KIS-only artifact 승격이 아니라 피처/라벨/확률 보정 연구다.
- LightGBM feature profile 실험은 `python -m app --run-lightgbm-feature-profile-experiment --horizon-min 15`로 실행한다. 이 명령은 KIS live 피처에 시간대, 모멘텀, 최근 변동성 후보를 메모리 안에서만 붙여 `base`, `time`, `momentum`, `volatility`, `time_momentum_volatility` 후보를 비교하고 `runtime-data/reports/challengers/latest-lightgbm-feature-profile-experiment-h15.json`과 `.md`에 남긴다. artifact, active model, gate 기준값은 바꾸지 않는다.
- LightGBM label band 실험은 `python -m app --run-lightgbm-label-band-experiment --horizon-min 15`로 실행한다. 이 명령은 라벨의 상승/하락 band threshold 후보를 메모리 안에서만 재라벨링해 비교하고 `runtime-data/reports/challengers/latest-lightgbm-label-band-experiment-h15.json`과 `.md`에 남긴다. `config/`, gate 기준값, 실제 라벨 정책은 자동 변경하지 않는다.
- LightGBM label band 재현성 리뷰는 `python -m app --run-lightgbm-label-band-reproducibility-review --horizon-min 15`로 실행한다. 이 명령은 label band 후보를 최근 KIS live labeled row 기준 full walk-forward 와 기간 분리 fold 로 다시 평가하고 `runtime-data/reports/challengers/latest-lightgbm-label-band-reproducibility-h15.json`과 `.md`에 남긴다. 2026-06-12 기준 `0.40` 후보는 전체 walk-forward 가상 방향 순수익은 양수였지만 기간별 양수 재현이 0/3이라 정책 변경 후보가 아니다.
- LightGBM probability calibration 실험은 `python -m app --run-lightgbm-calibration-experiment --horizon-min 15`로 실행한다. 이 명령은 최신 LightGBM artifact 의 확률을 온도 보정과 prior blending 후보로 후처리해 NLL, Brier score, ECE, 3분류 정확도, 가상 방향 순수익률을 비교하고 `runtime-data/reports/challengers/latest-lightgbm-calibration-experiment-h15.json`과 `.md`에 남긴다. calibration 결과는 자동 채택하지 않는다.
- paper/KIS mismatch trace 는 `python scripts/trace_paper_kis_mismatch.py`로 실행한다. 이 명령은 최신 reconciliation, broker sync, SQLite 원장을 read-only로 묶어 `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`과 `.md`에 남긴다. 계좌를 정렬하거나 주문/체결 상태를 변경하지 않는다. 최신 `paper-account-sync` 리포트가 있으면 그 mismatch 목록을 우선 기준으로 쓰고, 없을 때만 `dual-account-match` 리포트로 fallback 한다. 리포트에는 `mismatch_source_report`를 함께 남긴다.
- gate walk-forward 극단 fold 요약은 `python scripts/summarize_walk_forward_extreme_folds.py`로 실행한다. 이 명령은 최신 `latest-walk-forward-h15.json`에서 정확도가 낮은 fold를 추려 `runtime-data/reports/backtests/latest-walk-forward-extreme-folds-h15.json`과 `.md`에 남긴다. 원인 판정이 아니라 후속 장세/데이터 품질 분석 후보를 고르는 진단이다.
- gate walk-forward 극단 fold 장세 분석은 `python scripts/analyze_walk_forward_extreme_fold_regimes.py`로 실행한다. 이 명령은 최신 gate fold 기간을 `feature_labels`, `curated_minute_bars`와 read-only 로 조인해 label imbalance, prediction bias, 기간 수익률, 분봉 변동성 후보를 `runtime-data/reports/backtests/latest-walk-forward-extreme-fold-regimes-h15.json`과 `.md`에 남긴다. 2026-06-13 기준 최저 fold 들은 flat 라벨 비중이 높지만 flat 적중률이 붕괴하고, 분봉 변동성이 높은 구간으로 분류됐다. 이 리포트만으로 label/gate 기준값은 바꾸지 않는다.
- LightGBM 방어 신호 후보 요약은 `python scripts/summarize_lightgbm_defensive_signal_candidates.py`로 실행한다. 이 명령은 기존 성능 진단과 calibration 실험에서 하락 예측의 비용 차감 양수 후보를 모아 `runtime-data/reports/challengers/latest-lightgbm-defensive-signal-candidates-h15.json`과 `.md`에 남긴다. 이 결과는 매수 승격이나 live short 신호가 아니라 buy-avoid / early-exit paper shadow 검증 후보를 고르는 자료다.
- LightGBM 방어 shadow 비교는 `python scripts/summarize_lightgbm_defensive_shadow.py`로 실행한다. 이 명령은 baseline 매수 허용 신호와 같은 시각의 `lightgbm-h15-v1` shadow 예측, 닫힌 h15 label, closed paper lot 을 read-only 로 조인해 `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`과 `.md`에 남긴다. 2026-07-05 random-control 기준 KIS threshold `0.40`은 `filter_worse_than_random_p95`, `random_control_gate.passed=false`이므로 현재 표준 표현은 `재검증 필요, 무작위 대조군 대비 우위 미확인`이다. 같은 하락 신호를 조기 청산에 쓰는 것은 실제 paper 청산보다 악화되어 보류다. 이 결과는 active model, threshold, paper/live 주문을 바꾸지 않는다.
- 신호 정보계수 진단은 `python scripts/summarize_signal_ic.py --horizon-min 15`로 실행한다. 이 명령은 방어 shadow와 같은 baseline 매수 허용 row 에서 LightGBM 확률과 미래 수익률의 일별 Spearman 순위상관을 계산해 `runtime-data/reports/research/latest-signal-ic-h15.{json,md}`에 남긴다. 2026-07-05 review_ver_26 반영 기준 시간대(`open_early/midday/close`), 종목, 최근 변동성 tercile 구간별 daily IC 분해도 함께 기록한다. 사전 등록 기준은 부분집합별 `abs(mean_daily_ic) >= 0.03`, `abs(t_stat) >= 2.5`, `days_usable >= 5`이며 2026-07-18 재측정 전까지 진단용으로만 본다. 전체 `probability_down`은 `mean_daily_ic=0.004754`, `t_stat=0.367342`, `decision=signal_quality_insufficient`라 E2/E3 threshold/EV 필터 튜닝으로 바로 넘어가지 않는다. 구간 분해에서는 시간대와 변동성 bucket은 기준 통과 후보가 없고, 종목 단위에서 `005380 probability_up(expected)`, `035420 probability_down(expected)`, `105560 probability_down(reverse)`만 후속 관찰 후보로 남았다.
- 비용/시간지평 구조 진단은 `python scripts/summarize_cost_horizon_diagnostics.py --horizons 15 30 60`으로 실행한다. 이 명령은 `feature_labels`를 read-only 로 조회해 horizon별 절대 미래수익률 분포와 비용 기준을 비교하고 `runtime-data/reports/research/latest-cost-horizon-diagnostics.{json,md}`에 남긴다. 2026-07-12 신 비용 재생성은 `trade_cost_pct=0.29`, `2 * cost=0.58`, `cost_model_version=krx-common-stock-2026-v1`이다. KIS live 근사 h15는 `rows=79,422`, `median_abs=0.376648%`, p75 `0.721772%`, baseline-buy join h15는 `rows=33,007`, `median_abs=0.365344%`라 중위값은 모두 2배 비용 기준에 미달한다. KIS live h60은 `rows=69,962`, `median_abs=0.739523%`, baseline-buy join h60은 `rows=29,159`, `median_abs=0.718133%`로 기준을 넘는다. 이는 h15 비용 여유 경고와 h60 상대 연구 우선순위를 뜻할 뿐, h15 수익 가능성의 구조적 부정이나 h60 주문 정책 전환 근거는 아니다. `breakeven_win_rate_long_reference`도 모델 적중률이 아닌 구조 참고값이다.
- E6는 각 source/horizon에 `observation_window.event_time_start/end`를 기록한다. 최신 broad KIS h15/h60은 `2026-06-11 08:30`부터 각각 `2026-07-10 14:59/14:19`까지라 장전 행이 포함되고, baseline-buy join은 `09:15`부터 시작한다. broad long-only 손익분기 참고 승률 h15 `0.724041`, h60 `0.624676`과 baseline-buy join `0.748325/0.646466`은 현재 평균 이익·손실·비용으로 계산한 동적 기준선이다. 3분류 정확도나 long/short 방향 거래 적중률과 직접 비교하거나 고정 승격 gate로 쓰지 않는다.
- 모델 공통 overlay 비교는 `python scripts/summarize_model_overlay_comparison.py --horizon-min 15`로 실행한다. 이 명령은 `LightGBM` 저장 예측과 `linear-score` 내장 모델 계산값을 같은 KIS live h15 label 구간에서 비교해 `buy-avoid`, `buy-rescue`, `hold-rescue`를 한 표로 남긴다. 결과는 `runtime-data/reports/challengers/latest-model-overlay-comparison-h15.json`과 `.md`에 저장된다. 2026-07-03 첫 결과 기준 두 모델 모두 역할 후보는 `defensive_buy_avoid`이고, `buy-rescue`와 `hold-rescue`는 비용/손익 기준으로 후보가 아니다. 같은 리포트는 방향/시간대/확률대별 강점 구간과 `baseline`, `LightGBM veto`, `linear-score veto`, `either/both veto`, `both-up rescue` 조합 정책 후보도 진단 전용으로 비교한다. 이 리포트는 모델별 강점 구간 분류를 위한 진단이며 주문 정책, active model, gate, KIS live shadow 확장을 바꾸지 않는다.
- Cybos-KIS 전이성 리뷰는 `python scripts/summarize_cybos_kis_transfer_review.py --horizon-min 15`로 실행한다. 이 명령은 Cybos historical row 와 2026-06-11 이후 KIS live h15 label row 를 같은 feature bucket, 시간대, 단기 모멘텀, 변동성 구간으로 비교해 `runtime-data/reports/research/latest-cybos-kis-transfer-review.{json,md}`에 남긴다. 2026-07-03 첫 결과는 `kis_specific_shadow_candidates_only`이며, 공통 bar 피처에서 바로 전이 가능한 수익 신호는 없고 `bid_ask_imbalance`, `spread_bps` 같은 KIS 전용 orderbook 후보와 `midday`, `short_up` 회피/축소 후보만 진단 전용으로 남았다. 이 결과는 meta-policy/router 후보를 좁히기 위한 연구 리포트이며 모델 승격, gate 변경, 주문 정책, KIS live shadow 확장을 자동 변경하지 않는다.
- meta-policy shadow 요약은 `python scripts/summarize_meta_policy_shadow.py --horizon-min 15`로 실행한다. 이 명령은 모델 overlay, Cybos-KIS 전이성, Cybos buy-rescue proxy, hold-rescue paper replay 결과를 한 리포트로 묶어 `runtime-data/reports/research/latest-meta-policy-shadow-h15.{json,md}`에 남긴다. 현재 기준 적용 방향은 `baseline 주문 판단 유지 + meta filter/router 후보 shadow 관측`이며, active model, gate, paper/KIS 주문 정책, KIS live shadow 확장은 바꾸지 않는다.
- SNS/공개 영향력 이벤트 shadow 평가는 `python scripts/summarize_social_signal_shadow.py --horizon-min 15`로 실행한다. 기본 이벤트 파일은 `runtime-data/social/signals/social_events.jsonl`이고, 이벤트가 없으면 `no_events_file`로 안전 종료한다. 이벤트가 있으면 `feature_labels`를 read-only 로 조회해 source/author/event_type/impact_direction 별 h15 사후 방향 적중률과 평균 미래 수익률을 `runtime-data/reports/research/latest-social-signal-shadow-h15.{json,md}`에 남긴다. Phase 1에서는 공식 API, 공개 feed, 수동 export 만 허용하고 주문 판단에는 쓰지 않는다.
- 오래된 데이터는 삭제하지 않고 변화 점검, 구간 비교, 재생, 회귀 검증에 보관
- Cybos 연구 실험은 `source=cybos-historical`만 사용하고, 호가가 없는 과거 데이터 특성상 `mid_price`, `spread_bps`, `bid_ask_imbalance`는 제외한다.
- Cybos rule challenger review는 고정 long-only 룰 후보를 비용 반영 walk-forward로 비교한다. 결과가 좋아도 자동 승격하지 않고 기간 분리 재현성 검증 후보로만 기록한다.
- Cybos 연구 실험의 지원 피처 세트는 `bar_only`, `bar_context`, `bar_context_momentum`이다.
- Cybos 손익 진단은 F-5 재현, 거래 원장 기반 손익 분해, 0.13% 왕복 비용 기준선, train-only confidence threshold, 60분 horizon 비교를 리포트로 남긴다.
- Cybos 라벨 민감도 진단은 threshold별 결과를 비교하되, 가장 좋은 threshold를 자동 채택하지 않는다.
- Cybos 라벨 재현성 진단은 민감도 진단에서 양수였던 threshold를 다른 fold 설계와 기간 샘플로 다시 검증한다.
- Cybos expected-value review는 각 walk-forward fold 안에서 train tail calibration 구간으로만 `probability_up` threshold를 선택하고 test 구간에 적용한다. 선택 기준은 비용 차감 평균 기대값 양수 여부이며, 수동 필터를 사후 튜닝하거나 자동 승격하지 않는다.
- Cybos buy-avoid/rescue proxy 는 `python scripts/summarize_cybos_buy_avoid_proxy.py --trade-cost-pct 0.13`으로 실행한다. 이 스크립트는 기존 Cybos `bar_context_momentum` LightGBM 프로파일과 기존 walk-forward 샘플링 구조를 재사용해, KIS `down_threshold=0.40` 수치를 직접 옮기지 않고 skip-rate coverage 기준으로 매수 회피 구조를 검증한다. 동시에 `proxy_buy_rescue`를 계산해 매수하지 않았던 후보 중 `probability_up` 상위 고정 coverage 를 가상 매수했을 때의 비용 차감 손익도 본다. 결과는 `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.{json,md}`, `latest-cybos-rescue-proxy-h15.{json,md}`, `latest-cybos-regime-performance-h15.{json,md}`에 남긴다. 이 리포트는 모델 승격, gate 기준 변경, 주문 정책 변경을 수행하지 않는다.
- Cybos proxy의 고정 `trade_cost_pct=0.13`은 당시 구조 비교용 역사적 가정이며 2026 보통주 매도세를 포함한 현행 KIS 수익성 정본이 아니다. Cybos random-control 선별력은 진단에 쓸 수 있지만 절대수익 통과나 KIS 주문 전이 근거로 쓰지 않는다.
- Cybos buy-avoid proxy 의 `baseline`은 실제 runtime baseline 주문 판단이 아니라 Cybos LightGBM 자체 매수 후보 집합이다. 2026-06-14 Step 0 확인 결과 `BaselineDirectionModel`은 `return_1m_pct`, `bid_ask_imbalance`, `spread_bps`를 쓰지만 Cybos bar row에는 live orderbook 피처인 `bid_ask_imbalance`, `spread_bps`가 없다. 따라서 Cybos rescue 1차 실험은 `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로 진행한다. `summarize_cybos_buy_avoid_proxy.py`는 새 report 에 `runtime_baseline_replay.available=false`, `status=not_replayed_orderbook_features_missing`, `recommended_experiment_mode=proxy_buy_rescue`를 남긴다.
- `proxy_buy_rescue`는 no-buy pool, 즉 Cybos LightGBM self-filter 기준으로 매수 후보가 아닌 row 중 `probability_up` 상위 `0.05`, `0.10`, `0.20`, `0.30` coverage 를 고정 grid 로 본다. 성공 후보는 최소 rescued trade `500`건, 비용 차감 순손익 양수, fold `2/3` 이상 비음수, 단일 fold 양수 손익 집중도 `0.50` 이하를 모두 만족해야 한다. 이 기준을 만족해도 KIS live buy-rescue shadow 는 별도 비매수/차단 로그 가용성 확인 뒤에만 검토한다.
- 2026-06-14 기준 Cybos buy-avoid proxy 는 비용 `0.13%` 기준 target skip `0.3665`에서 실제 skip `0.3617`, baseline net `-538.040362%p`, kept net `-170.325157%p`, 개선 `+367.715205%p`, 개선 fold `12/12`를 기록했다. 이는 buy-avoid shadow 를 계속 볼 근거지만, kept net 이 여전히 음수이므로 단독 매수 전략 또는 active model 승격 근거가 아니다.
- 2026-06-14 기준 Cybos `proxy_buy_rescue` full 12 fold 는 `decision=buy_avoid_candidate_only`다. target rescue `0.05`, `0.10`, `0.20`, `0.30` 모두 비용 `0.13%` 반영 후 rescued net 이 음수였고, nonnegative fold share 는 `0/12`였다. 따라서 KIS live buy-rescue shadow 는 시작하지 않고, 기존 buy-avoid shadow 순차 관측을 유지한다.
- 2026-06-14 추가 정밀 검토 기준으로 `proxy_buy_rescue`는 `0.001`, `0.0025`, `0.005`, `0.01`, `0.02`, `0.03`, `0.05` rescue coverage 도 함께 본다. 이 검토는 이전 5~30% grid 가 너무 넓어서 실패했는지 확인하기 위한 것이다. full 12 fold 결과는 `0.001`에서도 rescued trade `727`건, 거래당 평균 총수익 `0.005543%`, 거래당 평균 순수익 `-0.124457%`였고, `0.01`에서도 거래당 평균 총수익 `0.047194%`, 순수익 `-0.082806%`였다. 전 구간이 비용 `0.13%`를 넘지 못해 `diagnostic_only_cost_drag` 또는 `coverage_out_of_bounds`로 끝났다. 따라서 현재 buy-rescue 는 단순히 넓게 잡아서 실패한 것이 아니라, Cybos proxy 기준 가장 강한 상승 후보도 거래비용을 이길 증거가 부족한 상태로 해석한다.
- buy-rescue 후속은 완전 폐기가 아니라 우선순위 하향이다. no-trade decision ledger는 실제 표본을 확보했지만 현행 비용 기준의 KIS live 진단이 모두 음수다. 따라서 새 주문 정책이 아니라 동일 decision episode portfolio replay와 same-count random control을 갖춘 재검토 전까지 KIS live shadow 확장은 buy-avoid 순차 관측만 유지한다.
- 2026-06-14 기준 hold-rescue 는 full Cybos 실험이 아니라 `_simulate_hold_rescue_lifecycle` synthetic helper 와 테스트까지만 구현돼 있다. 이 helper 는 entry, baseline exit, rescue exit, probability drop, max extension, max loss, 거래비용을 단일 synthetic path 에서 검증하기 위한 준비 단계다.
- hold-rescue paper replay 가능성 점검은 `python scripts/summarize_hold_rescue_paper_replay_feasibility.py --horizon-min 15`로 실행한다. 이 명령은 `paper_orders`, `paper_fills`, `serving_predictions`, `curated_minute_bars`를 read-only 로 묶어 실제 paper 진입/청산 lot, LightGBM exit 예측 매칭, 이후 h15 분봉 매칭을 `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-feasibility-h15.{json,md}`에 남긴다. 2026-06-17 기준 판정은 `feasible_for_offline_replay`지만, warning 으로 남은 orphan sell, open lot, 주말/장외 sync lot 은 본 replay 실험에서 분리해야 한다. 이 명령은 성과 검증, 주문 정책 변경, active model 교체, gate 기준 변경을 수행하지 않는다.
- hold-rescue paper-only 본 replay 는 `python scripts/summarize_hold_rescue_paper_replay.py --horizon-min 15`로 실행한다. 이 명령은 실제 paper sell fill 을 baseline exit 으로 두고, 해당 시점의 LightGBM `probability_up`이 고정 threshold grid(`0.40, 0.45, 0.50, 0.55, 0.60, 0.65`)를 넘는 경우 h15 이내 추가 보유를 가정해 baseline 대비 현금 손익 delta, 수익률 delta, 최대 낙폭, 종료 사유를 계산한다. 결과는 `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.{json,md}`에 남긴다. 2026-06-19 기준 판정은 `diagnostic_only_no_hold_rescue_candidate`이고, threshold `0.40`은 적용 lot `20`건에서 `-21,487원`, threshold `0.45`는 적용 lot `3`건에서 `-6,496원`으로 악화됐으며 `0.50` 이상은 적용 lot 이 없다. 이 명령도 성과 진단 전용이며 주문 정책, active model, gate, KIS live shadow 를 변경하지 않는다.
- Cybos regime performance 진단은 같은 실행에서 생성되며, 방향 regime 과 변동성 regime 별 3분류 정확도, buy signal net, virtual direction net, reference buy-avoid delta 를 비교한다. 2026-06-14 기준 high-vol 구간은 정확도 `0.467210`, buy signal net `-435.709195%p`로 가장 약했다. 이 진단은 새 regime별 모델 학습 결정 전 원인 후보를 좁히는 자료다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:
변경 전에는 LightGBM 학습 뒤 label refresh 등으로 labeled row가 추가되면 challenger holdout tail 이 뒤로 밀려 `holdout_window_mismatch`가 반복될 수 있었다.
변경 후에는 최신 LightGBM 학습 run 의 holdout 시작 시각을 anchor 로 삼아 challenger 평가 구간을 재구성한다.
영향 범위는 `app/services/research.py`의 challenger 평가와 LightGBM buy-signal diagnostics CLI, `app/__main__.py`의 CLI 옵션, 관련 research 테스트다.
회귀 위험은 artifact metadata 가 없는 legacy 모델에서는 anchor 를 만들 수 없어 기존 tail split/fail-safe 로 돌아간다는 점이다. 이 경우 자동 승격하지 않고 상태를 리포트에 남긴다.
- Cybos expected-value review는 거래별 퍼센트 손익 합산과 별도로 `fixed_fraction_per_signal_horizon_proxy` 포트폴리오 프록시를 기록한다. 기본 해석은 `5% 고정 비중`, `총 익스포저 100% 제한`, `horizon 기반 청산`이며 실제 paper 계좌 수익률이 아니라 승격 전 진단값이다.
- Cybos 연구 suite 요약은 기존 `latest-cybos-*` 리포트를 재학습 없이 묶어 `latest-cybos-research-suite-summary.{json,md}`로 남긴다. 이 요약은 후보 승격이 아니라 다음 실험 우선순위를 정하는 진단표다.
- KIS live data quality 요약은 `raw_market_ticks`, `raw_orderbook_ticks`, 실제 KIS 분봉, feature, h15/h60 label coverage와 함께 거래일별 `serving_decision_ledger` active/shadow lineage 완전성, decision stage, WebSocket reconnect/storm을 `runtime-data/reports/data-quality/latest-kis-live-data-quality.{json,md}`로 남긴다. 재연결이 있어도 storm=0, 닫힌 분 coverage 95% 이상, lineage 100%이면 수집 성공과 연결 주의를 분리한다.
- KIS live vs Cybos historical feature source drift 요약은 `runtime-data/reports/data-quality/latest-feature-source-drift.{json,md}`로 남긴다. KIS 표본은 가능하면 Cybos 마지막 일자 이후 live 날짜만 사용하며, `spread_bps`, `bid_ask_imbalance`처럼 Cybos historical 에 구조적으로 없는 호가 feature 분포 차이를 승격 판단 전에 확인한다. Cybos-only 후보는 실제 KIS live 성능의 직접 대리값이 아니라 구조 탐색과 후보 축소용으로 본다.
- KIS live feature diagnostics 요약은 `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.{json,md}`로 남긴다. Cybos 마지막 일자 이후 live 날짜 중 h15 label 이 닫힌 feature row만 사용해, 단일 피처별 future return 상관과 구간별 label 분포를 확인한다. 이 리포트는 피처 후보 탐색용이며 모델 승격 근거로 쓰지 않는다.

## 과거 데이터 Backfill

5년치 분봉 학습 데이터는 현재 B안으로 운영한다.
KIS `주식일별분봉조회`는 과거 분봉 조회가 가능하지만 공식 샘플 기준 보관 기간이 최대 1년이라 2021년부터 현재까지의 5년치 기본 수집에는 쓰지 않는다.
대신 pykrx 일봉 OHLCV를 거래일당 26개 15분 proxy bar 로 변환해 기존 `curated_minute_bars`에 적재하고, feature 생성을 위해 같은 시각의 proxy orderbook 을 `raw_orderbook_ticks`에 `pykrx-daily-proxy` source 로 적재한다.

실행:

```bash
./scripts/collect_historical_data.sh --start-date 2021-01-01
```

최신 품질 리포트:

- `runtime-data/reports/historical/latest-historical-collection.json`
- `runtime-data/reports/historical/latest-historical-collection.md`

실데이터만 다시 구축:

```bash
./scripts/rebuild_actual_ml_state.sh
```

장후 머신러닝 관리:

```bash
./scripts/run_post_close_ml_maintenance.sh
./scripts/run_post_close_label_refresh.sh
```

장후 관리는 장외에 실시간 수집기를 다시 켜지 않는다.
이미 켜져 있으면 중지해 WebSocket 재연결 루프가 CPU를 계속 쓰지 않게 한다.
기본 실행은 quick 경로이며 `runtime-data/dev.db`를 무겁게 재학습하지 않고 runtime report, KIS live 데이터 품질, KIS-Cybos feature drift, KIS live feature-label 진단, dashboard snapshot 만 갱신한다.
quick 경로의 데이터 품질 진단은 warning-only 로 실행되어, 개별 진단 실패가 장후 상태 파일 전체 실패나 heavy research 자동 실행으로 이어지지 않는다.
watchdog 은 장마감 후 기본 30분이 지나면 이 경로를 하루 한 번 백그라운드로 시작한다.
같은 날짜의 post-close maintenance 상태 파일에 `starting`, `running`, `ok`, `failed` 등 status 값이 이미 있으면 watchdog 은 같은 작업을 반복 시작하지 않는다.
quick 경로는 10분 목표를 지키기 위해 전체 feature/label 재생성을 포함하지 않는다. 장후 라벨까지 닫아야 할 때는 `./scripts/run_post_close_label_refresh.sh`를 명시 실행한다. 이 경로는 live DB에서 `--recent-days` 값에 맞춰 `python -m app --build-feature-dataset --feature-dataset-recent-days N`으로 최근 구간만 갱신한 뒤 KIS live 품질, feature source drift, KIS live feature diagnostics, runtime report, dashboard 를 다시 만들고 `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`에 상태를 남긴다. 이미 feature/label rebuild 가 끝난 뒤 리포트만 다시 맞출 때는 `--skip-build`를 사용할 수 있다. 전체 이력 feature/label 재생성은 연구/복구용 명시 작업으로만 실행한다.
`run_post_close_ml_maintenance.sh`와 `run_post_close_label_refresh.sh`는 `config/market_calendar.toml` 기준 `weekend` 또는 `holiday`이면 기본 실행에서 `skipped` 상태 파일만 쓰고 학습, 라벨, dashboard 재생성 작업을 수행하지 않는다. 운영자가 휴장일에 의도적으로 재실행해야 할 때만 `--force`를 사용한다.
snapshot DB와 격리된 research run runtime 을 쓰는 heavy research 는 아래처럼 명시적으로 실행한다.

```bash
./scripts/run_post_close_ml_maintenance.sh --heavy-research --use-snapshot
```

## 로컬 가상 계좌와 KIS 모의계좌

로컬 가상 계좌는 프로그램 내부 모의주문 엔진의 장부다.
KIS 모의계좌는 한국투자 모의투자 서버에서 직접 조회한 계좌 상태다.
두 값은 주문 거절, 부분 체결, 체결 시차, KIS 예수금 표시 방식 때문에 일시적으로 다를 수 있다.

브로커 모의계좌 잔고 갱신:

```bash
./scripts/refresh_kis_account.sh
python -m app --kis-account-balance
```

로컬 가상 계좌와 브로커 모의계좌 비교:

```bash
./scripts/reconcile_paper_accounts.sh
python -m app --reconcile-paper-accounts
```

reconciliation을 실제 실행하면 계좌 식별자와 원문 응답을 제외한 일별 요약을 `runtime-data/reports/reconciliation/paper-account-history/YYYY-MM-DD.json`에 자동 기록한다.
최근 10개 유효 장후 거래일 집계는 `latest-paper-account-history.json/.md`에 남고, 대시보드 계좌 화면의 `10거래일 누적 정합성`과 `거래일별 정합성` 카드에서 확인한다.
`post-close`, 브로커 조회 성공, 브로커 제출 이력 존재가 모두 확인된 날만 Phase 0 분모에 포함한다. 10일이 차기 전에는 `insufficient_history`, 한 날이라도 불일치하면 `needs_review`, 10일 모두 정합할 때만 `ready`다.

Phase 0의 bounded recent lookup이 alignment 이후 기간을 덮지 못하면 아래 probe로 전체 기간 scope와 cooldown을 먼저 확인한다.

```bash
python3 scripts/probe_kis_paper_account_activity.py
```

`--execute`는 계좌 소유자의 해당 작업 명시 승인, 장외, live runtime 정지 상태에서만 1회 허용한다. 구현은 KIS paper 주문·체결을 read-only로 페이지 끝까지 확인하고, 계좌/주문 식별자와 raw response 없이 외부 활동·로컬 원장 차이·snapshot 차이를 분리한다. 불완전 pagination, 중복키, 빈 이력, rate limit은 모두 fail-closed이며 자동 align과 `SyncInitialCash`는 허용하지 않는다.
기존 최신 보고서를 네트워크 호출 없이 이력으로 반영하거나 현재 집계만 읽을 때는 아래 명령을 쓴다.

```bash
python scripts/summarize_paper_reconciliation_history.py --record-latest
python scripts/summarize_paper_reconciliation_history.py
```

브로커 기준으로 로컬 가상 계좌 현재 상태 정렬:

```bash
./scripts/align_local_paper_to_broker.sh
python -m app --align-local-paper-to-broker
```

장 시작 전 시작 예수금 동기화와 정렬:

```bash
./scripts/verify_paper_dual_account_match.sh -SyncInitialCash -AlignToBroker -AsJson
```

브로커 모의계좌에 이미 보유 종목이 있으면 현재 현금은 총 시작 예수금이 아니므로 `-SyncInitialCash`는 사용하지 않는다. 이 경우에는 브로커 기준 marker 만 정렬한다.

```bash
./scripts/verify_paper_dual_account_match.sh -AlignToBroker -AsJson
```

장중 또는 장후 상태 확인:

```bash
./scripts/verify_paper_dual_account_match.sh -AsJson
```

초기 현금 gap 조치 전 read-only 영향 분석:

```bash
python scripts/summarize_paper_cash_gap.py --as-json
```

이 분석은 `.env`, alignment marker, paper ledger 를 변경하지 않는다.
`-SyncInitialCash`는 코드상 root `.env`의 `PAPER_INITIAL_CASH`만 브로커 원시 예수금(`cash_balance`)으로 바꾸며, 최신 portfolio snapshot, fills, broker order backlog 는 다시 쓰지 않는다.
따라서 브로커 원시 예수금과 유효현금(`total_asset_amount - stock_evaluation_amount`)이 다르거나 local snapshot cash gap 이 남아 있으면, `-SyncInitialCash`만으로는 정합성 blocker가 닫히지 않을 수 있다.
`-AlignToBroker`는 marker-only baseline 을 새로 쓰고 과거 paper row 를 현재 view 에서 cutoff 하므로, 원장 보존성은 남지만 paper 기준선이 바뀐다.
alignment은 `runtime-data/backups/paper-alignment/`에 microsecond timestamp의 immutable JSON marker를 함께 기록한다. `backup_path`가 실제로 존재하지 않는 `.sqlite3`를 가리키던 문제는 2026-08-15 수정했다.
이 명령은 open order backlog 와 당일 감사 메모를 확인한 뒤 적용한다.

브로커 주문 backlog read-only 분석:

```bash
python scripts/summarize_broker_order_backlog.py --as-json
```

이 분석은 최신 alignment marker 이후의 브로커 제출 주문과 최신 broker status snapshot 을 읽어 현재 view 에 남은 open order 수, fixed sync 해석 적용 시 닫힐 row 수, 예상 final/open 상태를 보여준다. SQLite 원장과 KIS 계좌를 변경하지 않고 `runtime-data/reports/broker-paper/latest-open-order-backlog-analysis.{json,md}`만 갱신한다.

브로커 모의계좌 주문 미러링 실행:

```bash
$env:ENABLE_BROKER_PAPER_MIRRORING="true"
./scripts/start_runtime_autoboot.sh
```

현재 기본 전략 설정은 `ENABLE_BROKER_PAPER_MIRRORING=true` 이다.
로컬 가상 주문은 KIS 모의계좌에도 제출될 수 있고, 브로커 상태/체결 동기화로 로컬 장부를 맞춘다.

계좌 비교에서 KIS 원시 현금값은 체결 뒤에도 총 예수금처럼 보일 수 있다.
따라서 대시보드와 reconciliation 은 `total_asset_amount - stock_evaluation_amount` 로 계산한 브로커 유효현금을 기준으로 비교하고, 원시 현금 차이는 `raw_cash_gap` 으로 따로 남긴다.
브로커 기준 paper baseline alignment 도 보유 종목 유무와 관계없이 같은 유효현금 기준으로 로컬 `cash_balance`를 만든다.

KIS 주문/체결 조회는 수동·장후 배치·장중 종료 동기화 모두 HTTP 1회만 시도하고, `EGW00201` rate-limit 뒤 같은 호출 안에서 재시도하지 않는다.
제한이 발생하면 실행기를 죽이지 않고 `rate_limited` 리포트를 남기며 기존 제출 주문 종목을 대기 상태로 유지한다.
최초 제한 리포트부터 `cooldown_active=true`, `retry_after_seconds=7200`을 남기고, 2시간 안의 후속 실행은 같은 endpoint 를 호출하지 않은 채 `skipped_broker_call=true`로 끝낸다.
실시간 수집기도 `rate_limited` 결과에 120분 process pause를 적용한다. timeout, gateway routing error 같은 일반 예외는 5분부터 시작해 10/20/40/60분으로 늘어나는 지수 백오프를 적용하고, 정상 sync 뒤 실패 횟수를 초기화한다.
broker sync는 분봉 확정 경로 안의 동기 호출이므로 장애 시 반복 호출을 줄여 WebSocket frame 처리 여유를 보호한다. 회귀 위험은 체결 상태 반영이 늦어지는 것이며 pending 상태와 강제 종료 sync를 유지해 주문 상태를 임의 확정하지 않는다.

브로커 order-fill 조회가 정상 응답했는데 특정 주문이 최신 KIS lookback 에서 사라지면, paper sync 는 이전 status snapshot 과 이미 적용한 체결 수량을 우선 보존한다.
이전 적용 체결 수량이 주문 수량 이상이면 `filled`로 유지하고, 잔량이 남은 과거 주문일 row 는 다음 거래일에 새 체결로 이어질 수 없으므로 `expired` 또는 `expired_partial` final 상태로 해석한다.
이 처리는 KIS 조회가 정상 응답한 경우의 해석이며, `EGW00201` rate-limit 등으로 조회 자체가 실패했을 때는 기존처럼 pending 상태를 안전하게 보존한다.
2026-06-14 수정 뒤 실제 broker paper sync 를 1회 실행해 marker 이후 현재 view 의 open order backlog 는 0건으로 닫혔다.
같은 날 `-SyncInitialCash` 없이 marker-only `-AlignToBroker`를 적용한 뒤 최신 dual account match 는 `matched_waiting_first_submission`, effective cash gap 과 total asset gap 은 `0원`이다. 브로커 원시 예수금과 유효현금 차이는 `raw_cash_gap`으로 별도 표시한다.

2026-08-15 계좌 소유자 승인으로 KIS paper snapshot 기준 clean baseline을 생성했다. 새 current view는 `086520 5주`, `247540 10주`, `373220 1주`, 현금 `5,992,204원`, 총자산 `7,996,704원`이며 KIS/local mismatch, cash gap, total asset gap은 모두 0이다. 과거 원장과 과거 10거래일 mismatch 이력은 삭제하지 않고 새 기준선 epoch를 `0/10`에서 시작한다.

2026-07-10 재점검 기준 최신 paper/KIS position mismatch는 4종목(`035420`, `086520`, `105560`, `247540`)이다. `scripts/trace_paper_kis_mismatch.py`가 계산한 KIS order-fill 원장 순수량과 로컬 paper 수량은 네 종목 모두 일치하지만 KIS 계좌 잔고 snapshot 수량만 다르므로, 즉시 `AlignToBroker`로 덮지 않고 `kis_account_snapshot_vs_order_fill_ledger_divergence`로 분류한다. `035420`, `105560`은 주문/체결 원장은 보유를 말하지만 계좌 잔고가 flat 이고 반복 청산 주문이 거부된 상태이며, `086520`, `247540`은 계좌 잔고 수량이 order-fill 순수량과 다르다. `005380`은 최신 mismatch 목록에서 빠졌다. 다음 조치는 2시간 cooldown 이후의 다음 거래일 장후에 account snapshot과 order-fill sync를 1회만 비교하고, 계속 유지되면 KIS 모의계좌의 수동/외부 체결 또는 계좌 snapshot 원천 차이를 사람 검토 대상으로 올리는 것이다.

`scripts/recheck_paper_kis_mismatch.py`는 실제 sync/reconcile/trace 실행 결과만 `latest-paper-kis-mismatch-recheck.json`에 기록한다. dry-run 또는 장중·주말 차단 시도는 `latest-paper-kis-mismatch-recheck-attempt.json`에 따로 기록해 마지막 정상 운영 증거를 덮지 않는다.

broker paper sync는 KIS 주문/체결 행과 로컬 broker 제출 원장의 연결 상태를 식별정보 없는 건수로 함께 기록한다. `broker_rows_unlinked_to_submissions`는 수동/외부 주문 또는 제출 원장 누락 후보, `fallback_matched_orders`는 주문일 없는 보조 매칭 사용, `ambiguous_fallback_key_count`는 보조키 중복을 뜻한다. 이 값은 mismatch 원인 범위를 좁히기 위한 진단이며 계좌 align, 주문 정책, position 원장을 자동 변경하지 않는다. 장후 자동화는 당일 유효 reconciliation history가 이미 있으면 broker endpoint를 중복 호출하지 않고, 실제 거래일 장후인데 당일 기록이 없을 때만 통합 recheck를 한 번 실행한다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:
변경 전에는 KIS lookback 에서 사라진 주문이 이미 full fill 로 적용됐거나 과거 주문일 잔량으로 남아도 다음 sync 에서 `pending_lookup`으로 되돌아가 open count 를 부풀릴 수 있었다.
변경 후에는 이전 final/applied fill 상태를 보존하고, 정상 조회 후에도 남은 과거 주문일 잔량은 final 만료 상태로 해석해 현재 open backlog 를 부풀리지 않는다.
영향 범위는 `app/services/broker_paper_sync.py`의 KIS 모의계좌 paper sync 해석과 관련 테스트에 한정된다.
회귀 위험은 당일 open 주문을 잘못 final 처리하는 경우인데, 주문일이 동기화일보다 이전인지 확인하고, 조회 실패(rate limit) 경로에서는 final 전환을 하지 않는 방식으로 줄였다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:
변경 전에는 장후 batch가 한 실행에서 최대 5회(10/30/60/120초 대기), 기본 helper가 최대 4회, 장중 종료 force sync가 기본 재시도를 사용할 수 있었다.
변경 후에는 모든 운영 order-fill 조회가 한 번의 HTTP 시도만 수행하고, 최초 `EGW00201`부터 2시간 cooldown과 남은 초를 리포트에 기록한다.
영향 범위는 `app/services/broker_paper.py`, `app/services/broker_paper_sync.py`, `app/services/streaming.py`와 관련 테스트에 한정된다.
회귀 위험은 제한이 빨리 풀려도 체결 감사 복구가 최대 2시간 늦어지는 경우다. 안전 측으로 pending 상태를 보존하고, 계좌 정렬이나 초기 현금 동기화로 원인을 덮지 않는다.

## KIS 계좌 설정 메모

모의투자 계좌 화면에 상품코드가 따로 없으면 root `.env` 의 `KIS_PRODUCT_CODE_PAPER` 는 빈 값으로 둔다.
앱은 KIS REST 계좌/주문 호출에 상품코드가 필요할 때 paper 기본값을 내부에서 적용한다.

계좌가 `12345678-01` 형태로 들어오면 설정 로더는 아래처럼 나눈다.

- `KIS_ACCOUNT_NO_PAPER=12345678`
- `KIS_PRODUCT_CODE_PAPER=01`

`.env` 에 템플릿 placeholder 값이 남아 있으면 빈 값으로 간주하고 paper 기본값을 적용한다.

KIS app key/secret 복구:

```bash
./scripts/restore_kis_env_interactive.sh
```

계좌 항목까지 함께 복구:

```bash
./scripts/restore_kis_env_interactive.sh -IncludeAccountFields
```

모의계좌번호만 연결 또는 복구:

```bash
./scripts/connect_kis_paper_account_interactive.sh
```

## 실시간 수집기

실시간 수집기 백그라운드 시작/상태/중지:

```bash
./scripts/start_live_runtime_background.sh
./scripts/get_live_runtime_status.sh
./scripts/stop_live_runtime.sh
```

실시간 수집기가 실행 중이면 아래를 수행한다.

- 관심 종목 목록의 종목을 계속 수집한다.
- 새 분이 닫힐 때마다 15분과 60분 예측을 기록한다.
- 신호와 주문 판단은 15분 기준으로 수행한다.
- 대시보드 상단 프로그램 상태와 로컬 모의운용 계좌가 `운용 중`으로 바뀐다.

실시간 실행 ID는 실행별 고유 이름공간을 포함한다.
재시작 뒤에도 `paper-order-online-*` ID를 재사용해 기존 SQLite row를 덮어쓰지 않는다.

## 실행 감시기

실행 감시기 시작/상태/중지:

```bash
./scripts/start_runtime_watchdog_background.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/stop_runtime_watchdog.sh
```

감시기 동작 기준은 아래와 같다.

- 정규장에는 대시보드와 실시간 수집기가 둘 다 살아 있는지 확인하고, 꺼져 있으면 다시 올린다.
- 정규장 시작 60분 전부터는 장전 준비 단계로 실시간 수집기를 미리 켠다.
- 대부분의 장외 시간과 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기를 새로 켜지 않고, 켜져 있으면 중지해 WebSocket 재연결 루프를 막는다.
- `holidays`는 KRX 전일 휴장일을 명시하는 로컬 운영 캘린더이며, 연도 변경이나 임시 휴장 공지가 있으면 장 시작 전 갱신한다.
- 대시보드 스냅샷 전체 재생성은 기본 10분 간격으로 제한해 CPU 사용을 줄인다.
- 실시간 지연 판단은 우선 실시간 수집기 상태값과 최신 KIS 검증 파일을 사용한다.
- 감시기 상태 조회는 프로세스 존재와 함께 `last_checked_at` 심박 나이를 확인한다. 프로세스가 살아 있어도 기본 10분 이상 상태 파일이 갱신되지 않으면 `stale` 로 본다.
- 감시기 시작 스크립트는 stale 심박을 가진 기존 감시기 프로세스를 재사용하지 않고 중지 후 새로 시작한다.
- 정규장에 실시간 수집기가 이미 최신 분봉을 쓰고 있으면 별도 KIS 검증 WebSocket 을 중복 실행하지 않는다.
- root `.env` 또는 KIS 자격정보가 없으면 차단 상태를 기록하고 같은 실패를 반복하지 않는다.
- `.env` 가 복구되고 활성 거래 모드 기준 app key/secret 이 준비되면 오래된 차단 상태를 해제한다.
- 실시간 수집기 상태 출력은 현재 장 상태와 마지막 KIS 검증 당시 장 상태를 분리해서 보여준다.
- 로컬 setup 점검은 현재 장 상태와 장전 준비 시간을 계산해, 장외나 장전 준비 전 실시간 수집기 중지를 정상 상태로 해석한다.

감시기 상태 파일:

- `runtime-data/reports/runtime-watchdog/state/watchdog-state.json`

## PC 로그인 후 자동 복구

PC 재부팅 후 자동 시작 루틴:

```bash
./scripts/start_runtime_autoboot.sh
./scripts/install_runtime_startup_launcher.sh
./scripts/get_runtime_startup_launcher_status.sh
./scripts/remove_runtime_startup_launcher.sh
```

`start_runtime_autoboot.sh` 는 아래를 수행한다.

- demo/sample SQLite row 정리
- 대시보드 백그라운드 시작
- 장중 또는 장전 준비 시간에는 실시간 수집기 백그라운드 시작
- 장외와 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기 중지 상태 유지
- 실행 감시기 시작
- KIS 브로커 모의계좌 잔고 갱신
- 브로커 모의계좌 주문 동기화
- 모의계좌 정합성 점검
- 실행 리포트 갱신
- 대시보드 스냅샷 재생성

하위 `python -m app ...` 명령이 실패하면 성공처럼 넘기지 않고 즉시 오류로 처리한다.

WSL2/Windows 환경의 `install_runtime_startup_launcher.sh`는 Windows 시작프로그램의 `RealTimeStockRuntime.cmd`를 현재 WSL 정본 저장소 경로로 설치한다.
Windows 로그인 직후 WSL 준비 지연을 줄이기 위해 시작 전 짧게 대기하고, 실행 결과는 `runtime-data/logs/automation/RealTimeStockRuntime.log`에 남긴다.
Windows 시작프로그램 launcher는 장전 자동 시작이 DB cleanup 때문에 지연되지 않도록 `--skip-runtime-cleanup --skip-dashboard-build`를 붙여 빠른 시작 경로로 실행한다.
Windows 시작프로그램을 사용할 수 없는 순수 Linux 환경에서만 systemd user service 를 fallback 으로 사용한다.

## 월요일 시작 루틴

```bash
./scripts/start_monday_runtime.sh
```

이 스크립트는 아래를 수행한다.

- 대시보드 서버 시작
- 장중 또는 장전 준비 시간에는 실시간 수집기 수신기 시작
- 장외와 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기 중지 상태 유지
- 실행 감시기 시작
- demo/sample SQLite 행 정리
- 실행 리포트와 대시보드 스냅샷 갱신
- 그림자 머신러닝 갱신
- 브로커 모의계좌 캐시 갱신
- 모의계좌 정합성 점검
- KIS 검증
- 주요 상태 JSON 요약 출력

## KIS WebSocket 검증

```bash
./scripts/verify_kis_ws.sh
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

검증은 아래를 분리해서 기록한다.

- `.env` 존재 여부
- 자격정보 준비 여부
- `websockets` 패키지 사용 가능 여부
- approval key 발급 여부
- 연결 준비 완료 여부
- 실제 장중 데이터 수신 여부
- 장 상태에 따른 해석

장외에는 시장 데이터가 들어오지 않는 것이 정상일 수 있으므로 연결 준비 상태와 시장 데이터 흐름을 분리해 본다.

## 매시간 저장소 점검

1회 실행:

```bash
./scripts/run_hourly_repo_audit_iteration.sh
```

백그라운드 시작/상태/중지:

```bash
./scripts/start_hourly_repo_audit_background.sh
./scripts/get_hourly_repo_audit_status.sh
./scripts/stop_hourly_repo_audit.sh
```

권장 스케줄러는 Codex 자동화다.
bash 백그라운드 실행기는 Codex 자동화가 없을 때만 쓰는 예비 경로로 본다.

자동화는 아래를 수행한다.

- 기준 문서 재읽기
- 저장소 구조, runtime-data, git 상태 점검
- 정규장 시간에만 KIS 검증 후보 실행
- Codex CLI 기반 검토, 웹 메모, 초안, 문맥, 진행 상태, 우선순위 목록 산출
- `runtime-data/reports/codex/automation/` 아래 상태 보존
- 같은 미해결 항목 식별자 유지
- 저장된 pid 와 실제 bash 명령줄 대조

## 실데이터 정리와 재구축

테스트 운용 흔적 정리:

```bash
./scripts/cleanup_runtime_test_data.sh
```

저장소 생성 부산물 정리:

```bash
./scripts/cleanup_repo_generated_artifacts.sh
./scripts/cleanup_repo_generated_artifacts.sh --apply
```

이 wrapper 는 `.tmp-tests`의 하위 산출물, `app/`, `scripts/`, `tests/` 아래 Python `__pycache__`, 루트 PowerShell provider prefix 오염 디렉터리를 대상으로 한다. 기본은 dry-run 이고 `.tmp-tests/codex-ops/`와 `app/risk/` 아래 생성물은 제외한다.

실제 운용 데이터만 남기고 ML/검증 산출물 재생성:

```bash
./scripts/rebuild_actual_ml_state.sh
```

실데이터 전용 정리는 아래를 정리한다.

- demo / replay / synthetic 원시 체결과 호가
- 파생 분봉
- 서빙 테이블
- 모의운용 테이블
- 테스트용 포트폴리오 스냅샷

단, 실제 브로커 체결 시각에 생성된 portfolio snapshot 은 실제 운용 데이터로 보존한다.

## 추천 개발 흐름

합성 데이터 전체 흐름:

```bash
./scripts/run_full_synthetic_cycle.sh
```

명시적 백테스트:

```bash
./scripts/run_backtest.sh
```

명시적 워크포워드:

```bash
./scripts/run_walk_forward_backtest.sh
```

정본 gate reference 워크포워드:

```bash
./scripts/run_gate_walk_forward_backtest.sh
```

현재 데이터셋 권장 워크포워드 변형:

```bash
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
```

KIS REST 개발 흐름:

```bash
./scripts/run_full_kis_cycle.sh
```

안전한 활성 모델 초기화:

```bash
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
```

그림자 머신러닝 갱신:

```bash
./scripts/run_ml_shadow_cycle.sh
```

도전자 모델 비교:

```bash
./scripts/run_challenger_review.sh
```

## 유용한 CLI 명령

저장소 구조와 현재 Markdown 감사:

```bash
python scripts/audit_repository_structure.py
```

```bash
python -m app --kis-current-price --symbol 005930
python -m app --kis-orderbook --symbol 005930
python -m app --kis-watchlist-poll --iterations 5 --interval-seconds 5
python -m app --build-minute-bars
python -m app --build-feature-dataset
python -m app --train-baseline --horizon-min 15
python -m app --train-lightgbm --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
python -m app --run-backtest --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
python -m app --run-challengers --horizon-min 15
python -m app --build-runtime-report
python -m app --reconcile-paper-accounts
python -m app --sync-broker-paper-orders
python -m app --replay-sample-ws --symbol 005930
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

## 주요 산출물 경로

- 실행 리포트: `runtime-data/reports/runtime/latest-runtime-report.md`
- 실행 리포트 JSON: `runtime-data/reports/runtime/latest-runtime-report.json`
- 백테스트 리포트: `runtime-data/reports/backtests/latest-backtest-h15.md`
- 백테스트 리포트 JSON: `runtime-data/reports/backtests/latest-backtest-h15.json`
- 워크포워드 리포트: `runtime-data/reports/backtests/latest-walk-forward-h15.md`
- 워크포워드 리포트 JSON: `runtime-data/reports/backtests/latest-walk-forward-h15.json`
- 도전자 모델 리포트: `runtime-data/reports/challengers/latest-challengers-h15.md`
- 도전자 모델 리포트 JSON: `runtime-data/reports/challengers/latest-challengers-h15.json`
- 도전자 모델 순위표 JSON: `runtime-data/reports/challengers/leaderboard-h15.json`
- KIS 검증 리포트: `runtime-data/reports/kis-ws/latest-verification.md`
- KIS 검증 리포트 JSON: `runtime-data/reports/kis-ws/latest-verification.json`
- 모의계좌 정합성 리포트: `runtime-data/reports/reconciliation/latest-paper-account-sync.md`
- 모의계좌 정합성 리포트 JSON: `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- 모의계좌 시작금 일치 리포트: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.md`
- 모의계좌 시작금 일치 리포트 JSON: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
- 대시보드 스냅샷 HTML: `runtime-data/reports/dashboard/latest-dashboard.html`
- 대시보드 스냅샷 JSON: `runtime-data/reports/dashboard/latest-dashboard.json`
- 복구 setup 점검 JSON: `runtime-data/reports/recovery/latest-local-setup-check.json`
- 복구 setup 점검 Markdown: `runtime-data/reports/recovery/latest-local-setup-check.md`
- 모델 등록부: `runtime-data/ml/registry.json`
- centroid 산출물: `runtime-data/ml/models/`

## 현재 운영 권장

현재는 `baseline-h15-v1` 을 활성 실시간 모델로 유지하고, `lightgbm-h15-v1` 은 도전자 모델 산출물로 학습/비교한다.
장중 streaming 경로(`app/services/streaming.py`)는 active 모델 예측으로 신호와 paper 주문을 만들고, `app/models/loader.py`의 최신 LightGBM shadow loader 로 불러온 artifact 예측은 `serving_predictions`에만 추가 저장한다. 따라서 대시보드 `예측 흐름`은 baseline과 LightGBM을 한 종목/시각 라인에서 비교할 수 있지만, LightGBM row가 있어도 active 승격이나 주문 판단 변경을 의미하지 않는다. 현재 저장소에는 15분 LightGBM artifact가 있고, 60분 artifact가 없으면 60분 shadow 저장은 건너뛴다.
최신 워크포워드 기준이 약하면 검증 구간에서 더 좋아 보여도 자동 승격하지 않는다.

다음 우선순위는 아래와 같다.

1. 실제 장중 수집 안정성 유지
2. 로컬 가상 계좌와 KIS 모의계좌 정합성 점검
3. 장후 재학습 산출물 검토
4. LightGBM 승격 기준 고도화
5. 뉴스/공시/반응 데이터 특징 추가
