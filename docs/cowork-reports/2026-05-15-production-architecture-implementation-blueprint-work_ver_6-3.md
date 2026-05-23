# Codex 통합 리포트 work_ver_6-3: review_ver_5 반영 + Slice 2b + Codex CLI 운영 자동화 설계

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_5.md`
- 포함 범위:
  - `work_ver_6`: review_ver_5 즉시 보강
  - `work_ver_6-1`: Slice 2b live 체결/포지션/감사/승인/readiness 원장
  - `work_ver_6-2`: phase approval/readiness record service
  - 추가 설계: 장전 준비, 장후 학습, 장중 장애 대응에서 Codex CLI를 운영 보조로 호출하는 구조
- 시작 전 상태:
  - `get_live_runtime_status.sh`: `status=stopped`, `session_status=post-close`, `trading_mode=paper`
  - `get_runtime_watchdog_status.sh`: watchdog running, `market_session_status=post-close`, `live_runtime_should_run=false`
- 금지 준수:
  - 실전 주문 API 호출 없음
  - 운영 DB `runtime-data/dev.db` migration apply 실행 없음
  - `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음
  - 자동 commit/push 없음

## 2. 구현 완료 요약

| 영역 | 완료 내용 | 대표 파일 |
|---|---|---|
| review_ver_5 보강 | SQLite native backup/restore, watchdog 정지 확인, sample smoke check, phase unknown 차단 | `app/storage/sqlite_store.py`, `scripts/script_dispatch.sh`, `app/services/live_order_guard.py` |
| Slice 2b 원장 | live fill/position/portfolio/audit/approval/readiness dataclass, table, writer, smoke test | `app/storage/contracts.py`, `app/storage/sqlite_store.py`, `app/storage/runtime_writer.py`, `tests/test_live_storage.py` |
| approval/readiness record | approval hash, readiness hash, active approval 조회 | `app/services/live_phase_readiness.py`, `tests/test_live_phase_readiness.py` |
| 기준 문서 | 구현 상태와 다음 권장 순서 반영 | `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md` |

## 3. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|
| DB 백업/복구가 file copy 기반으로 남을 수 있었다. | SQLite native backup/restore 사용. | storage migration, 운영 DB apply 준비 | native backup 중 DB lock이 있으면 실패 가능. service stop check로 완화 |
| migration apply가 live runtime/dashboard만 봤다. | runtime watchdog running도 차단 조건으로 추가. | 운영 DB schema apply | watchdog을 먼저 stop해야 해 절차가 늘어남 |
| smoke check가 table/index 존재만 확인했다. | Slice 2a/2b table에 sample insert/read/delete 수행. | schema apply 안전 검증 | smoke가 더 엄격해져 누락 schema를 즉시 차단 |
| phase 문자열 오타가 silent bypass 가능했다. | known phase 검증, 미등록 phase는 `phase_unknown`. | live order guard | 새 phase 추가 시 guard 목록 갱신 필요 |
| live 실전 체결/포지션/감사 원장이 없었다. | `live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs` 추가. | 향후 execution sync/order manager/dashboard | KIS 실제 응답 field mapping은 후속 확인 필요 |
| phase 승인/readiness가 문서나 bool 후보에 가까웠다. | approval/readiness hash record 생성 helper와 active approval 조회 추가. | Phase 1/2 readiness 기록 | fault injection runner와 dashboard 연결은 아직 없음 |

## 4. Codex CLI 운영 자동화 포함 설계

### 4.1 결론

장전 준비, 장후 학습, 장중 버그 대응에서 Codex CLI를 호출하는 구조화는 가능하다. 단, Codex CLI는 자동매매 판단자나 주문 실행자가 아니라 운영 보조 에이전트로 격리해야 한다. 실전 주문 submit/cancel, `ALLOW_LIVE_ORDERS` 변경, gate 기준값 변경, `app/risk/` 변경은 Codex CLI 자동 작업 범위 밖에 둔다.

관련 문서/코드 경로: `AGENTS.md`, `docs/Production-Architecture.md`, `docs/Production-Implementation-Blueprint.md`, `scripts/`, `runtime-data/reports/codex/`

### 4.2 권장 job 종류

