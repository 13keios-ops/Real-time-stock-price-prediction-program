# Codex work_ver_13 통합본: Phase 1 P0 후속 보강과 상태 라벨 정정

작성: Codex
대상 리뷰: Claude cowork `review_ver_13`
통합 범위: `work_ver_13`, `work_ver_13-1` ~ `work_ver_13-8`
작성 시점 상태: `overnight`, live runtime `stopped`, runtime watchdog `running`, `live_runtime_should_run=false`

## 0. Claude 5시간 한도와 이번 전달 토큰 추정

Anthropic 공식 문서 기준으로 Claude 사용량 제한은 5시간 세션 단위로 리셋되지만, 정확한 토큰 총량은 고정 공개값이 아니다. 사용량은 메시지 길이, 첨부 파일 크기, 현재 대화 길이, 모델, 도구 사용, 현재 수용량에 따라 달라진다. 길이 제한은 별도 개념이고, 일반 paid plan의 대화 context window는 기본 200K tokens로 안내되어 있다.

공식 안내상 짧은 대화 기준 메시지 수 예시는 다음과 같다.

| plan | 공식 안내상 5시간 세션 예시 | 비고 |
|---|---:|---|
| Pro | 약 45 messages / 5 hours | 메시지 길이와 현재 대화 길이에 따라 변동 |
| Max 5x | 최소 225 messages / 5 hours | context window는 일반적으로 200K |
| Max 20x | 최소 900 messages / 5 hours | 실제 사용량은 변동 |
| Team premium seat | 225 messages / 5 hours | seat type 기준 |

참고 공식 문서:

- Anthropic Help Center: `Understanding Usage and Length Limits` (`https://support.anthropic.com/en/articles/11647753-understanding-usage-and-length-limits`)
- Anthropic Help Center: `About Claude's Pro Plan Usage` (`https://support.anthropic.com/en/articles/8324991-about-claude-s-pro-plan-usage/`)
- Anthropic Help Center: `About Claude's Max Plan Usage` (`https://support.anthropic.com/en/articles/11014257-about-claude-s-max-plan-usage/`)
- Anthropic Help Center: `About Claude for Work Usage` (`https://support.anthropic.com/en/articles/9267304-does-my-team-or-individual-members-have-message-limits`)

로컬 파일 크기 기준:

- `work_ver_13*` 원문 9개 합계: 41,736 bytes, 30,412 characters, 4,465 whitespace words.
- 원문 전체를 그대로 붙이면 한국어/코드/표 혼합 기준 대략 input 12K~18K tokens 정도로 추정한다.
- 이 통합본만 전달하면 대략 input 4K~7K tokens, cowork가 2K~4K tokens로 답하면 왕복 6K~11K tokens 정도로 추정한다.
- 보수 추정 상한은 15K tokens 안쪽이다. 200K context window 관점에서는 충분히 작고, 5시간 사용량 관점에서도 원문 9개 전체 전달보다 안전하다.

Codex 권장 전달 방식:

- cowork에게는 이 통합본 하나만 전달한다.
- 질문은 아래 `8. Cowork 리뷰 요청` 4개만 답하게 한다.
- 원문 확인이 꼭 필요할 때만 특정 파일명을 지정해 추가 전달한다.

## 1. 이번 통합본의 핵심 결론

`review_ver_12` 이후 Codex는 Phase 1 진입 전 P0 중 코드로 밀 수 있는 부분을 상당히 진행했다. 특히 KIS REST HTTP `Date` header를 reference clock 후보로 삼는 연결, system clock readiness check, submit guard 검증, WS reconnect metric 보강, NAS recovery dry-run, 그리고 `overnight`/`pre-open` 상태 라벨 오판 수정까지 완료했다.

하지만 Phase 1 진입 전 남은 핵심은 아직 있다.

- runtime caller/readiness runner가 fresh KIS read-only 조회 직후 `system_clock` decision/check를 자동 생성해 주입하는 실제 연결은 미완료.
- KIS live account read-only response header shape 확인은 미완료.
- WS reconnect snapshot의 dashboard/readiness read-only 노출은 미완료.
- NAS는 self-test와 `--dry-run` 명령 검증은 됐지만, 실제 tar package 생성/NAS 복구 drill은 미완료.
- legacy PowerShell 경로의 `overnight` 라벨 분리는 아직 반영하지 않았다. 현재 정본 운용은 WSL script 기준이다.

## 2. 작업별 요약

