# Codex 전달 리포트: Production Architecture 구현 청사진 보강

## 요약

Codex는 `docs/Production-Architecture.md`를 상위 기준 문서로 유지하면서, 실제 코드 작업으로 바로 넘어갈 수 있도록 `docs/Production-Implementation-Blueprint.md`를 새로 작성했다.

이번 작업은 문서 작업만 수행했으며 코드, 설정값, `VERSION`, `app/risk/`, gate 기준값, `ALLOW_LIVE_ORDERS`는 변경하지 않았다. commit/push도 하지 않았다.

## 용어 정리

문서의 "운영자"는 Claude나 Codex가 아니라 **계좌 소유자 또는 실전 운용 승인권자**를 뜻한다.

앞으로 결정 필요 항목은 단순히 판단을 요청하는 형태로 두지 않고, Codex 권장안을 함께 제시한다.

## 주요 산출물

- `docs/Production-Implementation-Blueprint.md`
  - Phase 1 read-only 구조
  - live enable guard
  - live order 상태머신
  - idempotency key와 재시작 복구
  - market status / VI / 동시호가 / 주문 타입 정책
  - SQLite schema 초안
  - service interface 초안
  - dashboard/report 초안
  - 테스트 초안
  - Slice 1~9 구현 순서
- `docs/Production-Architecture.md`
  - 새 구현 청사진 문서를 실제 작업 순서 기준으로 참조하도록 연결
- `README.md`, `AGENTS.md`
  - 핵심 문서 / 문서 역할에 새 청사진 추가
- `docs/logbook.md`
  - 작업 기록과 검증 결과 갱신

## 구현 준비 상태

다음 코드 작업은 Slice 1부터 시작할 수 있게 정리했다.

1. `app/brokers/kis_readonly.py`
   - `KisRestQuoteClient`를 composition으로 감싼 read-only wrapper
   - 조회 메서드만 노출
   - `submit_cash_order`, `cancel_order`는 노출하지 않거나 hard fail
2. `tests/test_live_readonly_guard.py`
   - live read-only client가 주문/취소를 못 하는지 확인
   - 기존 paper mirroring 경로가 깨지지 않는지 확인
3. 이후 Slice
   - Slice 2: live SQLite schema
   - Slice 3: market status 순수 로직
   - Slice 4: live order guard
   - Slice 5 이후: order manager, execution sync, audit, dashboard, NAS recovery self-test

## 검증 결과

- `git diff --check` 통과
- `app/risk/`, `app/`, `VERSION`, `config/strategy.toml` diff 없음 확인
- 새 문서 참조가 README/AGENTS/logbook/Production-Architecture에 연결됐는지 확인
- 문서에 현재 경로처럼 적은 기존 경로 존재 확인
- 새 모듈/테이블/report 경로는 `제안 신규`, `후보`, `확인 필요`로 표시
- 비밀값은 본문에 없음

## 남은 P0 결정과 Codex 권장안

🔴 Phase 1 read-only 차단 방식

- Codex 권장안: 별도 read-only client를 기본으로 한다. `ALLOW_LIVE_ORDERS=false`는 보조 방어선으로만 둔다.
- 이유: 주문 메서드 자체가 노출되지 않는 구조가 런타임 flag보다 강하다.
- 결정 필요: read-only client에서 주문/취소 메서드를 아예 만들지, 호출 시 hard fail 메서드로 둘지.

🔴 VI 발동 중 open 주문 처리

- Codex 권장안: Phase 2에서는 VI 발동 중 신규 주문 금지, 이미 open된 주문은 자동 추가 주문 없이 조회 보류로 둔다. 잔량 취소는 cancel-only guard를 거쳐 허용 후보로 둔다.
- 이유: VI 구간은 체결 메커니즘과 가격 형성이 달라 슬리피지 추정이 불안정하다.
- 결정 필요: open 주문을 유지할지, 자동 취소할지, 사람 승인 후 취소할지.

🔴 Phase 2 주문 타입

- Codex 권장안: 신규 진입은 지정가 only. 시장가는 기본 금지. 비상 청산도 처음에는 수동 승인된 경우에만 시장가 예외 후보로 둔다.
- 이유: 소액 canary 단계의 핵심 목적은 체결 품질과 회계 정합성 검증이지 빠른 포지션 확대가 아니다.
- 결정 필요: 비상 청산에서 시장가를 완전 금지할지, 수동 승인 예외로 둘지.

🔴 일일 손실 한도와 슬리피지 budget

- Codex 권장안: Phase 2는 매우 낮은 명목 손실 한도와 슬리피지 budget으로 시작하고, 값이 정해지기 전까지 live 주문은 금지한다.
- 이유: 수치 없는 hard limit은 invariant가 아니며, 실전 주문 전에 반드시 고정되어야 한다.
- 결정 필요: Phase 2 일일 손실 한도, 종목별 손실 한도, 주문별 슬리피지 budget 수치.

🔴 market status 데이터 원천

- Codex 권장안: 1차 구현은 운영자 수동 calendar + fixture 기반 순수 로직으로 시작하고, KIS REST 또는 한국거래소 OpenAPI 연동은 별도 slice로 분리한다.
- 이유: 외부 API 연결 전에도 게이트/상태머신/테스트를 먼저 잠글 수 있다.
- 결정 필요: Phase 1/2에서 자동 market status 원천을 어디까지 요구할지.

🔴 audit chain과 NAS 백업

- Codex 권장안: live 주문 관련 audit은 append-only hash chain으로 남기고, NAS recovery export self-test 통과 전에는 Phase 2 주문을 열지 않는다.
- 이유: 실전 주문은 사후 추적과 복구 가능성이 안전장치의 일부다.
- 결정 필요: hash chain anchor 방식과 보관 기간.

## Claude cowork에게 요청할 리뷰 포인트

1. `docs/Production-Implementation-Blueprint.md`의 Slice 1~4가 실제 코드 작업 단위로 충분히 잘게 나뉘었는지
2. read-only client + live order guard의 이중 차단 구조가 Phase 1 P0로 충분한지
3. live order 상태머신에서 빠진 국내 주식 특수 상태가 있는지
4. SQLite schema 초안에서 주문/체결/감사 추적에 빠진 필드가 있는지
5. "제안 신규"와 "현재 구현"의 경계가 아직 흐릿한 부분이 있는지
