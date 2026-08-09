# 작업 기록

## 역할

이 파일은 현재 상태, 활성 체크리스트, 최신 검증만 유지한다.
긴 과거 기록은 `docs/logbook_archive/`와 `docs/archive/`에 보관한다.

## 현재 스냅샷

- 기준 시각: 2026-08-09 20:50 KST
- 장 상태: weekend
- live runtime: 휴장 정상 정지
- watchdog/dashboard/startup launcher: 정상
- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 현재 수익 후보: `0개`
- Phase 0: 유효일 `10/10`, matched 0일, mismatch 10일이다. 최신 3일 KIS 조회는 0행이고 보관된 320건은 전체 계좌 활동이 아닌 historical mirrored-order evidence라 `blocked_requires_full_account_history_or_clean_baseline`이다.
- Phase 1b: bounded read-only 관측 1회 통과; 기본 preflight는 네트워크·주문 호출 0회
- runtime 원장: 2026-08-07 decision ledger 3,803행과 active/shadow complete lineage 100%를 확인했다. broker paper status는 현재 1,819건만 SQL 조회하며 기존 원장은 보존한다.
- 수익성 판정: 비용·순방향 lineage·decision episode portfolio replay 기준 통과 후보 0개. buy-avoid는 19거래일에서 손실만 완화했고 정책 계좌 수익률은 `-34.3196%`다.

상세 현재값은 `docs/STATUS.md`, Phase 상태는 `docs/Production-Transition-Progress.md`를 기준으로 한다.

## 활성 체크리스트

- [x] 2026-07-13~16 complete lineage decision ledger 축적 확인 (2026-07-17 KIS 수집 공백 별도 P0)
- [x] prediction artifact lineage와 baseline 판단/gate/allocator/주문·체결 chain 연결 확인 (2026-08-02)
- [ ] Phase 0 해소: bounded recent lookup과 historical mirrored-order evidence를 분리했다. 자동 align은 금지하며 sanitized full-period account activity 또는 계좌 소유자 승인 clean baseline이 필요하다.
- [x] 2026-07-20 장전 KIS approval-key 재시도와 decision ledger 수집 정상화 확인 (3,812행, complete lineage 3,812행)
- [ ] E1/E5 결과 확보: 2026-08-09 명시 실행도 180초 snapshot timeout으로 안전 종료됐다. 같은 작업에서 재실행하지 않았다. 다음 실행부터 8GiB 이상 DB는 repo-local D드라이브 물리 snapshot 경로와 token별 partial cleanup을 사용한다.
- [ ] E1/E5 유효 결과에 따라 h15 저빈도/h60 비교 여부 결정
- [ ] 수익 후보가 없으면 threshold tuning 대신 새 가설 사전등록

현재 상세 작업 범위는 `docs/SPRINT_CURRENT.md`를 따른다.

## 최신 검증

- 전체 unittest: 2026-08-09 `539 tests OK`
- targeted unittest: data quality, WSL ops, Phase 0 trace, E1/E5 snapshot 33건 OK
- 실제 KIS data-quality 재생성: 2026-08-09 20:49 KST, latest trade date 2026-08-07, assessment `watch`
- decision ledger: 3,803행, complete lineage 3,803행, ratio 1.0
- WebSocket: reconnect 29, storm 0; raw/feature coverage와 함께 연결 주의로 판정
- dashboard server/API와 runtime watchdog/startup launcher: 정상; live runtime은 휴장 정상 정지
- 작업 시작 시 git: `main`과 `origin/main` 동기화

## [2026-08-09] Phase 0 증거 범위 교정, E1/E5 snapshot 보호, 세션 연속성 계측

