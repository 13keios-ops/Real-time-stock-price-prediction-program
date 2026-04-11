# Runtime Configuration

## 1. 목적

이 문서는 프로젝트의 설정 체계를 정의합니다.

목표:

1. `paper`와 `live`를 명확히 분리
2. 모델/전략/DB 설정을 분리
3. 코드 수정 없이 설정만으로 운영 모드를 바꿀 수 있게 함

## 2. 설정 계층

권장 우선순위는 아래와 같습니다.

1. 코드 기본값
2. `.env` 또는 환경변수
3. 실행 시 전달되는 환경별 설정

초기 버전에서는 `환경변수 + 설정 파일` 조합이 적합합니다.

## 3. 설정 카테고리

### 앱 전역

- `APP_ENV=dev|prod`
- `APP_TIMEZONE=Asia/Seoul`
- `LOG_LEVEL=INFO|DEBUG`
- `RUNTIME_DATA_DIR=./runtime-data`

### 브로커/실행 모드

- `TRADING_MODE=paper|live`
- `ORDER_EXECUTION_ENABLED=true|false`
- `ALLOW_LIVE_ORDERS=false`

### 한국투자 paper

- `KIS_PAPER_APP_KEY`
- `KIS_PAPER_APP_SECRET`
- `KIS_PAPER_ACCOUNT_NO`
- `KIS_PAPER_PRODUCT_CODE`

### 한국투자 live

- `KIS_LIVE_APP_KEY`
- `KIS_LIVE_APP_SECRET`
- `KIS_LIVE_ACCOUNT_NO`
- `KIS_LIVE_PRODUCT_CODE`

### DB/캐시

- `POSTGRES_DSN`
- `REDIS_URL`

### 머신러닝

- `FEATURE_SET_VERSION`
- `MODEL_VERSION_H15`
- `MODEL_VERSION_H60`
- `LABEL_POLICY_VERSION`

### Codex 보조 루프

- `CODEX_REVIEW_ENABLED=true|false`
- `CODEX_REPORT_DIR=./runtime-data/reports/codex`
- `CODEX_REVIEW_SCOPE=intraday|eod|weekly`

### 전략/리스크

- `STRATEGY_VERSION`
- `MAX_POSITION_PCT`
- `MAX_OPEN_POSITIONS`
- `DAILY_LOSS_LIMIT_PCT`
- `STOP_LOSS_PCT`
- `TAKE_PROFIT_PCT`

## 4. 권장 분리 방식

### paper 전용 실행

- `TRADING_MODE=paper`
- `ORDER_EXECUTION_ENABLED=true`
- `ALLOW_LIVE_ORDERS=false`

### live 조회 전용 실행

- `TRADING_MODE=live`
- `ORDER_EXECUTION_ENABLED=false`
- `ALLOW_LIVE_ORDERS=false`

이 조합이면 live 키를 써도 주문은 나가지 않습니다.

## 5. 설정 검증 규칙

앱 시작 시 아래를 검사하는 것이 좋습니다.

1. `TRADING_MODE=paper`인데 paper 키가 없는지
2. `TRADING_MODE=live`인데 live 키가 없는지
3. `ALLOW_LIVE_ORDERS=true`인데 운영 승인 플래그가 없는지
4. live 주문이 허용된 상태인지

현재 기준으로는 `ALLOW_LIVE_ORDERS`를 항상 `false`로 둡니다.

## 6. 권장 파일 구조

```text
.env.example
.env.paper
.env.live.readonly
config/
  app.toml
  strategy.toml
  market_calendar.toml
  codex_review.toml
```

## 7. 비밀정보 관리 원칙

1. 실제 키는 저장소에 커밋하지 않음
2. `.env.example`에는 변수 이름만 둠
3. paper와 live 비밀은 물리적으로 분리
4. 로그에는 키와 계좌번호를 마스킹

## 8. 현재 권장 실행 패턴

초기 개발 단계에서는 아래 두 프로세스만 있어도 충분합니다.

### 프로세스 A

- paper 시세 수집 + 예측 + 모의주문

### 프로세스 B

- live 조회 전용 상태 점검

이 구조가 단순하고 안전합니다.

## 9. 구현 시 체크리스트

1. 설정 로더를 중앙집중식으로 둠
2. 어디서나 환경변수를 직접 읽지 않음
3. 설정값 유효성 검사를 앱 시작 시 수행
4. `paper/live` 혼용 시 프로세스를 즉시 중단
