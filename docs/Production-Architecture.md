# 실전 운용 아키텍처

## 1. 운용 목표와 가정

이 문서는 학습/연구 단계가 끝나고 실제 자금 자동매매 단계로 넘어갈 때 필요한 목표 구조와 안전 기준을 정의한다. 현재 저장소의 기본 운영은 여전히 `paper` 검증이다. 이 문서는 상위 설계 기준이고, 코드 작업 여부와 최신 구현 상태는 `docs/Production-Implementation-Blueprint.md`와 `docs/logbook.md`를 함께 본다.

실제 자금 운용 단계의 목적은 `데이터 수집 -> 특징/예측 -> 신호 -> 리스크 게이트 -> 주문 -> 체결 -> 포지션 -> 회계/감사 -> 장후 리뷰` 흐름을 사람의 승인 아래 점진적으로 실계좌에 연결하는 것이다. 범위는 국내 주식 현물, KIS REST/WebSocket, 장중 자동 주문, 장후 검증, 모니터링, 사고 정지 절차까지다. 제외 범위는 옵션/선물, 야간거래, 신용/대출, 레버리지, 자동 이체, 자동 펀딩, 타 증권사 멀티 브로커 라우팅이다.

이 문서의 표현은 세 단계로 구분한다. `현재 확인`은 현재 코드 또는 기준 문서에서 확인한 사실이다. `제안 신규`는 아직 파일이나 테이블이 없는 목표 구조다. `확인 필요`와 `운영자 결정 필요`는 실전 전환 전까지 확정되지 않은 정책 슬롯이며, safety invariant(항상 참이어야 하는 안전 규칙)로 간주하지 않는다. 본문에서 `운영자`는 Codex나 Claude cowork가 아니라 계좌 소유자 또는 실전 운용 승인권자를 뜻한다.

코드 작업 단위, 상태머신, SQLite 초안, 테스트 slice는 `docs/Production-Implementation-Blueprint.md`를 기준으로 한다. 이 문서는 목표 구조의 상위 기준이고, 구현 청사진 문서는 실제 작업 순서를 다룬다.

현재 흐름과 목표 흐름의 차이는 아래처럼 본다.

| 구분 | 현재 paper / KIS 모의계좌 mirroring | 실전 운용 목표 |
|---|---|---|
| 계좌 | 로컬 가상 계좌와 KIS 모의계좌 | KIS 실전 계좌 |
| 기본 모드 | `TRADING_MODE=paper` | `TRADING_MODE=live`와 별도 실전 enable 승인 필요 |
| 주문 전송 | 로컬 가상 주문, 선택적으로 KIS 모의계좌 제출 | 리스크 게이트 통과 뒤 실전 계좌 주문 제출 |
| 주문 상태 | `paper_orders`, `paper_order_events`, 브로커 모의 상태 snapshot | 실전 주문 전용 상태머신과 미체결 복구 |
| 체결 반영 | 모의 체결 또는 KIS 모의계좌 조회 동기화 | KIS 실전 체결 조회와 내부 원장 대조 |
| 손실 제한 | 시간/스프레드/포지션 수 중심 | 일일 손실, 최대 낙폭, 노출, 슬리피지, kill switch |
| 시장 미시 규칙 | `docs/Market-Schedule-Rules.md`에 시간 규칙, `docs/Universe-Freeze-Policy.md`에 유니버스 제외 원칙이 일부 문서화되어 있다. | 상한가/하한가, 거래정지, 관리/투자유의, VI(변동성완화장치), 동시호가, 주문 타입, T+2, 기업행위까지 주문 전 차단 |
| 감사 추적 | prediction, signal, order가 각각 저장되지만 연결 키 부족 | 모든 실전 주문이 prediction_id, signal_id, rule version, gate decision, model version, 데이터 snapshot id로 추적 가능 |
| 모델 교체 | active model 자동 교체 금지, registry JSON | 승인된 promotion/rollback 트랜잭션과 기동 self-check |
| 운영자 개입 | 모의계좌 정렬, 장후 검토 | phase 전환, 실전 enable, kill switch 해제, 모델 승격 승인, 비상 escalation |

자동 처리 영역은 데이터 수집, 분봉/특징 생성, 예측, 신호 후보 생성, 사전 리스크 평가, 주문 상태 조회, 포지션/체결 정합성 리포트, 대시보드 갱신이다. 운영자 개입이 반드시 필요한 영역은 실전 주문 enable, phase 전환, 일일 손실 한도 재개, 미확인 체결 수동 판정, 모델 승격/롤백 승인, 브로커 장애 장중 재개 판단이다. 운영자가 1명인 전제는 단일 장애점이므로, Phase 1 전에는 대체 승인자 또는 운용 중지 기준을 별도로 정해야 한다.

관련 문서/코드 경로: `AGENTS.md`, `README.md`, `docs/Current-Implementation.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Account-Safety.md`, `docs/Market-Schedule-Rules.md`, `docs/Universe-Freeze-Policy.md`, `docs/Market-Data-Policy.md`, `app/config/settings.py`, `config/strategy.toml`, `config/app.toml`

## 2. 현재 구조 진단

현재 코드는 paper 운용과 KIS 모의계좌 검증에는 사용할 수 있지만, 실전 운용에는 아래 모듈과 상태가 부족하다. 표에서 `확인됨`은 실제 코드 또는 문서에서 확인한 내용이고, `부족`은 실전 전환 전 보강이 필요한 내용이다.

