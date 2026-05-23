# Production Transition Progress

이 문서는 실전 전환 작업의 단계별 목표와 현재 진행상태를 한눈에 보기 위한 진행판이다.
작업이 끝날 때마다 Codex는 이 문서를 갱신하고, 최종 보고에 이 파일 링크를 함께 출력한다.

## 1. 갱신 규칙

- 갱신 시점: 실전 전환 관련 작업이 끝날 때마다.
- 갱신 범위: 단계 상태, 완료 항목, 남은 blocker, 다음 권장 작업, 최신 cowork 전달 파일.
- 세부 논쟁과 리뷰 전문은 `docs/cowork-reports/`에 남기고, 이 문서에는 현재 판단 기준만 남긴다.
- KIS app key, app secret, token, 계좌번호 등 비밀값은 적지 않는다.
- `app/risk/`, `config/`, `VERSION`, gate 기준값, `ALLOW_LIVE_ORDERS`는 이 진행판 갱신 목적으로 수정하지 않는다.

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/cowork-reports/`, `docs/logbook.md`

## 2. 상태 범례

| 상태 | 의미 |
|---|---|
| 완료 | 코드/문서/테스트가 현재 기준으로 닫힌 상태 |
| 진행 중 | 구현 또는 검증이 일부 끝났고 후속 연결이 남은 상태 |
| 대기 | 운영자 승인, cowork 리뷰, 장외 시간, 외부 조건을 기다리는 상태 |
| 미시작 | 아직 설계 또는 코드 작업을 시작하지 않은 상태 |
| 차단 | 다음 phase 진입 전에 반드시 해결해야 하는 blocker |

관련 문서/코드 경로: `docs/logbook.md`, `docs/cowork-reports/README.md`

## 3. 현재 스냅샷

| 항목 | 현재 상태 |
|---|---|
| 마지막 갱신 | 2026-05-23 |
| 현재 런타임 상태 | 주말 `weekend`, live runtime 중지, runtime watchdog 실행 중, trading mode `paper` |
| 작업 모드 | 비장중 코드/문서 보강 가능 모드 |
| 최신 cowork 기준 | `review_ver_15` 반영 |
| 최신 통합 리포트 | `docs/cowork-reports/2026-05-23-production-architecture-implementation-blueprint-work_ver_16.md` |
| 다음 cowork 예상 리뷰 | `review_ver_16` |

관련 문서/코드 경로: `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`, `docs/cowork-reports/2026-05-23-production-architecture-implementation-blueprint-work_ver_16.md`

## 4. Phase별 목표와 진행상태

| Phase | 목표 | 현재 상태 | 진입/통과 기준 | 남은 blocker |
|---|---|---|---|---|
| 설계 기준 정리 | 실전 전환 목표 구조, 구현 청사진, cowork ping-pong 이력 정리 | 완료 | `Production-Architecture`, `Production-Implementation-Blueprint`, cowork reports 유지 | 없음 |
| Phase 0 | 현재 paper + KIS 모의계좌 mirroring 안정화 | 진행 중 | paper-vs-broker 정합성, KIS live 데이터 품질, 장후 quick maintenance 안정 | 누적 자동 집계와 dashboard 노출은 추가 확인 필요 |
| Phase 1 | 실전 계좌 read-only 연결, 주문 금지 | 대기 | read-only client 구조적 차단, live order path hard fail, freshness/readiness 통과, sanitized 복구 drill | live account read-only shape 확인, sanitized NAS drill 표본, 실제 market status snapshot 증적, kill switch 상태 파일 |
| Phase 2 | 실전 1종목/소액 canary, 1일 1주문/1주 제한 | 미시작 | Phase 1 관측 통과, submit guard, kill switch, alert, audit, 모델 성능 선행 게이트, operator approval | Phase 1 미통과, active model 승격 기준 미충족 |
| Phase 3 | 다종목 일일 한도 운용 | 미시작 | Phase 2 20~60거래일 관측, 손실/슬리피지/체결/감사 안정 | Phase 2 미시작 |
| 지속 연구/학습 | 장중 수집과 장후 학습/개선의 분리 운영 | 진행 중 | 장중 live DB 보호, snapshot 기반 research, 장후 quick/heavy 분리 | active model 자동 승격은 계속 금지 |
| Codex 운영 자동화 | 장전 readiness, 장후 점검, 사고 triage를 Codex job으로 안전하게 구조화 | 진행 중 | dry-run report, 권한 manifest, root 적용 금지, live flag 변경 금지 | 실제 Codex CLI 자동 실행은 아직 연결하지 않음 |

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `app/services/codex_ops.py`, `scripts/run_live_readiness_dry_run.sh`

## 5. Phase 1 진입 전 P0 보드

| P0 항목 | 상태 | 현재까지 완료 | 다음 작업 | 권장안 |
|---|---|---|---|---|
| read-only 구조적 차단 | 진행 중 | `KisReadOnlyClient` 골격과 isolation 테스트 구현 | runtime/readiness flow 연결 전 최종 점검 | Phase 1 기본 client는 주문 메서드가 없는 read-only client로 고정 |
| live enable guard | 진행 중 | live order guard, KIS live order guarded adapter, submit guard 테스트 구현 | streaming/live submit caller 연결 전 clock/phase gate 자동 주입 | 주문 manager와 KIS adapter 양쪽에서 이중 확인 |
| system clock 검증 | 진행 중 | KIS REST HTTP `Date` parser, decision helper, sanitized readiness check 구현, timezone 없는/알 수 없는 timezone header invalid 차단, readiness `--system-clock-check-path` 병합 구현, read-only 현재가 조회 기반 `probe_kis_clock_reference.sh` wrapper 구현, `--compare-paper-live` paper/live reference delta 비교 helper 구현, KIS paper read-only probe 1회 성공(`system_clock=true`, skew 약 0.167초) | Phase 1 승인 뒤 live account header shape와 paper/live 비교 실행 증적 확보 | raw header 저장 금지, parsed reference time/skew/delta만 기록 |
| KIS paper/live 응답 shape | 진행 중 | KIS paper fixture export/redaction, paper quote `date` header 확인, account snapshot 필수 shape와 값 타입 자동 검증 구현 | Phase 1 read-only에서 live account 조회 shape 비교 | live 계좌는 조회만, 주문 메서드 노출 금지 |
| WS reconnect metric | 진행 중 | timestamp, storm duration, `to_dict()`, callback 안전 주석 구현, Phase 2/3 readiness와 submit guard에서 synthetic 증거 차단, dashboard readiness 카드에 evidence type/실제 증거 여부/freshness/stable frame/reconnect storm 표시 | 실제 KIS WS 관측 baseline 수집 | Phase 1은 관측만, Phase 2 submit은 real evidence type 없으면 차단 |
| market status readiness 증적 | 진행 중 | repo 내부 수동 snapshot을 읽어 `market_status` check를 만드는 `app/services/market_status_probe.py`, `scripts/probe_market_status_snapshot.sh` 구현, `docs/Manual-Market-Status-Runbook.md` 추가, 수동 source enum 고정 | 실제 거래일 snapshot 생성과 KIS/거래소 자동 원천 결정 | 데이터 원천 결정 전에는 enum으로 제한된 수동 snapshot만 허용하고, 증거 없으면 자동 통과 금지 |
| NAS recovery | 대기 | 기존 NAS 재난 복구용 전체 백업 폴더 확인, WSL `/mnt/backup` 마운트 확인, sanitized export include/exclude self-test와 NAS dry-run 완료 | `recovery-drills/phase1-readonly` 같은 별도 폴더에서 sanitized drill 표본 확인 | 기존 전체 백업은 유지하고, Phase readiness 증거는 비밀값 제외 sanitized export만 사용 |
| overnight/pre-open 상태 라벨 | 완료 | `overnight`와 60분 `pre-open` warmup 분리, watchdog 재시작 확인 | legacy PowerShell 사용 여부 확인 | WSL 정본만 쓰면 후순위, PS1 사용 시 미러링 |
| readiness 기록 저장 | 진행 중 | fixture 기반 dry-run, SQLite 기록은 `--record` 명시 때만 수행 | 실제 Phase 1 record schema 적용 여부 결정 | 장중/운영 DB schema apply 금지 유지 |
| readiness local fixture snapshot | 진행 중 | premarket report, token refresh check, synthetic WS recovery check, account snapshot check, market status check, system clock check, kill switch 상태를 읽어 로컬로 증명 가능한 항목만 fixture JSON으로 묶는 wrapper 구현. timestamp가 있는 핵심 증거는 key별 freshness를 요구한다. 실제 실행 결과 `token_refresh/ws_recovery/account_snapshot/system_clock/database/disk_space/dashboard/storage_migration_state=true`, `market_status=not_verified`, kill switch missing으로 failed | kill switch 상태 파일 생성 승인과 실제 market status snapshot 증적 확보 | 자동 통과 금지, 증거 없는 항목은 absent/not_verified 유지. Phase 2/3은 synthetic WS evidence를 통과시키지 않음 |
| 외부 알림 | 대기 | 정책 결정: Telegram 기본, 중요 사고는 email 병행 | 실제 connector/secret 관리 설계 | token/secret은 repo 문서에 기록 금지 |
| Phase 2 모델 성능 게이트 | 진행 중 | 현재 active는 `baseline-h15-v1`, LightGBM은 challenger로 유지. 최신 `latest-challengers-h15.json`은 `recommended_action=keep_active` | Phase 2 전 active model/challenger 기준을 명시하고 장후 연구축에서 통과 여부 확인 | 단순 accuracy가 아니라 독립 holdout, 비용 반영 net return, 거래 수, paper 성과, walk-forward gate를 함께 본다 |

관련 문서/코드 경로: `app/brokers/kis_readonly.py`, `app/brokers/kis_live_order.py`, `app/services/live_order_manager.py`, `app/services/system_clock.py`, `app/services/system_clock_probe.py`, `app/services/kis_token_probe.py`, `app/services/kis_account_probe.py`, `app/services/kis_ws_recovery_probe.py`, `app/services/market_status_probe.py`, `app/services/live_readiness_fixture.py`, `app/services/live_phase_readiness.py`, `app/brokers/kis_quote_ws.py`, `docs/Manual-Market-Status-Runbook.md`, `scripts/probe_kis_clock_reference.sh`, `scripts/probe_kis_token_refresh.sh`, `scripts/probe_kis_account_snapshot.sh`, `scripts/probe_kis_ws_recovery.sh`, `scripts/probe_market_status_snapshot.sh`, `scripts/build_live_readiness_fixture_snapshot.sh`, `scripts/export_kis_paper_fixture_candidates.py`

## 6. Phase별 통과 기준 초안

| Phase | 최소 관측/검증 기준 | 사람 승인 |
|---|---|---|
| Phase 0 | paper-vs-broker mismatch 0 또는 설명 가능, KIS live 데이터 품질 warning-only 관리, 장후 quick maintenance 실패 원인 추적 가능 | Phase 1 전 read-only 연결 승인 |
| Phase 1 | live 주문 함수 호출 0건, read-only 조회 stale/토큰/WS/drop/clock readiness 검증, sanitized NAS 복구 drill 1회 | Phase 2 canary 진입 승인 |
| Phase 2 | 1종목, 1주문/일, 1주 기본, 일일 손실/종목 손실/슬리피지 budget 위반 없음, audit trace 완전성, 모델 성능 선행 게이트 통과 | Phase 3 한도 확대 승인 |
| Phase 3 | 다종목 운용에서 손실 한도, 노출 한도, 체결/수수료/세금 정합성, 알림/kill switch 안정 | 한도 변경/전략 확대 승인 |

관련 문서/코드 경로: `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`

## 7. 현재 열린 결정 항목

| 구분 | 항목 | Codex 권장안 |
|---|---|---|
| 운영 | NAS 복구 drill 실행 시점 | 기존 재난 복구용 전체 백업은 유지하고, Phase 1 전 sanitized drill 표본만 별도 폴더에서 확인 |
| 운영 | Phase 1 live account read-only header 확인 허용 | 조회만 허용, 주문 메서드 없는 client로 수행 |
| 구현 | live account `system_clock` probe 실행 증적 확보 | Phase 1 read-only 승인 뒤 주문 메서드 없는 client로 1회 실행 |
| 구현 | legacy PowerShell `overnight` 미러링 | 실제 사용 중이면 Phase 1 전 반영, 아니면 후순위 |
| 구현 | WS reconnect metric submit 차단 연결 | Phase 1 관측 뒤 false positive 확인 후 결정 |
| 알림 | 외부 알림 채널 | Telegram 기본, 중요 사고는 email 병행 |

관련 문서/코드 경로: `docs/cowork-reports/2026-05-21-production-architecture-implementation-blueprint-work_ver_13.md`, `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision.md`, `docs/cowork-reports/2026-05-17-production-architecture-implementation-blueprint-operator-decision.md`

## 8. 작업 종료 시 체크리스트

매 작업 마지막에는 아래를 갱신한다.

- 이 문서의 `현재 스냅샷`.
- 해당 Phase/P0 항목의 상태.
- 최신 cowork 전달 파일 또는 리뷰 파일.
- 새 blocker와 다음 권장 작업.
- `docs/logbook.md` 최신 entry.

최종 보고에는 아래 링크를 항상 출력한다.

- `docs/Production-Transition-Progress.md`

관련 문서/코드 경로: `docs/logbook.md`, `docs/cowork-reports/README.md`
