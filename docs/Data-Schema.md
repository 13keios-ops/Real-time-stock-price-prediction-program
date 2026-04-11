# Data Schema Draft

## 1. 목적

이 문서는 초기 개발 시점에 필요한 최소 데이터 구조를 정의합니다.

설계 원칙:

1. 원본 이벤트와 가공 데이터를 분리합니다.
2. 모든 시각은 `Asia/Seoul` 기준으로 저장하되, 내부 저장은 명시적 타임스탬프를 사용합니다.
3. 예측 결과는 반드시 당시 입력 상태와 연결 가능해야 합니다.
4. 나중에 종목군 확대나 모델 교체가 있어도 스키마가 크게 깨지지 않도록 합니다.

## 2. 스키마 계층

초기 권장 스키마 분리:

- `master`: 종목 마스터와 기준정보
- `raw`: 원본 수집 이벤트
- `curated`: 정규화된 시세/이벤트 테이블
- `nlp`: 텍스트 이벤트 정규화와 연결 결과
- `feature`: 모델 입력 특징
- `serving`: 최신 상태와 예측 결과
- `paper`: 모의주문, 체결, 포지션, 손익
- `ops`: 리스크 이벤트와 안전장치 로그

## 3. 핵심 테이블

### 3.1 `master.symbols`

종목 마스터 테이블입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `symbol` | text PK | 내부 표준 종목코드 |
| `isin` | text null | ISIN 코드 |
| `name_kr` | text | 종목명 |
| `market` | text | KOSPI / KOSDAQ |
| `sector` | text null | 업종 |
| `is_common_stock` | boolean | 보통주 여부 |
| `is_active` | boolean | 현재 거래 가능 여부 |
| `listed_at` | timestamptz null | 상장일 |
| `delisted_at` | timestamptz null | 상장폐지일 |
| `updated_at` | timestamptz | 갱신 시각 |

### 3.2 `master.universe_membership`

초기 유니버스 편입 이력을 저장합니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `as_of_date` | date | 산출 기준일 |
| `symbol` | text | 종목코드 |
| `universe_name` | text | 예: `top_traded_value_30` |
| `universe_version` | text | 예: `univ_top_value_30_2026_04` |
| `effective_from` | date | 적용 시작일 |
| `effective_to` | date | 적용 종료일 |
| `rank_value` | numeric | 거래대금 기준값 |
| `rank_order` | integer | 순위 |
| `included` | boolean | 편입 여부 |

기본 키:

- `as_of_date`, `universe_name`, `symbol`

### 3.2b `master.universe_versions`

월간 유니버스 버전 메타정보입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `universe_version` | text PK | 버전 ID |
| `universe_name` | text | 유니버스 이름 |
| `selection_date` | date | 산출 기준일 |
| `effective_from` | date | 적용 시작일 |
| `effective_to` | date | 적용 종료일 |
| `selection_query_version` | text | 산출 로직 버전 |
| `metadata` | jsonb | 조건/통계 정보 |

### 3.2a `master.corporate_actions`

기업행위와 거래 상태 변화 이벤트입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `action_id` | bigserial PK | 이벤트 ID |
| `symbol` | text | 종목코드 |
| `action_type` | text | split / halt / resume / rights / code_change 등 |
| `effective_date` | date | 효력일 |
| `announced_at` | timestamptz null | 공지 시각 |
| `metadata` | jsonb | 배율, 사유 등 |

### 3.3 `raw.market_ticks`

실시간 체결 원본 이벤트를 저장합니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `id` | bigserial PK | 이벤트 ID |
| `source` | text | 예: `kis_ws` |
| `symbol` | text | 종목코드 |
| `event_time` | timestamptz | 거래소 기준 이벤트 시각 |
| `received_at` | timestamptz | 시스템 수신 시각 |
| `payload` | jsonb | 원본 메시지 |

### 3.4 `raw.orderbook_ticks`

