# 국장 유지 + 미장 연구 병행 구현 계획

작성: 2026-10-12 KST. 상태: 검토용 계획, 구현 및 외부 연결 미실행.

## 목적과 승인 범위

국장 수집/Phase 0/E7은 유지하고, 미장은 Alpaca 무료 데이터와 로컬 모의운용으로 별도 연구한다.
사용자는 데이터원 방향을 선택했다. 이 선택은 계정 생성, credential 입력, API 실행, 예약 추가 또는 주문 승인이 아니다.
이 문서는 다음 구현의 의존 순서와 통과 기준을 정하며 실행은 계획 검토 후 진행한다.

## 확인한 기존 제약

- `app/config/settings.py:AppSettings`는 KIS 자격정보와 하나의 시장 달력/시간대/전략 설정을 소유한다. US 경로에서 이 전역 설정을 변경하거나 그대로 로드하지 않는다.
- `app/utils/time.py:get_market_session_status`는 기존 KRX 운영용이다. 미국 휴일/조기마감/DST를 국장 설정 덮어쓰기로 처리하지 않는다.
- `app/storage/contracts.py:MinuteBar/FeatureSnapshot/PaperPosition`에는 시장/통화/수신 시각이 없다. 기존 DB에 미국 종목을 추가하면 평가·원장 범위를 혼합할 수 있다.
- `app/features/minute_bars.py:build_feature_snapshot`는 호가를 요구한다. 과거 OHLCV에 가짜 호가를 채워 기존 모델 입력을 흉내 내지 않는다.
- `app/paper_trading/costs.py`는 국내 일반주권 비용이고, `app/services/portfolio_replay_v2.py:_validate_v2_manifest`는 그 비용 버전만 허용한다. 미국 비용을 국내 버전이라고 표시하거나 기존 검사를 우회하지 않는다.
- 모델 artifact/registry도 runtime root에 종속된다. 미장 모델을 국장 active registry에 등록하지 않는다.
- 10/12 KST 00시경 실제 확인: runtime은 정상 장외 정지, watchdog은 process_running=false/stale다. 이전 정상 상태를 현재 정상으로 인용하지 않는다. 복구는 이 계획 작성에서 수행하지 않았다.

## 설계 선택

1. 채택: 같은 저장소의 공통 계산 로직 + 별도 US 프로세스/DB/모델/원장. 재사용과 장애 격리를 함께 확보한다.
2. 제외: 기존 KIS runtime에 미국 종목을 바로 추가. 설정/통화/세션/비용/원장의 혼합 위험이 크다.
3. 제외: 저장소 전체 복제. 지금은 기존 버그 수정과 검증을 중복 유지할 이유가 없다.

기존 국장 진입점은 바꾸지 않고 US 전용 CLI를 추가한다. 공통 로직 변경은 필요한 최소 계산 경계에 한정한다.

## 초기 연구 범위

- 유료 데이터 구독, 실전 계좌, Alpaca paper 주문, KIS 해외주문은 제외한다. 외부 요청은 시세 전용이다.
- pilot은 SPY/QQQ/IWM/XLF/XLV 5개 ETF를 제안한다. 현재 고정 종목군 연구이지 미국 전체 종목이나 과거 생존 종목 모집단을 대표하는 결과가 아니다. 구현 전 universe hash를 고정한다.
- 미국 정규장만, long-only/정수 주식/무레버리지/당일 청산으로 시작한다. 장전·장후, 공매도, 옵션, 소수점 주식은 후속 범위다.
- 1분 데이터, 15분 예측을 먼저 연결한다. 60분 모델은 첫 경로의 품질과 재현성이 확인된 뒤 별도 실험한다.
- USD 원장만 운영한다. KRW 환산은 별도 참고 지표이며 수익률에 환율 효과를 섞지 않는다.
- 초기 USD 10,000, 종목별 최대 25%, 최대 4포지션을 제안한다. 이는 US 연구용 제안이며 국장 allocator를 변경하지 않는다.
- 초기 비용 검증은 왕복 20bp/40bp의 종합 마찰 예산을 제안한다. 실제 수수료나 법정 세율이라고 부르지 않으며 spread/slippage/fee를 중복 차감하지 않는 비용 버전을 만든다. 실제 브로커 적용 검증에는 해당 브로커의 별도 수수료·규제비용 계약이 필요하다.
- threshold/model/feature는 미장 과거 train/validation에서 선택하고 미래 구간 전 고정한다. 국장 0.55나 active model을 미장에도 유효하다고 가정하지 않는다.

