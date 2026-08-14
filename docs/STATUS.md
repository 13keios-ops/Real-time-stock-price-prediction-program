# 현재 상태

## 기준 시각

- 확인 시각: 2026-08-15 00:47 KST
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

- 최신 KIS 거래일: 2026-08-14
- 2026-08-14 장후 ML: `status=ok`, `quick-live-train`, 16:32 KST 완료
- 2026-08-14 label refresh: `status=ok`, 17:01 KST 완료
- 최신 challenger: active `baseline-h15-v1`, `keep_active`, promotion 없음. top LightGBM은 거래 2건의 작은 표본이며 3분류 정확도 `0.4812`, buy hit `0.5000`, 겹치는 가상 방향 순수익 합 `+1.5325%p`, 매수 순수익 합 `+0.4283%p`라 수익 후보로 쓰지 않는다.
- 2026-08-14 raw market/orderbook symbol-minute는 `3,622/3,821`, 분봉·feature는 각각 `3,608`이다. 닫힌 분 기준 분봉·feature coverage는 `92.5128%`, feature/bar ratio는 `100%`다.
- 2026-08-14 serving decision ledger는 `3,608`행이며 complete lineage `3,608/3,608`, ratio `100%`다. 판단 단계는 signal blocked 2,037, position/pending constraint 1,180, allocator zero target 391건이다.
- WebSocket 재연결은 47회, storm 19회다. 10종목 공통 market 공백은 `15:01~15:29`, orderbook 공백은 `15:01~15:24`이며 수집 판정은 `needs_attention`이다.
- 같은 날 분봉 확정 경로의 broker paper sync 실패는 38회였다. 일반 예외는 5/10/20/40/60분 지수 백오프, `EGW00201` 결과는 120분 process pause를 적용해 WebSocket 처리 여유를 보호한다.
- live runtime 상태 출력은 다음 거래일부터 현재 RSS와 peak RSS를 함께 제공한다.
- 호가 무결성: bid 또는 ask가 0 이하이거나 crossed인 호가는 raw 감사 원장에는 보존하지만 신호 상태, feature, 연구 입력에는 반영하지 않고 fail-closed로 차단한다.
- feature JSONL 보조본: 2026-08-02 SQLite 정본 6,603,588 입력과 11,936,383 라벨로 재생성해 54GB에서 3.6GB로 정리했다. 이후 오프라인 재구축은 SQLite만 upsert해 JSONL 이력을 중복 기록하지 않는다.
- 브로커 상태 원장: 과거 SQLite snapshot은 2,725,917건이지만 현재 주문 상태는 1,819건이다. 최신 상태만 SQL에서 읽고 실질 상태 변화만 새 snapshot으로 보관한다.

학습이 멈춘 것이 아니라 현재 모델이 비용 후 양수 기대값을 입증하지 못한 상태다.

## Rescue/Avoid

- buy-avoid: `2026-07-13~2026-08-14`, joined 68,597행/완전 lineage 35,590행이다. threshold `0.40` portfolio replay는 baseline `-41.9823%`에서 `-40.3788%`로 손실을 `+1.6036%p` 줄였지만 절대 수익이 음수라 `rejected_no_absolute_portfolio_profit`이다.
- buy-rescue: serving no-trade decision ledger는 실제로 존재한다. rescue eligible 45,585행이며 LightGBM 최선 6건 `-4.153997%p`, linear-score 최선 294건 `-100.308821%p`로 모두 음수다.
- hold-rescue: paper-only replay는 eligible 161 lot 중 threshold 0.40을 37 lot에 적용했을 때 `delta_cash_sum=-26,387원`으로 후보가 아니다.
- meta-policy: `blocked_evidence`; primary candidate는 없다.
- 비용 구조: 현행 `krx-common-stock-2026-v1` 왕복 `0.29%`, 2배 여유 `0.58%`다. KIS live h15 중위 절대변동 `0.371216%`는 기준 미달, h60 `0.695410%`는 기준 초과지만 실행·보유 replay 미검증이라 연구 우선순위일 뿐 후보가 아니다.

세 항목은 관측/진단용이며 주문 정책에 반영되지 않는다.

## Phase