| 점검 항목 | 현재 확인 | 부족한 이유 | 실전 사고 시나리오 |
|---|---|---|---|
| 실전 주문 lifecycle 상태머신 | `app/paper_trading/engine.py`는 `created`, `acknowledged`, `filled` 중심이다. `app/services/broker_paper_sync.py`에는 `submitted`, `pending_lookup`, `open`, `partially_filled`, `filled`, `cancelled`, `cancelled_partial`, `rejected`를 해석하는 상당히 풍부한 모의계좌 기반이 있다. `live_orders`, `live_order_events` 초기 원장은 2026-05-14에 추가됐고, `app/services/live_order_manager.py`는 2026-05-16~17에 live intent/submit/cancel/recovery 상태 전이를 구현했다. | `unknown`/`stuck`의 시간 기반 자동 전이, 실제 KIS live adapter 연결, 사람 호출/알림, live 포지션/포트폴리오 회계 반영은 아직 없다. 기존 모의계좌 상태 해석을 live에 그대로 재사용하지 않고 `app/services/live_execution_sync.py`로 분리했다. | REST 응답은 성공했지만 체결 조회가 누락되어 같은 신호를 재주문할 수 있다. |
| 주문 idempotency(중복 실행 방지) 키와 재시작 복구 | 실시간 ID는 `online-시간-pid-uuid` namespace로 겹침을 줄인다. `paper_orders.order_id`는 기본 키다. `live_orders.idempotency_key`는 unique로 추가됐다. `LiveOrderManager.create_intent()`는 signal/prediction/rule/gate 기반 deterministic key를 생성하고, intent 생성 전 필수 trace field, side, qty, limit price를 검증한다. 주문 manager와 execution sync가 저장하는 broker raw response/output은 KIS redaction helper로 계좌/토큰/key 계열 값을 가린다. 재시작 open 계열 복구는 `unknown`으로 잠근다. | streaming 재시작 흐름과 실제 KIS live 주문/체결 조회 복구에는 아직 연결되지 않았다. `blocked`는 terminal이므로 재시도에는 새 `prediction_id` 또는 `signal_id`가 필요하다. | 네트워크 타임아웃 뒤 재시작하면 주문 성공 여부를 모른 채 새 주문을 낼 수 있다. |
| 일일 손실 한도와 최대 낙폭 kill switch(즉시 정지 장치) | `app/risk/gates.py`에는 시간 게이트와 스프레드 게이트가 있다. | 일일 실현/미실현 손실률, 연속 손실, 계좌 기준 최대 낙폭, 전 종목 청산/신규 차단 장치가 없다. | 모델 오류나 시장 급변 때 하루 손실이 운영자 허용치를 넘어 계속 주문될 수 있다. |
| 종목별/섹터별 노출 한도와 단일 종목 최대 비중 | `config/strategy.toml`에 `max_position_pct=0.08`, `max_open_positions=5`가 있고, `app/portfolio/allocator.py`가 현금 기준 종목당 비중을 계산한다. | 섹터 분류, 총 노출, 동일 테마 집중, 실전 계좌 기존 보유분 포함 한도가 없다. | 같은 섹터 종목이 여러 개 동시에 열려 계좌가 단일 위험에 노출될 수 있다. |
| 슬리피지 budget과 실제 슬리피지 추적 | paper 체결은 `slippage_bps=3.0` 고정 가정으로 계산한다. | 실전 주문 의도 가격, 접수 가격, 평균 체결가, 시장 중간가 기준 실제 슬리피지 추적과 차단 budget이 없다. | 백테스트에서는 수익이지만 실전 체결 비용이 커져 기대값이 음수로 바뀔 수 있다. |
| KIS rate limit, 휴장, 점검, 토큰 만료 대응 | KIS REST rate-limit 재시도와 broker paper 조회 5분 cooldown, `config/market_calendar.toml` 휴장일, KIS token manager가 있다. | 실전 주문 경로의 rate limit budget, KIS 점검 시간표, token refresh 실패 시 주문 중단 규칙은 분리되어 있지 않다. | 주문 취소가 rate limit에 막힌 상태에서 신규 주문이 계속 생성될 수 있다. |
| 실전 enable 플래그 시행 지점 | `app/config/settings.py` 212~218행은 `ALLOW_LIVE_ORDERS=true`이면 `TRADING_MODE=live`여야 한다고 검증한다. `app/brokers/kis_quote_rest.py` 480~527행의 `submit_cash_order`와 544~578행의 `cancel_order`는 profile mode에 따라 live TR을 선택하지만 `allow_live_orders`를 직접 보지 않는다. `app/services/live_order_guard.py`와 `app/brokers/kis_live_order.py`는 별도 순수 guard/wrapper로 시작했다. | 설정 일관성 검증, 주문 매니저 직전 guard, KIS live order adapter 직전 guard 골격은 있다. 아직 streaming/runtime 실제 주문 경로에는 연결하지 않았다. | `live` profile을 직접 만든 코드가 raw `KisRestQuoteClient.submit_cash_order`를 우회 호출하면 위험하므로, 정적 격리 테스트가 허용 경계 밖 주문 함수 등장을 막는다. |
| 실현 손익, 수수료, 세금, 증거금 정합성 | `PaperTradingEngine`은 고정 수수료/세금으로 `paper_fills`를 쓴다. KIS 계좌 조회는 `app/services/kis_account.py`가 처리한다. | 실전 수수료/세금/거래소 비용/정산 지연/증거금/미수 가능성의 브로커 기준 대조가 없다. 세율과 비용 항목은 실전 전 브로커/세무 기준 확인 필요다. | 내부 PnL은 이익인데 KIS 정산 기준으로는 손실이거나 주문 가능 현금이 부족할 수 있다. |
| T+2 결제와 주문 가능 현금 | 모의계좌 reconciliation은 브로커 유효현금을 `총자산 - 주식평가액`으로 본다. | 매도 체결 후 실제 결제와 주문 가능 금액 차이를 상태로 분리하지 않는다. | 매도 체결 직후 내부 현금은 늘었지만 KIS 주문 가능 금액이 부족해 다음 매수가 reject될 수 있다. |
| 상한가/하한가/거래정지/관리종목/투자유의 | `docs/Universe-Freeze-Policy.md`는 관리종목/거래정지 제외 원칙을 둔다. | 당일 거래 가능 여부, 가격 제한, 단일가매매 전환을 주문 전 필터로 강제하는 구현은 확인되지 않았다. | watchlist 종목이 당일 거래정지인데 매일 같은 주문 reject가 누적될 수 있다. |
| 시초가/종가 동시호가와 시간외 단일가 | `config/market_calendar.toml`은 신규 진입 `09:15~15:00`, 강제 정리 `15:20`, 정규장 종료 `15:30`을 둔다. `docs/Market-Schedule-Rules.md`도 `09:00~09:15` 신규 진입 금지를 기록한다. | 동시호가 체결 방식, 09:00~09:05 변동성 폭주 구간, 15:20~15:30 취소/정리 정책, 시간외 단일가 금지의 주문 타입 검증이 없다. | 첫 5분 또는 종가 동시호가에서 슬리피지 가정이 무너져 손실이 집중될 수 있다. |
| VI(변동성완화장치) | 현재 문서/코드에서 VI 발동 상태를 주문 전 필터로 쓰는 경로는 확인되지 않았다. | 동적/정적 VI 발동 시 단일가매매로 전환되는 상태를 market status에 반영하지 않는다. | 주문 제출 직후 VI가 발동되면 주문이 대기/체결 보류/불명확 상태로 남아 unknown이 누적될 수 있다. |
| 주문 타입 정책 | `app/brokers/kis_quote_rest.py`의 `submit_cash_order`는 `order_type` 인자를 받는다. Phase 2 신규 진입 지정가 only, 시장가 기본 금지, 비상 청산 시장가 청산 건별 수동 승인 후보는 결정됐다. | 결정은 문서화됐지만 live order guard와 주문 매니저가 아직 강제하지 않는다. | 시장가 주문은 슬리피지를 크게 만들고, 지정가 주문은 미체결 잔량을 남겨 1일 1주문 정책과 충돌할 수 있다. |
| 기업행위 캘린더 | `docs/Market-Data-Policy.md`는 기업행위와 거래정지를 별도 정책/테이블로 다룬다고 한다. | 권리락, 배당락, 액면분할, 유상증자 캘린더가 실전 gate와 stop/슬리피지 계산에 연결되지 않았다. | 권리락으로 가격이 인위적으로 내려가 stop loss나 일일 손실 한도가 오발동할 수 있다. |
| 부분 체결, 단주, 1일 1주문 제한 | broker paper sync는 부분 체결을 `partially_filled`로 해석한다. `app/services/live_order_manager.py`는 Phase 2 기본값으로 1거래일 1개 부모 주문서, 부모 주문 수량 `max_order_qty=1`, 같은 종목 pending 차단, live fill mismatch 감지 시 신규 intent 차단을 `blocked`로 기록하고, 차단 detail에 부모 주문 현재 수/한도와 수량 현재값/한도 context를 남긴다. `app/services/live_execution_sync.py`는 `live_fills`에 미기록 delta만 멱등 기록하고 `live_orders.filled_qty`와 fill 합계 정합성을 검사한다. | 단주 잔량 자동 취소 시점, 포지션/포트폴리오 반영은 아직 후속이다. | 잔량이 남아 있는 동안 새 신호가 와서 같은 방향 두 번째 주문을 낼 수 있다. |
| kill switch 청산과 슬리피지 게이트 충돌 | kill switch는 목표 정책으로만 있다. | 비상 청산 주문이 슬리피지 budget을 넘을 때 우회/완화/유지 규칙이 없다. | 손실 한도 도달 뒤 시장가 청산이 슬리피지 게이트에 막혀 포지션이 방치될 수 있다. |
| 시스템 시계 오차 | `app/services/system_clock.py`는 local timestamp와 reference timestamp의 차이를 기본 후보 `±2초`로 판정한다. HTTP `Date` 헤더를 reference timestamp와 clock decision으로 바꾸는 순수 helper와 readiness `system_clock` fixture/CLI wrapper 평가가 있다. timezone 없는 header와 알 수 없는 timezone은 invalid로 차단한다. `app/brokers/kis_quote_rest.py`는 마지막 성공 응답 header를 read-only 진단용 copy로 노출하고, `app/brokers/kis_readonly.py`는 read-only client에서 이 header copy를 주문 메서드 없이 노출한다. `app/services/system_clock_probe.py`와 `scripts/probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 raw header 원문 없이 sanitized `system_clock` check JSON을 만들 수 있다. `scripts/probe_kis_clock_reference.sh --compare-paper-live`는 paper/live HTTP `Date` reference를 raw header 없이 비교하는 진단 JSON을 만들 수 있다. `app/services/live_order_manager.py`는 HTTP `Date` 기반 clock decision을 필수 submit guard 입력으로 받아 broker 호출 전 통과/차단할 수 있다. `scripts/run_live_readiness_dry_run.sh`는 `--system-clock-check-path`로 받은 sanitized check JSON을 fixture보다 우선 병합할 수 있다. 2026-05-20 KIS paper 현재가 read-only 조회 1회에서 실제 response header에 `date`가 있음을 확인했고, 2026-05-21 `probe_kis_clock_reference.sh --mode paper` 실행에서 `system_clock=true`, skew 약 0.167초로 readiness dry-run에 병합되는 것을 확인했다. | live account header shape와 paper/live 비교 실행 증적은 아직 남아 있다. | 로컬 시계가 몇 초 이상 어긋나 주문/취소가 거부되거나 stale prediction이 정상처럼 처리될 수 있다. |
| dashboard 외 알림 채널 | 대시보드 상태 카드와 status alert는 있다. 검색 기준으로 전용 email/slack/webhook 알림 모듈은 확인되지 않았다. | 화면을 보지 않는 동안 사고를 전달할 독립 채널과 escalation 정책이 없다. | 장중 실시간 수집 중단이나 unknown order가 발생해도 운영자가 늦게 알 수 있다. |
| 운영자 단일 장애점 | 문서상 승인자와 kill switch 담당자는 아직 역할만 있고 대체자 정책이 없다. | 휴가/병가/외출 시 운용 지속/중지 기준이 없다. | 사고 알림이 1명에게만 가고 응답이 없으면 미체결/포지션 처리가 지연될 수 있다. |
| 운영자 승인 기록 무결성 | 제안 신규 JSON 경로만 있었다. `ops_live_audit_events` hash chain helper는 2026-05-17에 구현됐다. | 승인 이벤트 전체 연결, 외부 anchor, 서명, NAS 복구 검증은 아직 없다. | 사고 후 승인 여부나 한도 변경 시각을 입증하기 어렵다. |
| 감사 로그 | `serving_predictions`, `serving_trade_signals`, `paper_orders`, `paper_order_events`, `ops_risk_events`가 있다. `app/services/live_audit.py`는 live audit event hash chain 생성/검증을 제공한다. | `paper_orders`에 `prediction_id`/`signal_id`가 없고, 실전 주문 manager/체결 sync가 모든 decision을 audit chain에 자동 연결하지는 않았다. rule version과 gate decision snapshot도 분리되어 있다. | 주문 하나가 어떤 모델/신호/게이트 판단에서 나왔는지 사후 설명하지 못한다. |
| paper-vs-live 격차 계산 | paper/live 비교 기준은 목표 문서에만 있다. | 동일 signal이 서로 다른 시점/수량으로 체결될 때 어떤 metric으로 격차를 볼지 정의되지 않았다. | Phase 2 통과 여부를 운영자가 수동 감으로 판단하게 된다. |
| 모델 승격/롤백과 active model 교체 안전성 | active 자동 교체는 정책으로 금지되어 있다. `runtime-data/ml/registry.json`을 `ModelRegistry.save()`가 JSON으로 쓴다. | 현재 위험은 “자동 교체가 실행 중”인 결함이 아니라, 향후 승격 기능을 만들 때 필요한 atomic replace, process 기동 self-check, rollback 로그가 없다는 점이다. | 장후 교체 뒤 새 process가 새 registry를 읽었는지 확인하지 못해 의도와 다른 모델로 장중 운용할 수 있다. |
| 장중 운영축과 장후 연구축 자원 격리 | quick/heavy 분리, snapshot DB 연구 실행, `run_post_close_label_refresh.sh`가 있다. | 장중 DB lock 사고가 기록되어 있고, 실전 주문 중에는 cleanup/heavy 작업 차단이 별도 lock으로 강제되지 않는다. | 장중 cleanup이나 heavy research가 SQLite 잠금을 잡아 실전 주문/체결 동기화가 멈출 수 있다. |

실전 전환용 코드 변경 제안은 아래처럼 기록한다. 이미 구현된 slice의 최신 상태는 `docs/Production-Implementation-Blueprint.md`와 `docs/logbook.md`를 함께 본다.

| 제안 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| 초기 구현 `app/services/live_order_manager.py` | paper engine과 broker paper sync가 주문 흐름을 나눠 가진다. | 실전 주문 제출, 상태 전이, idempotency, 미체결 복구, Phase 2 1일 1부모주문/같은 종목 pending 차단을 한 서비스가 관리한다. 현재 KIS live adapter와 streaming 연결은 하지 않는다. | `app/services/streaming.py`, `app/brokers/kis_quote_rest.py`, SQLite 주문 테이블 | 중복 주문 차단이 과하면 정상 주문도 막힐 수 있다. |
| 제안 신규 `app/risk/live_gates.py` | `app/risk/gates.py`는 시간/스프레드 중심이다. | 일일 손실, 최대 낙폭, 노출, 슬리피지, 운영자 kill switch, 시장 미시 규칙을 별도 게이트로 둔다. | `app/risk/`, `app/services/streaming.py`, dashboard | 기준값 오류가 신규 주문 전체를 차단하거나 과도하게 허용할 수 있다. |
| 초기 구현 `app/services/market_status.py` | 휴장일과 유니버스 제외 원칙은 문서/설정에 흩어져 있다. | 현재는 `MarketStatusSnapshot`을 입력으로 받아 종목별 신규 주문 차단 사유를 계산한다. 당일 거래정지, 상하한가, 관리/투자유의, VI, 동시호가/단일가, 기업행위 데이터 원천 연결은 후속 작업이다. | `app/services/market_status.py`, `app/collectors/`, `app/services/streaming.py`, `app/risk/` | 외부 상태가 stale이면 정상 주문을 막거나 위험 주문을 허용할 수 있다. runtime 연결 전에는 fixture 기반 보장에 한정된다. |
| 초기 구현 `app/services/system_clock.py`, `app/brokers/kis_quote_rest.py`, `app/brokers/kis_readonly.py`, `app/services/system_clock_probe.py`, `scripts/probe_kis_clock_reference.sh`, `app/services/live_order_manager.py` | 시스템 시계 오차 허용 범위가 문서 후보로만 있었다. | local timestamp와 신뢰 reference timestamp를 입력받아 기본 후보 `±2초` 안인지 판정하는 순수 helper를 제공한다. HTTP `Date` 헤더에서 reference timestamp를 파싱하고 clock decision으로 바꿀 수 있으며, timezone 없는 header와 알 수 없는 timezone은 invalid로 차단한다. KIS REST client와 read-only wrapper는 마지막 성공 응답 header copy를 노출한다. `probe_kis_system_clock_check()`와 `probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 raw header 원문 없이 sanitized check JSON을 생성하고, `run_live_readiness_dry_run.sh`는 `--system-clock-check-path`로 받은 check를 fixture보다 우선 병합할 수 있다. KIS paper probe 1회에서 `system_clock=true`, skew 약 0.167초를 확인했다. `LiveOrderGuard.assert_can_submit()`과 `LiveOrderManager.submit_intent()`에는 선택적 `clock_skew_decision` hook이 있으며, caller가 check를 필수로 요구하면 누락 시 submit을 차단한다. HTTP `Date` 기반 decision의 통과/차단 및 wrapper 연결 테스트가 있다. | readiness, 주문 직전 guard 후보 | live account header shape 확인, runtime 자동 호출 여부와 강제 여부는 후속 결정이 필요하다. |
| 초기 구현 `app/services/live_audit.py` | prediction/signal/order가 따로 저장된다. | 실전 주문 감사 이벤트를 append-only hash chain으로 생성/검증한다. `prediction_id`, `signal_id`, `gate_decision_id`, `rule_version`, `model_version`, `data_snapshot_id`, `previous_hash` 같은 필수 추적 필드는 빈 값이면 event build를 거부한다. 현재는 순수 helper와 runtime report read-only 검증이며, 주문 경로 전체 자동 연결과 외부 anchor는 후속이다. | `app/storage/`, `runtime-data/ops/`, `app/services/reporting.py` | 저장 실패 시 주문 차단 정책을 강하게 잡으면 가용성이 낮아질 수 있다. |
| 초기 구현 `app/services/live_alerting.py` | dashboard 안에서만 상태를 본다. | 사고 등급별 로컬 파일 outbox를 만들고 텔레그램/이메일 발송 대상 메시지를 분리한다. 같은 event type/trading day/state fingerprint의 동일 alert는 같은 날짜 outbox에 중복 기록하지 않는다. `unknown/stuck` attention payload는 선택적 grace window 안이면 alert 생성을 미룰 수 있다. outbox JSONL의 `detail_json`은 저장 직전에 KIS redaction helper로 계좌/토큰/app secret 계열 key를 가린다. 실제 외부 발송기는 비밀값과 네트워크 의존성을 갖기 때문에 후속 승인 뒤 별도 연결한다. | `runtime-data/reports/alerts/`, `app/services/reporting.py`, dashboard, 운영 스크립트 | 실제 외부 sender가 붙기 전까지는 운영자가 파일 또는 dashboard를 확인해야 한다. message/title 같은 자유 텍스트 redaction은 후속이다. raw minute lag 같은 연속 조건 기반 hysteresis는 후속이다. |
| 제안 신규 `app/models/deployment.py` | registry JSON을 직접 읽고 쓴다. | active model 교체를 검증, 백업, atomic replace, rollback 로그, 기동 self-check로 감싼다. | `app/models/registry.py`, `runtime-data/ml/registry.json` | 기존 테스트와 수동 baseline 설정 명령의 동작 차이가 생길 수 있다. |

관련 문서/코드 경로: `docs/Order-Lifecycle.md`, `docs/Portfolio-And-Reconciliation.md`, `docs/Machine-Learning-Operations.md`, `docs/Market-Schedule-Rules.md`, `docs/Universe-Freeze-Policy.md`, `docs/Market-Data-Policy.md`, `app/risk/gates.py`, `app/services/streaming.py`, `app/services/broker_paper.py`, `app/services/broker_paper_sync.py`, `app/brokers/kis_quote_rest.py`, `app/storage/sqlite_store.py`, `app/storage/contracts.py`, `app/models/registry.py`