- Phase 0 trace가 보관된 mirrored status를 최신 KIS 전체 주문·체결 원장처럼 해석하던 문제를 고쳤다. 최신 bounded lookup은 3일·0행이고, 보관된 320 submission은 완전한 계좌 활동 원장이 아니다. 네 종목은 `current_account_vs_historical_mirrored_order_ledger_unresolved`이며 해소 상태는 `blocked_requires_full_account_history_or_clean_baseline`이다.
- 계좌 소유자 명시 승인으로 E1/E5 wrapper를 정확히 1회 실행했다. gate/label은 통과했지만 25GB snapshot이 180초 timeout으로 종료됐다. final snapshot 교체와 네트워크·주문 호출은 모두 0회이며 재실행하지 않았다.
- 대형 DB가 WSL 9P 경계를 건너 복사되는 경우 repo-local `runtime-data/research-snapshots/`를 기본으로 선택하고, timeout partial DB/journal/manifest를 실행 token 단위로 정리하도록 보강했다. WSL 배포판이 D드라이브에 있어 산출물 정책은 유지된다.
- KIS data-quality 리포트에 거래일별 decision ledger active/shadow lineage와 WebSocket reconnect/storm을 추가했다. 2026-08-07은 decision 3,803행, complete lineage 100%, feature closed coverage 97.5128%, reconnect 29/storm 0으로 수집 정상·연결 주의다.
- live runtime 상태와 watchdog 증거에 현재 RSS/peak RSS를 추가했다. 다음 장전/장중에 실제 실행 프로세스 값을 확인한다.
- 관련 targeted unittest 33건과 실제 25GB DB 리포트 재생성을 통과했다. 주문 정책, gate, threshold, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, 실전 주문·취소, NAS 백업은 변경하지 않았다.

## [2026-08-09] 전체 수익성·근거 감사와 fail-closed 교정

- 휴장 상태에서 runtime/watchdog/dashboard/startup launcher, 2026-08-07 수집 품질, 학습/label refresh, Phase 0, 모델·rescue/avoid 원장을 read-only로 전수 점검했다. live runtime은 정상 정지이고 데이터 품질은 `ok`다.
- dashboard signal replay가 수수료·세금을 빼고 slippage 0.06%만 차감하던 문제를 공통 비용 `krx-common-stock-2026-v1` 왕복 0.29%로 고쳤다. 558건 합산 순수익은 `-150.3476%p`, 추정손익은 `-1,052,218원`이며 실제 계좌 수익률이 아님을 표시한다.
- LightGBM defensive shadow가 매일 새 artifact 하나만 선택해 최소 10거래일 조건을 구조적으로 채울 수 없던 문제를 고쳤다. 학습 완료 시각이 예측보다 앞선 완전 lineage 19개만 순방향 chain으로 결합하고, 누락·동일 결정 복수 lineage·동일 거래일 복수 artifact는 fail-closed로 차단한다.
- buy-avoid threshold 0.40은 baseline `-36.4241%`에서 policy `-34.3196%`로 손실을 `+2.1045%p` 줄였지만 절대수익·평균 기대값·일별 일관성 실패로 후보가 아니다. buy-rescue와 hold-rescue도 비용 후 음수이며 meta-policy primary candidate는 없다.
- 장후 label refresh에 buy-avoid, model overlay, hold-rescue, meta-policy 갱신을 포함해 학습만 최신이고 수익성 근거는 stale인 상태를 막았다. dashboard는 Phase 0 matched `0/10`일 때 로컬 누적손익을 수익 증거로 사용하지 않는다고 명시한다.
- 전체 unittest 534건, 수익성 targeted 38건, Python/bash 문법, dashboard 실제 재생성, 구조/Markdown 감사 errors=0을 통과했다. 주문 정책, gate, threshold, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, KIS 주문/취소, NAS 백업은 변경하지 않았다.

## [2026-08-06] 장후 운영 점검과 broker snapshot 메모리 가드

- live runtime은 15:30 KST에 정상 정지했고 watchdog, dashboard, Windows startup launcher는 정상이다. 2026-08-06 raw tick/orderbook JSONL은 09:00 이후 전 종목 1분 초과 공백 및 JSON 파싱 오류가 없었다.
- 장후 ML은 `ok`/`quick-live-train`(16:27 KST), label refresh는 `ok`(16:55 KST), KIS data quality는 `ok`다. active `baseline-h15-v1`, `keep_active`, promotion 없음은 유지한다.
- 당일 Phase 0 유효 기록이 이미 있어 KIS broker sync/reconciliation은 중복 호출하지 않았다. trace와 hold-rescue replay, buy-rescue overlay는 네트워크 없이 갱신했다. Phase 0은 matched 0일, mismatch 10일과 네 종목 snapshot divergence를 유지한다.
- `broker_paper_order_status_snapshots` 2,725,917건을 매 분 전부 Python으로 읽던 경로를 local order별 최신 1,819건 SQL 조회로 바꿨다. 상태 변화가 없는 polling 결과는 JSONL/SQLite에 다시 쓰지 않는다. 실제 `dev.db` 인덱스는 장후 12.7초에 적용됐고, 기존 raw JSONL과 과거 SQLite 행은 삭제하지 않았다.
- `tests.test_broker_paper_sync`, `tests.test_sqlite_store`, `tests.test_streaming_pipeline` 38건과 전체 unittest 533건, 구조/Markdown 감사 errors=0을 통과했다. 주문 정책, threshold, gate, active model, `app/risk/`, config, VERSION, ALLOW_LIVE_ORDERS, KIS 네트워크 호출, 실제 주문/취소는 변경하지 않았다.

