# Codex work_ver_14-1: read-only system_clock probe wrapper 구현

작성: Codex
기준 리뷰: `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
직전 작업: `2026-05-21-production-architecture-implementation-blueprint-work_ver_14.md`
작업 시점 상태: `post-close`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 1. 작업 요약

`work_ver_14`에서 남긴 P0 권장안 중 fresh KIS read-only 조회 직후 sanitized `system_clock` check를 만드는 wrapper를 구현했다.

- `KisReadOnlyClient`가 주문/취소 메서드 없이 마지막 read response header copy를 노출한다.
- `probe_kis_system_clock_check()`가 read-only 현재가 조회 1회 뒤 HTTP `Date` header를 readiness `system_clock` check로 변환한다.
- `probe_kis_clock_reference.sh`가 repo 내부 JSON으로 check를 저장한다.
- 기존 `run_live_readiness_dry_run.sh --system-clock-check-path ...` 연결 테스트까지 통과했다.

이번 작업에서는 KIS 모의투자 paper 현재가 read-only 1회만 실제 호출했다. 실전 주문, 운영 DB schema apply, runtime restart는 하지 않았다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| read-only header 접근 | `KisRestQuoteClient`만 마지막 response header copy를 노출했다. Phase 1에서 쓰는 read-only wrapper 경계에서는 header를 가져올 수 없었다. | `KisReadOnlyClient.last_response_headers`가 delegate header copy를 다시 copy로 노출한다. `get_kis_readonly_client()`는 paper/live read-only client를 만들고, 기존 `get_kis_live_readonly_client()`는 live 전용 제약을 유지한다. | `app/brokers/kis_readonly.py`, `tests/test_live_readonly_guard.py` | read-only wrapper에 진단 속성이 하나 늘었지만 주문/취소 메서드는 계속 노출하지 않는다. |
| system_clock probe | HTTP `Date` parser와 readiness check builder는 있었지만 KIS read-only 조회 직후 check JSON을 만드는 caller가 없었다. | `app/services/system_clock_probe.py`가 read-only 현재가 조회 1회 후 sanitized `system_clock` check를 생성한다. raw header 원문과 예외 메시지는 저장하지 않고, source/skew/reference_time/probe metadata만 남긴다. | `app/services/system_clock_probe.py`, `tests/test_kis_clock_reference_probe.py` | broker header가 없거나 비표준이면 readiness가 `not_verified`/`invalid_fixture`로 막힌다. 안전 측 동작이다. |
| CLI wrapper | `run_live_readiness_dry_run.sh --system-clock-check-path`에 넘길 파일을 만드는 표준 wrapper가 없었다. | `scripts/probe_kis_clock_reference.py`와 `scripts/probe_kis_clock_reference.sh`를 추가하고 `scripts/script_dispatch.sh`에 연결했다. 기본 mode는 `paper`, output은 `runtime-data/reports/live-readiness/system-clock-check.json`이다. | `scripts/`, `runtime-data/reports/live-readiness/` | 실제 실행 시 KIS token/quote read가 필요하다. 실패해도 주문은 나가지 않지만 readiness는 통과하지 않는다. |
| 기준 문서/진행판 | `fresh KIS read-only probe/caller`가 남은 작업으로 표시됐다. | 기준 문서와 진행판을 “wrapper 구현 완료, 실제 KIS paper/live 실행 증적과 live header shape 확인 남음”으로 갱신했다. | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/Production-Transition-Progress.md`, `README.md`, `AGENTS.md`, `docs/logbook.md` | 실제 실행 증적까지 완료된 것으로 오해하지 않도록 명시했다. |

## 3. 현재 닫힌 항목과 남은 항목

닫힘:

- read-only wrapper에서 마지막 response header copy 접근.
- KIS read-only 현재가 조회 기반 `system_clock` check 생성 helper.
- CLI wrapper와 script dispatch 연결.
- raw HTTP `Date` 원문 및 broker exception message 비노출 테스트.
- `run_live_readiness_dry_run.sh --system-clock-check-path` 연결 회귀 테스트.
- KIS paper read-only probe 1회 실행 증적: `system_clock=true`, skew 약 0.167초.
- 생성된 `system_clock` check가 readiness dry-run에서 `system_clock=true`로 병합되는지 확인. 다른 fixture가 없어 전체 readiness는 `blocked`.

남음:

- Phase 1 승인 뒤 live account read-only header shape 확인.
- generated `system_clock` check를 장전 readiness 절차에 자동으로 넣을지, 수동 명령으로 둘지 결정.
- NAS 실제 package/복구 drill.

## 4. 검증

- `python -m unittest tests.test_live_readonly_guard tests.test_kis_clock_reference_probe tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_live_client_isolation tests.test_kis_http_clients tests.test_live_order_manager`
  - 통과, 84개.
- `python -m py_compile app/brokers/kis_readonly.py app/services/system_clock_probe.py scripts/probe_kis_clock_reference.py tests/test_kis_clock_reference_probe.py tests/test_live_readonly_guard.py`
  - 통과.
- `bash -n scripts/probe_kis_clock_reference.sh scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과.
- `./scripts/probe_kis_clock_reference.sh --mode paper --output-path runtime-data/reports/live-readiness/system-clock-check.json`
  - 통과. `system_clock=true`, skew 약 0.167초.
- `./scripts/run_live_readiness_dry_run.sh --system-clock-check-path runtime-data/reports/live-readiness/system-clock-check.json --report-path runtime-data/reports/live-readiness/latest-readiness.json`
  - 통과. `system_clock=true` 병합, 전체 readiness는 다른 fixture 미제공으로 `blocked`.

## 5. Cowork 리뷰 요청

다음 리뷰에서는 아래만 보면 된다.

1. `KisReadOnlyClient.last_response_headers`를 read-only wrapper에 노출하는 것이 주문 메서드 구조적 차단 원칙을 약화하지 않는지.
2. `probe_kis_system_clock_check()`가 raw header 원문과 예외 메시지를 저장하지 않는 방식이 감사/디버깅과 보안 사이에서 적절한지.
3. `probe_kis_clock_reference.sh` 기본 mode를 `paper`로 두고, live는 Phase 1 승인 뒤 별도 실행하는 절차가 안전한지.
4. paper probe 증적을 Phase 1 readiness 판단 자료로 충분히 볼 수 있는지, live account header shape 확인 전까지 어떤 blocker로 남길지.

## 6. 다음 권장 작업

🟢 Codex 권장안:

- live account header shape 확인은 Phase 1 read-only 승인 뒤 별도 작업으로 둔다.
- system clock probe는 장전 readiness 절차에 자동 포함할지, 운영자가 명령으로 호출할지 결정한다. Codex 권장안은 Phase 1 동안 수동 명령으로 실행해 증적을 모으고, false alarm이 없으면 자동화하는 것이다.

🔴 운영자 판단 필요:

- live account read-only probe 실행 시점.
- NAS 실제 package/복구 drill 실행 시점과 용량/경로 제한.