## 3. 목표 구조

목표 레이어는 아래 순서를 따른다.

| 레이어 | 책임 | 입력 | 출력 | 실패 시 fallback |
|---|---|---|---|---|
| 데이터 수집 | KIS 체결/호가, 계좌/주문 조회, 휴장/장상태 반영 | KIS WebSocket/REST, `config/watchlist.txt`, `config/market_calendar.toml` | raw tick, raw orderbook, account snapshot | 수집 지연이면 신규 주문 차단, dashboard/알림 |
| 시장 상태 필터 | 당일 거래 가능 여부, 상하한가, VI, 동시호가, 거래정지, 관리/투자유의, 기업행위 반영 | KIS/거래소 상태 데이터 후보, 운영자 calendar | market status snapshot | 상태가 없거나 stale이면 해당 종목 신규 주문 차단 |
| 특징/예측 | 분봉, feature, active model 추론 | raw data, `runtime-data/ml/registry.json`, market status snapshot | feature snapshot, prediction | 모델 로딩 실패 시 신규 주문 차단. baseline fallback은 paper에서만 허용, live는 운영자 승인 필요 |
| 신호 | 예측을 매수/매도 의도로 변환 | prediction, orderbook, strategy config | signal | confidence 부족, 장시간 외, 매도-only raw signal은 주문 차단 |
| 리스크 게이트 | hard limit와 운영 상태 판단 | signal, 계좌, 포지션, 손실, 노출, 슬리피지, kill switch, 시장 상태 | gate decision | 하나라도 hard fail이면 신규 주문 차단. 보호성 취소/청산은 별도 정책 적용 |
| 주문 매니저 | idempotency, 주문 상태머신, 주문 타입 정책, 재시작 복구 | approved signal, target position, gate decision | live order intent, order event | 제출 결과 불명확하면 `unknown`으로 신규 차단, 조회/취소, 사람 호출 |
| 브로커 어댑터 | KIS REST 주문/취소/조회 실행 | order intent | broker order id, fill snapshot | rate limit/토큰/점검 시 신규 차단, 미체결 보존 |
| 체결/포지션 | 체결 반영, 수수료/세금/현금/보유 계산 | broker fills, account snapshot | position, portfolio snapshot, PnL | 내부/브로커 불일치면 신규 차단, reconciliation |
| 리포트 | dashboard, runtime report, 일일 정합성 | SQLite, JSON state, reports | HTML/JSON/Markdown report | stale 표시, 알림, 사람 확인 요청 |

새로 만들어야 하는 모듈은 제안 신규로만 적는다.

- 초기 구현 `app/services/live_order_manager.py`: 실전 주문 상태머신, idempotency key, 미체결 복구, guard 차단 `blocked`, broker protocol 주입형 submit/cancel, Phase 2 1거래일 1개 부모 주문서/기본 `max_order_qty=1`/같은 종목 pending/live fill mismatch 신규 intent 차단, Phase 2 부모 주문 금액 한도 차단.
- 초기 구현 `app/services/live_execution_sync.py`: 실전 체결 조회 record를 live order 상태와 fill delta로 해석한다. 기존 `app/services/broker_paper_sync.py`의 아이디어를 실전 계좌용으로 분리하고, `live_fills` delta 멱등 기록까지 구현했다. 실제 KIS live 조회 연결과 포지션/포트폴리오 반영은 후속이다.
- 초기 구현 `app/services/market_status.py`: 당일 거래정지/상하한가/VI/동시호가/기업행위 상태를 주문 전 필터에 제공하기 위한 순수 판정 로직이다. `LiveOrderGuard.assert_can_submit()`은 `MarketStatusDecision`을 입력으로 받아 차단 사유를 반영한다. 데이터 원천은 확인 필요다. 후보는 KIS REST, 한국거래소 OpenAPI, 운영자 수동 calendar다. streaming과 실제 market status snapshot 생성 연결은 후속 작업이다.
- 초기 구현 `app/services/live_kill_switch.py`, `scripts/set_live_kill_switch.sh`: `runtime-data/reports/live-risk/kill-switch.json` 후보 파일을 fail-closed로 읽고 atomic write로 저장한다. missing/broken/stale 상태는 신규 submit 차단, cancel-only 허용 후보로 처리한다. CLI는 기본 status/dry-run이며 실제 ON/OFF 기록은 `--apply`가 필요하고 OFF 해제는 `--confirm-disable`을 요구한다.
- 초기 구현 `app/services/system_clock.py`, `app/services/system_clock_probe.py`, `scripts/probe_kis_clock_reference.sh`: local timestamp와 reference timestamp 차이가 기본 후보 `±2초` 안인지 판정한다. read-only 현재가 조회 1회에서 받은 HTTP `Date` header를 raw 원문 없이 sanitized `system_clock` check JSON으로 만들 수 있고, `run_live_readiness_dry_run.sh --system-clock-check-path`로 readiness에 연결할 수 있다. `--compare-paper-live`는 paper/live HTTP `Date` reference를 sanitized JSON으로 비교한다. 2026-05-21 KIS paper probe 1회에서 `system_clock=true`, skew 약 0.167초를 확인했다. `app/services/live_order_guard.py`에는 선택적 submit guard hook이 있어 clock decision이 차단이면 submit을 막을 수 있고, caller가 필수 check로 요구하면 누락도 차단한다. live account probe 실행과 기본 강제 정책은 후속이다.
- 초기 구현 `app/services/live_order_guard.py`: live submit/cancel 직전 순수 가드다. `TRADING_MODE`, `ALLOW_LIVE_ORDERS`, live profile, phase approval, 지정가 주문, kill switch, market status decision을 확인한다. `app/services/live_order_manager.py`의 첫 caller로 연결됐지만 아직 streaming runtime 경로에는 연결하지 않았다.
- 초기 구현 `app/brokers/kis_live_order.py`: 이미 생성된 KIS client를 감싼다. `submit_cash_order` 위임 직전에는 `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=true`, live profile을 재검증하고, 보호성 `cancel_order` 위임 직전에는 `TRADING_MODE=live`와 live profile을 재검증한다. import나 생성만으로 KIS 네트워크를 호출하지 않는다. 실제 runtime 연결은 후속이다.
- 초기 구현 `app/services/live_phase_readiness.py`, `app/services/dashboard.py`: phase approval hash와 readiness run record를 생성하고, dashboard live readiness 카드에 WS recovery evidence type/실제 증거 여부/freshness/stable frame/reconnect storm을 read-only로 표시한다. active approval 운영 절차는 후속이다.
- 초기 구현 `app/services/live_order_manager.py`: live 주문 intent, deterministic idempotency key, 상태 전이, guard 차단 기록, broker 제출/취소 interface 주입, broker 예외 시 `unknown`, 재시작 복구 시 open 계열 `unknown` 잠금, Phase 2 live fill mismatch 신규 intent 차단, 부모 주문 수량 기본 `max_order_qty=1`, 부모 주문 금액 한도 `min(100,000원, 운용 배정금의 10%)` 차단을 제공한다. 운용 배정금이 전달되지 않으면 100,000원을 기본 한도로 쓴다. 실제 KIS live adapter와 체결 sync 연결은 후속이다.
- 초기 구현 `app/services/live_order_monitoring.py`: 거래일 단위 live order를 read-only로 훑어 `unknown`/`stuck` 주문 수, 열린 주문 수, 최장 미확인 경과 시간을 계산한다. 이 helper는 주문 전이, 취소, 브로커 조회를 수행하지 않는다.
- 초기 구현 `app/services/live_position_accounting.py`: 기록된 `live_fills`만 입력으로 받아 장부상 long-only 평균단가 포지션을 순수 계산한다. buy/sell로 해석되지 않는 fill side는 조용히 반영하지 않고 `invalid_side_count`로 기록한다. 자동 포지션 저장, 브로커 잔고 reconcile, portfolio snapshot, 세금/결제 반영은 후속이다.
- 초기 구현 `app/services/live_execution_sync.py`: KIS daily order/fill record를 live 상태와 delta fill로 해석하고, `live_orders` 상태/수량, `live_order_events`, `live_fills` delta 기록까지 반영한다. `tests/test_kis_http_clients.py`는 대체 필드명과 KIS 연속 조회(`tr_cont=M`) fixture를 잠근다. 실제 KIS 조회 호출과 포지션/포트폴리오/세금 정산 적용은 후속이다.
- 초기 구현 `app/services/codex_ops.py`, `app/services/kis_token_probe.py`, `app/services/kis_account_probe.py`, `app/services/kis_ws_recovery_probe.py`, `app/services/market_status_probe.py`, `app/services/live_readiness_fixture.py`, `scripts/run_codex_ops_job.sh`, `scripts/run_live_readiness_dry_run.sh`, `scripts/probe_kis_clock_reference.sh`, `scripts/probe_kis_token_refresh.sh`, `scripts/probe_kis_account_snapshot.sh`, `scripts/probe_kis_ws_recovery.sh`, `scripts/probe_market_status_snapshot.sh`, `scripts/build_live_readiness_fixture_snapshot.sh`: Codex CLI 운영 job manifest와 장 상태별 권한 모델을 순수 함수로 판정하고, `premarket-readiness` dry-run report와 10개 check(`token_refresh`, `ws_recovery`, `account_snapshot`, `market_status`, `system_clock`, `kill_switch`, `database`, `disk_space`, `dashboard`, `storage_migration_state`) 기반 live readiness dry-run report를 생성한다. `database` check는 SQLite read-only smoke로 보고, `storage_migration_state`는 schema 적용 상태로 분리한다. `token_refresh` check는 KIS auth-only probe로 token 원문 없이 생성한 sanitized JSON이 있을 때만 통과 후보가 된다. `account_snapshot` check는 read-only 계좌 snapshot 조회 결과를 계좌번호 없이 생성한 sanitized JSON이 있고 필수 shape와 값 타입이 맞을 때만 통과 후보가 된다. `ws_recovery` check는 현재 synthetic/offline fault injection 증거이며 실제 KIS WebSocket 네트워크 복구 관측은 Phase 1 진입 뒤 별도 수집한다. `market_status` check는 repo 내부 수동 snapshot을 `app/services/market_status.py`의 순수 판정 로직으로 평가한 sanitized JSON이 있을 때만 통과 후보가 된다. KIS/거래소 자동 원천은 아직 연결하지 않는다. `system_clock` check는 fixture/dry-run 또는 read-only KIS quote probe로 생성한 sanitized check JSON이 있을 때만 통과 후보가 된다. local fixture snapshot wrapper는 premarket report, token refresh check, account snapshot check, synthetic WS recovery check, market status check, system clock check, kill switch 상태 파일을 읽어 로컬로 증명 가능한 항목만 fixture로 묶고, market status check 파일이 없으면 통과시키지 않는다. 기본 실행은 JSON only이고, SQLite 기록은 `--record --database-path <repo 내부 경로>`를 명시한 경우에만 시도한다. 실제 Codex CLI 호출과 실제 장애 주입은 후속이다.
- 2026-05-22 보강 `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py`, `app/services/live_order_manager.py`, `app/services/kis_account_probe.py`: `account_snapshot`은 `position_row_count`, `summary_row_count`, `cash_balance`, `stock_evaluation_amount`, `total_asset_amount` shape가 모두 있어야 통과 후보가 된다. Phase 2/3 readiness와 live submit guard는 synthetic `ws_recovery`를 실전 제출 증거로 쓰지 못하게 막고, 실제 KIS WebSocket 관측 evidence type이 없으면 broker 호출 전에 `ws_recovery_real_evidence_required`로 차단한다.
- 2026-05-23 보강 `app/services/ws_recovery_evidence.py`, `app/services/live_phase_readiness.py`: 실제 KIS WebSocket 관측 evidence type을 단일 모듈에서 정의한다. timestamp가 있는 readiness 증거는 key별 freshness 기준을 넘으면 `stale_evidence`로 차단한다. 현재 기준은 `system_clock/ws_recovery=30분`, `account_snapshot/market_status=1시간`, `token_refresh=4시간`이다. HTTP `Date` 기반 `system_clock` skew는 초 단위 header 한계 때문에 밀리초 정밀도가 아니라 대략 1초 이내 여부를 보는 증거다.
- 2026-05-23 보강 `docs/Manual-Market-Status-Runbook.md`, `app/services/market_status_probe.py`: 자동 market status 원천 전 수동 snapshot 절차를 분리했고, 수동 snapshot `source`를 `manual_operator_snapshot`, `manual_krx_snapshot`, `manual_kis_snapshot` 세 값으로 제한한다. 자유 문자열 source는 readiness 증거로 인정하지 않는다. `symbol_set_hash`는 sorted symbol list의 SHA-256 prefix로 결정적으로 계산하며, mismatch면 snapshot을 차단한다.
- 초기 dashboard/report 연결: `app/services/dashboard.py`는 `premarket-readiness`와 `live-readiness` JSON report를 read-only로 읽어 `상태 및 설정` 탭의 `실전 전환 readiness dry-run` 카드에 표시한다. 또한 `live_orders.filled_qty`와 `SUM(live_fills.fill_qty)` 정합성, `unknown`/`stuck` 미해결 주문 요약, Phase 2 부모 주문 한도 사용량을 `실 운용계좌` 탭의 read-only 카드와 상단 status alert로 표시한다. `app/services/reporting.py`도 같은 정합성/미해결 주문 요약과 Phase 2 부모 주문 한도를 runtime report JSON/Markdown에 기록하고, mismatch/attention이 있으면 `runtime-data/reports/alerts/` 아래 로컬/텔레그램/이메일 outbox를 만든다. 운영 DB insert, 실전 주문, 포지션/회계 반영, 실제 외부 발송에는 연결하지 않는다.
- 제안 신규 `app/risk/live_gates.py`: 일일 손실, 최대 낙폭, 노출, 슬리피지, 시장 상태, 운영자 kill switch. `app/risk/` 변경은 운영자 승인 필요.
- 초기 구현 `app/services/live_audit.py`: prediction/signal/gate/order/fill 연결을 append-only hash chain 감사 이벤트로 생성/검증한다. 필수 추적 필드가 빈 값이면 event build를 거부한다. 현재는 RuntimeWriter/SQLite 기반 helper와 runtime report integrity 요약까지이며, 주문 경로 전체 자동 연결과 외부 anchor는 후속이다.
- 초기 구현 `app/services/live_alerting.py`: dashboard 밖 알림을 위한 로컬/텔레그램/이메일 outbox와 routing 정책. 동일 state fingerprint alert의 같은 날짜 중복 outbox append는 억제하고, `unknown/stuck` attention payload에 `attention_grace_minutes`가 있으면 grace window 안의 신규 attention alert는 만들지 않는다. outbox JSONL의 `detail_json`은 저장 직전에 KIS redaction helper로 가린다. 실제 외부 발송 sender는 후속.
- 초기 구현 `scripts/export_kis_paper_fixture_candidates.py`: 현재 `runtime-data/dev.db`의 broker paper 주문 제출/상태 snapshot table을 SQLite read-only URI로 열고, KIS 모의투자 raw 응답 후보를 민감정보 제거 후 `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json`에 저장한다. export 결과에는 `redaction_ok`와 `redaction_findings` 요약을 함께 남긴다. KIS live/paper API를 새로 호출하지 않는다.
- 제안 신규 `app/models/deployment.py`: active model 교체/롤백 트랜잭션과 첫 기동 self-check.