실시간 호가 원본 이벤트를 저장합니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `id` | bigserial PK | 이벤트 ID |
| `source` | text | 데이터 소스 |
| `symbol` | text | 종목코드 |
| `event_time` | timestamptz | 호가 시각 |
| `received_at` | timestamptz | 수신 시각 |
| `payload` | jsonb | 원본 메시지 |

### 3.5 `raw.disclosures`

공시 원본 메타데이터입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `id` | bigserial PK | 이벤트 ID |
| `source` | text | 예: `opendart` |
| `external_id` | text | 외부 문서 ID |
| `symbol` | text null | 종목 매핑 결과 |
| `published_at` | timestamptz | 게시 시각 |
| `received_at` | timestamptz | 수집 시각 |
| `title` | text | 공시 제목 |
| `payload` | jsonb | 원본 응답 |

### 3.6 `raw.news_items`

뉴스 검색 기반 원본 메타데이터입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `id` | bigserial PK | 이벤트 ID |
| `source` | text | 예: `naver_news` |
| `external_id` | text null | 외부 ID |
| `symbol` | text null | 종목 매핑 결과 |
| `query` | text | 검색 질의 |
| `published_at` | timestamptz null | 기사 발행 시각 |
| `received_at` | timestamptz | 수집 시각 |
| `title` | text | 기사 제목 |
| `summary` | text null | 요약 |
| `url` | text null | 원문 링크 |
| `payload` | jsonb | 원본 응답 |

### 3.7 `curated.minute_bars`

1분 바를 기본 테이블로 둡니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `symbol` | text | 종목코드 |
| `bar_time` | timestamptz | 바 기준 시각 |
| `open` | numeric | 시가 |
| `high` | numeric | 고가 |
| `low` | numeric | 저가 |
| `close` | numeric | 종가 |
| `volume` | bigint | 거래량 |
| `trade_value` | numeric | 거래대금 |
| `vwap` | numeric null | VWAP |
| `trade_count` | integer null | 체결 수 |

기본 키:

- `symbol`, `bar_time`

### 3.8 `curated.orderbook_snapshots`

호가 요약 스냅샷입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `symbol` | text | 종목코드 |
| `snapshot_time` | timestamptz | 스냅샷 시각 |
| `best_bid` | numeric | 최우선 매수호가 |
| `best_ask` | numeric | 최우선 매도호가 |
| `spread` | numeric | 스프레드 |
| `bid_size_1_5` | bigint | 매수 1~5호가 잔량 합 |
| `ask_size_1_5` | bigint | 매도 1~5호가 잔량 합 |
| `imbalance_1_5` | numeric | 호가 불균형 |

기본 키:

- `symbol`, `snapshot_time`

### 3.9 `curated.market_events`

공시, 뉴스, 검색량 급증 등 모든 이벤트를 공통 구조로 정규화합니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `event_id` | bigserial PK | 이벤트 ID |
| `symbol` | text null | 종목코드 |
| `event_type` | text | disclosure / news / trend_spike 등 |
| `event_time` | timestamptz | 이벤트 기준 시각 |
| `source_table` | text | 원본 소스 |
| `title` | text null | 제목 |
| `sentiment_score` | numeric null | 감성 점수 |
| `attention_score` | numeric null | 관심도 점수 |
| `metadata` | jsonb | 추가 속성 |

### 3.9a `nlp.text_events`

정규화된 텍스트 이벤트 테이블입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `text_event_id` | bigserial PK | 이벤트 ID |
| `source_type` | text | disclosure / news / search |
| `source_id` | bigint | 원본 ID |
| `normalized_title` | text | 정규화 제목 |
| `normalized_summary` | text null | 정규화 요약 |
| `published_at` | timestamptz null | 발행 시각 |
| `received_at` | timestamptz | 수집 시각 |
| `event_type` | text null | 분류 결과 |
| `sentiment_label` | text null | positive / neutral / negative |
| `sentiment_score` | numeric null | 감성 점수 |
| `attention_score` | numeric null | 관심도 점수 |
| `is_duplicate` | boolean | 중복 여부 |
| `metadata` | jsonb | 추가 정보 |