| report | 핵심 작업 | 현재 판정 |
|---|---|---|
| `work_ver_13` | `review_ver_12` 반영. WS reconnect snapshot timestamp, `to_dict()`, callback docstring, Phase 1 P0 진행표, Phase 2 `max_order_qty=1` 문서화. | 완료 |
| `work_ver_13-1` | NAS recovery export `--dry-run` 실행, HTTP `Date` parser, readiness `system_clock` fixture 평가 추가. | 코드/fixture 완료, 실제 package/NAS drill 미완료 |
| `work_ver_13-2` | `KisRestQuoteClient.last_response_headers` read-only copy 추가, HTTP `Date` -> clock decision helper 추가, stale header clear. | 완료 |
| `work_ver_13-3` | HTTP `Date` 기반 clock decision이 live order manager submit guard를 통과/차단하는 테스트 추가. | 테스트 closure 완료 |
| `work_ver_13-4` | `scripts/run_live_readiness_dry_run.sh` wrapper가 HTTP `Date` 기반 `system_clock` fixture를 통과하는 테스트 추가. | 완료 |
| `work_ver_13-5` | KIS paper REST 현재가 read-only 조회 1회로 실제 response header에 `date`가 있음을 확인. | paper quote 확인 완료 |
| `work_ver_13-6` | raw HTTP header 원문을 저장하지 않는 sanitized `system_clock` readiness check helper 추가. | 완료 |
| `work_ver_13-7` | 당시 `pre-open` 보호 모드로 판단해 코드 변경 없이 다음 slice 설계: probe wrapper -> readiness merge -> submit caller injection. | 이후 `pre-open` 라벨 오판으로 재해석 필요 |
| `work_ver_13-8` | 새벽/야간을 `overnight`, 정규장 시작 60분 전만 `pre-open`으로 분리. watchdog 재시작 후 상태 정상화. | 완료 |

## 3. 상태 라벨 이슈와 정정

사용자가 2026-05-21 00~01시대에 "지금 프리오픈이 아닌데?"라고 지적했다. 확인 결과 지적이 맞았다.

변경 전:

- `app/utils/time.py`, `scripts/wsl_ops.py`, `scripts/common_process_helpers.sh`가 정규장 시작 전 모든 시간을 `pre-open`으로 표시했다.
- `scripts/wsl_ops.py`는 warmup 여부 boolean은 계산했지만, 상태 라벨은 warmup 밖 새벽/야간에도 `pre-open`으로 반환했다.

변경 후:

- 일반 거래일 정규장 시작 60분 전부터 개장 전까지: `pre-open`
- 그보다 이른 새벽/야간: `overnight`
- 정규장: `regular-session`
- 장후: `post-close`

관련 변경:

- `app/utils/time.py`: `get_market_session_status(..., pre_open_warmup_minutes=60)`
- `scripts/wsl_ops.py`: `market_settings(root, pre_open_warmup_minutes=60)`
- `scripts/common_process_helpers.sh`: shell helper 동일 기준 반영
- `app/services/kis_verification.py`: `overnight`는 market data expected false
- `app/services/dashboard.py`: `overnight`는 정규장 장애가 아니라 장외 안내
- `AGENTS.md`, `README.md`, `docs/Current-Implementation.md`: 기준 문서 반영

재시작/확인:

- 수정 전 코드를 들고 있던 runtime watchdog만 재시작했다.
- live runtime은 재시작하지 않았다.
- 수정 후 `get_live_runtime_status`: `session_status=overnight`, `status=stopped`
- 수정 후 `get_runtime_watchdog_status`: `market_session_status=overnight`, `live_runtime_should_run=false`, `live_runtime_action=off_session_hold_overnight`

## 4. System clock / KIS HTTP Date 진행 상태

현재 구현된 것:

- KIS REST client가 마지막 성공 응답 header를 `last_response_headers`로 read-only copy 제공.
- 요청 시작 시 stale header를 먼저 비워 이전 성공 header 오용을 방지.
- HTTP `Date` header를 reference timestamp로 파싱하는 helper 추가.
- HTTP `Date` header와 local time으로 clock skew decision을 만드는 helper 추가.
- live order manager submit guard가 `clock_skew_decision`을 받아 `require_clock_skew_check=True` submit을 통과/차단하는 테스트 추가.
- readiness dry-run이 HTTP `Date` fixture를 통해 `system_clock` check를 평가하는 테스트 추가.
- sanitized readiness check helper는 raw header 원문을 저장하지 않고 source, skew, local/reference time, blocking reasons만 남긴다.
- 실제 KIS paper quote read-only 조회 1회에서 response header key `date` 존재 확인. 계좌번호, token, app key/secret은 출력/저장하지 않았다.

아직 미완료:

- runtime caller/readiness runner가 KIS read-only 조회 직후 자동으로 decision/check를 만들고 주입하는 실제 연결.
- live account read-only 응답에서도 `date` header가 동일하게 제공되는지 확인.
- raw header 저장 정책. 현재 권장안은 raw header 원문 저장 금지, parsed reference time과 skew만 감사/리포트에 기록.

Codex 권장안:

- Phase 1 readiness에서는 KIS paper quote `Date` header를 1차 reference clock 후보로 사용한다.
- live account read-only header 확인은 Phase 1 read-only 연결 직후 한 번 수행한다.
- Phase 2 submit 직전에는 fresh read-only 조회로 `system_clock` decision을 만들고, 실패 시 신규 live submit을 차단한다.