기존 모듈에서 분리해야 하는 책임은 아래와 같다.

- `app/services/streaming.py`: 실시간 데이터 처리와 paper 주문 실행이 함께 있다. 실전 전환 시 신호 생성까지만 담당하고, 주문은 주문 매니저로 넘긴다.
- `app/risk/gates.py`: 현재 시간/스프레드 게이트는 유지하되, 실전 계좌 손실/노출/시장 상태 hard limit은 별도 live 게이트로 둔다.
- `app/paper_trading/engine.py`: 모의 체결 계산은 계속 paper 전용으로 남긴다. 실전 체결은 브로커 조회 기반으로만 반영한다.
- `app/models/registry.py`: 단순 JSON 저장은 유지하되, 실전 교체는 deployment 서비스가 검증/백업/atomic replace/self-check를 감싼다.

상태 저장 위치는 아래처럼 둔다.

| 상태 | 현재/목표 저장 위치 |
|---|---|
| raw/curated/feature/label | 현재 SQLite `runtime-data/dev.db`의 `raw_market_ticks`, `raw_orderbook_ticks`, `curated_minute_bars`, `feature_model_inputs`, `feature_labels` |
| 시장 상태 snapshot | 현재 SQLite `market_status_snapshots` 초기 테이블. `corporate_action_events`, `volatility_interruption_events` 분리 여부는 확인 필요 |
| 예측/신호/목표 포지션 | 현재 SQLite `serving_predictions`, `serving_trade_signals`, `serving_target_positions` |
| paper 주문/체결/포지션 | 현재 SQLite `paper_orders`, `paper_order_events`, `paper_fills`, `paper_positions`, `paper_portfolio_snapshots` |
| KIS 모의계좌 제출/상태 | 현재 SQLite `broker_paper_order_submissions`, `broker_paper_order_status_snapshots`; JSONL `runtime-data/broker/` |
| 실전 주문/체결/포지션 원장 | 현재 SQLite `live_orders`, `live_order_events`, `live_fills`, `live_positions`, `live_portfolio_snapshots` 초기 테이블, `app/services/live_order_manager.py`의 주문 intent/상태 전이/Phase 2 pre-submit 정책, `app/services/live_execution_sync.py`의 상태/delta fill mapper와 `live_orders` 상태 반영 및 `live_fills` delta 멱등 기록 함수가 있다. 아직 streaming과 KIS live adapter, 포지션/포트폴리오 반영에는 연결되지는 않았다. |
| 실전 감사/승인/readiness 로그 | 현재 SQLite `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs` 초기 테이블과 JSONL writer 후보, `app/services/live_phase_readiness.py` approval/readiness record 생성, `app/services/live_audit.py` append-only hash chain 생성/검증, runtime report audit integrity 요약이 있다. 운영 승인 전체 절차와 외부 anchor는 후속 구현 필요 |
| kill switch 상태 | 초기 구현 `app/services/live_kill_switch.py`의 기본 후보 경로 `runtime-data/reports/live-risk/kill-switch.json`; `scripts/set_live_kill_switch.sh`는 status/dry-run 기본, `--apply` 명시 시 atomic write |
| 알림 상태 | 초기 구현 `app/services/live_alerting.py`와 `runtime-data/reports/alerts/{local,telegram,email}/alerts-YYYY-MM-DD.jsonl` outbox. 실제 텔레그램/이메일 발송기는 아직 연결하지 않는다. |
| 운영자 승인 기록 | 제안 신규 `runtime-data/reports/live-approvals/`; append-only/해시 체인/서명 방식은 확인 필요 |
| active model | 현재 `runtime-data/ml/registry.json`; 목표는 atomic replace와 제안 신규 backup `runtime-data/ml/registry-backups/` |
| 장후/대시보드 상태 | 현재 `runtime-data/reports/ml-maintenance/state/`, `runtime-data/reports/dashboard/`, `runtime-data/reports/recovery/` |

신호에서 체결까지의 목표 시퀀스는 아래와 같다.

```text
KIS raw tick/orderbook
-> minute bar
-> market status snapshot
-> feature snapshot
-> active model prediction(prediction_id)
-> signal(signal_id, prediction_id)
-> target position(target_id, signal_id)
-> live risk gates(gate_decision_id, rule_version)
-> order type policy 지정가/시장가 판단
-> idempotency key 생성
-> live order manager submit
-> KIS broker adapter
-> accepted/open/partial/filled/cancelled/rejected/unknown/stuck 상태 저장
-> fill sync
-> live position/accounting snapshot
-> reconciliation report
-> dashboard/alert/audit archive
```

관련 문서/코드 경로: `README.md`, `docs/Architecture.md`, `docs/Signal-Policy.md`, `docs/Market-Schedule-Rules.md`, `app/services/streaming.py`, `app/storage/sqlite_store.py`, `runtime-data/reports/`, `runtime-data/ml/registry.json`

## 4. 안전 invariants와 정책 슬롯

invariant(항상 참이어야 하는 안전 규칙)는 실전 코드보다 먼저 확정되어야 한다. 이 절은 `현재 코드로 확인된 안전 사실`, `구현되면 invariant가 되어야 하는 후보`, `값이 필요한 정책 슬롯`을 분리한다. 값이 아직 없는 정책은 invariant가 아니라 `운영자 결정 대기 슬롯`이다.

현재 코드로 확인된 안전 사실은 아래뿐이다.

| 항목 | 현재 확인 | 해석 |
|---|---|---|
| 기본 모드 | `app/config/settings.py` 212행은 기본 `TRADING_MODE`를 `paper`로 읽는다. | 기본 실행은 paper다. |
| 설정 일관성 | `app/config/settings.py` 216~218행은 `ALLOW_LIVE_ORDERS=true`가 `TRADING_MODE=live`가 아닐 때 오류를 낸다. | `ALLOW_LIVE_ORDERS=true`를 paper와 함께 쓰는 오설정은 막는다. |
| paper mirror 경로 | `app/services/broker_paper.py` 37~43행은 `trading_mode == "paper"`이고 paper profile이 준비되어야 mirroring을 켠다. | 현재 실시간 주문 연동은 모의계좌 경로에 묶여 있다. |
| KIS 주문 함수 | `app/brokers/kis_quote_rest.py` 480~527행, 544~578행은 profile mode가 `live`면 live TR을 선택한다. | 이 함수 자체는 `allow_live_orders`를 직접 확인하지 않는다. 실전 전환 전 P0로 보강해야 한다. |
| Phase 1 read-only wrapper | `app/brokers/kis_readonly.py`는 조회 메서드만 노출하고 `submit_cash_order`, `cancel_order`를 만들지 않는다. | 실전 계좌 조회 전용 구조적 차단의 첫 구현이다. 아직 runtime flow에 연결되지는 않았다. |
| live order guard | `app/services/live_order_guard.py`는 submit 전 `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=true`, live profile, phase approval, 지정가 주문, kill switch, market status decision을 확인한다. `app/brokers/kis_live_order.py`는 KIS client 위임 직전 submit enable/profile을 다시 확인하고, cancel은 live/profile만 확인해 보호성 취소 정책과 충돌하지 않게 한다. | `app/services/live_order_manager.py`의 submit/cancel 경로와 KIS adapter wrapper 골격에 연결됐다. streaming runtime에는 아직 연결되지는 않았다. |

따라서 최상위 live-order invariant는 아직 완전 구현 상태로 쓰면 안 된다. 실전 주문은 `TRADING_MODE=live`와 `ALLOW_LIVE_ORDERS=true`가 동시에 명시되고, 주문 매니저와 브로커 어댑터 호출 직전에서 다시 검증될 때만 허용한다. 이중 잠금은 두 책임 경계로 나눈다. 1층은 Phase 1 read-only client가 주문 메서드를 노출하지 않는 구조적 차단이다. 2층은 Phase 2 이후 live order manager와 KIS 어댑터 호출 직전의 `ALLOW_LIVE_ORDERS` 재검증이다. 2026-05-15 기준 1층은 `app/brokers/kis_readonly.py`로 시작했고, 2026-05-18 기준 2층은 `app/services/live_order_guard.py`와 `app/brokers/kis_live_order.py`의 순수 wrapper로 시작했다. 아직 streaming runtime에는 연결되지 않았다.

구현되면 값 없이도 invariant가 되어야 하는 후보는 아래다.

| 우선순위 | invariant 후보 | 현재 상태 | 기본 동작 후보 |
|---:|---|---|---|
| 1 | Phase 1 read-only에서는 주문 메서드가 구조적으로 호출 불가해야 한다. | wrapper 구현, runtime 연결 전 | 별도 read-only client 유지 |
| 2 | 운영자 kill switch가 켜져 있으면 신규 위험 증가 주문은 나가지 않는다. | 순수 가드 구현, 주문 경로 연결 전 | 신규 주문 차단, 보호성 취소는 별도 cancel-only 경로 후보 |
| 3 | `TRADING_MODE=live`와 `ALLOW_LIVE_ORDERS=true`가 모두 없으면 실전 주문은 나가지 않는다. | 설정 검증, read-only wrapper, live order guard, KIS live order adapter wrapper 존재. streaming runtime 연결 전 | 주문 매니저와 KIS 어댑터 직전에서 재검증 |
| 4 | market status가 거래정지, VI, 관리/투자유의, stale이면 해당 종목 신규 주문은 나가지 않는다. | 순수 market status decision 구현, 주문 경로 연결 전 | 해당 종목 신규 주문 차단, 사람 확인 |
| 5 | Phase 2 기본 주문 타입은 지정가만 허용한다. 시장가는 비상 청산 후보로만 별도 승인한다. | 결정 완료, 순수 guard 구현 | 신규 진입 시장가 차단 |
| 6 | Phase 2에서는 1거래일 1개 부모 주문서와 같은 종목 pending 차단을 기본으로 한다. | `app/services/live_order_manager.py` pre-submit `blocked` 정책 구현, runtime 연결 전 | broker 호출 없이 `blocked` 기록 |
| 7 | Phase 2 부모 주문 수량은 기본 1주를 넘지 않는다. | `app/services/live_order_manager.py` pre-submit `blocked` 정책 구현, runtime 연결 전 | broker 호출 없이 `blocked` 기록 |
| 8 | Phase 2 부모 주문 금액은 승인된 한도 안이어야 한다. | `app/services/live_order_manager.py` pre-submit `blocked` 정책 구현, runtime 연결 전 | broker 호출 없이 `blocked` 기록 |