| Job | 실행 시점 | Codex CLI 역할 | 기본 권한 |
|---|---|---|---|
| premarket-readiness | 장전 | runtime/watchdog/KIS credential/storage/market status/approval 상태 점검, readiness report 생성 | 읽기 중심, report 생성 |
| postclose-research | 장후 | snapshot DB 기반 학습/분석/결과 해석/다음 실험 제안 | 격리 snapshot과 `.tmp-tests/` 중심 |
| intraday-incident-triage | 장중 장애 | 로그/상태 파일 분석, 원인 후보, patch 초안, 운영자에게 조치안 제시 | 읽기 전용 + 격리 patch 초안 |
| postclose-maintenance-review | 장후 자동관리 후 | quick maintenance 결과, dashboard freshness, paper/broker gap 검토 | report 생성 |
| cowork-handoff | 필수 리뷰 시점 | Claude cowork 전달용 요약 리포트 생성 | 문서 생성 |

관련 문서/코드 경로: `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`, `scripts/run_post_close_ml_maintenance.sh`, `scripts/create_research_db_snapshot.sh`, `runtime-data/reports/ml-maintenance/`, `docs/cowork-reports/`

### 4.3 제안 신규 배치

| 제안 신규 경로 | 책임 |
|---|---|
| `scripts/run_codex_ops_job.sh` | 장 상태 확인, job type 검증, Codex CLI 호출 wrapper |
| `app/services/codex_ops.py` | job manifest, 허용 권한, 입력 snapshot, 출력 report schema 정의 |
| `runtime-data/reports/codex/ops/` | 장전/장후/장중 Codex job 결과 JSON/Markdown 저장 |
| `runtime-data/reports/codex/ops/latest-job.json` | 최신 job 상태 |
| `.tmp-tests/codex-ops/` | 장중 격리 테스트/patch draft 작업 위치 |

관련 문서/코드 경로: `scripts/`, `app/services/`, `runtime-data/reports/codex/`, `.tmp-tests/`

### 4.4 장 상태별 권한 모델

| 장 상태 | 허용 | 금지 |
|---|---|---|
| pre-open / regular / live_runtime_should_run=true | 상태 조회, 로그 분석, report 생성, 격리 patch 초안 | root 코드 수정, full test, DB migration, runtime restart, `python -m app ...`, 실전 주문 관련 flag 변경 |
| post-close | 코드 수정, 테스트, 문서 갱신, snapshot 기반 연구 | 실전 주문 API 호출, gate 기준값 무승인 변경, 운영 DB apply 무승인 실행 |
| holiday / off-session | 장후와 유사하되 live runtime 재기동은 market calendar 기준 확인 | 휴장일 WebSocket 무한 재시작 |

관련 문서/코드 경로: `AGENTS.md`, `config/market_calendar.toml`, `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`

### 4.5 장전 준비 job 초안

입력:
- live runtime status
- runtime watchdog status
- dashboard status
- latest KIS verification
- latest phase approval
- latest readiness run
- market calendar / watchlist / market status snapshot

출력:
- `runtime-data/reports/codex/ops/premarket-readiness/YYYY-MM-DD.json`
- `runtime-data/reports/codex/ops/premarket-readiness/YYYY-MM-DD.md`
- 통과/차단 사유
- 운영자 승인 필요 항목

초기 기준:
- `ALLOW_LIVE_ORDERS`는 변경하지 않는다.
- Phase 1 read-only 전에는 주문 메서드 미노출 self-check를 포함한다.
- Phase 2 전에는 approval hash와 readiness hash를 함께 기록한다.

관련 문서/코드 경로: `app/services/live_phase_readiness.py`, `app/brokers/kis_readonly.py`, `app/services/live_order_guard.py`, `runtime-data/reports/live-readiness/`

### 4.6 장후 학습 job 초안

입력:
- live DB가 아니라 research snapshot DB
- post-close quick maintenance 결과
- label refresh 결과
- latest backtest/walk-forward/challenger reports

출력:
- 실험 실행 여부
- 결과 요약
- paper 동작 회귀 여부
- 다음 실험 제안

안전 원칙:
- 장후 학습 job은 active model 자동 교체를 하지 않는다.
- model registry 교체/승격은 별도 승인 workflow로 남긴다.

관련 문서/코드 경로: `scripts/create_research_db_snapshot.sh`, `scripts/run_post_close_ml_maintenance.sh`, `scripts/run_post_close_label_refresh.sh`, `runtime-data/reports/ml-maintenance/`, `runtime-data/ml/registry.json`

