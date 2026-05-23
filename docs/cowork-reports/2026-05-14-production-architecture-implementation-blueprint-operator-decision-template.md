# 계좌 소유자/실전 운용 승인권자 결정 템플릿

이 파일은 `docs/Production-Implementation-Blueprint.md`의 P0/P1 결정 슬롯을 실제 결정 기록으로 옮길 때 쓰는 템플릿이다. 아직 승인 기록이 아니며, 기본값은 Codex 권장안이다.

## P0 결정

### Phase 1 read-only 차단 방식

- Codex 권장안: 별도 `KisReadOnlyClient`를 만들고 `submit_cash_order`, `cancel_order`는 메서드 자체를 노출하지 않는다.
- 기본 이유: 주문 메서드가 없으면 type 단계와 코드 리뷰 단계에서 우회 호출을 먼저 잡을 수 있다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

### VI 발동 중 open 주문 처리

- Codex 권장안: Phase 2에서는 신규 주문 금지, 기존 open 주문은 조회 보류, 잔량 취소는 cancel-only guard 통과 후 허용 후보로 둔다.
- 기본 이유: VI 구간의 체결 방식과 가격 형성이 일반 정규장과 달라 슬리피지 추정이 불안정하다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

### Phase 2 주문 타입

- Codex 권장안: 신규 진입은 지정가 only. 시장가는 기본 금지. 비상 청산 시장가는 청산 건별 수동 승인 후보로 두고, kill switch 발동 시 자동 fallback을 별도 검토한다.
- 기본 이유: Phase 2 목적은 수익 극대화가 아니라 체결 품질, 회계 정합성, 안전장치 검증이다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

### 손실 한도와 슬리피지 budget

- Codex 권장안: Phase 2 live 주문은 일일 손실 한도, 종목별 손실 한도, 주문별 슬리피지 budget 수치가 정해질 때까지 금지한다.
- 기본 이유: 수치 없는 hard limit은 invariant가 아니며, 사고 시 자동 차단 기준으로 쓸 수 없다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

### reference clock 원천

- Codex 권장안: KIS REST 응답의 HTTP `Date` 헤더 또는 KIS 응답 서버시각을 1차 reference로 쓰고, 사용할 수 없을 때 OS/NTP 확인을 보조 reference로 둔다. 수동 시각 확인은 긴급 fallback으로만 둔다.
- 기본 이유: KIS 주문/조회 경로와 같은 외부 시스템 기준을 쓰는 편이 KIS timestamp 거부와 stale 판정 위험을 가장 직접적으로 줄인다.
- 현재 구현 상태: HTTP `Date` 헤더 parser/decision helper와 readiness fixture 평가는 구현됐다. KIS REST client는 마지막 성공 응답 header를 read-only 진단용 copy로 노출한다. live order manager는 HTTP `Date` 기반 decision을 필수 submit guard 입력으로 받아 통과/차단할 수 있다. 2026-05-20 KIS paper 현재가 read-only 조회 1회에서 실제 `date` header 존재를 확인했다. runtime submit caller/readiness가 이 header에서 decision을 자동 생성해 주입하는 작업은 남아 있다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

### NAS recovery 실제 package 또는 NAS drill

- Codex 권장안: Phase 1 read-only 진입 전 장외 시간에 `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run`을 1회 완료 확인한다. 실제 NAS 공유 쓰기 백업은 별도 승인 뒤 실행한다.
- 기본 이유: self-test는 포함/제외 정책을 검증하지만 실제 export 명령 완료와 package 표본 확인을 대체하지 못한다.
- 현재 구현 상태: 저장소 내부 dry-run 명령은 통과했다. 저장소가 약 56GB이고 `runtime-data`가 약 45GB라 실제 local package 생성 또는 NAS 강제 백업은 별도 승인 없이는 실행하지 않는다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

## P1 결정

### market status 데이터 원천

- Codex 권장안: Slice 3은 fixture와 수동 calendar 기반 순수 로직으로 시작하고, KIS REST 또는 한국거래소 OpenAPI 연동은 별도 slice로 분리한다.
- 기본 이유: 외부 API 연동 전에도 gate와 상태머신 테스트를 먼저 잠글 수 있다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

### audit chain과 NAS 백업

- Codex 권장안: live 주문 관련 audit은 append-only hash chain으로 남기고, NAS recovery export self-test 통과 전에는 Phase 2 주문을 열지 않는다.
- 기본 이유: 실전 주문은 사후 추적과 복구 가능성이 안전장치의 일부다.
- 결정값: 미정
- 승인자: 미정
- 승인 시각: 미정

관련 문서/코드 경로: `docs/Production-Implementation-Blueprint.md`, `docs/Production-Architecture.md`, `docs/cowork-reports/README.md`