확정했거나 확정해야 할 수치 정책 슬롯은 아래다. 값이 없는 슬롯은 아직 invariant가 아니다.

| 우선순위 | 정책 슬롯 | 현재 상태 | 기본 동작 후보 |
|---:|---|---|---|
| 1 | Phase 2 일일 손실 | 결정 완료: 보수 모드 `min(A의 1%, 30,000원)`, 기본 모드 `min(A의 2%, 50,000원)` | 신규 주문 차단. 전 종목 자동 청산 여부는 별도 결정 |
| 2 | Phase 2 부모 주문 금액 | 결정 완료: `min(100,000원, 운용 배정금의 10%)`. 운용 배정금이 없으면 100,000원 | 부모 주문 intent를 `blocked` 처리 |
| 2-1 | Phase 2 부모 주문 수량 | 결정 완료: 기본 `max_order_qty=1`. `order_policy.max_order_qty` 또는 `max_qty` 명시 시 후속 phase에서 조정 가능 | 부모 주문 intent를 `blocked` 처리 |
| 3 | 최대 낙폭 `-Z%` | 운영자 결정 필요 | 다음 거래일까지 신규 주문 차단 |
| 4 | 단일 종목 최대 비중 `A%` | 운영자 결정 필요 | 해당 종목 신규/추가 매수 차단 |
| 5 | 섹터/테마 총 노출 `B%` | 운영자 결정 필요 | 같은 섹터 신규 진입 차단 |
| 6 | Phase 2 종목별 손실 | 결정 완료: 보수 모드 `min(A의 0.5%, 20,000원)`, 기본 모드 `min(A의 1%, 30,000원)` | 해당 종목 신규 주문 차단 |
| 7 | 실제 슬리피지 budget | 결정 완료: warning 10 bps, hard 20 bps, 호가단위 반영은 `max(1 tick, 10 bps)`와 `max(2 ticks, 20 bps)` | 해당 종목 또는 전체 전략 신규 주문 차단 |
| 8 | 시스템 시계 오차 허용 범위 | 순수 helper 구현: 기본 후보 `±2초`. HTTP `Date` 헤더 parser/decision helper, readiness fixture/CLI wrapper 평가, sanitized readiness check result helper, KIS REST 마지막 성공 응답 header 노출, live order manager submit guard 주입 테스트는 구현됐고, runtime caller/readiness 자동 연결은 확인 필요 | 허용 범위 밖이면 신규 주문/취소 제출 전 차단하고 사람 호출 |

게이트 우선순위는 `운영자 kill switch > 실전 enable 플래그 > 시장/휴장/점검/거래정지 > 일일 손실/최대 낙폭 > 미확인 주문/체결 > 계좌 현금/증거금/T+2 주문가능금액 > 종목/섹터 노출 > 슬리피지 > 모델 신뢰도 > 시간/스프레드` 순서다.

무효 상태의 기본 동작은 아래처럼 안전 측으로 둔다.

- orphan order: 내부 주문이 없는데 브로커 주문이 있으면 신규 주문 차단, 브로커 조회/취소 후보 등록, 운영자 확인.
- unknown fill: 체결 수량/가격을 확인할 수 없으면 내부 포지션을 보수적으로 잠그고 신규 주문 차단.
- stale prediction: 예측 생성 시각이 허용 지연을 넘으면 신호 폐기.
- stale account snapshot: 계좌 snapshot이 오래되면 신규 주문 차단.
- stale market status: 거래정지/상하한가/기업행위 상태가 오래되면 해당 종목 신규 주문 차단.
- DB lock: 주문 제출 전이면 주문 중단, 제출 후면 `unknown`으로 복구 루틴 진입.

`ALLOW_LIVE_ORDERS=false`는 현재 권장 의미상 신규 위험 증가 submit을 막는 플래그로 둔다. 미체결 취소는 위험 증가가 아니라 보호성 정리일 수 있으므로 `app/services/live_order_guard.py`의 cancel-only 경로에서는 이 플래그를 직접 보지 않는다. 이 cancel-only 정책은 아직 주문 매니저에 연결되지 않은 후보이며, 자동 cancel과 명시적 승인 cancel의 분리는 Slice 5에서 다시 잠근다.

kill switch가 켜진 뒤의 취소 요청과 청산 요청은 신규 위험을 늘리는 주문과 분리한다. 미체결 취소는 보호성 동작으로 보고 별도 `cancel-only` 경로 후보를 둔다. 비상 청산은 슬리피지 budget을 초과할 수 있으므로 일반 신규 진입 슬리피지 게이트가 자동으로 막지 않게 별도 `protective liquidation` 정책을 둔다. 이 정책의 자동 청산 허용 여부는 운영자 결정 필요다.

관련 문서/코드 경로: `AGENTS.md`, `docs/Account-Safety.md`, `app/config/settings.py`, `app/brokers/kis_quote_rest.py`, `app/services/broker_paper.py`, `app/risk/gates.py`, `config/strategy.toml`, `config/market_calendar.toml`

## 5. 단계적 전환 경로

Phase 0은 현재 상태다. 로컬 가상 계좌와 KIS 모의계좌 mirroring을 유지하고, 실전 계좌 주문은 하지 않는다.

| Phase | 목표 | 진입 조건 | 통과 기준 | 사람 승인 |
|---|---|---|---|---|
| Phase 0: 현재 paper + KIS 모의계좌 mirroring | paper 전략과 KIS 모의계좌 정합성 유지 | `check_local_setup` ok, KIS paper 자격정보 준비, dashboard/watchdog 정상 | 최소 10거래일 paper-vs-broker 정합성. 누적 자동 집계는 제안 신규이며 현재 구현 여부 확인 필요, 미확인 주문 0건, label 닫힘 확인 | 현재 유지 승인 |
| Phase 1: 실전 계좌 read-only 연결 | 실전 계좌 조회만 연결, 주문 금지 | 실전 자격정보 준비, read-only client가 기본 후보, 주문 메서드 hard fail, `ALLOW_LIVE_ORDERS=false`, live account balance 조회 가능 | 5거래일 이상 조회 성공, token refresh 정상 관측 또는 fault injection 1회, WS drop은 발생 시 정상 복구 관측 또는 fault injection 1회, 계좌 snapshot stale 알림 강제 테스트 1회. 주문 함수가 호출되면 통과 실패가 아니라 P0 버그 | 실전 조회 연결 승인 |
| Phase 2: 실전 1종목 소액 / 1일 1부모주문 옵저버 모드 | 1종목, 소액, 1일 1개 부모 주문서 제한, 기본 지정가 주문 | Phase 1 통과, live order manager와 kill switch 테스트 통과, VI/주문 타입 정책 확정, live fill mismatch 0건, 모델 성능 선행 게이트 통과, 운영자 당일 승인 | 최소 20거래일 이상, unknown/stuck 0건, 부분 체결 잔량 처리 정상, 실제 슬리피지 허용 범위 내, paper-vs-live 격차 한도 내, 상승/하락/고변동 후보일 포함 또는 미포함 사유 기록 | 매일 장전 승인 또는 자동 갱신 조건 승인, 당일 종료 리뷰 승인 |
| Phase 3: 실전 다종목 일일 한도 운용 | watchlist 일부 또는 전체를 일일 한도 안에서 운용 | Phase 2 통과, 종목/섹터 노출 한도와 알림 채널 검증 | 최소 60거래일 누적 관측. 미충족 시 Phase 2 유지 또는 한도 감액 조건으로만 제한 확대 검토, 장애 대응 정상, 일일 손실 한도 미발동 또는 정상 차단, 정합성 리포트 mismatch 0 | phase 승격 승인, 한도 변경 승인 |

Phase 2의 `1일 1주문`은 “부모 주문서 1건”을 뜻한다. 부분 체결로 잔량이 남아 있으면 같은 종목 신규 주문은 막고, live order/fill 수량 불일치가 있으면 신규 주문 intent도 막는다. 잔량 취소/정정은 보호성 절차로만 허용한다. 2026-05-17 기준 이 정책은 `app/services/live_order_manager.py`에서 pre-submit `blocked` 전이로 구현됐다. 완전 체결 1건 기준으로 완화하는 것은 Phase 3 이후 별도 결정 후보로 둔다.

Phase 2의 기본 부모 주문 수량은 `max_order_qty=1`이다. 2주 이상 주문은 `order_policy.max_order_qty` 또는 `max_qty`로 명시 override할 때만 허용한다. 수량 초과는 broker 호출 전 `phase2_order_qty_limit_exceeded` 사유와 `{current, limit}` context로 `blocked` 기록한다.

Phase 2 부분 체결 잔량 정책은 계좌 소유자/실전 운용 승인권자 결정으로 Codex 권장안을 채택한다. 기본값은 자동 잔량 취소 금지, 잔량 유지, 같은 종목 신규 부모 주문 차단이다. 잔량 취소가 필요하면 cancel-only guard를 통과한 수동 승인 취소로 처리한다. 장마감 전 자동 잔량 취소는 KIS 취소 응답 fixture, cancel-only 정합성 테스트, 알림/장후 리뷰가 안정된 뒤 Phase 3 전 별도 후보로 둔다.

Phase 2의 모델 성능 선행 게이트는 단순 예측 정확도만 보지 않는다. 현재 active model은 `runtime-data/ml/registry.json`의 `baseline-h15-v1`이며 LightGBM은 장후 재학습되는 challenger다. Phase 2 실전 주문 전에는 최신 challenger 리포트의 `recommended_action`이 `keep_active`가 아니거나, 운영자가 별도 승인한 active model이 있어야 하고, 독립 holdout, 비용 반영 net return, 거래 수, paper 성과, walk-forward gate를 함께 확인한다. baseline fallback 상태 또는 challenger가 `keep_active`를 권고한 상태에서는 Phase 2 신규 실전 주문을 내지 않는 것을 기본 후보로 둔다.

관련 문서/코드 경로: `runtime-data/ml/registry.json`, `runtime-data/reports/challengers/latest-challengers-h15.json`, `runtime-data/reports/backtests/latest-walk-forward-h15.json`, `docs/Machine-Learning-Operations.md`

관측 기간과 수치 기준은 운영자가 확정해야 한다. 10거래일은 Phase 2 승격 판단에 충분한 안정성 표본으로 보지 않고, smoke 관측 또는 중간 점검으로만 본다.

- 관측 기간: Phase 1 최소 5거래일, Phase 2 최소 20거래일, Phase 3 전 최소 60거래일 누적 관측. 미충족 예외는 한도 감액 또는 Phase 2 유지 조건으로만 운영자 승인한다.
- 다양한 장 상황 후보: KOSPI/KOSDAQ 중 운영 대상 시장 기준 상승일, 하락일, 고변동일을 각각 1일 이상 포함하는 것을 후보로 둔다. 지수 기준, 변동성 기준, 대체 조건은 확인 필요다.
- 슬리피지 허용 범위: 종목별 평균, p95, 비상 청산 예외 기준 확인 필요.
- paper-vs-live 격차 한도: 동일 signal 기준 체결가 차이 bps, 체결 수량 차이, 실현/미실현 수익률 차이를 함께 기록. 최종 통과 metric은 확인 필요.
- 일일 손실 한도: 금액과 퍼센트 모두 확인 필요.
- phase 통과 판단: Phase 0의 누적 정합성, Phase 1 fault injection, Phase 2/3 관측 기간과 mismatch는 dashboard 또는 일일 리포트에서 자동 집계하는 것을 목표로 한다. 자동 집계 구현 전에는 운영자 수동 서명이 필요하지만, 수동 판단만으로 phase를 승격하지 않는다.

각 phase의 사람 승인 절차는 `장전 체크리스트 확인 -> dashboard와 최신 report 확인 -> 당일 phase/한도/종목 승인 기록 -> 장중 변경 금지 -> 장후 review 서명` 순서로 둔다. 다만 매일 장전 승인이 운영자 1인의 가용성에 묶이면 자동 운용성이 낮아진다. Phase 3에서는 전일 통과, 한도 변경 없음, watchlist 변경 없음, 미확인 주문 0건일 때 자동 갱신을 허용할지 운영자 결정 필요다.

관련 문서/코드 경로: `docs/Current-Implementation.md`, `docs/Realtime-Operations.md`, `scripts/check_local_setup.sh`, `scripts/verify_paper_dual_account_match.sh`, `app/services/kis_account.py`, `app/config/settings.py`

## 6. 장애 시나리오 대응

아래 표의 자동 동작은 실전 목표 동작이다. 현재 코드에서 이미 확인된 동작은 관련 경로를 별도로 적고, live 전용 주문 매니저/market status/alert 경로가 필요한 항목은 구현 전 목표로 본다.

