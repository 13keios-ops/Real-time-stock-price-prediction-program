# 런타임 설정

## 역할

실행 시 어떤 설정 파일과 환경변수를 기준으로 동작하는지 정리하는 참고 문서다.

## 주요 파일

- `config/app.toml`
- `config/strategy.toml`
- `config/market_calendar.toml`
- `.env`
- `autopush.json`

## 주요 목적

- paper / live 설정 분리
- runtime-data 경로 통일
- watchlist와 전략 파라미터 분리
- KIS 자격증명은 환경변수 또는 로컬 비공개 파일에서만 관리

## 운영 원칙

- tracked repo에는 실제 비밀값을 넣지 않는다.
- 기본 실행 모드는 paper 중심으로 둔다.
- live 주문 관련 스위치는 명시적으로 꺼둔다.
- `config/market_calendar.toml`의 `holidays`는 감시기, 자동 시작, KIS 검증, 대시보드 장 상태 판단에 같이 쓰이므로 전일 휴장일 누락 여부를 장 시작 전 확인한다.
