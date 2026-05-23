# Codex work_ver_11-3: Phase 2 부모 주문 한도 카운터와 pre-submit context

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_11-3`
- 기준 리뷰: `review_ver_10`
- 사유: cowork 토큰 제한 중이라 KIS 실제 응답 sample 없이 진행 가능한 운영 안전 보강을 계속 진행했다.

## 시작 전 상태

- `./scripts/get_live_runtime_status.sh`: `status=stopped`, `session_status=weekend`, `trading_mode=paper`, live runtime 실행 없음.
- `./scripts/get_runtime_watchdog_status.sh`: `status=running`, `market_session_status=weekend`, `live_runtime_should_run=false`.
- 실제 KIS live 주문/취소/조회 호출 없음.

## 변경 요약

1. `app/services/live_order_manager.py`
   - Phase 2 pre-submit 기본 정책 대상에 `phase2_canary`를 추가했다.
   - 기존 차단 사유 문자열은 유지했다.
   - `pre_submit_policy_context`를 order detail에 남긴다.
   - 기록 항목: phase, 부모 주문 한도, 현재 부모 주문 수, 남은 부모 주문 수, 같은 종목 pending 수, live fill mismatch 수.

2. `app/services/live_order_monitoring.py`
   - `build_live_phase2_parent_order_limit_summary_from_store()`를 추가했다.
   - 거래일별 Phase 2 부모 주문 수/한도, 차단 여부, 한도에 포함된 주문 ID를 read-only로 요약한다.

3. `app/services/dashboard.py`
   - `live_phase2_parent_order_limit` payload를 추가했다.
   - `실 운용계좌` 탭에 `Phase 2 부모 주문 한도`, `Phase 2 부모 주문 상세` 카드를 추가했다.
   - 이 카드는 SQLite read-only 조회만 하며 주문/체결/포지션 상태를 바꾸지 않는다.

4. `app/services/reporting.py`
   - runtime report JSON/Markdown에도 `Live Phase 2 Parent Order Limit` 요약을 추가했다.
   - summary에 `live_phase2_parent_orders`, `live_phase2_parent_order_limit_blocked`를 기록한다.

5. `app/services/live_alerting.py`
   - live fill mismatch와 live order attention alert id를 생성 시각이 아니라 state fingerprint 기반으로 만들었다.
   - 같은 event type/trading day/state fingerprint의 동일 alert는 같은 날짜 outbox에 중복 append하지 않는다.
   - 실제 텔레그램/이메일 발송은 여전히 하지 않는다.

6. 문서
   - `docs/Production-Architecture.md`
   - `docs/Production-Implementation-Blueprint.md`
   - `docs/cowork-reports/README.md`
   - `docs/logbook.md`

## 검증

- `python -m py_compile app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py` 통과.
- `python -m unittest tests.test_live_order_manager tests.test_dashboard` 통과, 27개.
- `python -m py_compile app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py app/services/reporting.py` 통과.
- `python -m unittest tests.test_live_order_manager tests.test_dashboard tests.test_reporting` 통과, 28개.
- `python -m py_compile app/services/live_alerting.py app/services/reporting.py` 통과.
- `python -m unittest tests.test_live_alerting tests.test_reporting tests.test_live_order_manager tests.test_dashboard` 통과, 36개.
- `python -m py_compile app/brokers/kis_response_redaction.py app/services/live_alerting.py app/services/reporting.py app/services/live_order_manager.py app/services/live_order_monitoring.py app/services/dashboard.py` 통과.
- `python -m unittest tests.test_kis_response_redaction tests.test_live_alerting tests.test_reporting tests.test_live_order_manager tests.test_dashboard` 통과, 38개.
- `python -m unittest discover -s tests -p "test_*.py"` 통과, 237개.
- `git diff --check` 통과. 단, `docs/logbook.md` CRLF/LF 정규화 경고가 함께 표시됐다.
- `git diff -- app/risk VERSION config` 출력 없음.
- 전체 테스트와 `git diff --check`는 이 파일 작성 뒤 실행 예정.

## 의도적으로 하지 않은 것

- 실제 KIS live 주문/취소/조회 호출 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- `max_parent_orders_per_day`를 설정 파일로 옮기지 않았다. 현재는 Phase 2 기본값 1과 request `order_policy` override 구조를 유지한다.
- 자동 commit/push 없음.

## cowork 리뷰 요청

1. `phase2_canary`를 Phase 2 pre-submit 기본 정책 대상에 포함한 것이 안전 측에서 적절한가?
2. 차단 사유 문자열은 안정적으로 유지하고, 상세 숫자는 `pre_submit_policy_context`에 분리한 설계가 감사/운영 관점에서 충분한가?
3. dashboard와 runtime report 양쪽에 Phase 2 부모 주문 카운터를 노출한 범위가 적절한가?
4. state fingerprint 기반 alert id와 같은 날짜 outbox 중복 append 억제가 sender 전 단계 false alarm 완화로 충분한가?
5. `max_parent_orders_per_day` 설정 분리는 Phase 3 전으로 미뤄도 되는가?

## 다음 단계 권장

🟢 다음 단계 권장: KIS 실제 주문/체결 조회 응답 sample을 비밀값 제거 후 fixture로 추가해 `snapshot_from_kis_daily_order_fill()` field mapping을 더 잠근다.

🟢 다음 단계 권장: alert sender는 outbox reader로 별도 slice를 만들고, 실제 발송은 환경변수 또는 로컬 secrets 파일에서만 자격정보를 읽게 한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: Phase 2 주문 금액 한도와 audit hash chain 외부 anchor/보관 정책.