| 시나리오 | 신규 주문 자동 동작 | 진행 중 주문 운명 | 사람 개입 트리거 |
|---|---|---|---|
| KIS WebSocket 끊김 | live runtime reconnect, stale raw minute 감지, 신규 주문 차단 후보 | REST 조회가 가능하면 open/partial 상태 동기화, REST도 실패하면 조회 보류와 `unknown` 후보 | 장중 최신 raw minute 지연이 grace 초과 또는 REST 조회도 실패 |
| KIS REST 실패 | 주문 전이면 제출 중단 | 주문 후면 `unknown`으로 두고 조회 재시도. 취소 실패면 open 유지 또는 사람 호출 | 주문 제출 후 결과 불명확 또는 취소 실패 |
| 토큰 만료 | token manager 재발급 시도, 실패 시 신규 주문 차단 | 이미 제출된 주문은 조회 보류. 취소가 필요하면 token 복구 뒤 cancel-only 후보 | 재발급 실패가 주문/취소/조회 경로에 영향 |
| KIS rate limit | 조회는 cooldown, 신규 주문 차단 | 취소 요청은 전용 budget 후보. budget도 실패하면 open 유지와 사람 호출 | 취소 요청까지 rate limit에 막히거나 open order가 남아 있을 때 |
| 시장 휴장 | `config/market_calendar.toml` 기준 live runtime 재기동 제한 | 기존 주문은 없어야 한다. 남아 있으면 orphan/open 의심으로 사람 호출 | 임시 휴장/거래시간 변경 정보가 로컬 캘린더에 없을 때 |
| 거래소/KIS 시스템 점검 | 신규 주문 차단, 조회 실패를 점검 상태로 분류 | open 주문은 조회 보류. 취소 가능 여부는 점검 종료 후 확인 | 점검 종료 뒤 재개 판단 |
| 상한가/하한가 | 해당 종목 신규 진입 차단 후보 | 보유 청산은 가격 제한 방향에 따라 가능/불가능을 표시하고, 불가능하면 유지와 사람 호출 | 보유 종목이 가격 제한에 걸려 청산 불가하거나 연속 제한 상태 |
| 거래정지/관리종목/투자유의 | 당일 market status snapshot이 막으면 주문 전 차단 | open 주문은 취소 시도 후보. 취소/체결 불명확이면 `unknown` | 상태 데이터가 없거나 watchlist에 제한 종목이 남아 있을 때 |
| VI(변동성완화장치) | VI 발동 종목 신규 주문 차단 또는 단일가 구간 주문 금지 후보 | 이미 제출된 주문은 자동 추가 주문 금지. 취소 가능하면 cancel-only, 아니면 대기/조회 보류 | VI 중 open/partial 주문이 남아 있거나 VI 종료 뒤 상태가 불명확 |
| 시초가 동시호가/초반 변동성 | 현재 설정상 09:15 전 신규 진입 금지. 실전에서는 09:00~09:05 별도 watch 상태로 표시 | 기존 주문은 없어야 한다. 있으면 취소 후보 | 09:15 이후에도 급변동/호가 공백이 지속될 때 |
| 종가 동시호가/시간외 단일가 | 현재 설정상 15:00 이후 신규 진입 금지, 15:20 정리 우선. 시간외 단일가 주문은 1차 설계 제외 | 15:20 이후 open 주문은 취소 시도 후보. 보유 포지션은 보호성 청산 후보이나 자동 여부는 운영자 결정 | 15:20 이후 미체결/보유 포지션이 남아 있고 취소/청산 실패 |
| 주문 타입 정책 위반 | Phase 2 신규 진입 시장가 주문 차단 후보 | 이미 제출된 시장가 주문은 사후 감사와 사람 호출. 비상 청산 주문이면 별도 승인 여부 확인 | 지정가/시장가 정책과 실제 주문 타입 불일치 |
| 네트워크 단절 | 신규 주문 차단 | 미체결 조회 보류, 로컬 상태 `unknown`, 자동 재주문 금지 | 단절 중 주문 제출 가능성이 있었거나 포지션 노출이 큰 경우 |
| 부분 체결/단주 잔량 미회수 | 같은 종목 신규 주문 차단. Phase 2 pre-submit 정책은 구현됐지만 runtime 연결 전이다. | 체결 조회 반복, 미기록 delta fill만 멱등 반영. Phase 2 기본은 자동 취소 금지와 잔량 유지다. 취소가 필요하면 cancel-only guard와 수동 승인으로 처리한다. | 체결 수량이 장 종료까지 불명확 또는 단주 잔량이 남음 |
| 알 수 없는 주문 상태 | 신규 주문 차단 | `unknown`/`stuck`으로 두고 조회/취소. 실패하면 사람 호출 | 한 번 이상 조회/취소 실패 |
| kill switch 청산과 슬리피지 충돌 | 신규 주문은 차단 | 보호성 취소는 cancel-only 후보. 보호성 청산은 일반 슬리피지 게이트와 분리하되 시장가/지정가 선택은 승인 필요 | 자동 청산 허용 여부, 시장가/지정가 선택, 슬리피지 초과 승인 필요 |
| T+2 결제/주문가능금액 불일치 | 주문가능금액 부족 시 신규 매수 차단 | open 주문이 주문가능금액 부족으로 reject되면 rejected로 확정하고 재주문 금지 | 매도 후 다음날 주문 가능 금액이 내부 계산과 다를 때 |
| 기업행위(권리락/배당락/분할/증자) | 이벤트 대상 종목 신규 주문 차단 후보 | 보유 포지션은 이벤트 조정 전 자동 청산 금지. 손익/슬리피지 계산 보정 필요 | 보유 종목에 이벤트가 있고 가격 급변이 hard limit에 영향을 줄 때 |
| 시스템 시계 오차 | 후보 기준 `±2초` 초과 시 신규 주문/취소 제출 전 차단. 실제 허용 범위는 확인 필요 | 이미 제출된 주문은 상태 조회 우선. 새 취소도 시계 보정 전 자동 제출 금지 후보 | OS/NTP 보정 실패 또는 KIS timestamp 거부 |
| DB 잠금 | 주문 전이면 중단 | 주문 후면 `unknown` 복구 루틴, 상태 미기록 시 사람 호출 | lock이 grace 초과 또는 제출 후 상태 미기록 |
| 디스크 부족 | 신규 주문 차단, 로그/리포트 저장 실패 알림 | 이미 제출된 주문은 조회 가능하면 별도 최소 로그에 기록. 기록도 실패하면 사람 호출 | runtime-data 여유 공간 임계치 미만 |
| 모델 추론 실패 | live에서는 새 진입 신호 차단 | 보유 포지션은 모델 비의존 exit 룰이 있는지 확인 필요. 없으면 사람 호출 전까지 유지 후보 | active model artifact 손상, registry 불일치, 보유 포지션 출구 전략 미정 |
| 운영자 미응답 | 알림 escalation, 자동 신규 주문 중지 후보 | open 주문은 사전 정의된 cancel-only 정책이 없으면 유지/조회 보류 | 1차 운영자 응답 timeout 또는 대체 승인자 부재 |

장애 대응의 공통 원칙은 `주문 전 장애는 차단`, `주문 후 장애는 unknown 복구`, `계좌/체결/시장상태 불일치는 신규 주문 차단`, `사람 확인 전 자동 재개 금지`다. 진행 중 주문의 운명은 시나리오별로 `취소 시도`, `조회 보류`, `유지`, `보호성 청산 후보`를 구분해 기록해야 한다.

관련 문서/코드 경로: `app/services/streaming.py`, `app/services/kis_verification.py`, `app/services/broker_paper_sync.py`, `scripts/run_runtime_watchdog_loop.sh`, `config/market_calendar.toml`, `docs/Market-Schedule-Rules.md`, `docs/Universe-Freeze-Policy.md`, `runtime-data/reports/runtime-watchdog/state/`

## 7. 운영 절차

장전 체크리스트:

1. `./scripts/check_local_setup.sh`로 dashboard, watchdog, live runtime 필요 여부, KIS 시세 자격정보, LightGBM 사용 가능 상태를 확인한다.
2. `config/market_calendar.toml`의 오늘 휴장 여부와 거래시간 변경 여부를 확인한다.
3. 당일 거래정지, 관리종목, 투자유의, 상하한가 근접, VI, corporate action(기업행위) 대상 종목을 확인한다. 자동 데이터 원천은 확인 필요이며 후보는 KIS REST, 한국거래소 OpenAPI, 운영자 수동 calendar다.
4. Phase 0에서는 `./scripts/verify_paper_dual_account_match.sh -AsJson` 또는 필요 시 `-AlignToBroker -AsJson`로 paper 정합성을 확인한다.
5. Phase 1 이상에서는 실전 계좌 read-only snapshot 신선도, 주문가능금액, T+2 결제 차이를 확인한다. 실전 주문은 Phase 2 전까지 금지한다.
6. active model, latest KIS live 품질, source drift, feature diagnostics를 dashboard에서 확인한다.
7. 운영자와 대체 승인자 연락 가능 상태를 확인한다. 대체자가 없으면 자동 운용 대신 신규 주문 차단으로 시작할지 결정한다.
8. 실전 phase에서는 운영자 승인 기록을 남긴다. 현재 승인 기록 경로와 변조 방지 방식은 확인 필요다.

장중 체크리스트:

1. latest raw minute lag와 closed feature coverage를 확인한다.
2. 미체결 주문, unknown/stuck 주문, pending symbols를 확인한다.
3. 일일 손실, 노출, 슬리피지, 계좌 snapshot 신선도, 주문가능금액을 확인한다.
4. 09:00~09:15, 15:00~15:30, VI, 시간외 단일가 구간의 주문 제한이 의도대로 적용되는지 확인한다.
5. Phase 2 이상에서는 신규 진입 주문 타입이 지정가인지 확인한다. 시장가 주문은 비상 청산 후보로만 별도 승인한다.
6. 장중에는 heavy research, cleanup, schema 변경, gate 기준값 변경을 하지 않는다.

장후 체크리스트:

1. live runtime이 post-close로 정상 중지됐는지 확인한다.
2. `./scripts/run_post_close_ml_maintenance.sh --quick` 상태를 확인한다.
3. 라벨 닫힘이 필요하면 `./scripts/run_post_close_label_refresh.sh`를 실행한다.
4. `python -m app --build-runtime-report`와 `python -m app --build-dashboard` 결과를 확인한다. runtime report와 dashboard의 live fill 정합성 mismatch 수, `unknown`/`stuck` 미해결 주문 수가 다르면 report 생성 시각과 선택 거래일을 함께 확인한다.
5. paper/live reconciliation, 당일 PnL, 슬리피지, gate 발동 횟수, paper-vs-live 격차, 세금/수수료/정산 차이를 리뷰한다.

주문 대기 잔량과 미보고 처리 절차는 `open/partially_filled/pending_lookup`이 있으면 신규 주문을 차단하고, 브로커 조회 -> 취소 가능 여부 판단 -> 운영자 확인 -> 정합성 리포트 순서로 둔다. Phase 2에서는 부분 체결 잔량이 남아 있으면 같은 종목의 두 번째 부모 주문을 내지 않는다.

사고 발생 시 즉시 정지 절차는 `kill switch ON -> 신규 주문 차단 -> 미체결 취소 시도 -> 체결/계좌 snapshot refresh -> 포지션 청산 여부 사람 판단 -> 사고 리포트 작성 -> 다음 거래일 재개 금지 상태 유지` 순서다. kill switch ON 트리거는 자동 hard limit, 운영자 수동, 시스템 헬스 실패로 나눌 수 있다. 현재 수동 CLI 후보는 `scripts/set_live_kill_switch.sh --enable --reason <사유> --actor account_owner --apply`다. OFF는 운영자 승인과 사후 원인 기록 없이는 허용하지 않으며, CLI도 `--disable --apply --confirm-disable`을 요구한다.

월요일 장전 readiness 점검은 기존 `check_local_setup`과 dashboard `장전 readiness` 카드에 연결한다. 월요일 09:00~09:30에는 live runtime warmup과 KIS symbol-minute 증가를 우선 보되, 현재 설정상 신규 진입은 09:15 전까지 금지된다는 점을 함께 확인한다.

관련 문서/코드 경로: `docs/Realtime-Operations.md`, `docs/Current-Implementation.md`, `docs/Market-Schedule-Rules.md`, `scripts/check_local_setup.sh`, `scripts/run_post_close_ml_maintenance.sh`, `scripts/run_post_close_label_refresh.sh`, `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`

## 8. 모니터링/알림

dashboard에 추가할 카드 목록은 아래와 같다.

