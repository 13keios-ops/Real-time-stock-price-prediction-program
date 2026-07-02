# Social Signal Shadow Plan

## 1. 목적

이 문서는 기업인, 주요 주식시장 발언자, 기업 공식 채널, 산업 관련 공개 채널의 SNS/공개 이벤트가 국내 주식 단기 가격 변화와 연결되는지 Phase 1부터 shadow 로 관측하기 위한 기준이다.

여기서 shadow 는 실제 주문 판단에 쓰지 않고, 같은 시각의 모델 예측, 신호, 체결, h15/h60 실제 결과와 나중에 비교하기 위한 연구 기록을 뜻한다.

Phase 1에서는 SNS 신호로 paper 주문, KIS 모의계좌 주문, 실전 주문, gate, active model, `config/`, `app/risk/`를 바꾸지 않는다.

관련 문서/코드 경로:
`scripts/summarize_social_signal_shadow.py`,
`runtime-data/social/signals/social_events.jsonl`,
`runtime-data/reports/research/latest-social-signal-shadow-h15.json`,
`docs/Current-Implementation.md`

## 2. 수집 원칙

공식 API, 공개 feed, 운영자가 직접 export 한 파일만 쓴다.

금지 범위는 아래와 같다.

- 비공개 계정, 비공개 게시물, 로그인 우회, paywall 우회, scraping 방지 우회.
- API 약관을 어기는 자동 수집.
- 원문 전체를 장기 저장해 저작권/개인정보 위험을 키우는 방식.
- SNS 이벤트 하나로 즉시 주문하는 방식.

권장 저장 방식은 짧은 excerpt, URL, source id, 작성 시각, 수집 시각, 종목 후보, 이벤트 타입, 영향 방향 후보, 신뢰도, text hash 를 저장하는 것이다. API token, bearer token, 계정 비밀번호, session cookie 는 본문과 git 추적 파일에 쓰지 않는다.

관련 문서/코드 경로:
`AGENTS.md`,
`../secrets/README.local.md`(있을 때),
`runtime-data/social/signals/`

## 3. 후보 원천

Phase 1a는 자격정보 없이 시작할 수 있는 manual/fixture JSONL 을 우선한다.

Phase 1b 이후 공식 API 연결 후보는 아래다.

- X filtered stream: 공개 post 를 rule 기반으로 거의 실시간 stream 으로 받는 공식 API 후보다. 승인된 developer 계정과 bearer token 이 필요하다.
- Bluesky firehose/Jetstream: 공개 event stream 후보다. 국내 주식 영향 계정 coverage 는 확인 필요다.
- YouTube Data API: 기업 공식 채널, IR 채널, 경제 인플루언서 채널의 신규 영상/라이브/커뮤니티 관련 공개 metadata 를 polling 한다.
- Naver Search API: 블로그/뉴스성 공개 반응을 polling 하는 후보다. 실시간 SNS라기보다 공개 반응 보조 지표다.
- Threads/Instagram 계열: 공식 API에서 실시간 공개 계정 추적이 가능한지와 약관 범위는 확인 필요다.

첫 적용 권장안은 X/Bluesky 실시간 stream 을 바로 붙이는 것이 아니라, 운영자가 고른 whitelist 계정과 키워드에 대해 manual export 또는 fixture 로 1~2주 평가하는 것이다. 그 다음 실제 API token 과 rate limit 을 확인하고 connector 를 붙인다.

관련 문서/코드 경로:
`scripts/summarize_social_signal_shadow.py`,
`runtime-data/reports/research/latest-social-signal-shadow-h15.md`

## 4. 이벤트 스키마

기본 JSONL 한 줄은 아래 필드를 권장한다.

```json
{
  "event_id": "x-20260703-example",
  "source": "x",
  "source_event_id": "123",
  "author_id": "official-or-public-id",
  "author_display": "display name",
  "published_at": "2026-07-03T09:10:00+09:00",
  "ingested_at": "2026-07-03T09:10:08+09:00",
  "url": "https://example.com/post/123",
  "symbols": ["005930"],
  "entities": ["삼성전자"],
  "event_type": "executive_comment",
  "impact_direction": "positive",
  "sentiment_score": 0.72,
  "confidence": 0.6,
  "text_hash": "sha256:...",
  "text_excerpt": "짧은 발췌만 저장",
  "language": "ko"
}
```

