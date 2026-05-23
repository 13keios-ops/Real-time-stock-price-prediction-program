# Codex work_ver_13-7: pre-open 보호 모드 next slice 설계

## 1. 작업 맥락

2026-05-21 00시대 작업 시작 시 `./scripts/get_live_runtime_status.sh`는 `session_status=pre-open`, `status=stopped`, `trading_mode=paper`였고, `./scripts/get_runtime_watchdog_status.sh`는 `market_session_status=pre-open`, `live_runtime_should_run=false`, `errors=[]`였다. 저장소 규칙상 `pre-open`은 장중 수집 보호 모드이므로 루트 코드 파일 변경, 운영 DB 접근 가능성이 있는 명령, runtime restart, 전체 테스트는 하지 않았다.

새 cowork `review_ver_*` 파일은 없어서, `work_ver_13-6` 이후 하위 설계 리포트로 남긴다.

## 2. 현재 기준

- KIS paper quote REST response header에 `date`가 있음을 2026-05-20 read-only 조회 1회로 확인했다.
- `app/services/system_clock.py`는 HTTP `Date` header를 reference timestamp와 clock decision으로 바꿀 수 있다.
- `app/brokers/kis_quote_rest.py`는 마지막 성공 response header를 read-only copy로 노출한다.
- `app/services/live_order_manager.py`는 clock decision을 필수 submit guard 입력으로 받아 broker 호출 전 통과/차단할 수 있다.
- `app/services/live_phase_readiness.py`는 raw header 원문을 저장하지 않는 sanitized `system_clock` readiness check result를 만들 수 있다.
- 남은 연결은 runtime caller/readiness runner가 fresh KIS read-only 조회 직후 header에서 decision/check를 자동 생성해 주입하는 부분이다.

## 3. 다음 코드 slice 권장안

### Slice A: KIS clock reference probe wrapper

| 항목 | 내용 |
|---|---|
| 배치 위치 | `scripts/probe_kis_clock_reference.py` 또는 기존 dispatch 기반 `scripts/run_kis_clock_reference_probe.sh` 후보 |
| 변경 전 | system clock helper는 caller가 headers를 직접 넘겨야 한다. |
| 변경 후 | KIS read-only quote 조회 1회 후 `client.last_response_headers`를 `build_system_clock_check_from_http_date_headers()`에 넘겨 sanitized JSON만 출력한다. |
| 영향 범위 | `app/brokers/kis_quote_rest.py`, `app/services/live_phase_readiness.py`, `runtime-data/reports/live-readiness/` |
| 회귀 위험 | 장중/장전 KIS read-only 호출이 token refresh를 유발할 수 있다. 주문은 아니지만 readiness 절차 안에서 호출 시각과 대상 symbol을 명시해야 한다. |
| Codex 권장안 | 기본은 KIS paper quote `005930` 1회로 시작한다. live account read-only header 확인은 계좌 소유자/실전 운용 승인권자 승인 뒤 별도 옵션으로 둔다. |

### Slice B: live readiness dry-run merge

| 항목 | 내용 |
|---|---|
| 배치 위치 | `scripts/run_live_readiness_dry_run.sh`, `scripts/script_dispatch.sh` |
| 변경 전 | readiness dry-run은 `--fixture-path`의 `system_clock` 항목을 평가한다. |
| 변경 후 | `--system-clock-check-path <repo 내부 JSON>` 옵션 후보를 추가해 probe가 만든 sanitized check를 fixture보다 우선 병합한다. |
| 영향 범위 | readiness dry-run wrapper, `tests/test_live_readiness_dry_run_script.py` |
| 회귀 위험 | fixture와 probe 결과가 동시에 있을 때 우선순위가 모호하면 readiness 통과/차단이 흔들릴 수 있다. |
| Codex 권장안 | 명시 옵션이 있을 때만 병합하고, 없으면 기존 fixture 동작을 그대로 둔다. probe 결과는 raw header 없이 `{key,status,passed,summary,details}` shape만 허용한다. |

### Slice C: submit guard 자동 주입은 마지막

| 항목 | 내용 |
|---|---|
| 배치 위치 | 이후 `app/services/streaming.py` 또는 live runtime submit caller |
| 변경 전 | `LiveOrderManager.submit_intent()`는 `clock_skew_decision`을 받을 수 있지만 caller가 자동으로 만들지는 않는다. |
| 변경 후 | Phase 2 submit 직전 fresh KIS reference clock decision을 만들고 `require_clock_skew_check=True`와 함께 넘긴다. |
| 영향 범위 | live submit caller, order manager, alert/report |
| 회귀 위험 | clock check 생성 실패가 모든 live submit을 차단한다. Phase 2 안전 기준으로는 맞지만, 장애 알림이 없으면 원인 파악이 늦다. |
| Codex 권장안 | Phase 1에서는 readiness evidence로만 사용하고, Phase 2 submit 직전부터 `require_clock_skew_check=True`를 기본으로 올린다. |

## 4. 보호 모드에서 보류한 작업

- 새 코드 파일 생성 또는 루트 코드 수정.
- KIS live account read-only 조회.
- runtime restart 또는 dashboard 재생성.
- 운영 DB schema apply.
- 전체 테스트.

## 5. cowork 리뷰 요청

1. 다음 코드 slice 순서를 `probe wrapper -> readiness merge -> submit caller 주입`으로 두는 것이 충분히 보수적인지 확인해 달라.
2. KIS paper quote로 reference clock probe를 시작하고 live account read-only header 확인은 별도 승인 뒤 진행하는 권장안이 적절한지 봐 달라.
3. probe output을 raw header 없이 sanitized check JSON으로만 남기는 방향이 감사/보안 균형상 충분한지 확인해 달라.

## 6. 남은 위험

- 실제 runtime caller 자동 주입 전까지는 Phase 1 readiness가 자동으로 KIS clock reference를 확보하지 않는다.
- live account read-only response header는 아직 확인되지 않았다.
- KIS 점검/장애 시 quote read-only 호출이 실패할 수 있으므로, failure는 `system_clock_not_verified`로 신규 주문 차단 쪽에 둬야 한다.
