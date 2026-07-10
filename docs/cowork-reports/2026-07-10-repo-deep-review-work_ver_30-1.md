# 2026-07-10 Repository Deep Review Work Ver 30-1

## 범위

기준 문서에 정리됐지만 실제 구현이 끝나지 않은 항목을 완료 증거 기준으로 다시 감사했다. 이번 후속의 P0는 paper/KIS mismatch가 다음 거래일 장후에도 남을 경우 KIS order-fill 호출량을 줄이는 작업이다.

## 발견

2026-07-10 장후 mismatch는 4종목으로 계속 남았고, 주문·체결 조회는 `EGW00201` 뒤 10/30/60초를 기다리며 같은 실행 안에서 재호출했다. 실행 계획의 “mismatch 지속 시 호출량 축소” 조건은 충족됐지만 아래 운영 경로는 아직 다중 재시도 상태였다.

- 기본 `BrokerPaperMirror.fetch_recent_order_fills()`: 최대 4회
- 장후 `sync_broker_paper_orders()`: 최대 5회
- 장중 종료 `flush() -> force sync`: 기본 재시도 사용 가능

## 적용

- 세 운영 경로 모두 한 실행당 KIS order-fill HTTP 호출을 1회로 제한했다.
- 최초 `EGW00201`부터 `cooldown_active=true`, `retry_after_seconds=7200`을 기록한다.
- 2시간 안의 후속 실행은 실제 KIS endpoint를 호출하지 않고 `skipped_broker_call=true`로 끝난다.
- 기본 helper의 단일 호출, 장후 batch 기본값, 종료 force sync를 각각 테스트로 잠갔다.
- 종료 전 자기검토에서 default dry-run이 authoritative recheck 요약을 덮는 문제를 발견해 실제 실행과 attempt 출력 파일을 분리했다.
- 보존된 sync·reconciliation·trace 증거로 최신 recheck 요약을 정직하게 복원하고, dry-run 전후 SHA-256 동일성을 확인했다.
- `Current-Implementation`, KIS runbook, daily ops skill, 실행 계획, Phase 진행판을 같은 정책으로 동기화했다.

## 결과

- 관련 단위 테스트: 28개 통과.
- 전체 unittest: 464개 통과.
- 전체 pytest: 464개 및 subtest 62개 통과.
- 최신 mismatch: `035420`, `086520`, `105560`, `247540` 4종목.
- 자동 align, `SyncInitialCash`, 주문 정책, active model, gate 변경 없음.

## Codex 의견

이번 변경은 체결 복구 속도를 높이는 작업이 아니라 모의투자 REST 제한을 반복해서 자극하지 않도록 감사 경로를 안정화하는 작업이다. 최대 2시간 동안 체결 원장 복구가 늦어질 수 있지만, 제한 상태에서 여러 번 호출하고 불완전한 원장을 계좌 정렬로 덮는 것보다 안전하다.

현재 4종목 문제는 로컬 원장 자체보다 KIS 계좌 snapshot과 KIS order/fill 원장이 서로 다른 상태다. 그러므로 코드에서 수량을 강제로 맞추지 않고 다음 거래일 장후 1회 비교를 유지한다.

## 다음 방향

- 다음 장전 08:20~08:40: ws recovery와 read-only probe 3종, fail-closed market status/kill switch readiness를 최신화한다.
- 2026-07-20 장후: 사전등록된 E1 재측정과 E5 역발상 관찰을 한 라운드로 수행한다.
- 그 전까지 신규 threshold/EV tuning, 종목별 주문 정책, h60 정책, active model/gate 변경은 하지 않는다.
- 다음 cowork 리뷰는 2026-07-20 E1/E5 결과가 나온 뒤가 적절하다.
