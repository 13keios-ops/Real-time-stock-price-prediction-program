# 작업 기록

## 역할

이 파일은 현재 상태, 활성 체크리스트, 최신 검증만 유지한다.
긴 과거 기록은 `docs/logbook_archive/`와 `docs/archive/`에 보관한다.

## 현재 스냅샷

- 기준 시각: 2026-08-02 18:00 KST
- 장 상태: weekend
- live runtime: 휴장 정상 정지
- watchdog/dashboard/startup launcher: 정상
- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 현재 수익 후보: `0개`
- Phase 0: 유효일 `10/10` 관측 완료, matched 0일, mismatch 10일, mismatch 4종목, cash gap `714,840.9593원`. 완료 조건은 통과하지 못했다.
- Phase 1b: bounded read-only 관측 1회 통과; 2026-08-02 preflight도 `ready/passed` (네트워크·주문 호출 0회)

상세 현재값은 `docs/STATUS.md`, Phase 상태는 `docs/Production-Transition-Progress.md`를 기준으로 한다.

## 활성 체크리스트

- [x] 2026-07-13~16 complete lineage decision ledger 축적 확인 (2026-07-17 KIS 수집 공백 별도 P0)
- [x] prediction artifact lineage와 baseline 판단/gate/allocator/주문·체결 chain 연결 확인 (2026-08-02)
- [ ] Phase 0 KIS account snapshot 대 order/fill ledger divergence 해소 확인. 자동 align과 SyncInitialCash는 보류. 2026-08-02 trace에서 네 종목 rejected sell recent count는 모두 0건이며, fail-closed 차단 뒤 active retry는 없다.
- [x] 2026-07-20 장전 KIS approval-key 재시도와 decision ledger 수집 정상화 확인 (3,812행, complete lineage 3,812행)
- [ ] E1/E5 결과 확보: 2026-07-20 장후 wrapper를 1회 실행했으나 D드라이브 research snapshot I/O 대기로 완료 파일이 생성되지 않음. 자동 재실행 금지. 다음 명시 실행은 180초 timeout과 atomic snapshot/attempt 기록으로 보호.
- [ ] E1/E5 유효 결과에 따라 h15 저빈도/h60 비교 여부 결정
- [ ] 수익 후보가 없으면 threshold tuning 대신 새 가설 사전등록

현재 상세 작업 범위는 `docs/SPRINT_CURRENT.md`를 따른다.

## 최신 검증

- 전체 unittest: 2026-08-02 `525 tests OK`
- 전체 pytest: 이번 작업에서는 실행하지 않음 (이전 기준 `518 passed, 67 subtests passed`)
- 저장소 구조/Markdown 감사: 2026-08-02 errors=0, 구조 부채 경고 2건
- dashboard snapshot: 최신 artifact lineage guard 확인; 휴장 중 dashboard 재생성은 하지 않음
- dashboard server/API: 정상
- 작업 시작 시 git: `main`과 `origin/main` 동기화

## [2026-08-02] 휴장 운영 감사와 원장 진단 갱신

- live runtime은 휴장 정상 정지, watchdog heartbeat fresh, dashboard server/API와 Windows startup launcher는 정상이다. Phase 1b 기본 preflight는 `ready/passed`이며 KIS 네트워크와 주문 호출은 각각 0회다.
- 2026-07-31 장후 ML은 `ok`/`quick-live-train`(16:24 KST), label refresh는 `ok`(16:54 KST), KIS data quality는 `ok`다. active `baseline-h15-v1`, `keep_active`, promotion 없음은 유지한다.
- P0 trace를 KIS 네트워크 호출 없이 갱신했다. local paper/KIS order-fill 순수량 `2/6/4/5`와 KIS snapshot `0/5/0/10`의 divergence는 그대로지만, 네 종목의 rejected close recent count는 모두 0건이다. 과거 lifetime 누적을 active retry로 오인하지 않으며 자동 align과 `SyncInitialCash`는 실행하지 않았다.
- hold-rescue paper-only replay는 161 eligible lot 중 37 lot 적용, `delta_cash_sum=-26,387원`, `diagnostic_only_no_hold_rescue_candidate`다. buy-avoid/buy-rescue는 stale 또는 proxy 관측만 유지한다.
- 전체 unittest `525 tests OK`, 구조 감사 errors=0을 확인했다. 주문 정책, threshold, gate, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, KIS 네트워크 호출, 실제 주문/취소는 변경하지 않았다.