## 데이터 및 자원 격리

- US 누적: `runtime-data/us/`; DB `runtime-data/us/us-research.db`; raw/log/model/report는 그 아래에 둔다.
- US 연구 snapshot: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/us/`; 격리 테스트: `.tmp-tests/us/`.
- credential은 추적하지 않는 US 전용 비밀 경로, 권한 0600, 대화/로그/리포트 redaction을 적용한다. KIS credential과 루트 .env는 US 경로가 읽지 않는다.
- 모든 dataset/result는 market=US, currency=USD, provider/feed, session_date, universe/model/evaluator/cost/manifest hash를 가진다.
- 저장 시각은 aware UTC, 거래일/세션 판정은 America/New_York, 화면 참고 시각만 KST다. grouping/당일 청산 전에 New York 거래일을 확정한다.
- 첫 수집은 분봉과 호가만, 5종목/1연결이다. 틱 전체 수집과 대규모 종목 확대를 기본으로 넣지 않는다.
- 무거운 학습은 동시에 1개, 국장 보호 시간에는 시작하지 않는다. 이미 실행 중인 연구는 체크포인트로 중지/연기하고 두 시장 수집을 종료하지 않는다.

## 실행 순서

`U0 → U1 → U2 → U3 → U4 → U5 → U6`

U2 이후 승인된 원본 수집은 계속할 수 있다. U3/U4 과거 연구는 별도 snapshot에서 수행한다.

### U0. 국장 운영 보호 확인

예상 범위: 기존 status/startup helper와 `docs/STATUS.md`; 서비스 복구는 별도 실행 범위다.

- [ ] 실제 KST/세션/runtime/watchdog/dashboard/startup launcher를 다시 확인한다. watchdog 미실행 원인을 기존 로그/시작 경로로 확인한다.
- [ ] 필요한 안전 복구 후 should-run/heartbeat/process를 검증한다. 장외 live runtime을 임의로 시작하지 않는다.
- [ ] 원래 E7 latest/고정 계약/Phase 0 baseline의 식별 해시를 확보한다. 이후 US 작업 전후에 대조한다.

통과: 국장 시작/수집 경로가 살아 있고 US 작업으로 국장 프로세스/DB/설정/원장을 변경하지 않음을 검증한다.
현재 예약 PAUSED와 토큰 절약 결정은 유지한다. 재개는 운영자 결정이며 watchdog 복구와 별개다.

### U1. US 실행 경계와 시간/저장 계약

예상 신규: `app/config/us_research.py`, `app/utils/us_market_time.py`, `app/storage/us_research_store.py`.
테스트: `tests/test_us_runtime_isolation.py`, `tests/test_us_market_time.py`, `tests/test_us_research_store.py`.

- [ ] 먼저 root dev.db/모델 registry/KIS 설정에 대한 접근 거부, USD/KRW 혼합, US→KR 모델 선택 거부 테스트를 작성한다.
- [ ] `USResearchSettings`는 US root/DB/universe/feed/timezone만 소유하고 실전·broker mirror 실행 인자를 제공하지 않는다.
- [ ] `resolve_us_session(timestamp)`는 UTC open/close와 New York session_date를 반환한다. calendar 제공 범위 밖은 휴장으로 추측하지 않고 차단한다.
- [ ] 표준 zoneinfo와 검증된 exchange_calendars를 사용한다. 추가 의존성은 US 전용 requirements/환경에 고정해 현재 국장 설치를 업그레이드하지 않는다.
- [ ] 미국 별도 schema에 raw envelope, minute-bar revisions, prediction/decision, paper accounting 및 checkpoint를 저장한다. SQLite transaction을 사용하며 기존 root schema를 migration하지 않는다.

통과: DST 전후, KST 자정 넘김, 미국만 휴장/한국만 휴장, 조기마감, 종목/통화/DB 경계 회귀가 모두 통과한다.
이 단계는 fixture만 사용하고 외부 인증/API 호출은 0회다.

### U2. Alpaca 시세 adapter와 승인된 수집

예상 신규: `app/brokers/alpaca_market_data.py`, `app/collectors/us_market_data.py`, `scripts/run_us_collection.py`.
테스트: `tests/test_alpaca_market_data.py`, `tests/test_us_collection.py`.

- [ ] 데이터 host만 허용하고 Trading API host/주문·취소 method를 거부하는 테스트를 먼저 작성한다.
- [ ] 사용자가 무료 계정과 key를 준비한 뒤 별도 승인된 bounded read-only 확인으로 IEX 과거/stream 권한을 검증한다. 권한 부족을 자동 유료 전환이나 새 브로커 가입으로 해결하지 않는다.
- [ ] explicit feed=iex, REST 최대 120요청/분, WS 1연결/5종목을 내부 상한으로 둔다. pagination checkpoint, 중복 page token, 429/Retry-After, auth 차단, 네트워크 backoff 및 redaction을 검증한다.
- [ ] provider 분봉을 기본으로 받아 직접 trade-condition 집계를 새로 만들지 않는다. raw timestamp/received_at/available_at/message hash/feed/revision을 보존한다.
- [ ] bars/updatedBars를 append-only 버전으로 보존한다. 이미 생성한 판단은 수정 분봉으로 재생성하지 않는다. restart checkpoint와 유일 decision key를 DB에서 검증한다.
- [ ] 미래 판단은 최초 정상 bar 수신 뒤 생성한다. 이후 updatedBars는 기존 판단을 바꾸지 않으며 다음 판단의 과거 입력에 사용하려면 그 판단의 as-of 이전 수신 증거가 있어야 한다. decision key는 market/feed/symbol/bar_time/model_version/policy_version으로 고정하고 실행 중 revision 변경으로 새 주문을 만들지 않는다.
- [ ] 호가의 round-lot 단위를 raw metadata에 보존한다. IEX 호가를 전체 시장 NBBO라고 표시하지 않는다.

통과: 수정 분봉/중복 frame/reconnect/restart에도 판단 재생성 0, 주문·취소 0, KR 파일/DB 접근 0이다.
IEX 무거래 분의 bar 부재와 연결 장애를 구분한다. 빈 분을 거래된 분봉으로 합성하지 않는다.

### U3. 과거 데이터와 미장 feature/label

예상 신규: `app/features/us_minute_features.py`, `app/services/us_research_dataset.py`, `scripts/build_us_research_dataset.py`.
테스트: `tests/test_us_research_dataset.py`, `tests/test_us_features.py`.

- [ ] 파일 import/작은 기간 download부터 동일 parser를 검증한 뒤 5종목 최근 24개월로 확대한다. 실제 접근/보유 범위를 확인하기 전 24개월 확보를 완료로 표시하지 않는다.
- [ ] 초기 feature는 가격 기반 OHLC/과거 return/rolling volatility다. 존재하지 않는 과거 호가·spread·imbalance를 0이나 추정값으로 채워 기존 모델을 사용하지 않는다.
- [ ] 15분 label은 같은 US session 안의 실제 관측 가능한 가격만 사용한다. 누락/정지/장마감으로 horizon이 닫히지 않으면 미적격 이유를 보존한다.
- [ ] unadjusted 가격과 기업행사 정보를 분리하고 adjustment/asof/download snapshot을 고정한다. 기업행사 처리나 정보 시점이 불명확한 구간은 fail-closed한다.
- [ ] historical provider 수정본과 future as-observed 분봉은 다른 dataset version이다. 사후 수정된 역사 데이터를 실제 당시 알고 있었던 입력이라고 주장하지 않는다.

통과: 시각/가격/volume 검증, 동일 다운로드 hash 재현, cross-session label 0, future leakage 0, 누락/수정/기업행사 fixture가 통과한다.
무거운 작업은 US snapshot만 사용한다. 미래 raw 수집은 이 작업의 완료를 기다릴 필요가 없다.

### U4. 비용/체결/MTM와 walk-forward 백테스트

예상 신규: `app/models/us_research.py`, `app/paper_trading/us_costs.py`, `app/services/us_portfolio_replay.py`, `scripts/run_us_backtest.py`.
공통 수정 후보: `app/services/portfolio_replay_v2.py`의 계산 경계와 필요한 `app/services/portfolio_replay_core.py` 추출만.
테스트: `tests/test_us_model_research.py`, `tests/test_us_portfolio_replay.py` 및 기존 portfolio_replay_v2/E7/MTM 회귀.

- [ ] 기존 KR v2 입력/결과/metadata/manifest hash golden fixture를 먼저 고정한다. US version을 기존 E7 validator에 허위 국내 비용으로 통과시키지 않는다.
- [ ] 계산 로직의 최소 추출로 KR wrapper/validation/defaults는 그대로 유지하고 US wrapper에 별도 비용/세션/입력 계약을 적용한다. 필요 이상으로 전체 research.py나 streaming.py를 재구성하지 않는다.
- [ ] historical bar 기반 비용 후 평가와 quote 관측 paper fill을 분리한다. 한 분봉 안의 지정가 체결 순서/queue는 OHLC만으로 확정하지 않는다.
- [ ] signal price를 즉시 체결가로 쓰지 않는다. decision available_at 뒤의 첫 실행 가능 시점으로 진입하고, close/received_at을 보기 전에 next-minute open에 체결시키는 look-ahead를 차단한다.
- [ ] 학습/선택/미사용 과거 test를 날짜로 분리하고 horizon purge를 적용한다. 후보 수/선택 규칙/피처/threshold를 기록하며 전체 기간을 보고 고른 결과를 독립 검증이라고 부르지 않는다.
- [ ] 학습은 기존 sklearn/LightGBM 기반의 작은 후보 집합부터 시작한다. `train_us_model(dataset_manifest, split_spec)`은 US artifact root에만 모델과 feature/label/split/seed hash를 저장한다. `predict_us_model(artifact, feature_rows)`는 모델별 feature 계약과 학습 종료 시각을 검증한다. KR active registry를 읽거나 승격하지 않으며 US 모델 선택도 미래 구간 전 별도 manifest로 고정한다.
- [ ] baseline 대비 후보 선택과 threshold 탐색은 validation에서만 수행한다. 미사용 과거 test를 본 뒤 같은 test로 재선택하지 않는다. 동일 seed 재현, feature 누락, train/validation/test 시간 교차, US/KR artifact 혼용 거부를 테스트한다.
- [ ] USD cash/position MTM, 비용 normal/2x, 동일 모집단 random control, 장기보유 참고 기준을 비교한다. 과거 검증은 탐색 결과이며 live 수익성 통과가 아니다.
- [ ] normal/2x 비용은 같은 체결 경로의 비용 예산만 달리한다. quote 체결가에 이미 반영된 spread를 비용 예산에 다시 전액 더하지 않도록 포함 항목과 잔여 비용을 명시한다. 역사 분봉 결과와 실시간 quote-paper 결과는 같은 execution version으로 합산하지 않는다.

통과: KR golden 및 전체 relevant unittest 불변, US fee 중복 차감/미래 가격 사용/누락 mark/자정 거래일 오류 0, 재실행 결과와 hash 일치다.
필요한 공통 수정은 장외 통합한다. 보호 중에는 별도 worktree/격리 테스트에서만 준비한다.

### U5. 독립 미래 shadow와 로컬 paper

예상 신규: `app/services/us_shadow.py`, `app/paper_trading/us_paper.py`, `scripts/run_us_shadow.py`.
테스트: `tests/test_us_shadow.py`, `tests/test_us_paper.py`.

- [ ] 미장 model/feature/universe/cost/entry/exit/threshold를 별도 preregistration과 manifest로 고정한다. 미래 구간 시작은 최종 고정 이후의 거래일로 정한다.
- [ ] 서로 비중복인 두 구간을 사전에 고정한다. 최소 기준은 구간별 10거래일/100 완료 paper 거래/5종목을 제안하며 부족하면 관측 부족으로 남긴다. 기간/정책을 성과에 따라 옮기거나 거래를 강제하지 않는다.
- [ ] 정확한 raw/bar revision → feature → prediction → decision → paper order/fill/portfolio ID를 연결한다. recheck에서도 당시 판단 가격과 available_at 증거를 보존한다.
- [ ] missing/stale/crossed quote 또는 데이터 장애 때 새 진입을 차단한다. 보유 평가 불가·청산 불가를 보유가 없는 것처럼 숨기지 않는다.
- [ ] 단절/restart/미적용 fill의 멱등성과 USD 회계를 검사한다. broker mirror나 실제 account reconciliation은 초기 범위에 없다.

통과: 최소 5개 실제 US session의 운영 안정 관측, KR 영향 없음, ID 연결 100%, 단절/restart fixture와 quote/MTM health 검증이다.
5일은 운영 안정 확인일 뿐 수익성 통과가 아니다. 두 고정 미래 구간의 비용 후/대조군 판정은 별도 결과다.

### U6. 운영 보고와 병행 자원 검증

예상 신규: `scripts/get_us_runtime_status.py`, `scripts/summarize_us_research.py`.
필요 시 추가: `scripts/run_us_watchdog.py` 및 dashboard의 읽기 전용 US report 표시.
테스트: `tests/test_us_ops.py`, UI를 연결할 때만 `tests/test_dashboard.py` 관련 회귀.

- [ ] 먼저 CLI/JSON report로 US session/feed/coverage/revisions/decision lineage/USD 원장/RSS/지연을 보여준다. 국장 Phase 0와 US local-paper 상태를 같은 통과 지표로 합산하지 않는다.
- [ ] 최소 3개의 KR+US 연속 주기에서 collection lag/CPU/RSS/디스크/WAL/학습 소요를 측정한다. KR 수집에 영향이 생기면 US 연구를 먼저 연기한다.
- [ ] US session close+15분부터 품질, close+30분부터 가벼운 보고를 제안한다. 고정 KST 시간으로 DST/조기마감을 무시하지 않는다. heavy ML은 별도 자원 guard를 통과한 때만 실행한다.
- [ ] US 프로세스 제어는 US root/PID에만 한정한다. 단일 US 장애로 KR watchdog/runtime을 종료하지 않는다.
- [ ] 필요한 운영자 승인 뒤 US 예약을 별도로 등록한다. 기존 KR 예약의 prompt/시간/PAUSED 상태는 변경하지 않으며 새 예약은 이 계획 작성에서는 생성하지 않는다.

통과: 양 시장 운영 보고 분리, KR/US 상호 kill 없음, DST/휴일 무효 실행 없음, 반복 실행/캐시 시각/장외 요약/비밀값 회귀 통과다.
dashboard 표시나 자동 복구 service는 수집/검증이 준비되기 전에 추가하지 않는다.

## 단계별 검증과 중단 기준

- 각 U 단계는 신규 failing fixture → focused unittest → 최소 구현 → focused 성공 → 독립 변경 단위 검토 순서다.
- `python3 -m unittest tests.test_us_runtime_isolation tests.test_us_market_time tests.test_us_research_store`는 U1 focused 명령이다. 아직 파일이 없으므로 이 계획에서 실행하지 않았다.
- U4 공통 계산 변경 뒤에는 기존 E7/portfolio 관련 회귀와 `python3 -m unittest discover -s tests -p "test_*.py"` 전체 검증을 수행한다.
- 현재 계획의 문서 검증은 `git diff --check`와 `python3 scripts/audit_repository_structure.py`다. 테스트를 실행하지 않고 통과했다고 기록하지 않는다.
- auth/entitlement 또는 보유 데이터 부족: 연결 범위를 보고하고 차단한다. credential을 추정하거나 유료 서비스/실전 계좌를 자동으로 추가하지 않는다.
- 원천/모델/비용/hash 혼합: 평가 차단. 불리한 표본 제거, threshold 사후 변경, 국장 E7 결과로 미장 표본 보충은 금지한다.
- 국장 영향: US rollout 중단/격리. 기존 DB/설정/Phase 기준/E7 증거를 되돌리거나 재작성하는 해결책은 사용하지 않는다.

## 가장 먼저 구현할 3개

1. U1 시간/통화/저장 격리: 안전한 병행의 선행조건이고 credential 없이 fixture로 시작할 수 있다.
2. U2 시세 수집/원천 revision 계약: 연구 엔진 구현 중에도 데이터가 쌓이며 과거 재생성·중복 판단 사고를 예방한다.
3. U3 과거 데이터/feature/label: 축적만 기다리지 않고 사용할 수 있는 미장 입력과 모델 연구 기반을 만든다.

U0 운영 안전 확인은 위 세 구현에 앞서는 사전 점검이다. 다음 실행에서는 U0 확인 후 U1만 첫 변경 묶음으로 시작한다.

## 공식 근거 (2026-10-12 확인)

- [Alpaca Basic 데이터 조건](https://docs.alpaca.markets/us/docs/about-market-data-api): 무료 실시간 IEX, WS 30종목, 과거 API 200요청/분으로 명시한다. 실제 계정 권한은 별도 확인한다.
- [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq): IEX는 단일 거래소이며 SIP와 다른 거래량/가격을 가진다. 최근 SIP 권한과 무료 IEX를 섞지 않는다.
- [Alpaca Paper Only](https://docs.alpaca.markets/us/docs/paper-trading): 전 세계 paper-only 가입과 IEX 권한을 설명한다. 계정은 데이터 인증용이며 이번 초기 경로는 Alpaca paper 주문을 보내지 않는다.
- [Alpaca stream](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data): minute bars/updatedBars와 늦은 체결의 수정 메시지, 호가 수량 단위를 설명한다.
- [NYSE 공식 시간/휴일](https://www.nyse.com/trade/hours-calendars): 정규장 ET 09:30~16:00과 휴일/조기마감을 확인하는 기준이다.
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars): 거래소 세션/분 캘린더를 제공한다. 라이브러리 결과와 공식 달력 대조 및 버전 고정은 U1의 검증 범위다.
