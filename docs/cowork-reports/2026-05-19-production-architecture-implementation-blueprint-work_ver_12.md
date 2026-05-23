# Codex work_ver_12: review_ver_11 반영 계획과 장중 보호 상태

작성: Codex
기준 리뷰: `2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`
현재 상태: 2026-05-19 정규장, live runtime `paper` 모드 실행 중
주의: 장중 수집 보호 모드라 루트 코드 변경은 하지 않고, 반영 계획과 우선순위만 정리했습니다.

## 1. review_ver_11 결론

cowork는 `work_ver_11` 시리즈를 그대로 사용 가능하다고 평가했습니다. 다만 Phase 1 진입 전 마지막 P0로 아래 3개를 우선 보강하라고 봤습니다.

1. NAS 복구 drill 결과 검증.
2. KIS 실제 응답 fixture와 `snapshot_from_kis_daily_order_fill()` 매핑 검증.
3. WebSocket keepalive + reconnect metric 코드 검증.

Codex도 이 우선순위에 동의합니다. 특히 2026-05-18 장중 KIS WebSocket 반복 재연결 관찰 때문에 3번은 Phase 2 주문 전이 아니라 Phase 1 readiness 관측 전부터 지표화하는 쪽이 안전합니다.

관련 문서/코드 경로: `docs/cowork-reports/2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`, `app/brokers/kis_quote_ws.py`, `app/services/live_execution_sync.py`, `scripts/wsl_ops.py`

## 2. 코드 상태 빠른 대조

| cowork 지적 | 현재 확인 | Codex 판단 |
|---|---|---|
| Phase 2 `max_order_qty=1` | `max_order_qty` 정책은 아직 검색되지 않음. 현재는 금액 한도 중심. | Phase 2 canary 의도와 맞추려면 추가 필요. |
| WS keepalive/reconnect metric | `ping_interval=None`, `ping_timeout=None`, `reconnect_attempt` 누적 카운터만 확인. | 누적/연속 reconnect 분리와 reconnect storm metric 필요. |
| KIS 실제 응답 fixture 검증 | paper fixture export/redaction helper는 있음. 실제 응답 fixture 기반 mapper 확장은 후속. | Phase 1 read-only 전 또는 병행 P0로 유지. |
| NAS 복구 drill | recovery export self-test는 있음. 실제 NAS 공유 복구 drill은 후속. | Phase 1 진입 전 1회, Phase 2 진입 전 1회 권장. |
| reference clock 원천 | `system_clock.py` 순수 helper와 guard hook은 있음. 원천 미결. | KIS read-only HTTP 응답 `Date` 후보를 1순위로 검토. |
| 비주문 audit event | 주문 audit 필수 field 강제는 있음. 비주문 sentinel/chain 분리는 후속. | Phase 2 전 sentinel 정책부터 문서화 권장. |

관련 문서/코드 경로: `app/services/live_order_manager.py`, `app/services/system_clock.py`, `app/services/live_audit.py`, `app/services/market_data_freshness.py`

## 3. 다음 구현 순서 권장

장중에는 문서/읽기 전용 점검만 하고, 장 종료 후 아래 순서로 구현합니다.

| 순서 | 작업 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|---|
| 1 | WS reconnect metric | reconnect attempt가 누적 카운터처럼만 보이고 성공 후 연속 실패 reset 없음. | 누적 reconnect, 연속 reconnect, 마지막 성공 데이터 시각, reconnect storm 판단 helper/test 추가. | `app/brokers/kis_quote_ws.py`, KIS WS tests | metric hook이 과하면 정상 reconnect도 경고로 보일 수 있음. 기본 주문/수집 동작은 바꾸지 않는 방향. |
| 2 | Phase 2 `max_order_qty=1` | 주문금액 한도는 있으나 5만원 종목 2주 주문 가능. | Phase 2 기본 정책에 `max_order_qty=1` 추가, override는 명시 정책으로만 허용. | `app/services/live_order_manager.py`, tests | 기존 test fixture 중 qty>1은 정책 override가 필요할 수 있음. |
| 3 | KIS fixture mapper 검증 | paper raw 후보 export는 있으나 실제 fixture 확장 전. | redacted fixture를 테스트 fixture로 승격하고 alternate field mapping을 더 잠금. | `tests/fixtures/` 후보, `tests/test_live_execution_sync.py` | 민감정보 잔존 위험이 있어 redaction audit과 수동 확인 필요. |
| 4 | NAS 복구 drill wrapper/절차 | export self-test만 있음. 실제 NAS drill은 수동 정책. | Phase 1 전 소형 recovery drill 절차와 결과 report를 남김. | `scripts/`, `runtime-data/reports/recovery/` | 실제 NAS 접근은 외부 의존이라 실패 가능. 실패 시 Phase 진입 차단이 안전. |
| 5 | clock reference source | `±2초` 판정만 있고 기준 시각 원천 없음. | KIS read-only 응답 시간 또는 OS/NTP 관측 결과를 evidence로 저장하는 설계. | `app/services/system_clock.py`, readiness runner 후보 | 외부 시간 원천 불안정 시 readiness가 과하게 차단될 수 있음. |

관련 문서/코드 경로: `app/brokers/kis_quote_ws.py`, `app/services/live_order_manager.py`, `tests/test_live_order_manager.py`, `tests/test_kis_ws_verification.py`, `scripts/run_live_readiness_dry_run.sh`

## 4. Codex 권장안

🟢 다음 단계 권장:

- 장중에는 코드 변경하지 않고 `review_ver_11` 대응 계획만 남깁니다.
- 장 종료 후 1순위는 WS reconnect metric입니다. 2026-05-18 실제 관찰 이슈와 직접 연결됩니다.
- 2순위는 Phase 2 `max_order_qty=1`입니다. 작은 변경이지만 canary 안전 의미가 큽니다.
- KIS fixture와 NAS drill은 외부 데이터/환경 의존성이 있어, 가능한 범위의 dry-run/절차 고정부터 진행합니다.

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요:

- 실제 NAS 공유 복구 drill을 오늘 장후 바로 실행할지 여부.
- KIS 실제 응답 fixture를 cowork/테스트에 넣기 전 수동 육안 확인 방식.
- Phase 2 `max_order_qty=1`을 기본 hard limit으로 둘지, `order_policy` override를 허용할지.

관련 문서/코드 경로: `docs/cowork-reports/2026-05-19-production-architecture-implementation-blueprint-work_ver_12.md`