### 3.9b `nlp.text_event_entities`

텍스트 이벤트와 종목 연결 결과입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `entity_link_id` | bigserial PK | 링크 ID |
| `text_event_id` | bigint | 텍스트 이벤트 ID |
| `symbol` | text | 연결된 종목코드 |
| `link_confidence` | text | high / medium / low |
| `link_method` | text | official_name / alias / metadata 등 |
| `is_primary` | boolean | 주요 연결 여부 |
| `metadata` | jsonb | 세부 정보 |

### 3.10 `feature.model_inputs`

실시간 추론과 학습에 사용할 특징 스냅샷입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `feature_time` | timestamptz | 특징 기준 시각 |
| `symbol` | text | 종목코드 |
| `feature_set_version` | text | 특징 버전 |
| `features` | jsonb | 특징 묶음 |

기본 키:

- `feature_time`, `symbol`, `feature_set_version`

초기 특징 예시:

- 최근 1/5/15/60분 수익률
- 최근 거래대금 급증 비율
- VWAP 괴리율
- 호가 불균형
- 최근 뉴스 건수
- 최근 공시 건수
- 검색량 변화율
- 장중 시간대 인코딩

### 3.11 `feature.labels`

학습용 정답 라벨 테이블입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `label_time` | timestamptz | 라벨 기준 시각 |
| `symbol` | text | 종목코드 |
| `horizon_min` | integer | 15 또는 60 |
| `return_pct` | numeric | 향후 수익률 |
| `label_class` | text | up / down / neutral |
| `threshold_up` | numeric | 상승 임계값 |
| `threshold_down` | numeric | 하락 임계값 |

기본 키:

- `label_time`, `symbol`, `horizon_min`

### 3.12 `serving.predictions`

실시간 예측 결과 테이블입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `prediction_id` | bigserial PK | 예측 ID |
| `prediction_time` | timestamptz | 예측 시각 |
| `symbol` | text | 종목코드 |
| `horizon_min` | integer | 15 또는 60 |
| `model_version` | text | 모델 버전 |
| `feature_set_version` | text | 특징 버전 |
| `score_up` | numeric | 상승 확률 또는 점수 |
| `score_down` | numeric | 하락 확률 또는 점수 |
| `score_neutral` | numeric | 중립 확률 또는 점수 |
| `predicted_class` | text | 최종 클래스 |
| `confidence` | numeric | 신뢰도 |
| `top_reasons` | jsonb | 상위 근거 특징 |

### 3.13 `serving.trade_signals`

예측을 주문 후보 신호로 변환한 결과입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `signal_id` | bigserial PK | 신호 ID |
| `prediction_id` | bigint | 원본 예측 ID |
| `signal_time` | timestamptz | 신호 생성 시각 |
| `symbol` | text | 종목코드 |
| `strategy_version` | text | 전략 규칙 버전 |
| `signal_side` | text | buy / flat |
| `signal_strength` | numeric | 신호 강도 |
| `allowed_to_trade` | boolean | 주문 가능 여부 |
| `blocked_reason` | text null | 차단 사유 |
| `signal_payload` | jsonb | 세부 규칙 결과 |

### 3.14 `serving.target_positions`

신호를 계좌 기준 목표 포지션으로 변환한 결과입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `target_id` | bigserial PK | 목표 ID |
| `signal_id` | bigint | 원본 신호 ID |
| `computed_at` | timestamptz | 산출 시각 |
| `symbol` | text | 종목코드 |
| `portfolio_version` | text | 자본 배분 규칙 버전 |
| `target_weight` | numeric | 목표 비중 |
| `target_qty` | integer | 목표 수량 |
| `action` | text | open / hold / reduce / close / skip |
| `reason` | text | 산출 사유 |

### 3.15 `serving.prediction_outcomes`

예측 사후 평가 결과입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `prediction_id` | bigint PK | 예측 ID |
| `actual_return_pct` | numeric | 실제 수익률 |
| `actual_class` | text | 실제 클래스 |
| `is_correct` | boolean | 적중 여부 |
| `evaluated_at` | timestamptz | 평가 시각 |

