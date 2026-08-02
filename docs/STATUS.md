# 현재 상태

## 기준 시각

- 확인 시각: 2026-08-02 22:24 KST
- 장 상태: weekend
- live runtime: 휴장 정상 정지
- runtime watchdog: 실행 중, heartbeat fresh
- dashboard: `http://127.0.0.1:8765`, server/API 정상
- Windows startup launcher: 설치 및 정상

## 운용 상태

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 현재 통과한 수익 후보: `0개`

## 데이터와 학습

- 최신 KIS 거래일: 2026-07-31
- 2026-07-31 장후 ML: `status=ok`, `quick-live-train`, 16:24 KST 완료
- 2026-07-31 label refresh: `status=ok`, 16:54 KST 완료
- 전체 데이터 품질: `assessment=ok`; 2026-07-31 raw tick, orderbook, 분봉, feature, h15/h60 label이 생성됐고 분봉/feature 장마감 기준 coverage는 약 97.3%다.
- artifact lineage: 최신 dashboard는 `artifact_lineage_guard_ok=true`이며 LightGBM artifact가 해당 training run과 일치한다. 2026-07-17 수집 공백은 과거 P0로 유지한다.
- 수집 안정성: 2026-07-20 complete lineage 3,812행은 보존됐고 KIS WebSocket `no close frame` 재연결 29회는 계속 관찰한다.
- 호가 무결성: bid 또는 ask가 0 이하이거나 crossed인 호가는 raw 감사 원장에는 보존하지만 신호 상태, feature, 연구 입력에는 반영하지 않고 fail-closed로 차단한다.
- feature JSONL 보조본: 2026-08-02 SQLite 정본 6,603,588 입력과 11,936,383 라벨로 재생성해 54GB에서 3.6GB로 정리했다. 이후 오프라인 재구축은 SQLite만 upsert해 JSONL 이력을 중복 기록하지 않는다.

학습이 멈춘 것이 아니라 현재 모델이 비용 후 양수 기대값을 입증하지 못한 상태다.

## Rescue/Avoid

- buy-avoid: 최신 관측은 2026-07-12로 stale이며 `joined_rows=33,007`, `0.40`은 random-control 역선별로 `rejected_random_control` 유지
- buy-rescue: KIS live no-trade ledger는 52,417행 중 eligible 25,726행으로 존재한다. 2026-08-02 진단에서 LightGBM 최선 6건은 `-4.154%p`, linear-score 최선 229건은 `-84.697%p`, 두 모델 동시 상승 35건은 `-23.768%p`라 후보가 아니다. Cybos proxy도 `buy_avoid_candidate_only`다.
- hold-rescue: 2026-08-02 paper-only replay는 `diagnostic_only_no_hold_rescue_candidate`; eligible 161 lot 중 37 lot 적용, `delta_cash_sum=-26,387원`으로 후보가 아니다.

세 항목은 관측/진단용이며 주문 정책에 반영되지 않는다.

## Phase

- Phase 0: 유효 10거래일 관측은 완료됐지만 통과하지 못함
- Phase 0 matched/mismatch: `0일/10일`
- mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 원인 범위: local paper/KIS order-fill 순수량은 `2/6/4/5`, KIS account snapshot 수량은 `0/5/0/10`으로 달라 snapshot divergence가 남아 있다. lifetime rejected close는 수천 건이지만 2026-08-02 trace의 recent count는 네 종목 모두 0건으로, fail-closed 차단 뒤 active retry loop는 없다. 자동 align과 SyncInitialCash는 계속 보류한다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: live bounded read-only 관측과 전용 readiness 1회 통과; 2026-08-02 preflight도 `ready/passed`, 네트워크·주문 호출 0회
- Phase 2/3: 미시작

Phase 1b 통과는 조회 연결 준비이며 수익성 통과나 주문 승인이 아니다.

## 현재 blocker

1. Phase 0의 KIS account snapshot 대 order/fill ledger divergence 해소와 다음 거래일 재확인. 로컬 장부 재생/재시도 경로는 현재 근거상 주원인이 아니다.
2. KIS WebSocket `no close frame` 재연결 빈도와 2026-07-17 approval-key 장애의 재발 여부
3. 비용 후 양수 전략과 비중복 기간 재현성
4. Phase 2/3용 실제 WebSocket recovery 증거
5. 당일 fresh market status
6. 유효기간이 있는 kill switch OFF 상태

## 다음 일정

- 다음 거래일 장전: runtime/watchdog/dashboard 상태와 `run_phase1b_readonly_observation.sh` preflight를 확인한다. 기본 preflight는 네트워크·주문 호출 0회다.
- 다음 거래일 장후: 당일 유효 Phase 0 기록이 없고 runtime이 정지했을 때만 reconciliation을 1회 확인하고, snapshot/ledger divergence가 해소되는지 관찰한다.
- E1/E5: 2026-07-20 1회 시도는 D드라이브 research snapshot I/O 대기로 결과 파일이 생성되지 않았다. 자동 재실행은 금지하며, 다음 명시 실행만 180초 timeout, partial 파일 분리, 실패 attempt 기록으로 보호한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
