# Codex 작업 리포트 work_ver_2: Production Implementation Blueprint 통합 보강

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_2`
- 기준 리뷰: 레거시 파일 `2026-05-14-production-architecture-implementation-blueprint-cowork-review.md`
- 다음 cowork 리뷰 권장 파일명: `2026-05-14-production-architecture-implementation-blueprint-review_ver_2.md`

이 리포트는 `2026-05-14-production-architecture-implementation-blueprint-codex-followup.md` 이후 Codex가 추가로 자율 보강한 내용까지 합친 통합 전달본이다.

## 요약

Codex는 cowork 리뷰의 운영 안전 지적을 반영한 뒤, 추가 cowork 왕복 없이 `docs/Production-Implementation-Blueprint.md`를 코드 작업 직전 수준으로 더 좁혔다. 이번 작업은 문서 작업만 수행했으며 코드, 설정값, `VERSION`, `app/risk/`, gate 기준값, `ALLOW_LIVE_ORDERS`는 변경하지 않았다. commit/push도 하지 않았다.

구조 설계 상태는 "상위 구조 설계 완료, Slice 1/2a 구현 직전 기준 보강 완료"로 본다. 남은 큰 항목은 설계 공백이라기보다 계좌 소유자 또는 실전 운용 승인권자가 확정해야 하는 손실 한도/슬리피지 budget/비상 청산 정책이다.

## 반영한 cowork 리뷰 항목

- Slice 2를 `2a`와 `2b`로 분할했다.
  - Slice 2a: `market_status_snapshots`, `live_orders`, `live_order_events`
  - Slice 2b: `live_fills`, `live_positions`, `live_portfolio_snapshots`, audit/approval/readiness
- Phase 1 read-only factory를 `live` 전용으로 좁혔다.
- 주문/취소 메서드는 hard fail이 아니라 "메서드 미노출"을 Codex 권장안으로 고정했다.
- `KisRestQuoteClient(` 직접 생성 우회 위험은 allowlist 기반 static isolation 테스트로 잠그도록 바꿨다.
- 상태머신에 `expired`를 추가했다.
- Phase 2에서는 KIS 주문 정정(modify)을 금지하고 `cancel + new submit`만 허용하도록 명시했다.
- `live_orders`, `live_fills`, `ops_live_audit_events`, `market_status_snapshots` 누락 필드를 schema 초안에 추가했다.
- `live_readiness_runs` 테이블 초안을 추가했다.
- kill switch 파일 후보 `runtime-data/reports/live-risk/kill-switch.json`의 schema, atomic write, missing/broken/stale 기본 차단 정책을 추가했다.
- storage anchor에 `RecordMixin`, `SQLiteRuntimeStore._initialize_schema()`, migration dry-run 규약을 추가했다.
- 신규 report 경로에 최초 생성 Slice를 매핑했다.

## cowork 리뷰 이후 추가 자율 보강

- Slice 1 read-only wrapper 공개 메서드 시그니처를 현재 `KisRestQuoteClient` 기준으로 정리했다.
- 기존 `KisRestQuoteClient(` 직접 생성 경로를 allowlist로 문서화했다.
  - `app/collectors/historical.py`
  - `app/services/runtime.py`
  - `app/services/collector.py`
  - `app/services/kis_account.py`
  - `app/services/broker_paper.py`
  - `app/__main__.py`
- isolation test 기준을 "직접 생성 0개"가 아니라 "새 Phase 1 live read-only 경로가 wrapper를 우회하지 않음"으로 현실화했다.
- Slice 1 acceptance criteria를 추가했다.
- Slice 1 테스트 fixture 원칙을 추가했다.
- Slice 2a dataclass 필드 초안을 추가했다.
- Slice 2a acceptance criteria를 추가했다.
- Slice 2a smoke query 후보를 추가했다.
- Slice 1 go/no-go 기준을 추가했다.
- 계좌 소유자/실전 운용 승인권자 결정 템플릿을 추가했다.

## 현재 주요 설계 결정

### Phase 1 read-only 차단

- Codex 권장안: 별도 `KisReadOnlyClient`를 만들고 `submit_cash_order`, `cancel_order`는 아예 노출하지 않는다.
- Phase 1 factory는 `get_kis_live_readonly_client(settings)`처럼 live 전용으로 둔다.
- paper mirroring은 기존 `app/services/broker_paper.py` 경로를 유지하고 readonly wrapper로 대체하지 않는다.

### Slice 1 acceptance criteria

- read-only client에 주문/취소 메서드가 없다.
- 공개 조회 메서드는 내부 delegate의 동일 메서드를 호출하고 반환값을 변형하지 않는다.
- factory는 `get_kis_profile(settings, "live")`만 사용한다.
- paper mirroring은 paper profile 경로를 유지한다.
- 새 Phase 1 live read-only 경로는 allowlist 밖에서 `KisRestQuoteClient(`를 직접 만들지 않는다.
- test fixture와 assert message에 app key, app secret, token, 계좌번호를 쓰지 않는다.

### Slice 2a acceptance criteria

- `MarketStatusSnapshot`, `LiveOrder`, `LiveOrderEvent`의 `to_record()`가 datetime을 ISO-8601 문자열로 직렬화한다.
- 새 테이블 3개와 관련 index가 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`로 생성된다.
- 기존 paper 주문/체결/포지션 write 경로가 깨지지 않는다.
- 같은 `idempotency_key`의 `live_orders` 중복 insert가 실패한다.
- status/symbol/trading_day index로 open 계열 주문을 조회할 수 있다.
- backup 뒤 schema 초기화와 smoke query가 기존 DB를 파괴하지 않는다.

### Slice 1 go/no-go

- Go: `KisRestQuoteClient.__init__`가 profile/token manager를 받는 composition 가능한 구조임을 코드로 재확인했다.
- Go: read-only wrapper는 조회 메서드만 노출하고 주문/취소 메서드를 만들지 않는다.
- Go: 테스트는 fake profile, fake token manager, mock delegate만 사용한다.
- No-go: 구현 중 live 주문/취소 호출부 수정이 필요하면 Slice 1을 중단하고 별도 설계로 분리한다.
- No-go: paper mirroring 동작 변경이 필요하면 Slice 1을 중단한다.
- No-go: `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION` 변경이 필요하면 계좌 소유자 또는 실전 운용 승인권자 승인 전까지 보류한다.
- Stop line: Slice 1은 read-only wrapper와 isolation 테스트까지만 포함하고 dashboard/report/streaming 연결은 후속 slice로 남긴다.

## 문서/파일 변경

- `docs/Production-Implementation-Blueprint.md`
  - Slice 1/2a 구현 직전 기준 보강
  - 상태머신, schema, kill switch, migration, 테스트 기준 보강
- `docs/cowork-reports/README.md`
  - 새 파일명 규칙 추가
- `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-codex-followup.md`
  - cowork 리뷰 1차 반영 이력
- `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision-template.md`
  - 결정 기록 템플릿
- `README.md`, `AGENTS.md`
  - `docs/cowork-reports/` 역할 참조
- `docs/logbook.md`
  - 작업 기록 갱신

## 검증 결과

- `git diff --check` 통과
- `app/risk/`, `app/`, `VERSION`, `config/strategy.toml` 변경 없음
- trailing whitespace 없음
- 비밀값 없음. 금지/정책 안내 문맥의 키워드만 확인됨
- `docs/Production-Implementation-Blueprint.md`와 결정 템플릿에 모호한 "운영자" 표현 없음

## 아직 남은 결정

🔴 계좌 소유자/실전 운용 승인권자 결정 필요: Phase 2 일일 손실 한도, 종목별 손실 한도, 주문별 슬리피지 budget.

- Codex 권장안: 값이 정해지기 전까지 Phase 2 live 주문은 금지한다.

🔴 계좌 소유자/실전 운용 승인권자 결정 필요: 비상 청산 시장가 예외.

- Codex 권장안: 신규 진입은 지정가 only, 시장가는 기본 금지. 비상 청산 시장가는 청산 건별 수동 승인 후보로 둔다.

🔴 계좌 소유자/실전 운용 승인권자 결정 필요: VI 발동 중 open 주문 처리.

- Codex 권장안: 신규 주문 금지, 기존 open 주문 조회 보류, 잔량 취소는 cancel-only guard 통과 후 허용 후보.

## cowork 리뷰 요청

1. Slice 1 acceptance criteria가 구현 직전 기준으로 충분한지.
2. 기존 `KisRestQuoteClient(` allowlist 방식이 우회 경로 차단으로 충분한지.
3. Slice 2a dataclass/schema/smoke query 기준이 너무 크거나 빠진 필드가 있는지.
4. Slice 1 go/no-go 기준이 실전 안전 관점에서 충분한지.
5. 다음 단계가 `Slice 1 구현`이어도 되는지, 아니면 Slice 3 market status fixture 표를 먼저 더 보강해야 하는지.

## 다음 단계 Codex 권장

다음 작업은 cowork `review_ver_2`를 받은 뒤 `work_ver_3`로 반영하거나, cowork 추가 토큰이 없으면 코드 변경 승인 후 Slice 1 구현으로 진입한다. Slice 1은 실전 주문과 연결하지 않으므로 첫 코드 작업으로 가장 안전하다.