### 3.16 `paper.orders`

모의주문 엔진이 생성한 주문입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `paper_order_id` | bigserial PK | 주문 ID |
| `target_id` | bigint null | 원본 목표 포지션 ID |
| `signal_id` | bigint | 원본 신호 ID |
| `client_order_id` | text | 멱등성 키 |
| `created_at` | timestamptz | 주문 생성 시각 |
| `symbol` | text | 종목코드 |
| `side` | text | buy / sell |
| `order_type` | text | market / limit |
| `order_price` | numeric null | 주문 가격 |
| `order_qty` | integer | 주문 수량 |
| `status` | text | created / queued / sent / acknowledged / partially_filled / filled / cancelled / rejected / recovery_pending |
| `reason_code` | text null | 생성 또는 거절 사유 |

### 3.17 `paper.order_events`

주문 상태 전이 로그입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `order_event_id` | bigserial PK | 이벤트 ID |
| `paper_order_id` | bigint | 주문 ID |
| `event_time` | timestamptz | 상태 변경 시각 |
| `from_status` | text null | 이전 상태 |
| `to_status` | text | 변경 상태 |
| `event_type` | text | sent / ack / fill / cancel / recover 등 |
| `metadata` | jsonb | 응답/오류 세부 정보 |

### 3.18 `paper.fills`

모의체결 결과입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `paper_fill_id` | bigserial PK | 체결 ID |
| `paper_order_id` | bigint | 주문 ID |
| `filled_at` | timestamptz | 체결 시각 |
| `fill_price` | numeric | 체결 가격 |
| `fill_qty` | integer | 체결 수량 |
| `commission_cost` | numeric | 수수료 가정값 |
| `tax_cost` | numeric | 세금 가정값 |
| `slippage_cost` | numeric | 슬리피지 가정값 |

### 3.19 `paper.positions`

현재 모의보유 포지션 상태입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `symbol` | text PK | 종목코드 |
| `opened_at` | timestamptz | 최초 진입 시각 |
| `updated_at` | timestamptz | 최근 갱신 시각 |
| `net_qty` | integer | 순보유 수량 |
| `avg_price` | numeric | 평균 단가 |
| `market_price` | numeric | 최근 기준가 |
| `unrealized_pnl` | numeric | 미실현 손익 |
| `strategy_version` | text | 포지션 생성 전략 |

### 3.20 `paper.portfolio_snapshots`

시점별 포트폴리오 상태 스냅샷입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `snapshot_time` | timestamptz | 스냅샷 시각 |
| `cash_balance` | numeric | 현금 잔고 |
| `gross_exposure` | numeric | 총 노출 |
| `net_exposure` | numeric | 순노출 |
| `open_positions` | integer | 보유 종목 수 |
| `portfolio_value` | numeric | 총 평가자산 |

기본 키:

- `snapshot_time`

### 3.21 `paper.daily_equity`

일자별 모의투자 성과 요약입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `trade_date` | date PK | 기준일 |
| `starting_equity` | numeric | 시작 자산 |
| `ending_equity` | numeric | 종료 자산 |
| `realized_pnl` | numeric | 실현 손익 |
| `unrealized_pnl` | numeric | 미실현 손익 |
| `max_drawdown` | numeric | 당일 최대 낙폭 |
| `trade_count` | integer | 체결 건수 |

### 3.22 `ops.risk_events`

주문 차단, 데이터 지연, 손실 한도 초과 같은 운영 이벤트입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `risk_event_id` | bigserial PK | 이벤트 ID |
| `occurred_at` | timestamptz | 발생 시각 |
| `severity` | text | info / warning / critical |
| `event_type` | text | data_delay / risk_limit / api_error 등 |
| `symbol` | text null | 관련 종목 |
| `message` | text | 이벤트 메시지 |
| `metadata` | jsonb | 세부 내용 |

### 3.23 `ops.reconciliation_runs`

