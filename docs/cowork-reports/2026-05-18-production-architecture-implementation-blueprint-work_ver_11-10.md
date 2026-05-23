# Production Architecture / Implementation Blueprint work_ver_11-10

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: 시스템 시계 오차 점검을 Phase readiness dry-run의 필수 확인 슬롯으로 연결

## 1. 작업 요약

- `app/services/system_clock.py`로 분리한 시스템 시계 오차 순수 helper를 `app/services/live_phase_readiness.py`의 readiness check key에 연결했습니다.
- 기존 9개 check는 10개 check가 되었습니다.
  - `token_refresh`
  - `ws_recovery`
  - `account_snapshot`
  - `market_status`
  - `system_clock`
  - `kill_switch`
  - `database`
  - `disk_space`
  - `dashboard`
  - `storage_migration_state`
- `system_clock`은 실제 네트워크 시각 보정, NTP 호출, KIS 호출을 하지 않습니다.
- readiness dry-run에서 fixture 또는 명시 override가 없으면 `system_clock_not_verified_*` 이유로 Phase readiness가 차단됩니다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | 시스템 시계 오차 `±2초` 후보는 순수 helper와 단위 테스트까지만 있었고, Phase readiness dry-run에는 연결되지 않았습니다. |
| 변경 후 | `system_clock`이 readiness 필수 check key가 되어, fixture가 없으면 `not_verified`로 차단됩니다. |
| 영향 범위 | `app/services/live_phase_readiness.py`, readiness dry-run script의 출력 payload, `checks_json` 내부 check 목록, 관련 문서/테스트 |
| 회귀 위험 | 기존 fixture 파일에 `system_clock`이 없으면 readiness dry-run이 `blocked`가 됩니다. 이는 안전 측 동작입니다. SQL schema 변경은 없고 새 check는 `checks_json`에만 저장됩니다. |

## 3. 검증

- `python -m py_compile app/services/live_phase_readiness.py app/services/system_clock.py tests/test_live_phase_readiness.py tests/test_live_readiness_dry_run_script.py tests/test_system_clock.py`
- `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_system_clock`
- 결과: 20개 테스트 통과.

## 4. 안전 확인

- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- runtime DB 기본 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 실전 주문 경로 연결 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. `system_clock`을 readiness 필수 check로 넣되 SQL 컬럼 승격 없이 `checks_json`에만 두는 방향이 충분히 보수적인지 확인 부탁드립니다.
2. fixture 누락 시 readiness를 차단하는 정책이 Phase 1 read-only 준비 기준으로 과하거나 약하지 않은지 봐 주세요.
3. 다음 단계에서 기준 시각 원천을 실제로 연결할 때, KIS 응답 시간 기준과 OS/NTP 기준 중 어느 쪽을 우선 후보로 문서화해야 하는지 운영 안전 관점에서 의견 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: 기준 시각 원천은 바로 자동 연결하지 말고, Phase 1에서는 `system_clock` fixture를 장전 수동 dry-run evidence로만 채우는 방식을 권장합니다. 이후 KIS read-only API 응답 헤더 또는 별도 NTP 관측을 비교한 뒤 주문/취소 guard에 연결하는 순서가 안전합니다.

🔴 운영자 판단 필요: Phase 1 진입 전 `system_clock` 기준을 `±2초`로 확정할지, 더 보수적으로 `±1초`로 둘지 결정이 필요합니다. 현재 Codex 권장안은 `±2초`입니다.