## [2026-07-28] Phase 0 재시도 차단과 E1/E5 snapshot 보호

- runtime 원장을 read-only로 분석한 결과 035420, 086520, 105560, 247540은 실패한 KIS paper mirrored sell을 장중 매 분 재시도했다. 2026-07-27 최근 24시간 거절 건수는 각각 382, 379, 380, 380이며 누적 전체는 9,753, 7,830, 9,864, 3,901건이다.
- OnlinePipelineProcessor는 broker submission acknowledgement를 받지 못한 close를 rejected로 기록한 뒤 같은 symbol의 추가 close submission을 차단한다. runtime 재시작 시에도 마지막 sell 상태가 rejected이고 local position이 남아 있으면 차단을 복원한다. 명시적인 정합성 수리 전에는 재시도하지 않는다.
- mismatch trace는 lifetime rejected count와 24시간 recent count를 분리해, 과거 흔적만으로 active loop라고 단정하지 않도록 바꿨다.
- research snapshot은 D드라이브 복사 중 180초를 넘기면 final snapshot/manifest를 교체하지 않는다. partial 파일에서 quick_check 뒤 atomic replace하고, E1/E5 runner는 latest-completed-round 대신 sanitized snapshot_failed attempt만 남긴다.
- 주문 정책, threshold, gate, active model, app/risk, config, VERSION, ALLOW_LIVE_ORDERS, KIS 네트워크 호출, 실제 주문/취소는 변경하지 않았다.
- 관련 회귀 테스트 20건, 전체 unittest 525 tests OK, 작은 SQLite snapshot atomic smoke를 통과했다.

## [2026-07-23] Phase 0 10일 관측 종료와 장후 점검

- 장후 ML은 `ok`(16:18 KST, `quick-live-train`), label refresh는 `ok`(16:52 KST)였다. KIS live data quality도 `ok`이며 2026-07-23까지 거래일 58일을 관측했다.
- live runtime은 장후 정상 정지했고 watchdog, dashboard, Windows startup launcher는 정상이다.
- Phase 0은 유효 거래일 10일을 채웠지만 matched `0일`, mismatch `10일`이어서 완료 조건을 통과하지 못했다. 불일치 종목은 `035420`, `086520`, `105560`, `247540`이다.
- 당일 유효 정합 기록이 이미 있어 broker sync/reconciliation은 재호출하지 않았다. 오래된 mismatch trace만 로컬에서 갱신했으며, 네 종목 모두 local paper와 KIS order/fill 순수량은 맞고 KIS account snapshot 수량만 다른 `kis_account_snapshot_vs_order_fill_ledger_divergence`로 분류됐다.
- 자동 align, `SyncInitialCash`, 주문 정책, threshold, gate, active model, 실전 주문은 변경하지 않았다.
- hold-rescue paper-only replay는 `diagnostic_only_no_hold_rescue_candidate`다. buy-avoid와 buy-rescue도 기존 관측 결과만 유지했다.

## [2026-07-20] 월요일 수집 복구와 장후 점검

- 장전 readiness는 `ok`였다. runtime, watchdog, dashboard, KIS quote 자격정보, SQLite read-only smoke가 모두 통과했다.
- `serving_decision_ledger`는 08:30~15:19 KST에 3,812행을 추가했고, active prediction/artifact와 shadow prediction을 모두 포함한 complete lineage도 3,812행이었다. 2026-07-17 수집 공백은 해소됐지만 과거 공백 기록은 보존한다.
- live runtime은 장후 정상 정지했고 watchdog/dashboard/startup launcher는 정상이다. 다만 KIS WebSocket은 `no close frame`으로 29회 재연결됐으므로, 데이터 품질은 유지됐어도 연결 안정성 관찰을 계속한다.
- 장후 ML은 `ok`(16:24 KST, `quick-live-train`), label refresh는 `ok`(16:55 KST)였다. active 모델과 주문 정책, threshold, gate는 바꾸지 않았다.
- Phase 0은 `7/10`, matched `0일`, mismatch `7일`이다. mismatch 종목은 `035420`, `086520`, `105560`, `247540`이며 당일 유효 기록이 이미 있어 broker sync/reconciliation을 중복 호출하지 않았다.
- E1/E5 wrapper는 장후에 1회 실행했다. SQLite snapshot을 `/mnt/d/CodexData/.../research-snapshots`로 복사하는 단계가 WSL `p9_client_rpc` I/O 대기에 걸려 결과 파일 없이 중단됐다. 중복 실행은 하지 않았고, 주문/네트워크 호출은 없었다.