브로커 상태와 내부 상태, live와 replay 간 비교 실행 로그입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `reconciliation_id` | bigserial PK | 실행 ID |
| `started_at` | timestamptz | 시작 시각 |
| `ended_at` | timestamptz null | 종료 시각 |
| `reconciliation_type` | text | broker_state / live_vs_replay |
| `status` | text | running / completed / failed |
| `summary` | jsonb | 요약 결과 |

### 3.24 `ops.reconciliation_items`

재조정 실행에서 발견된 개별 차이 항목입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `item_id` | bigserial PK | 항목 ID |
| `reconciliation_id` | bigint | 실행 ID |
| `severity` | text | info / warning / critical |
| `entity_type` | text | position / fill / prediction / replay |
| `entity_key` | text | 비교 대상 식별자 |
| `expected_value` | jsonb | 기대값 |
| `actual_value` | jsonb | 실제값 |
| `message` | text | 차이 설명 |

### 3.25 `ops.replay_runs`

리플레이 실행 이력입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `replay_id` | bigserial PK | 실행 ID |
| `started_at` | timestamptz | 시작 시각 |
| `ended_at` | timestamptz null | 종료 시각 |
| `replay_type` | text | decision / full_trading |
| `date_from` | timestamptz | 재생 시작 시각 |
| `date_to` | timestamptz | 재생 종료 시각 |
| `status` | text | running / completed / failed |
| `summary` | jsonb | 요약 결과 |

### 3.26 `ops.replay_items`

리플레이 중 발견된 차이 또는 중요 이벤트입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `replay_item_id` | bigserial PK | 항목 ID |
| `replay_id` | bigint | 실행 ID |
| `severity` | text | info / warning / critical |
| `item_type` | text | prediction / signal / order / position |
| `entity_key` | text | 비교 대상 식별자 |
| `live_value` | jsonb | 실시간 값 |
| `replay_value` | jsonb | 재생 값 |
| `message` | text | 차이 설명 |

## 4. 인덱스 권장안

초기에는 아래 인덱스를 우선 둡니다.

- `minute_bars(symbol, bar_time desc)`
- `orderbook_snapshots(symbol, snapshot_time desc)`
- `market_events(symbol, event_time desc)`
- `text_events(published_at desc)`
- `text_event_entities(symbol, text_event_id desc)`
- `predictions(symbol, prediction_time desc)`
- `trade_signals(symbol, signal_time desc)`
- `target_positions(symbol, computed_at desc)`
- `paper.orders(symbol, created_at desc)`
- `paper.fills(filled_at desc)`
- `paper.order_events(paper_order_id, event_time desc)`
- `labels(symbol, horizon_min, label_time desc)`
- `corporate_actions(symbol, effective_date desc)`
- `reconciliation_runs(started_at desc)`
- `replay_runs(started_at desc)`

## 5. 보관 주기 권장안

- `raw.*`: 장기 보관
- `curated.*`: 장기 보관
- `feature.model_inputs`: 초기에는 3~6개월 보관 후 압축 검토
- `serving.predictions`: 장기 보관

## 6. 초기 구현 우선순위

처음부터 모든 테이블을 만들 필요는 없습니다.

1차 우선 구현:

1. `master.symbols`
2. `master.universe_membership`
3. `raw.market_ticks`
4. `raw.orderbook_ticks`
5. `curated.minute_bars`
6. `feature.model_inputs`
7. `feature.labels`
8. `serving.predictions`
9. `serving.trade_signals`
10. `serving.target_positions`
11. `paper.orders`
12. `paper.order_events`
13. `paper.fills`

2차 구현:

- `raw.disclosures`
- `raw.news_items`
- `nlp.text_events`
- `nlp.text_event_entities`
- `curated.market_events`
- `serving.prediction_outcomes`
- `paper.positions`
- `paper.portfolio_snapshots`
- `paper.daily_equity`
- `ops.risk_events`
- `master.corporate_actions`
- `ops.reconciliation_runs`
- `ops.reconciliation_items`
- `ops.replay_runs`
- `ops.replay_items`
