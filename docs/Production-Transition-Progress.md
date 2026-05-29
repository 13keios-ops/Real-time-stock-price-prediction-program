# Production Transition Progress

이 문서는 실전 전환 작업의 현재 상태를 빠르게 보기 위한 진행판이다.
사이드패널에서 안정적으로 열리도록 긴 표 대신 짧은 섹션과 bullet 위주로 유지한다.

## 1. 갱신 규칙

- 실전 전환 관련 작업이 끝날 때마다 갱신한다.
- 현재 상태, 남은 blocker, 다음 권장 작업을 우선 기록한다.
- 긴 리뷰 전문은 `docs/cowork-reports/`에 둔다.
- 비밀값은 적지 않는다.
- 이 문서 갱신 목적으로 `app/risk/`, `config/`, `VERSION`, gate 기준값,
  `ALLOW_LIVE_ORDERS`는 수정하지 않는다.

관련 문서/코드 경로:
`docs/Production-Architecture.md`,
`docs/Production-Implementation-Blueprint.md`,
`docs/logbook.md`

## 2. 현재 스냅샷

- 마지막 갱신: 2026-05-29 18:31 KST
- 현재 런타임: `post-close`
- live runtime: 정지 상태가 정상
- runtime watchdog: 실행 중
- dashboard: 실행 중, 첫 화면은 `운영 콘솔`
- trading mode: `paper`
- 최신 cowork 기준: `review_ver_15` 반영
- 최신 통합 리포트:
  `docs/cowork-reports/2026-05-23-production-architecture-implementation-blueprint-work_ver_16.md`
- 최신 Phase readiness:
  `runtime-data/reports/live-readiness/latest-readiness.json`
  기준 `phase1a_paper_readonly`, `status=ok`, `passed=true`.
- 최신 dashboard snapshot:
  `runtime-data/reports/dashboard/latest-dashboard.html`
  기준 `generated_at=2026-05-29T18:31:42+09:00`.