- Phase 0: 과거 기준선의 유효 10거래일 관측은 `matched 0일/mismatch 10일`로 미통과 이력을 보존한다.
- 2026-08-15 00:20 KST 계좌 소유자 승인으로 KIS snapshot 기준 marker-only clean baseline을 생성했다. `SyncInitialCash`, 주문, 취소는 실행하지 않았다.
- 새 기준선 정합: KIS/local 보유 3종목, 현금, 총자산이 모두 일치하며 mismatch `0`, cash/total asset gap `0원`, 상태 `aligned_waiting_first_submission`이다.
- 새 Phase 0 epoch: 휴장일 기준 `0/10` 유효 거래일이다. 이후 10개 유효 거래일이 모두 matched여야 통과한다.
- 과거 mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 최신 trace는 KIS 최근 3일 조회 0행과 보관된 320건 historical mirrored submission을 전체 계좌 활동과 분리한다.
- 전체 기간 read-only probe 범위는 alignment `2026-06-14`부터 최신 account snapshot `2026-08-14`까지이며, 로컬 mirrored submission 320건/20거래일을 포함한다.
- 2026-08-14 새 명시 승인으로 `--max-pages 30 --execute`를 1회 실행해 22페이지, sanitized 활동 329행/20거래일, `pagination_complete=true`를 확보했다. 주문·취소는 0회다.
- 로컬 submission 320개는 모두 broker 활동과 연결됐고 추가 broker 활동 9행이 확인됐다. ambiguous fallback key는 1개지만 duplicate exact key는 0개다.
- 전체 활동 position 재구성은 KIS account snapshot과 일치하고 로컬 paper만 `035420 +2`, `086520 +1`, `105560 +4`, `247540 -5` 수량 차이다. root cause는 `external_or_unlinked_broker_activity`로 확정했다.
- Phase 0 해소 상태: `clean_baseline_created_waiting_10_matched_days`. 새 marker는 full-period 증거보다 뒤이며 자동 정렬은 계속 금지한다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: live bounded read-only 관측과 전용 readiness 1회 통과
- Phase 2/3: 미시작

Phase 1b 통과는 조회 연결 준비이며 수익성 통과나 주문 승인이 아니다.

## E1/E5

- 2026-08-09 계좌 소유자 명시 승인으로 wrapper를 정확히 1회 실행했다.
- gate와 label refresh는 통과했으나 25GB SQLite snapshot이 180초 안에 끝나지 않아 `snapshot_failed/research_snapshot_timeout`으로 안전 종료됐다. 네트워크·주문 호출은 각각 0회이고 final snapshot은 교체되지 않았다.
- 같은 작업에서 재실행하지 않았다. 8GiB 이상 DB가 WSL 9P 경로로 복사되는 경우 repo-local `runtime-data/research-snapshots/`를 쓰도록 보강했고 timeout partial 정리를 실행 token 단위로 고정했다.
- 유효 E1/E5 결과는 아직 없으며 자동화는 재실행하지 않는다.

## 현재 blocker

1. Phase 0 clean baseline 이후 새 유효 거래일 `0/10`; 이후 10거래일 모두 정합 필요
2. 2026-08-14 WebSocket storm 19회와 `15:01~15:29` 전 종목 market 공백의 재발 여부
3. 비용 후 양수 전략과 비중복 기간 재현성
4. Phase 2/3용 실제 WebSocket recovery 증거
5. 당일 fresh market status
6. 유효기간이 있는 kill switch OFF 상태
7. 26GB 운영 DB의 장기 보관. data-quality 최근 10일 집계는 전체 분 그룹화를 제거해 `439초 -> 126초`로 줄였지만 추가 인덱스/요약 테이블 여부는 계속 본다.

## 다음 일정

- 다음 거래일 장전: runtime/watchdog/dashboard/startup launcher와 Phase 1b 네트워크 0회 preflight를 확인한다. live runtime 실행 뒤 RSS/peak RSS와 broker sync backoff 로그를 함께 본다.
- 다음 거래일 장후: raw/feature coverage, 공통 누락 구간, decision ledger 증가와 lineage 100%, WebSocket reconnect/storm을 같은 리포트에서 확인한다. 당일 유효 Phase 0 기록이 없고 runtime이 정지했을 때만 reconciliation을 1회 실행한다.
- 수익 연구: E1/E5 유효 결과 전 신규 threshold 탐색은 하지 않는다. 이후에도 실현 p75를 entry 필터로 쓰지 않고, entry 시점 정보만 쓰는 저빈도 비용여유 후보, h60 별도 트랙, entry/exit 분리 가설을 동일 portfolio replay와 random control로만 비교한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
