# Production Architecture / Implementation Blueprint work_ver_11-18

작성: Codex
목적: `work_ver_11-10`부터 `work_ver_11-17`까지 cowork 전달용 통합 요약
주의: 이 파일은 상세 이력을 대체하지 않고, cowork 토큰 절약을 위한 handoff입니다.

## 1. 이번 묶음의 핵심

이번 묶음은 새 전략이나 모델 실험이 아니라 실전 전환 안전 골격을 더 단단하게 만드는 작업입니다.

- readiness dry-run이 `system_clock`까지 포함한 10개 check를 요구하도록 확장했습니다.
- alert/order/execution sync outbox와 원장 저장 payload에 redaction을 적용했습니다.
- live position 계산에서 invalid fill side가 조용히 묻히지 않도록 카운트를 남겼습니다.
- live audit event는 핵심 trace field가 비어 있으면 생성되지 않게 했습니다.
- live order intent는 필수 trace field, side, qty, limit price를 DB write 전에 검증합니다.
- system clock skew decision을 submit guard에서 선택적으로 사용할 수 있는 hook을 연결했습니다.
- market status는 이미 submit guard 입력으로 연결된 사실을 문서에 반영했습니다.

## 2. 변경 파일 묶음

주요 코드:

- `app/services/live_phase_readiness.py`
- `app/services/live_alerting.py`
- `app/services/live_position_accounting.py`
- `app/services/live_audit.py`
- `app/services/live_order_manager.py`
- `app/services/live_execution_sync.py`
- `app/services/live_order_guard.py`
- `app/services/system_clock.py`
- `app/brokers/kis_response_redaction.py`

주요 테스트:

- `tests/test_live_phase_readiness.py`
- `tests/test_live_readiness_dry_run_script.py`
- `tests/test_live_alerting.py`
- `tests/test_live_position_accounting.py`
- `tests/test_live_audit.py`
- `tests/test_live_order_manager.py`
- `tests/test_live_execution_sync.py`
- `tests/test_live_order_guard.py`
- `tests/test_system_clock.py`
- `tests/test_kis_response_redaction.py`

문서:

- `AGENTS.md`
- `README.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`
- `docs/cowork-reports/README.md`

## 3. 검증

개별 검증:

- `tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_system_clock`: 20개 통과.
- `tests.test_live_alerting tests.test_kis_response_redaction`: 14개 통과.
- `tests.test_live_position_accounting`: 5개 통과.
- `tests.test_live_audit`: 6개 통과.
- `tests.test_live_order_manager tests.test_live_order_guard`: 22개 통과.
- `tests.test_live_execution_sync tests.test_kis_response_redaction`: 14개 통과.
- `tests.test_live_order_guard tests.test_live_order_manager tests.test_system_clock`: 30개 통과.

묶음 검증:

- `python -m unittest tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_live_alerting tests.test_kis_response_redaction tests.test_live_position_accounting tests.test_live_audit tests.test_live_order_manager tests.test_live_order_guard tests.test_live_execution_sync tests.test_kis_live_order_adapter tests.test_live_client_isolation tests.test_live_readonly_guard tests.test_live_storage tests.test_reporting tests.test_dashboard`
  - 결과: 119개 통과.
- `python -m unittest tests.test_system_clock tests.test_market_status tests.test_live_order_guard tests.test_live_order_manager tests.test_live_execution_sync tests.test_live_alerting tests.test_live_audit tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_reporting tests.test_dashboard`
  - 결과: 100개 통과.

## 4. 안전 확인

- 실전 주문 전송 없음.
- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- runtime DB 기본 쓰기 없음. 테스트는 `.tmp-tests/` 아래 격리 DB를 사용했습니다.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 실제 텔레그램/이메일 발송기 연결 없음.
- 자동 commit/push 없음.

## 5. cowork에게 묻고 싶은 점

1. `system_clock`을 readiness 필수 check로 두되 SQL 컬럼 승격 없이 `checks_json`에만 둔 것이 적절한지.
2. 운영 원장에는 redacted broker payload만 저장하고 원본 raw response는 저장하지 않는 정책이 과하게 보수적인지.
3. live audit event에서 `symbol`, `order_id`까지 필수로 강제하는 것이 주문 감사 범위에서는 적절한지.
4. invalid live order intent를 `blocked` 원장으로 남기지 않고 DB write 전에 거부하는 정책이 맞는지.
5. system clock guard hook은 기본 강제하지 않고 Phase 2 submit 직전에 `require_clock_skew_check=True`로 올리는 순서가 맞는지.

## 6. Codex 권장안

🟢 다음 단계 권장:

- Phase 1은 read-only와 readiness evidence 수집에 집중하고, `system_clock`은 fixture/dry-run evidence로만 통과시킵니다.
- Phase 2 submit 직전부터 `require_clock_skew_check=True`를 켭니다.
- 운영 원장에는 redacted payload만 남기고, 원본 broker response 별도 보관은 Phase 2 전 별도 결정으로 둡니다.
- invalid intent는 DB write 전 거부를 유지합니다.
- 비주문 audit event가 필요하면 주문 감사 builder를 느슨하게 만들지 말고 별도 builder 또는 명시 sentinel 정책을 둡니다.

🔴 운영자 판단 필요:

- `system_clock` 기준을 기본 `±2초`로 유지할지, Phase 2 전 `±1초`로 낮출지.
- 원본 broker response를 암호화 저장소에 별도 보관할지.
- 비주문/global audit event의 sentinel 정책을 둘지.
