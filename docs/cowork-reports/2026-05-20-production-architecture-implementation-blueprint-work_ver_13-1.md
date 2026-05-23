# Codex work_ver_13-1: Phase 1 P0 후속 보강

## 1. 작업 맥락

Claude cowork 토큰 제한으로 `review_ver_13`을 기다리는 동안, `work_ver_13` 이후 남아 있던 Phase 1 P0 항목 중 코드와 read-only 검증으로 진행 가능한 부분을 더 밀었다. 작업 시작 전 live runtime은 `post-close`에서 stopped, runtime watchdog은 running/healthy였고 `live_runtime_should_run=false`였다.

이번 작업은 KIS 실제 운용 계좌 주문, runtime restart, 운영 DB schema apply 없이 진행했다. `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값은 변경하지 않았다.

## 2. 보강 내용

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| NAS recovery dry-run | self-test는 통과했지만 실제 export dry-run 명령은 미검증이었다. | `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run` 실행을 완료했다. 출력 후보는 `.tmp-tests/recovery-dry-run/codex-recovery-dry-run-20260520-220625.tar.gz`였다. | recovery export 운영 절차 | 저장소가 약 56GB, `runtime-data`가 약 45GB라 실제 tar package 생성은 자동 실행하지 않았다. 실제 package 표본 확인 또는 NAS 강제 백업은 별도 승인 필요. |
| reference clock parser | `system_clock`은 caller가 준 reference timestamp와 local timestamp 비교만 했다. | HTTP `Date` 헤더에서 reference timestamp를 파싱하는 순수 helper를 추가했다. KIS REST 응답 header를 나중에 연결할 수 있는 형태다. | `app/services/system_clock.py`, readiness fixture | 실제 KIS response header를 runtime reference로 연결한 것은 아니다. header가 없거나 형식이 다르면 fixture/adapter 보강 필요. |
| readiness `system_clock` fixture | readiness dry-run은 `system_clock` check 슬롯만 갖고 있었다. | fixture에 `local_time`과 `reference_time` 또는 HTTP `Date` header를 주면 skew를 평가해 `ok`/`failed`로 기록한다. | `app/services/live_phase_readiness.py`, `tests/test_live_phase_readiness.py` | fixture 기반 검증이다. 실제 네트워크 시각 보정이나 KIS 호출은 하지 않는다. |
| 기준 문서 동기화 | P0 표와 결정 슬롯 일부가 `미검증` 또는 `원천 없음` 표현으로 남아 있었다. | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, 운영자 결정 템플릿에 현재 상태를 갱신했다. | 기준 문서, cowork 전달 이력 | 실제 package/NAS drill과 실제 KIS header 연결이 끝난 것처럼 읽히지 않게 명시했다. |

## 3. 현재 Phase 1 P0 상태

| P0 항목 | 현재 상태 | Codex 권장안 |
|---|---|---|
| Phase 1 read-only 구조적 차단 | `KisReadOnlyClient` 구현 완료, runtime 연결 전 | Phase 1은 주문 메서드가 없는 read-only client를 기본으로 유지 |
| live enable guard | live order guard와 KIS live order wrapper 구현 완료, streaming 연결 전 | 주문 manager와 KIS adapter 양쪽에서 `TRADING_MODE=live` + `ALLOW_LIVE_ORDERS=true` 재검증 |
| WS reconnect metric | timestamp/storm/JSON helper까지 구현 완료 | dashboard/readiness 노출은 후속으로 진행 |
| NAS recovery drill | 포함/제외 self-test와 export dry-run 명령 완료. 실제 tar package/NAS backup은 미실행 | repo size가 커서 실제 package 생성은 장외 별도 승인 뒤 진행 |
| reference clock | HTTP `Date` parser와 readiness fixture 평가 완료. 실제 KIS header runtime 연결 전 | KIS REST HTTP `Date` 또는 KIS 응답 서버시각을 1차 reference, OS/NTP를 보조 reference |

## 4. 검증

- `python -m unittest tests.test_system_clock` 통과, 9개.
- `python -m unittest tests.test_system_clock tests.test_live_phase_readiness` 통과, 19개.
- `python -m unittest tests.test_live_readiness_dry_run_script` 통과, 8개.
- `python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_system_clock tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_wsl_ops` 통과, 51개.
- `python -m py_compile app/services/system_clock.py app/services/live_phase_readiness.py tests/test_system_clock.py tests/test_live_phase_readiness.py` 통과.
- `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run` 통과.
- `du -sh .` 기준 저장소 약 56GB, `du -sh runtime-data .git` 기준 `runtime-data` 약 45GB, `.git` 약 24MB.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.
- `git diff -- app/risk config VERSION` 결과는 비어 있었다.

## 5. cowork 리뷰 요청

1. HTTP `Date` 헤더 parser를 KIS REST 응답의 1차 reference 후보로 두는 방향이 충분히 보수적인지 확인해 달라.
2. readiness `system_clock` fixture 평가를 Phase 1 fault-injection 증거로 삼되, 실제 KIS header runtime 연결 전까지 Phase 1 진입 차단으로 남기는 판단이 적절한지 확인해 달라.
3. NAS는 dry-run 명령까지만 완료하고 실제 56GB급 package 생성/NAS 강제 백업을 별도 승인으로 둔 판단이 안전한지 확인해 달라.
4. 기준 문서에서 “완료”와 “후속”의 경계가 흐릿하게 읽히는 부분이 남아 있는지 봐 달라.

## 6. 남은 위험

- 실제 KIS response header가 HTTP `Date`를 안정적으로 제공하는지는 아직 확인하지 않았다.
- `system_clock` 결과를 runtime submit guard에 기본 강제하는 연결은 아직 하지 않았다.
- 실제 recovery package 표본 확인과 NAS 공유 복구 drill은 아직 하지 않았다.
- Phase 1 runtime flow에 read-only client를 연결하고 기존 live 조회 경로의 direct client 우회를 막는 작업은 후속이다.