## 5. WS reconnect metric 진행 상태

현재 구현된 것:

- `KisWebSocketReconnectSnapshot`에 `observed_at`, `last_reconnect_at`, `last_stable_at`, `storm_active_since` 추가.
- `KisWebSocketReconnectSnapshot.to_dict()` 추가.
- `metrics_callback`은 동기 호출이므로 DB/file/network I/O 대신 in-memory update 또는 worker queue를 쓰라는 docstring 추가.
- callback 예외는 warning으로 흡수해 quote stream이 끊기지 않도록 유지.

아직 미완료:

- snapshot을 readiness `ws_recovery` check 또는 dashboard 카드에 read-only로 노출.
- reconnect storm을 Phase 2 submit guard 차단 조건으로 연결할지 여부. false positive 위험 때문에 Phase 1에서는 관측 지표로만 쓰는 것을 권장.

## 6. NAS recovery 진행 상태

완료:

- recovery export self-test는 새 live ops 경로 포함과 secret/log/cache 제외를 검증한다.
- `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run` 실행 완료.
- 저장소 크기 확인: repo 약 56GB, `runtime-data` 약 45GB, `.git` 약 24MB.

미완료:

- 실제 tar package 생성.
- NAS 공유 쓰기.
- 실제 복구 package 표본 확인.

Codex 권장안:

- Phase 1 진입 전 최소 1회는 장외에 실제 package 표본을 만들거나, 운영자가 NAS 경로와 용량을 승인한 뒤 강제 백업 dry-run/drill을 수행한다.
- 지금처럼 대용량인 상태에서는 Codex가 자동으로 실제 package 생성을 밀지 않는 것이 안전하다.

## 7. 검증 요약

반복 검증 중 대표 묶음:

- `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification`
- `python -m unittest tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
- `python -m unittest tests.test_kis_http_clients tests.test_system_clock`
- `python -m unittest tests.test_live_order_manager tests.test_system_clock tests.test_kis_http_clients`
- `python -m unittest tests.test_live_order_manager tests.test_live_order_guard tests.test_system_clock tests.test_kis_http_clients tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_kis_ws_reconnect_metrics tests.test_wsl_ops`
- `python -m unittest tests.test_time_utils tests.test_codex_ops tests.test_kis_ws_verification tests.test_wsl_ops`
- `python -m py_compile ...` 관련 파일 통과.
- `bash -n scripts/common_process_helpers.sh scripts/script_dispatch.sh scripts/get_live_runtime_status.sh scripts/get_runtime_watchdog_status.sh` 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error 없음.
- `git diff -- app/risk config VERSION` 결과 비어 있음.

안전 준수:

- KIS 실전 주문 없음.
- live order submit/cancel 없음.
- 운영 DB schema apply 없음.
- live runtime restart 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 자동 commit/push 없음.

## 8. Cowork 리뷰 요청

이번에는 토큰 절약을 위해 아래 4개만 답해 달라.

1. `system_clock` 기준으로 KIS REST HTTP `Date` header를 1차 reference clock 후보로 쓰고, raw header 원문은 저장하지 않는 방향이 Phase 1/2 안전 기준에 충분한가?
2. Phase 1 진입 전 반드시 끝내야 할 P0를 `runtime caller/readiness runner의 system_clock decision/check 자동 주입`, `NAS 실제 package 또는 복구 drill`, `live account read-only header shape 확인` 세 가지로 보면 되는가? 더 줄이거나 늘릴 항목이 있는가?
3. `overnight`를 Codex ops 보호 세션에서 제외하고, `pre-open`은 정규장 시작 60분 전 warmup으로만 유지하는 해석이 맞는가? legacy PowerShell 경로도 같은 라벨 분리를 Phase 1 전 필수로 봐야 하는가?
4. WS reconnect metric은 Phase 1에서는 dashboard/readiness 관측 지표로만 두고, Phase 2 submit guard 차단 조건 연결은 false positive 관측 후로 미루는 것이 적절한가?

## 9. Codex 다음 권장 작업

🟢 권장 순서:

1. `system_clock` probe wrapper 또는 readiness runner 연결을 구현한다. KIS read-only 조회 직후 sanitized check를 생성해 readiness report에 병합한다.
2. `scripts/run_live_readiness_dry_run.sh`가 외부 `system_clock` check JSON을 fixture보다 우선 병합하도록 한다.
3. Phase 2 submit caller에서는 fresh clock decision이 없으면 신규 live submit을 차단한다.
4. legacy PowerShell runtime scripts 사용 여부를 확인한다. 실제 운용이 WSL 정본이면 문서상 legacy로만 두고, Windows PS1 경로를 계속 쓰면 `overnight` 라벨을 같은 기준으로 맞춘다.

🔴 운영자 판단 필요:

- 실제 NAS package 생성/공유 쓰기 drill을 언제, 어느 용량/경로 제한으로 실행할지.
- Phase 1 read-only에서 live account header shape 확인을 허용할지.