| 카드 | 표시 항목 |
|---|---|
| 실전 enable 상태 | `TRADING_MODE`, `ALLOW_LIVE_ORDERS`, phase, 당일 승인 여부, 주문 함수 차단 self-check |
| kill switch | 상태, ON 트리거, 켠 사람/시각, 사유, 해제 가능 여부 |
| 일일 손실/최대 낙폭 | 실현/미실현 PnL, 한도 대비 비율, 신규 주문 차단 여부 |
| 시장 상태 | 휴장/거래시간 변경, 동시호가, VI, 거래정지, 상하한가, 관리/투자유의, corporate action stale 여부 |
| 실전 주문 상태 | submitted/open/partial/filled/cancelled/rejected/unknown/stuck 수, `unknown`/`stuck` 최장 경과 시간 |
| 미체결/미보고 | pending symbols, oldest pending age, broker 조회 결과 |
| 실전 fill 정합성 | 거래일별 `live_orders.filled_qty`와 `live_fills` 합계 차이, 불일치 주문 ID |
| 실전 미해결 주문 | `unknown`/`stuck` 주문 ID, 종목, 잔량, 경과 시간 |
| Phase 2 부모 주문 한도 | 거래일별 부모 주문 수/한도, 잔여 수, 한도 차단 여부, 한도에 포함된 주문 ID |
| 슬리피지 | 의도 가격, 평균 체결가, mid 기준 bps, budget 초과 횟수, 비상 청산 예외 여부 |
| 주문 타입 정책 | phase별 허용 주문 타입, 실제 주문 타입, 시장가 예외 승인 여부 |
| T+2/주문가능금액 | 내부 현금, 브로커 예수금, 주문가능금액, 미정산 금액 |
| 노출 | 단일 종목 비중, 섹터/테마 비중, 총 gross exposure |
| 감사 추적 | 최근 주문별 prediction_id, signal_id, model version, rule version, gate decision |
| 운영자 승인 | 최신 승인 시각, 승인자, hash/서명 검증 상태, 대체 승인자 |
| 알림 상태 | 최근 알림, 억제 중인 알림, 미확인 사고, escalation 단계, live fill mismatch status alert |
| 실전 계좌 정합성 | 브로커 체결 vs 내부 기록 vs paper 기록 차이, runtime report의 live fill mismatch 수 |

dashboard 외 알림 채널은 외부 의존성을 최소화해 3단계로 둔다.

| 등급 | 발송 기준 | 채널 |
|---|---|---|
| 정상 | 장전/장후 체크 완료, quick maintenance 완료 | dashboard, 로컬 JSON outbox |
| 주의 | coverage watch, REST rate limit 반복, prediction stale, market status stale, paper-vs-live 격차 경고 | dashboard, 로컬 JSON outbox, 텔레그램 outbox |
| 사고 | kill switch, unknown/stuck live order, live fill mismatch, 일일 손실 한도, DB/disk 장애, 실전 계좌 불일치, 운영자 미응답 | dashboard, 로컬 JSON outbox, 텔레그램 outbox, 이메일 outbox |

외부 알림 채널 결정은 텔레그램을 기본 장중 메시지 채널로 쓰고, 중요한 이슈는 이메일도 함께 보내는 방식이다. 현재 구현은 `app/services/live_alerting.py`와 `app/services/reporting.py`의 outbox 기록까지이며, 같은 event type/trading day/state fingerprint의 동일 alert는 같은 날짜 outbox에 중복 append하지 않는다. outbox JSONL의 `detail_json`은 저장 직전에 계좌/토큰/app secret 계열 key를 redaction한다. 실제 텔레그램 bot token, SMTP/API key, 수신 주소는 문서와 git 추적 파일에 쓰지 않는다. 실제 발송기는 outbox를 읽는 별도 sender로 두고, 발송 실패가 실전 주문 경로를 막지 않도록 주문/체결 경로와 분리한다.

false alarm을 줄이기 위한 hysteresis(조건이 바로 튀지 않게 연속 조건을 보는 정책)와 grace 정책은 아래처럼 둔다.

- raw minute lag는 1회 초과가 아니라 연속 `N`분 초과 시 주의로 올린다. `N`은 확인 필요.
- coverage는 아직 닫히지 않은 마지막 1분을 제외하는 현재 정책을 유지한다.
- KIS rate limit은 현재 broker paper sync처럼 cooldown을 둔다. 실전 주문 취소 경로는 더 보수적으로 운영자 호출한다.
- market status snapshot은 stale 시간이 임계치를 넘으면 false alarm으로 낮추지 않고 해당 종목 신규 주문을 차단한다. VI 상태는 stale이면 신규 주문 차단 측으로 본다.
- 같은 alert key는 상태가 바뀌기 전까지 반복 발송하지 않는다. 현재 outbox 단계에서는 state fingerprint 기반 중복 append 억제까지 구현했다.
- `unknown/stuck` attention은 payload의 `max_attention_age_minutes`가 `attention_grace_minutes`보다 작으면 alert 생성을 미룰 수 있다. 이 hook은 2026-05-18 기준 순수 helper에 구현됐고, 어떤 경로에서 몇 분 grace를 줄지는 운영 절차에서 별도로 정한다.
- kill switch, live fill mismatch, DB/disk 장애처럼 이미 확정된 사고 등급은 grace로 억제하지 않는다.

관련 문서/코드 경로: `app/services/dashboard.py`, `app/services/reporting.py`, `app/services/live_alerting.py`, `runtime-data/reports/dashboard/latest-dashboard.json`, `runtime-data/reports/alerts/`, `runtime-data/reports/recovery/latest-local-setup-check.json`, `runtime-data/reports/data-quality/`, `app/services/broker_paper_sync.py`

## 9. 회계/감사 로그

모든 실전 주문은 아래 필드를 함께 기록해야 한다.

- `prediction_id`
- `signal_id`
- `target_id`
- `order_id`
- `idempotency_key`
- `rule_version`
- `gate_decision_id`
- `gate decision payload`
- `model_version`
- `feature_set_version`
- `data_snapshot_id`
- `market_status_snapshot_id`
- `strategy_version`
- `portfolio_version`
- `broker_order_no`
- `broker_branch_no`
- `submitted_at`, `accepted_at`, `last_synced_at`
- 주문 의도 가격, 평균 체결가, 실제 슬리피지
- 수수료, 세금, 거래소/브로커 비용, 실현 손익, 미실현 손익
- 주문가능금액, 예수금, T+2 미정산 금액

현재 `serving_predictions`와 `serving_trade_signals`는 각각 ID를 갖지만 직접 연결 필드가 없다. `paper_orders`에도 `signal_id`가 없다. 실전 전환 전에는 live 주문 테이블 또는 audit table이 이 연결을 강제해야 한다.

일일 정합성 리포트는 아래 3개 축을 비교한다.

| 축 | 비교 내용 |
|---|---|
| 브로커 체결 | KIS 일별 주문/체결 조회 결과, 계좌 잔고 snapshot, 주문가능금액, 미정산 금액 |
| 내부 기록 | live order/fill/position/portfolio snapshot, 수수료/세금/슬리피지 추정. 2026-05-17 기준 live order와 fill delta 기록, `live_fills` 기반 순수 position 계산 helper는 구현됐다. 자동 position 저장, portfolio snapshot, split fee 정산은 후속이다. |
| paper 기록 | 같은 signal을 기준으로 한 paper 결과, paper-vs-live 격차 |

`live_positions` 실제 저장 시점은 계좌 소유자/실전 운용 승인권자 결정으로 Codex 권장안을 채택한다. `app/services/live_position_accounting.py`의 순수 계산 helper는 유지하되, 계산 결과를 `live_positions` 정본 테이블에 자동 저장하는 것은 KIS 실제 응답 fixture, alert outbox, 장후 review 경로가 안정되고 live order/fill mismatch가 0임을 확인한 뒤 진행한다. 첫 저장 단계에서는 관측용 snapshot으로만 쓰고, 리스크 게이트나 주문 수량 산정의 정본 입력으로 쓰지 않는다.

paper-vs-live 격차는 최소한 아래 metric을 함께 남긴다.

- 동일 signal 기준 체결가 차이 bps.
- 체결 수량 차이와 미체결 잔량.
- paper 수익률과 live 수익률 차이.
- 슬리피지 추정치와 실제 체결 슬리피지 차이.
- 거래가 서로 다른 시점에 체결된 경우 비교 제외/보정 규칙. 기준은 확인 필요다.

보관 기간은 운영자 결정이 필요하다. 기본 제안은 실전 주문 감사 원장과 일일 정합성 리포트는 최소 5년이지만, 이 값은 세무/내부 정책/분쟁 대응 중 어느 기준으로 둘지 확인해야 한다. raw market data는 저장 공간 정책에 따라 hot/warm/cold 계층으로 분리한다.

감사 원장은 단순 JSON 덮어쓰기만으로는 충분하지 않다. 최소 기준은 append-only 기록, 파일 단위 hash chain, 운영자 승인 이벤트의 변경 불가 로그, 정기 백업에 포함되는 복구 검증이다. 2026-05-18 기준 `app/services/live_audit.py`는 `ops_live_audit_events`의 event hash와 previous hash를 생성/검증하고 runtime report에 integrity 요약을 표시한다. 필수 추적 필드가 빈 값이면 event build를 거부한다. 아직 모든 실전 주문 decision에 자동 연결하지 않았고, 외부 anchor, 서명, NAS 복구 self-test는 후속이다. git 추적을 쓸지, 별도 서명 파일을 쓸지, 로컬 전용 append-only 파일을 쓸지는 운영자 결정 필요다.

실전 감사 원장은 회전/삭제될 수 있는 일반 runtime 로그와 분리하기 위해 `runtime-data/logs/` 아래에 두지 않는다. NAS 운영은 재난 복구용 전체 백업과 실전 전환 검증용 sanitized recovery export를 구분한다. 재난 복구용 전체 백업은 이전 저장소 유실 사고 대응을 위한 접근 제한 NAS 이중 보관으로 보고, cowork 전달이나 readiness 증거로 직접 쓰지 않는다. 실전 전환 검증용 sanitized recovery export는 `scripts/run_weekly_nas_backup.sh`, `scripts/run_forced_nas_backup.sh`가 `scripts/script_dispatch.sh`의 `export_to_nas`를 거쳐 만들 수 있는 비밀값 제외 export 기준이다. 2026-05-17 기준 `tests/test_wsl_ops.py`는 `runtime-data/reports/live-risk/`, `runtime-data/reports/alerts/`, `runtime-data/reports/live-approvals/`, `runtime-data/ops/`, `runtime-data/ml/registry-backups/`가 sanitized recovery export에 포함되고, root `.env`, `runtime-data/cache/kis`, `runtime-data/logs`, key 파일이 제외되는지 잠근다. `scripts/wsl_ops.py`의 tar 추가는 디렉터리 재귀 추가가 제외 정책을 우회하지 않도록 `recursive=False`를 쓴다.

세금/수수료 항목은 단일 카테고리로 합치지 않는다. 증권거래세, 농어촌특별세, 브로커 거래수수료, 거래소/유관기관 비용, 기타 정산 차이를 분리한다. 현행 세율과 적용 대상은 실전 전 브로커/세무 기준으로 다시 확인해야 하며, 대주주 양도세 가능성은 운영자 판단 필요다.

관련 문서/코드 경로: `app/storage/sqlite_store.py`, `app/storage/contracts.py`, `app/paper_trading/engine.py`, `app/services/paper_reconciliation.py`, `app/services/kis_account.py`, `RECOVERY.md`, `scripts/run_weekly_nas_backup.sh`, `scripts/run_forced_nas_backup.sh`, `scripts/script_dispatch.sh`

## 10. 테스트/검증 기준

실전 진입 전 레이어별로 아래 테스트를 통과해야 한다. 현재 존재하는 테스트와 제안 신규 테스트를 분리한다.

| 레이어 | 현재 테스트 | 추가 필요 |
|---|---|---|
| 설정/안전 플래그 | `tests/test_settings.py` | live enable 이중 잠금, KIS 주문 함수 직전 allow flag 차단, read-only client가 주문 메서드를 노출하지 않는 검증, kill switch 설정 파싱 |
| KIS REST/WebSocket | `tests/test_kis_clients.py`, `tests/test_kis_http_clients.py`, `tests/test_kis_ws_parser.py`, `tests/test_kis_ws_verification.py`, `tests/test_system_clock.py` | 실전 read-only profile, rate limit budget, token refresh fault injection, WS drop fault injection, 시스템 시계 오차 순수 판정 |
| KIS fixture redaction | `tests/test_kis_response_redaction.py`, `tests/test_kis_paper_fixture_export_script.py` | 실제 응답 sample 반영 전 `redaction_ok=true` 확인과 사람이 민감 필드명 재검토, KIS live 주문/체결 sample 1~3건 fixture화 |
| 수집/분봉/feature | `tests/test_pipeline.py`, `tests/test_runtime_scope.py`, `tests/test_kis_live_data_quality_summary.py` | 장중 stale data 차단, data snapshot id, market status snapshot stale 차단 |
| 시장 상태 | `tests/test_market_status.py` | 외부 market status 원천 연동, 거래정지/관리종목/상하한가/VI/동시호가/기업행위 calendar fixture 확대 |
| 모델/registry | `tests/test_model_registry.py`, `tests/test_model_loader.py`, `tests/test_research_pipeline.py` | atomic registry 교체, rollback, live 중 교체 락, 첫 기동 registry self-check |
| 신호/리스크 | `tests/test_streaming_pipeline.py`, `tests/test_paper_book.py` | 일일 손실, 노출, 슬리피지, kill switch, T+2 주문가능금액 게이트 |
| 주문/체결 | `tests/test_broker_paper_sync.py`, `tests/test_paper_reconciliation.py`, `tests/test_paper_alignment.py`, `tests/test_live_order_manager.py`, `tests/test_live_execution_sync.py` | 실제 KIS live adapter 연결, 부분 체결 잔량 자동 취소 정책, 지정가/시장가 정책의 실제 KIS 응답 매핑, 포지션/포트폴리오 반영 |
| 대시보드/운영 | `tests/test_dashboard.py`, `tests/test_wsl_ops.py`, `tests/test_post_close_maintenance_script.py`, `tests/test_post_close_label_refresh_script.py`, `tests/test_live_alerting.py` | live fill 정합성 read-only 카드, `unknown`/`stuck` 미해결 주문 카드, Phase 2 부모 주문 한도 카드, readiness dry-run 카드, alert fingerprint dedupe, attention grace hook, alert outbox `detail_json` redaction. 남은 항목은 실제 외부 발송기, 자유 텍스트 redaction, raw minute lag 연속 조건 hysteresis, phase approval, 운영자 미응답 escalation, 누적 10/20/60거래일 통과 지표 |
| 백업/감사 | `tests/test_live_audit.py`, `tests/test_wsl_ops.py` | 감사 hash chain 검증, 필수 trace field 빈 값 거부, recovery export 포함/제외 self-test는 구현됐다. 실제 NAS 공유 접근/복구 drill은 후속 |

