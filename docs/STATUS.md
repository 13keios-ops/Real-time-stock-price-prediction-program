# 현재 상태

## 기준 시각

- 확인 시각: 2026-08-09 20:50 KST
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
- 2026-08-07 raw market/orderbook symbol-minute는 `3,815/4,059`, 분봉·feature는 각각 `3,803`이다. 닫힌 분 기준 분봉·feature coverage는 `97.5128%`, feature/bar ratio는 `100%`다.
- 2026-08-07 serving decision ledger는 `3,803`행이며 active lineage `3,803/3,803`, shadow lineage `7,606/7,606`, 전체 lineage completion `100%`다. 판단 단계는 signal blocked 2,266, position/pending constraint 1,261, allocator zero target 276건이다.
- WebSocket 재연결은 29회로, no-close-frame 28회와 no-frame timeout 1회다. reconnect storm은 0건이고 데이터·계보 손실로 번지지 않았으므로 수집은 정상, 연결 안정성은 주의로 분리한다.
- live runtime 상태 출력은 다음 거래일부터 현재 RSS와 peak RSS를 함께 제공한다.
- 호가 무결성: bid 또는 ask가 0 이하이거나 crossed인 호가는 raw 감사 원장에는 보존하지만 신호 상태, feature, 연구 입력에는 반영하지 않고 fail-closed로 차단한다.
- feature JSONL 보조본: 2026-08-02 SQLite 정본 6,603,588 입력과 11,936,383 라벨로 재생성해 54GB에서 3.6GB로 정리했다. 이후 오프라인 재구축은 SQLite만 upsert해 JSONL 이력을 중복 기록하지 않는다.
- 브로커 상태 원장: 과거 SQLite snapshot은 2,725,917건이지만 현재 주문 상태는 1,819건이다. 최신 상태만 SQL에서 읽고 실질 상태 변화만 새 snapshot으로 보관한다.

학습이 멈춘 것이 아니라 현재 모델이 비용 후 양수 기대값을 입증하지 못한 상태다.

## Rescue/Avoid

- buy-avoid: 완전 lineage 19거래일, `joined_rows=28,434`. threshold `0.40`은 baseline `-36.4241%`에서 `-34.3196%`로 손실을 `+2.1045%p` 줄였지만 절대 수익, 평균 거래 기대값, 일별 일관성이 모두 음수여서 `rejected_no_absolute_portfolio_profit`이다.
- buy-rescue: serving no-trade decision ledger는 실제로 존재한다. 71,369행 중 rescue eligible 35,573행이며 LightGBM 최선은 6건 `-4.153997%p`, linear-score 최선은 269건 `-90.797762%p`다.
- hold-rescue: paper-only replay는 eligible 161 lot 중 threshold 0.40을 37 lot에 적용했을 때 `delta_cash_sum=-26,387원`으로 후보가 아니다.
- meta-policy: `blocked_evidence`; primary candidate는 없다.

세 항목은 관측/진단용이며 주문 정책에 반영되지 않는다.

## Phase

- Phase 0: 유효 10거래일 관측은 완료됐지만 통과하지 못함
- Phase 0 matched/mismatch: `0일/10일`
- mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 최신 trace는 KIS 최근 3일 조회가 0행이고, 보관된 320건은 전체 계좌 활동이 아닌 과거 mirrored submission 증거임을 명시한다. 현재 계좌 snapshot과 이 과거 증거가 달라 `current_account_vs_historical_mirrored_order_ledger_unresolved`로 분류했다.
- Phase 0 해소 상태: `blocked_requires_full_account_history_or_clean_baseline`. 자동 align은 금지하며, 미러링 기간 전체를 덮는 sanitized 계좌 활동 또는 계좌 소유자가 승인한 clean paper-account baseline 뒤 새 local baseline이 필요하다.
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

1. Phase 0 해소를 위한 전체 기간 sanitized 계좌 활동 또는 계좌 소유자 승인 clean baseline 결정
2. KIS WebSocket no-close-frame 재연결 29회 수준의 반복 원인과 실제 stable-frame 복구 증거
3. 비용 후 양수 전략과 비중복 기간 재현성
4. Phase 2/3용 실제 WebSocket recovery 증거
5. 당일 fresh market status
6. 유효기간이 있는 kill switch OFF 상태
7. 25GB 운영 DB의 장기 보관과 장후 전체 품질 집계 비용

## 다음 일정

- 다음 거래일 장전: runtime/watchdog/dashboard/startup launcher와 Phase 1b 네트워크 0회 preflight를 확인한다. live runtime 실행 뒤 RSS/peak RSS를 함께 본다.
- 다음 거래일 장후: raw/feature coverage, decision ledger 증가와 lineage 100%, WebSocket reconnect/storm을 같은 리포트에서 확인한다. 당일 유효 Phase 0 기록이 없고 runtime이 정지했을 때만 reconciliation을 1회 실행한다.
- 수익 연구: E1/E5 유효 결과 전 신규 threshold 탐색은 하지 않는다. 이후에도 실현 p75를 entry 필터로 쓰지 않고, entry 시점 정보만 쓰는 저빈도 비용여유 후보, h60 별도 트랙, entry/exit 분리 가설을 동일 portfolio replay와 random control로만 비교한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