### 4.7 장중 incident job 초안

입력:
- live runtime status
- watchdog status
- 최근 app log
- dashboard stale 상태
- DB lock/disk/KIS 오류 요약

출력:
- 사고 분류
- 영향 범위
- 즉시 안전 조치 후보
- 적용 전/후 patch 초안
- 운영자 승인 필요 여부

금지:
- 장중 root 코드 직접 수정
- 운영 DB migration
- live runtime 강제 restart
- 실전 주문/cancel 호출
- `ALLOW_LIVE_ORDERS` 또는 gate 기준값 변경

관련 문서/코드 경로: `runtime-data/logs/`, `runtime-data/reports/runtime-watchdog/state/`, `scripts/get_live_runtime_status.sh`, `scripts/get_runtime_watchdog_status.sh`, `.tmp-tests/codex-ops/`

## 5. 검증 결과

이번 구현 라운드에서 확인한 검증:

- `python -m unittest tests.test_live_phase_readiness tests.test_live_storage tests.test_storage_migration_apply_script`
  - 통과, 13개
- `python -m unittest tests.test_live_order_guard tests.test_live_kill_switch tests.test_market_status`
  - 통과, 20개
- `bash -n scripts/script_dispatch.sh scripts/apply_storage_migration.sh scripts/run_storage_migration_dry_run.sh`
  - 통과
- `python -m unittest discover -s tests -p "test_*.py"`
  - 통과, 158개
- `git diff --check`
  - 통과. 단, `docs/logbook.md` CRLF -> LF 경고 표시
- `git diff -- app/risk VERSION config`
  - 출력 없음

## 6. 남은 위험

- Codex CLI 운영 자동화는 아직 설계 단계다. 실제 `scripts/run_codex_ops_job.sh`와 `app/services/codex_ops.py`는 구현하지 않았다.
- Codex CLI job이 장중에 root code를 수정하지 못하도록 job manifest와 장 상태 권한 모델을 코드로 강제해야 한다.
- phase approval/readiness hash는 local payload hash다. 외부 timestamp/서명 anchor는 아직 없다.
- live 원장은 구현됐지만 KIS 실전 응답 mapping, order manager, execution sync, dashboard 연결은 후속이다.
- 운영 DB migration apply는 아직 실행하지 않았다. dry-run/plan 검증을 먼저 해야 한다.

## 7. 다음 단계 권장

🟢 다음 단계 권장: `scripts/run_codex_ops_job.sh`를 바로 만들기보다, 먼저 `app/services/codex_ops.py`의 job manifest와 권한 모델을 순수 함수로 구현하고 테스트한다. 장중 보호 정책을 코드로 잠그기 쉽다.

🟢 다음 단계 권장: premarket-readiness job은 기존 `live_phase_readiness.py`를 사용해 dry-run report만 만드는 형태로 시작한다.

🟢 다음 단계 권장: postclose-research job은 research snapshot DB만 입력으로 받도록 제한한다. live DB 직접 heavy read/write는 금지한다.

🔴 운영자 판단 필요: Codex CLI가 장중 incident 때 patch 초안 파일을 어디까지 만들 수 있는지 결정해야 한다. Codex 권장안은 `.tmp-tests/codex-ops/` 또는 별도 worktree 안에서만 초안을 만들고 root 적용은 장후 또는 명시 승인 후로 제한하는 것이다.

🔴 운영자 판단 필요: Codex CLI job 실행 주체. Codex 권장안은 watchdog이 장중 incident를 자동으로 “분석 요청”까지는 할 수 있지만, 코드 적용/재시작/DB apply는 운영자 승인 없이는 하지 않는 것이다.

## 8. cowork 확인 질문

1. Codex CLI를 운영 보조 에이전트로 격리하는 방향이 충분히 보수적인지.
2. 장 상태별 권한 모델이 장중 수집 보호 규칙과 충돌하지 않는지.
3. premarket-readiness -> postclose-research -> intraday-incident-triage 순서로 구현하는 것이 맞는지.
4. Codex CLI job 결과 저장 위치를 `runtime-data/reports/codex/ops/`로 두는 것이 기존 backup/report 정책과 맞는지.
5. 장중 incident patch 초안 위치를 `.tmp-tests/codex-ops/`로 제한하는 안이 충분한지.