shadow 운용은 실전 주문을 내지 않고 실전 계좌 read-only와 paper 주문을 나란히 기록하는 운영 정책 단계로 정의한다. 현재 코드에 별도 `shadow` 실행 모드가 있다는 뜻은 아니다. 종료 조건은 최소 관측 기간 충족, 실전 조회 stale 0건, paper-vs-live 계산 격차가 한도 이내, unknown order 0건이다. Phase 1에서 주문 함수 호출이 1회라도 발생하면 단순 실패가 아니라 P0 버그로 분류한다.

canary 운용은 1종목/소액/1일 1부모주문 제한 실전 운용 정책 단계로 정의한다. 현재 코드에 별도 `canary` 실행 모드가 있다는 뜻은 아니다. 종료 조건은 실전 주문 lifecycle 전 상태 전이 검증, 일일 손실 한도 미발동, 실제 슬리피지 허용 범위 내, 장후 정합성 mismatch 0건이다. 10거래일 관측은 중간 점검으로만 보고, Phase 3 승격에는 최소 20거래일 이상과 다양한 장 상황 확인을 요구한다.

회귀 잠금 invariant는 아래 테스트가 맡아야 한다.

- paper 동작 불변: `tests/test_streaming_pipeline.py`, `tests/test_paper_book.py`, `tests/test_broker_paper_sync.py`, `tests/test_paper_reconciliation.py`
- dashboard 기존 카드 불변: `tests/test_dashboard.py`
- 장후 quick/heavy 분리 불변: `tests/test_post_close_maintenance_script.py`, `tests/test_post_close_label_refresh_script.py`
- active model 자동 교체 금지: `tests/test_research_pipeline.py`, `tests/test_model_registry.py`
- 실전 주문 비활성 불변: 제안 신규 live enable 이중 잠금 테스트

실전 진입 전 마지막 체크포인트는 운영자가 `🔴 운영자 판단 필요` 형식으로 phase, 종목, 금액, 일일 손실 한도, 주문 가능 시간, kill switch 담당자와 대체 승인자, 시장 미시 규칙 처리 기준을 승인하는 것이다. 승인 전 `ALLOW_LIVE_ORDERS`는 `false`여야 한다.

관련 문서/코드 경로: `tests/`, `docs/Validation-Plan.md`, `docs/Machine-Learning-Operations.md`, `docs/Paper-Trading-Validation.md`, `app/config/settings.py`, `app/brokers/kis_quote_rest.py`

## 11. NOT-DO 목록

1차 실전 설계에서 아래 항목은 하지 않는다.

- 옵션/선물, 야간거래, 시간외 단일가 자동 주문.
- 신용/대출, 레버리지, 미수, 자동 펀딩, 자동 이체.
- 외부 브로커 멀티 라우팅.
- 자동 모델 승격과 장중 active model 자동 교체.
- 운영자 승인 없는 실전 주문 enable.
- gate 기준값 자동 변경.
- 장중 heavy research, schema migration, cleanup 실행.
- 뉴스/공시/소셜 이벤트 기반 자동 주문 확대.
- 실전 계좌번호, KIS app key, app secret, token을 문서나 git 추적 파일에 기록.

관련 문서/코드 경로: `AGENTS.md`, `docs/Account-Safety.md`, `docs/Machine-Learning-Operations.md`, `config/strategy.toml`

## 12. 오픈 질문과 운영자 결정 필요 항목

✅ 결정 완료(P0): Phase 1 구조적 차단의 기본 방식은 주문 메서드를 노출하지 않는 별도 read-only client다. `app/brokers/kis_readonly.py` 구현은 완료됐고, Phase 1 runtime flow 연결은 후속 작업이다.

✅ 결정 완료(P0): VI 발동 중 신규 주문은 금지하고, 기존 open 주문은 조회 보류한다. 잔량 취소는 cancel-only guard 통과 뒤 허용 후보로 둔다. KIS가 VI 중 미체결 주문을 어떤 상태로 반환하는지는 확인 필요다.

✅ 결정 완료(P0): Phase 2 신규 진입은 지정가 only다. 시장가는 기본 금지이고, 비상 청산 시장가는 청산 건별 수동 승인 후보로 둔다.

✅ 결정 완료(P0): Phase 2 손실 한도와 슬리피지 budget은 `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision.md` 기준으로 둔다. 비상 청산은 일반 슬리피지 budget과 분리해 사고 리포트에 별도 기록한다.

🔴 운영자 판단 필요: 최대 낙폭 `Z`, 단일 종목 `A`, 섹터/테마 `B`, reference clock 원천.

🔴 운영자 판단 필요: Phase 1에서 사용할 실전 계좌 read-only 범위와 계좌 snapshot 보관 기간.

✅ 결정 완료(P1): Phase 2 부모 주문 금액 한도는 `min(100,000원, 운용 배정금의 10%)`다. 운용 배정금이 전달되지 않은 초기 경로에서는 100,000원을 기본 한도로 쓴다. `app/services/live_order_manager.py`는 `order_policy.max_order_notional`, `allocation_amount` 또는 `phase2_allocation_amount`, `max_order_allocation_pct` 또는 `max_order_allocation_ratio`로 후속 조정할 수 있게 구현했다.

✅ 결정 완료(P1): Phase 2 부모 주문 수량 한도는 기본 `max_order_qty=1`이다. 2주 이상 주문은 `order_policy.max_order_qty` 또는 `max_qty` 명시 override가 있을 때만 허용한다.

🔴 운영자 판단 필요(P0): reference clock 원천. Codex 권장안은 KIS REST 응답의 HTTP `Date` 헤더 또는 KIS 응답 서버시각을 1차 reference로 쓰고, OS/NTP 확인을 보조 reference로 두는 것이다. 현재 `app/services/system_clock.py`는 HTTP `Date` 헤더 parser/decision helper와 readiness fixture 평가를 제공하고, timezone 없는 header와 알 수 없는 timezone은 invalid로 차단한다. `app/brokers/kis_quote_rest.py`와 `app/brokers/kis_readonly.py`는 마지막 성공 응답 header를 read-only 진단용 copy로 노출한다. `app/services/system_clock_probe.py`와 `scripts/probe_kis_clock_reference.sh`는 read-only 현재가 조회 1회 뒤 raw header 원문 없이 sanitized `system_clock` check JSON을 만들 수 있고, `scripts/run_live_readiness_dry_run.sh`는 `--system-clock-check-path`로 받은 check를 fixture보다 우선 병합한다. `app/services/live_order_manager.py`는 이 decision을 필수 submit guard 입력으로 받을 수 있다. 2026-05-20 KIS paper 현재가 read-only 조회 1회에서 실제 `date` header 존재를 확인했고, 2026-05-21 paper probe wrapper 실행에서 `system_clock=true`, skew 약 0.167초를 확인했다. live account header shape 확인은 아직 남아 있다.

✅ 결정 완료(P1): Phase 2 부분 체결 잔량은 자동 취소하지 않는다. 잔량 유지와 같은 종목 신규 부모 주문 차단을 기본으로 하고, 필요 시 cancel-only guard와 수동 승인 취소로 처리한다. 자동 장마감 잔량 취소는 KIS cancel fixture와 alert/review 안정화 뒤 Phase 3 전 후보로 둔다.

✅ 결정 완료(P1): `live_positions` 실제 저장은 KIS 실제 응답 fixture, alert outbox, 장후 review 경로가 안정된 뒤 관측용 snapshot으로 먼저 시작한다. 초기 저장값은 리스크 게이트나 주문 산정의 정본 입력으로 쓰지 않는다.

🔴 운영자 판단 필요: kill switch ON 트리거와 OFF 승인자, 보호성 취소/비상 청산이 일반 주문 게이트를 어떻게 통과할지.

🔴 운영자 판단 필요: 매일 장전 승인 유지, 조건부 자동 갱신 허용, 운영자 부재 시 대체 승인자 또는 운용 중지 기준.

🔴 운영자 판단 필요: 단일 종목 최대 비중, 섹터/테마 총 노출 한도, 총 gross exposure 한도.

🔴 운영자 판단 필요: 국내장 미시 규칙 데이터 원천. 거래정지, 관리종목, 투자유의, 상하한가, VI, 동시호가/단일가, corporate action calendar를 어디서 읽을지 확인 필요. 후보는 KIS REST, 한국거래소 OpenAPI, 운영자 수동 calendar다.

✅ 결정 완료(P1): dashboard 외 사고 알림은 텔레그램을 기본 메시지 채널로 쓰고, 중요한 이슈는 이메일도 함께 보낸다. 현재 구현은 로컬/텔레그램/이메일 outbox 기록까지이며 실제 발송기와 비밀값 주입은 후속이다.

✅ 결정 완료(P1): 실전 감사 원장의 1차 anchor는 로컬 append-only hash chain과 sanitized recovery export 포함/제외 self-test로 시작한다. 재난 복구용 NAS 전체 백업은 별도 이중 보관으로 유지하고, 외부 timestamp/서명 anchor는 Phase 2/3 전 별도 후보로 미룬다. sanitized NAS drill 주기와 장기 보관 기간은 후속 운영 정책으로 남긴다.

🔴 운영자 판단 필요: 세금/수수료/거래소비용 항목과 현행 세율 확인 주체. 세무 판단은 코드 기준서가 아니라 운영자/전문가 확인 대상이다.

🔴 운영자 판단 필요: `app/risk/`에 실전 risk gate를 추가할 시점과 승인 절차.

🟢 다음 단계 권장: Slice 4 live order guard를 실제 주문 경로에 연결하기 전, `app/services/live_phase_readiness.py`를 fault injection runner/report와 연결해 phase approval/readiness를 자동 기록하게 한다. Codex CLI 운영 자동화는 `app/services/codex_ops.py` manifest를 먼저 통과하도록 wrapper를 만든다.

🟢 다음 단계 권장: Phase 1 runtime flow에 `KisReadOnlyClient`를 연결하기 전, 기존 live 조회 후보 경로가 직접 `KisRestQuoteClient`를 우회하지 않는지 allowlist를 유지한다.

🟢 다음 단계 권장: 상한가/하한가/거래정지/VI/T+2/부분 체결/corporate action 중 현재 순수 로직에 들어간 항목은 fixture를 유지하고, T+2/부분 체결은 주문/계좌 sync slice에서 별도로 잠근다.

🟢 다음 단계 권장: Slice 2b 원장은 구현됐으므로, 운영 DB 적용은 `scripts/run_storage_migration_dry_run.sh`와 `scripts/apply_storage_migration.sh` plan/apply 검증을 분리해 통과한 뒤 진행한다. 그 전에는 runtime DB에 apply하지 않는다.

🟢 다음 단계 권장: paper-vs-live 격차 metric을 체결가 bps, 수량, 수익률, 슬리피지로 분해해 dashboard 누적 지표로 만든다.

🟢 다음 단계 권장: sanitized recovery export 포함/제외 self-test와 저장소 내부 dry-run 명령은 통과했다. 기존 NAS 재난 복구용 전체 백업은 별도 이중 보관 체계로 유지한다. Phase 1 전에는 `recovery-drills/phase1-readonly` 같은 별도 폴더에서 sanitized drill 표본 확인을 수행할지 장외 시간에 별도 승인으로 정한다.

🟢 다음 단계 권장: active model deployment를 장중 runtime과 분리하는 atomic registry 교체와 첫 기동 self-check 설계를 먼저 테스트한다.

관련 문서/코드 경로: `docs/Current-Implementation.md`, `docs/Order-Lifecycle.md`, `docs/Account-Safety.md`, `docs/Portfolio-And-Reconciliation.md`, `docs/Market-Schedule-Rules.md`, `docs/Universe-Freeze-Policy.md`, `app/config/settings.py`, `app/brokers/kis_quote_rest.py`, `app/services/streaming.py`, `app/services/broker_paper_sync.py`