## [2026-08-02] 데이터 무결성 및 계좌 표시 보강

- 비정상 top-of-book 호가(bid 또는 ask 0 이하, crossed)를 raw 원장에는 보존하되 signal state, minute feature, offline research 입력에서 fail-closed로 제외했다. spread 기준값과 주문 정책은 바꾸지 않았다.
- P0 trace는 masked account number 없이 paper mode, product, fetch 시각, row-count shape를 함께 기록하도록 보강했다. 현재 근거는 local paper와 KIS order/fill net이 일치하고 KIS account snapshot만 다르다는 데까지이며, 외부 snapshot 원천 또는 수동 상태의 최종 원인 확정은 다음 거래일 재확인이 필요하다.
- feature JSONL은 SQLite primary key 정본에서 6,603,588 model input과 11,936,383 label을 전수 재생성·검증했다. 기존 54GB 보조본은 3.6GB canonical JSONL로 교체했고, 이전 디렉터리는 검증 뒤 제거했다. raw, order, fill, SQLite 정본은 변경하지 않았다.
- 오프라인 feature dataset 재구축은 SQLite가 있을 때 JSONL append를 생략하도록 바꿔 같은 중복 문제가 다시 누적되지 않게 했다.
- dashboard 모의계좌는 전체 정렬 원장의 현재 잔고/포지션과 선택 기간 주문·체결 활동을 분리해 표시한다. 계좌 현황이 날짜 필터에 따라 축소돼 보이던 혼선을 제거했다.
- 전체 unittest 531건과 구조/Markdown 감사 errors=0을 통과했다. 주문 정책, threshold, active model, 실전 주문과 취소, config, VERSION, ALLOW_LIVE_ORDERS는 변경하지 않았다. dashboard 검증 중 read-only 계좌 조회는 발생했지만 주문 호출은 없었다.

## [2026-08-02] 휴장 운영 감사와 원장 진단 갱신

- live runtime은 휴장 정상 정지, watchdog heartbeat fresh, dashboard server/API와 Windows startup launcher는 정상이다. Phase 1b 기본 preflight는 `ready/passed`이며 KIS 네트워크와 주문 호출은 각각 0회다.
- 2026-07-31 장후 ML은 `ok`/`quick-live-train`(16:24 KST), label refresh는 `ok`(16:54 KST), KIS data quality는 `ok`다. active `baseline-h15-v1`, `keep_active`, promotion 없음은 유지한다.
- P0 trace를 KIS 네트워크 호출 없이 갱신했다. local paper/KIS order-fill 순수량 `2/6/4/5`와 KIS snapshot `0/5/0/10`의 divergence는 그대로지만, 네 종목의 rejected close recent count는 모두 0건이다. 과거 lifetime 누적을 active retry로 오인하지 않으며 자동 align과 `SyncInitialCash`는 실행하지 않았다.
- hold-rescue paper-only replay는 161 eligible lot 중 37 lot 적용, `delta_cash_sum=-26,387원`, `diagnostic_only_no_hold_rescue_candidate`다. buy-rescue KIS live no-trade ledger는 52,417행 중 eligible 25,726행으로 확인했고, LightGBM 최선 6건 `-4.154%p`, linear-score 최선 229건 `-84.697%p`, 두 모델 동시 상승 35건 `-23.768%p`로 모두 후보가 아니다.
- buy-rescue 비교 리포트가 7월 12일 결과에 머물러 원장을 비어 있는 것으로 잘못 표시한 점을 수정했다. 실제 rescue가 0건인 threshold를 최선으로 선택하지 않도록 고쳤고, 장후 점검은 최신 overlay 리포트의 생성 시각과 ledger 행 수를 함께 확인한다.
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