## [2026-07-18] KIS 수집 장애 완화 및 월요일 장전 준비

- 2026-07-17 KIS approval-key REST의 SSL EOF/timeout으로 listener가 종료되고 watchdog이 60초마다 재시작한 기록을 확인했다. 해당 거래일 `serving_decision_ledger`는 새 행이 없다.
- `app/brokers/kis_quote_ws.py`에서 approval-key 발급을 WebSocket connect와 같은 재시도 경로로 옮기고, 5초에서 최대 60초까지 지수형 대기를 적용했다.
- `scripts/wsl_ops.py` watchdog은 failed listener 재시작을 2분에서 최대 15분까지 지수형 대기한다. 정상 실행을 확인하면 실패 카운터를 초기화한다.
- 2026-07-18은 주말이라 KIS 네트워크를 호출하지 않았다. 2026-07-20 장전에는 수집 재개와 `serving_decision_ledger` 증가를 우선 확인한다.
- 주문 정책, active model, threshold, gate, `app/risk/`, config, VERSION, 실전 주문은 변경하지 않았다.
- 전체 unittest: `522 tests OK`; `git diff --check`와 Python syntax 검사를 통과했다.

## [2026-07-13] 저장소 구조와 현재 문서 정리

- 전체 구조를 실제 파일 기준으로 감사했다: app Python 97개, 테스트 89개, scripts 최상위 139개.
- 감사 전 추적 Markdown 208개의 명시적 local link 누락과 불균형 code fence는 각각 0건이었다.
- `logbook`, `STATUS`, 초기 sprint/workflow/cowork guide, 실전 전환 진행판 원문을 `docs/archive/`에 보존했다.
- archive와 HEAD 원문은 줄바꿈 정규화 기준으로 모두 일치한다.
- 현재판 6개 문서를 합계 약 1만 줄에서 406줄로 축약하고 문서별 소유권을 고정했다.
- `docs/Repository-Structure.md`에 실제 레이어, wrapper 규칙, D드라이브 위치, 구조 부채를 기록했다.
- `scripts/audit_repository_structure.py`와 회귀 테스트 3개를 추가했다.
- 전체 unittest `518 tests OK`, pytest `518 passed, 67 subtests passed`.
- cleanup helper로 87개, `94,171,757 bytes`를 정리하고 root `.pytest_cache`도 제거했다.
- 최종 감사 `errors=0`, 경고는 `research.py`와 `dashboard.py` 대형 모듈 2건뿐이다.
- 대형 모듈은 현재 계약 범위가 넓어 이번 작업에서 분해하지 않고 별도 테스트 리팩터링 대상으로 남겼다.
- 주문 정책, 모델, threshold, gate, Phase 상태, runtime DB, NAS 백업은 변경하지 않았다.

## [2026-07-12] review_ver_33 수익성 증거 정합성

- hold-rescue 기본비용을 구형 `0.13%`에서 현재 `0.29%`로 교정했다.
- E6 `cybos_historical`을 순수 Cybos가 아닌 pre-KIS 혼합 근사치로 명시했다.
- 구형 비용 `0.108%` walk-forward를 현행 수익성 증거에서 제외했다.
- 모든 challenger와 rescue/avoid 후보가 비용 후 수익 또는 재현성 기준을 통과하지 못했다.
- 주문 정책, threshold, active model, gate는 변경하지 않았다.
- 작업 리포트: `docs/cowork-reports/2026-07-12-rescue-avoid-profitability-review-work_ver_34.md`

## 아카이브

- 최신 요약: `docs/logbook_archive/logbook_20260712.md`
- 2026-07-12까지 전체 원문: `docs/archive/logbook-full-through-20260712.md`
- 최초 아카이브: `docs/logbook_archive/logbook_20260411.md`