- 최신 장전 readiness:
  `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
  기준 `status=ok`, blockers/warnings 없음.
- 최신 장후 ML maintenance:
  `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`
  기준 `status=ok`, `mode=quick-live-train`.
- 최신 장후 label refresh:
  `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`
  기준 `status=ok`.
- 최신 paper/KIS 정합성:
  `runtime-data/reports/reconciliation/latest-paper-reconciliation.json`
  기준 `status=needs_review`, 포지션 mismatch 0,
  `cash_gap=28937.828660000116`.
- 최신 forced NAS backup:
  `/mnt/backup/repos/real-time-stock-price-prediction-program/recovery-exports/real-time-stock-price-prediction-program-recovery-20260528-224455.tar.gz`
  (`5558128973` bytes).
- NAS 백업 실행 기준:
  앞으로 Codex는 주간/강제 NAS 백업을 자율 실행하지 않고,
  사용자가 해당 작업에서 명시적으로 지시했을 때만 실행한다.
- 다음 cowork 리뷰 권장 시점:
  Phase 1b 실전 계좌 read-only shape 또는 Phase 2 submit readiness 정책을
  구체화한 뒤.

관련 문서/코드 경로:
`scripts/get_live_runtime_status.sh`,
`scripts/get_runtime_watchdog_status.sh`

## 3. Phase 상태

### 설계 기준 정리

- 상태: 완료
- 완료:
  - `docs/Production-Architecture.md`
  - `docs/Production-Implementation-Blueprint.md`
  - cowork reports 누적
- 남은 blocker: 없음

### Phase 0: paper + KIS 모의계좌 mirroring

- 상태: 진행 중
- 현재 기준:
  - 2026-05-28 장후 `initial_cash_mismatch`는 `-SyncInitialCash -AlignToBroker`로 조치했다.
  - 2026-05-29 장후 정합성은 `status=needs_review`다.
  - 포지션 mismatch는 0건이고, 현금/총자산 gap은 약 `28,938원`이다.
  - 같은 timestamp 스냅샷 중 오래된 행을 최신으로 고르는 문제는
    `app/storage/sqlite_store.py`에서 `rowid DESC` tie-break로 보강했다.
  - KIS order fill 조회는 `EGW00201` rate limit이 반복되어 추가 호출을 중단했다.
  - bounded post-close label refresh 수정과 재실행 완료.
  - 2026-05-29 장후 KIS live data quality는 `assessment.status=ok`.
- 남은 blocker:
  - 누적 paper-vs-broker 자동 집계와 dashboard 노출 확인.
  - KIS order fill 조회 rate limit 해소 뒤 잔여 `cash_gap`을 재평가한다.
  - 잔여 gap은 자동 align으로 덮지 않고 원인 확인 뒤 조치한다.

### Phase 1a: KIS 모의투자 read-only 리허설

- 상태: 1차 리허설 통과
- 목적:
  - 실전 계좌를 건드리지 않고 Phase 1 절차를 먼저 리허설한다.
  - token, account snapshot, system clock, dashboard, readiness flow를 검증한다.
- 현재 가능 여부:
  - 가능하며 2026-05-28 05:12 KST 기준 1차 dry-run을 통과했다.
  - 모의투자계좌 기반 `token_refresh`, `account_snapshot`, `system_clock` 증거를 생성했다.
  - `ws_recovery`는 실제 WebSocket 네트워크를 열지 않는 synthetic fault injection 증거다.
- 남은 blocker:
  - 현재 Phase 1a 자체 blocker는 없음.
  - 단, evidence freshness 기준을 넘기면 다음 리허설에서 다시 생성해야 한다.
- 비차단 관측:
  - `market_status=false`: Phase 1a 조회 리허설에서는 주문 제출 전 필터라 비차단.
  - `kill_switch=false`: Phase 1a 조회 리허설에서는 live submit OFF 파일을 요구하지 않음.
- 권장안:
  - Phase 1a는 필요 시 장전마다 반복 실행한다.
  - 다음 구조 작업은 Phase 1b 실전 계좌 read-only shape 확인 준비로 넘어간다.
  - kill switch OFF 파일은 Phase 2 live-submit 준비 전까지 만들지 않는다.

### Phase 1b: 실전 계좌 read-only 확인

- 상태: 대기
- 목적:
  - 실제 자금 운용 전에 실전 계좌의 조회 권한, 응답 shape, 예수금/주문가능금액,
    T+2 관련 필드가 실제로 어떻게 오는지 확인한다.
- 중요한 경계:
  - 주문 금지.
  - 실전 주문 메서드가 없는 read-only client로만 확인한다.
  - `ALLOW_LIVE_ORDERS=false` 유지.
- 왜 필요한가:
  - 모의투자와 실전 계좌의 응답 필드, 권한, 예수금/주문가능금액 계산이 다를 수 있다.
  - 실제 운용 전 이 차이를 모르면 Phase 2에서 주문 가능 금액, 포지션,
    정합성 판단이 틀어질 수 있다.
- 남은 blocker:
  - 실전 KIS 조회용 credentials를 비밀 저장소에 준비.
  - live account read-only shape 확인.
  - sanitized NAS 복구 drill 표본.
- 권장안:
  - Phase 1a를 먼저 완료한다.
  - 그다음 실전 계좌 read-only를 1회 연결한다.

### Phase 2: 실전 1종목 소액 canary

- 상태: 미시작
- 조건:
  - Phase 1a/1b 관측 통과.
  - submit guard, audit, alert, kill switch, model gate 통과.
- 남은 blocker:
  - Phase 1 미통과.
  - active model 승격 기준 미충족.

### Phase 3: 다종목 일일 한도 운용

- 상태: 미시작
- 조건:
  - Phase 2 20~60거래일 관측.
  - 손실/슬리피지/체결/감사 안정.

## 4. 현재 P0 보드

### read-only 구조적 차단

- 상태: 진행 중
- 완료:
  - `KisReadOnlyClient` 골격과 isolation 테스트 구현.
- 다음 작업:
  - Phase 1a/1b flow에 read-only client를 고정.
- 권장안:
  - Phase 1 기본 client는 주문 메서드가 없는 read-only client로 고정한다.

### live enable guard

- 상태: 진행 중
- 완료:
  - live order guard와 guarded adapter 구현.
  - submit guard 테스트 구현.
- 다음 작업:
  - streaming/live submit caller 연결 전 clock/phase gate 자동 주입.
- 권장안:
  - 주문 manager와 KIS adapter 양쪽에서 이중 확인한다.

### system clock 검증

- 상태: 진행 중
- 완료:
  - KIS REST HTTP `Date` parser.
  - readiness `--system-clock-check-path` 병합.
  - KIS paper read-only probe 1회 성공.
- 다음 작업:
  - Phase 1b에서 live account header shape와 paper/live 비교 증거 확보.
- 권장안:
  - raw header 저장 금지.
  - parsed reference time/skew/delta만 기록.

### market status readiness 증거

- 상태: 진행 중
- 완료:
  - repo-local 수동 snapshot probe 구현.
  - `docs/Manual-Market-Status-Runbook.md` 추가.
  - 수동 source enum 고정.
- 현재 blocker:
  - 실제 거래일 snapshot 없음.
- 권장안:
  - 자동 원천 전에는 수동 snapshot만 허용한다.
  - 증거 없으면 자동 통과시키지 않는다.

### kill switch 상태 파일

- 상태: 진행 중
- 현재 판단:
  - missing 상태는 fail-closed로 신규 live submit을 차단한다.
  - Phase 0 paper와 Phase 1 read-only에는 지금 OFF 파일을 만들 필요가 없다.
  - Phase 2 이후 live-submit readiness에서만 OFF 파일을 요구한다.
- 다음 작업:
  - read-only readiness와 live-submit readiness를 분리한다.
- 권장안:
  - pre-open/regular-session 중에는 명시 승인 없이 OFF 파일을 만들지 않는다.
  - missing/broken/stale은 계속 안전 차단으로 둔다.

### readiness local fixture snapshot

- 상태: Phase 1a 기준 통과
- 2026-05-28 Phase 1a 결과:
  - `token_refresh=true`
  - `ws_recovery=true`
  - `account_snapshot=true`
  - `system_clock=true`
  - `database=true`
  - `disk_space=true`
  - `dashboard=true`
  - `storage_migration_state=true`
  - `market_status=false`
  - `kill_switch=false`
- dry-run phase: `phase1a_paper_readonly`
- dry-run status: `ok`
- passed: `true`
- blocking reasons: 없음
- non-blocking reasons:
  - `market_status_fault_dry_run_failed`
  - `kill_switch_fault_dry_run_failed`
- 권장안:
  - Phase 1a read-only에서는 kill switch OFF를 요구하지 않는다.
  - Phase 1b와 Phase 2의 live-submit readiness는 별도 기준으로 유지한다.
  - Phase 2/3은 synthetic WS evidence를 통과시키지 않는다.

### Windows 장전 자동화

- 상태: 진행 중
- 완료:
  - Windows startup launcher를 현재 WSL 정본 경로로 갱신.
  - 로그인 직후 20초 대기와 repo-local 로그 기록 추가.
  - startup fast path는 `--skip-runtime-cleanup --skip-dashboard-build`로 실행.
- 다음 확인:
  - 2026-05-28 08:20 자동 실행 결과 확인.

## 5. 실전 계좌 read-only 연결 방법

### 사용자가 준비할 것

- KIS 실전 계좌 API 접근 권한.
- 실전용 app key와 app secret.
- 실전 계좌번호와 상품 코드.
- 위 값들은 저장소 문서, cowork 리포트, git 추적 파일에 적지 않는다.

### Codex가 처리할 것

- 비밀값은 `.env` 또는 `../secrets` 계열 로컬 비밀 저장소에서만 읽도록 한다.
- `ALLOW_LIVE_ORDERS=false`를 유지한다.
- 주문 메서드가 없는 read-only client만 사용한다.
- token refresh, account snapshot, current price/system clock만 조회한다.
- raw response와 계좌번호는 저장하지 않는다.
- sanitized shape와 count, 필드 존재 여부만 readiness 증거로 남긴다.

### 권장 절차

1. Phase 1a 모의투자 read-only 리허설을 먼저 완료한다.
2. 실전 credentials를 로컬 비밀 저장소에 준비한다.
3. read-only client로 token/account/current-price probe를 1회 실행한다.
4. 주문 함수 호출 0건을 확인한다.
5. paper/live 응답 shape 차이를 문서화한다.
6. 문제가 없으면 Phase 1b 관측 기간을 시작한다.

### 주의

- 실전 계좌 read-only는 실제 자금 주문을 보내는 단계가 아니다.
- 실전 주문 활성 플래그는 켜지 않는다.
- 실전 계좌 조회만으로도 민감 정보가 포함될 수 있으므로, 본문과 git에는 sanitized 결과만 남긴다.

## 6. 열린 결정 항목

- NAS 복구 drill 실행 시점:
  - 권장안은 Phase 1 전 sanitized drill 표본만 별도 폴더에서 확인.
- Phase 1b live account read-only 허용:
  - 권장안은 조회만 허용, 주문 메서드 없는 client로 수행.
- live account `system_clock` probe:
  - 권장안은 Phase 1b 승인 뒤 주문 메서드 없는 client로 1회 실행.
- read-only readiness와 live-submit readiness 분리:
  - 권장안은 Phase 1 read-only는 kill switch OFF 없이 통과 가능하게 한다.
  - live-submit/Phase 2에서만 OFF 파일을 요구한다.
- 외부 알림 채널:
  - 권장안은 Telegram 기본, 중요 사고는 email 병행.

## 7. 작업 종료 체크리스트

매 작업 마지막에는 아래를 확인한다.

- 이 문서의 현재 스냅샷 갱신.
- Phase/P0 상태 갱신.
- 새 blocker와 다음 권장 작업 기록.
- `docs/logbook.md` 최신 entry 확인.
- 최종 보고에 이 파일 링크 출력.

관련 문서/코드 경로:
`docs/logbook.md`,
`docs/cowork-reports/README.md`