`impact_direction`은 `positive`, `negative`, `neutral`, `unknown` 중 하나로 시작한다.
이 값은 주문 신호가 아니라 사후 평가를 위한 가설 라벨이다.

관련 문서/코드 경로:
`runtime-data/social/signals/social_events.jsonl`,
`scripts/summarize_social_signal_shadow.py`

## 5. 평가 방법

`scripts/summarize_social_signal_shadow.py`는 이벤트 파일을 읽고 `runtime-data/dev.db`의 `feature_labels`를 read-only 로 조회한다.

평가 흐름은 아래다.

1. 이벤트의 `published_at` 이후 max lag 구간 안에서 같은 종목의 첫 h15 또는 h60 label 을 찾는다.
2. `impact_direction=positive`이면 이후 수익률이 양수일 때 방향 적중으로 본다.
3. `impact_direction=negative`이면 이후 수익률이 음수일 때 방향 적중으로 본다.
4. `neutral`은 미래 수익률 절대값이 작은 경우만 별도 평가한다.
5. source, author, event_type, impact_direction 별 표본 수와 방향 적중률, 평균 미래 수익률을 집계한다.

표본이 부족하면 수익률보다 표본 부족을 먼저 해석한다.
특정 유명 계정 1~2건의 성공은 정책 후보가 아니라 사례 기록이다.

관련 문서/코드 경로:
`scripts/summarize_social_signal_shadow.py`,
`runtime-data/reports/research/latest-social-signal-shadow-h15.json`,
`runtime-data/reports/research/latest-social-signal-shadow-h15.md`

## 6. Phase 1 적용 방식

Phase 1 적용은 아래까지만 허용한다.

- 이벤트 기록과 사후 평가 리포트 생성.
- 대시보드 또는 리포트에서 “SNS 이벤트가 있던 예측/신호/주문/체결 라인” 표시.
- 모델 입력으로 쓰기 전 후보 피처로만 기록.
- 알림은 “정보성” 또는 “확인 필요”로만 발송.

Phase 1에서 하지 않는 것은 아래다.

- SNS 이벤트로 매수/매도/청산 실행.
- `buy-avoid`, `buy-rescue`, `hold-rescue` 정책 즉시 변경.
- active model 승격 또는 gate 우회.
- 실전 계좌 주문, KIS 모의계좌 주문, paper 주문 판단 변경.

관련 문서/코드 경로:
`docs/Production-Architecture.md`,
`docs/Production-Transition-Progress.md`,
`scripts/summarize_meta_policy_shadow.py`

## 7. 통과 기준 후보

SNS 신호를 모델 피처 후보로 올리려면 최소 아래 조건이 필요하다.

- 최소 20거래일 이상 관측.
- 단일 author 가 아니라 source/event_type 기준으로 표본이 분산.
- 방향 평가 가능 이벤트 최소 100건 이상.
- 비용을 고려한 h15/h60 사후 수익률이 기존 모델 shadow 대비 개선.
- 특정 하루나 특정 종목 한두 개가 전체 성과를 끌어올리지 않음.
- API 지연, 누락, 중복, 삭제 이벤트 처리 기준이 확인됨.

이 기준을 통과해도 바로 주문 신호가 아니라 feature candidate 로만 승격한다.

관련 문서/코드 경로:
`runtime-data/reports/research/latest-social-signal-shadow-h15.json`,
`docs/Execution-Plan.md`

## 8. 현재 결정

현재 권장안은 `manual/fixture social event shadow -> read-only 사후 평가 -> source별 표본 확인 -> 공식 API 연결 여부 결정` 순서다.

Phase 1부터 같이 운용할 수 있는 범위는 “같이 수집하고 같이 평가한다”까지다.
실제 주문 정책에 반영하는 것은 Phase 1 결과와 별도 검증 뒤에만 검토한다.

관련 문서/코드 경로:
`scripts/summarize_social_signal_shadow.py`,
`scripts/summarize_meta_policy_shadow.py`,
`docs/logbook.md`
