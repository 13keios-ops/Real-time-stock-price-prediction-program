# 현재 상태

## 기준 시각

- 확인 시각: 2026-08-09 19:38 KST
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

- 최신 KIS 거래일: 2026-08-07
- 2026-08-07 장후 ML: `status=ok`, `quick-live-train`, 16:28 KST 완료
- 2026-08-07 label refresh: `status=ok`, 16:55 KST 완료
- 최신 challenger: active `baseline-h15-v1`, `keep_active`, promotion 없음. top active-model 평가는 31거래의 작은 표본이며 3분류 정확도 `0.267826`, buy hit `0.580645`, 겹치는 거래 수익률 합 `+20.458524%p`이므로 포트폴리오 수익 증거로 쓰지 않는다.
- 장후 label refresh는 data quality뿐 아니라 buy-avoid, model overlay, hold-rescue, meta-policy를 같은 흐름에서 갱신한 뒤 dashboard를 만든다.
- 전체 데이터 품질: `assessment=ok`; 2026-08-07 KIS raw tick/orderbook, 분봉, feature, h15/h60 label 생성이 확인됐다. raw JSONL은 09:00 이후 전 종목에 1분 초과 공백과 JSON 파싱 오류가 없었다.
- artifact lineage: 최신 dashboard는 `artifact_lineage_guard_ok=true`이며 LightGBM artifact가 해당 training run과 일치한다. 2026-07-17 수집 공백은 과거 P0로 유지한다.
- 수집 안정성: 2026-07-20 complete lineage 3,812행은 보존됐고 KIS WebSocket `no close frame` 재연결 29회는 계속 관찰한다.
- 호가 무결성: bid 또는 ask가 0 이하이거나 crossed인 호가는 raw 감사 원장에는 보존하지만 신호 상태, feature, 연구 입력에는 반영하지 않고 fail-closed로 차단한다.
- feature JSONL 보조본: 2026-08-02 SQLite 정본 6,603,588 입력과 11,936,383 라벨로 재생성해 54GB에서 3.6GB로 정리했다. 이후 오프라인 재구축은 SQLite만 upsert해 JSONL 이력을 중복 기록하지 않는다.
- 브로커 상태 원장: 과거 SQLite snapshot은 2,725,917건이지만 현재 주문 상태는 1,819건이다. 2026-08-06부터 최신 상태만 SQL에서 읽고 실질 상태 변화만 새 snapshot으로 보관한다. 기존 raw JSONL과 SQLite 과거 행은 삭제하지 않았다.

학습이 멈춘 것이 아니라 현재 모델이 비용 후 양수 기대값을 입증하지 못한 상태다.

## Rescue/Avoid

- buy-avoid: 2026-08-09에 완전 lineage 19개 거래일을 순방향으로 묶어 `joined_rows=28,434`를 재평가했다. threshold `0.40`은 baseline `-36.4241%`에서 `-34.3196%`로 손실을 `+2.1045%p` 줄였지만 절대 수익, 평균 거래 기대값, 일별 일관성이 모두 음수여서 `rejected_no_absolute_portfolio_profit`이며 후보가 아니다.
- buy-rescue: 2026-08-09 overlay decision ledger는 `status=ok`, 71,369행 중 rescue eligible 35,573행이다. LightGBM 최선은 threshold 0.55의 6건 `-4.153997%p`, linear-score 최선은 0.65의 269건 `-90.797762%p`다. 실제 serving no-trade 판단 원장은 존재하지만 KIS 브로커의 별도 live no-trade 체결 원장을 뜻하지 않으며, 모두 주문 후보가 아니다.
- hold-rescue: 2026-08-09 paper-only replay는 `diagnostic_only_no_hold_rescue_candidate`; eligible 161 lot 중 threshold 0.40을 37 lot에 적용하면 `delta_cash_sum=-26,387원`으로 후보가 아니다.
- meta-policy: `blocked_evidence`, blocker는 `no_absolute_profit_portfolio_candidate`, `no_evidence_eligible_combination_policy`; primary candidate는 없다.

세 항목은 관측/진단용이며 주문 정책에 반영되지 않는다.

dashboard signal replay도 공통 비용 정본 `krx-common-stock-2026-v1`의 왕복 `0.29%`를 사용한다. 2026-08-07 신호 558건의 합산 순수익은 `-150.3476%p`, 추정 손익은 `-1,052,218원`이며 겹치는 신호 합이므로 계좌 수익률로 해석하지 않는다.

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
7. raw SQLite 장기 보관량 증가. 브로커 상태 snapshot 중복 적재는 차단했으며, 별도 보존형 compaction 전까지 기존 `dev.db` 크기는 유지된다.

## 다음 일정

- 다음 거래일 장전: runtime/watchdog/dashboard 상태와 `run_phase1b_readonly_observation.sh` preflight를 확인한다. 기본 preflight는 네트워크·주문 호출 0회다. 2026-08-07 이후 첫 수집에서 decision ledger와 complete lineage 증가, raw tick/orderbook 공백, live runtime RSS를 함께 확인한다.
- 다음 거래일 장후: 당일 유효 Phase 0 기록이 없고 runtime이 정지했을 때만 reconciliation을 1회 확인하고, snapshot/ledger divergence가 해소되는지 관찰한다.
- E1/E5: 2026-07-20 1회 시도는 D드라이브 research snapshot I/O 대기로 결과 파일이 생성되지 않았다. 자동 재실행은 금지하며, 다음 명시 실행만 180초 timeout, partial 파일 분리, 실패 attempt 기록으로 보호한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
