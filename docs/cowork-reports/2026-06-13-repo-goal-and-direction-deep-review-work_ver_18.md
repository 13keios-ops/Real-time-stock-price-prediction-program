# repo-goal-and-direction deep review work_ver_18

작성 시각: 2026-06-13 KST
작성자: Codex
직전 리뷰: `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-review_ver_18.md`

---

## 1. 전달 목적

`review_ver_18`에서 지적한 "장외에서 가능한데 미착수" 항목을 닫고, 2026-06-13 누적 작업을 다음 cowork 리뷰 기준점으로 묶는다.

이번 통합본은 새 구조 제안이 아니라, 운영 안전에 직접 영향을 주는 확인/보강 결과만 정리한다.

---

## 2. 시작 상태

- KST 2026-06-13 16:25, 토요일 `weekend`.
- live runtime: `stopped`, `session_status=weekend`, `trading_mode=paper`.
- runtime watchdog: `running`, `live_runtime_should_run=false`, `errors=[]`, heartbeat fresh.
- dashboard: `http://127.0.0.1:8765` 서버/API 응답 중.
- git: `main...origin/main`, untracked `review_ver_18.md`만 존재.

금지 범위 준수:

- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 실전 주문/취소 없음.
- NAS 백업 실행 없음.

---

## 3. review_ver_18 조치 결과

### P1-1. runtime scope minute-bar 전환 후 장애 감지 민감도 점검

조치 완료.

- `tests/test_runtime_scope.py`에 `test_runtime_scope_reveals_minute_bar_builder_lag`를 추가했다.
- 재현한 상황:
  - `raw_market_ticks`에는 `10:43`, `10:44` KIS 이벤트가 들어온다.
  - `curated_minute_bars`는 `10:43`까지만 존재한다.
- 확인한 안전 속성:
  - raw scope는 `10:44` 실제 이벤트를 본다.
  - dashboard용 curated scope는 `10:44`를 포함하지 않는다.
  - 따라서 분봉 생성기가 멈추면 dashboard의 `최근 분봉 시각`은 멈춰 있고, raw coverage 판단은 `KIS live 데이터 품질` 카드에서 별도로 해석해야 한다.

검증:

- `python -m unittest tests.test_runtime_scope`: 4개 통과.

### P1-4. data quality watch 반복 구체 원인 기록

조치 완료.

기준 파일:

- `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
- `runtime-data/reports/data-quality/latest-kis-live-data-quality.md`
- `runtime-data/dev.db` read-only 조회

날짜별 해석:

| 날짜 | raw market symbol-minute | orderbook symbol-minute | bars/features | 주요 공백 | 해석 |
| --- | ---: | ---: | ---: | --- | --- |
| 2026-06-05 | 3664 | 3907 | 3654 / 3654 | `09:04-09:05`, `09:13`, `09:20`, `09:26`, `09:32`, `09:45-09:46`, `13:01-13:03`, `15:15-15:17`, `15:19-15:29` | feature/bar 비율 1.0. feature 생성 실패가 아니라 raw market tick 기반 분봉 공백과 종가 동시호가 구간 영향 후보. |
| 2026-06-08 | 3501 | 3854 | 3491 / 3491 | full missing `15:09-15:10`, `15:20-15:29`; weak `09:04-09:33`, `14:37-15:06` | 전 종목 outage라기보다 orderbook은 비교적 유지되고 market tick symbol-minute가 약한 날. 다음 재발 시 watchdog heartbeat/WS frame과 교차 확인 필요. |
| 2026-06-09 | 3817 | 4075 | 3807 / 3807 | `15:20-15:29`, weak `09:22` | 종가 동시호가 10분 공백을 제외하면 정상에 가깝다. 반복 watch로 묶되 장애 증거로 단정하지 않는다. |

공통 결론:

- 세 날짜 모두 feature/bar 비율은 1.0이라, "분봉은 있는데 feature가 누락되는" 파이프라인 장애 증거는 없다.
- 6/8은 다음 거래일에 같은 패턴이 재발하면 수집기/WS 상태와 함께 P1 운영 이슈로 본다.
- 6/9 같은 종가 동시호가 공백은 다음 dashboard 해석에서 false alarm 후보로 분리한다.

### P1-2. work_ver_18 통합본 작성

조치 완료.

- 이 파일이 `work_ver_18` 통합본이다.
- `review_ver_18` 자체도 git 추적 대상으로 포함해 cowork ping-pong 이력을 보존한다.

---

## 4. 2026-06-13 누적 작업 요약

### 원장 추적 / paper-KIS mismatch

- `scripts/trace_paper_kis_mismatch.py`가 최신 `paper-account-sync` mismatch를 우선 기준으로 보도록 보강됐다.
- 최신 trace 기준 mismatch source는 `paper_account_sync`.
- mismatch는 `005380`, `035420`, `247540`, `373220` 4종목이다.
- 공통 후보 원인은 2026-06-12 15:07~15:08 청산 주문이 local/broker 모두 submitted 상태이고, broker order-fill 회수가 `EGW00201` 또는 장외 재시도 응답 지연으로 막힌 것이다.
- marker-only alignment로 덮지 않았다.

### 모델 / 알파 연구

- gate walk-forward extreme fold 요약 및 장세 분석 리포트 생성 완료.
- 최저 fold 5/12/11은 flat 라벨 비중이 높고 flat hit rate가 붕괴한 구간으로 분류됐다.
- LightGBM defensive candidates 및 defensive shadow 첫 결과 생성 완료.
- 현재 결론:
  - buy-avoid 후보는 손실 축소 가능성이 있다.
  - early-exit 후보는 첫 shadow에서 실제 paper 청산보다 악화되어 보류다.
  - active model은 계속 baseline이며 LightGBM은 승격되지 않았다.

### Phase 1a readiness

- 최신 `runtime-data/reports/live-readiness/latest-readiness.json`은 `phase1a_paper_readonly`, `status=ok`.
- token/account/system_clock/ws_synthetic/dashboard/database evidence는 freshness 기준을 통과했다.
- `market_status`와 `kill_switch`는 Phase 1a read-only에서 비차단 관측 실패로 남아 있다.
- Phase 1b는 live credentials 미준비로 대기다.

---

## 5. 의도적으로 하지 않은 것

- 4종목 local-only 체결 상태 확인을 위해 같은 KIS order-fill endpoint를 다시 반복 호출하지 않았다.
  - 사유: 2026-06-13 장외 1회 재시도가 2분 안에 완료되지 않아, 같은 endpoint 반복 호출은 rate limit/응답 지연을 키울 수 있다.
- live runtime을 주말에 새로 켜지 않았다.
- NAS 백업을 실행하지 않았다.
- active model, gate threshold, `ALLOW_LIVE_ORDERS`, 실전 주문 관련 설정을 바꾸지 않았다.

---

## 6. 남은 항목

### 다음 거래일 P0

1. 정규장 중 watchdog heartbeat 장시간 유지 실측
   - 수용 기준: 장중 1일치 이상 `heartbeat_stale=false`, `last_checked_at` 갱신 유지.
2. 장후 broker order-fill sync에서 `EGW00201` 재발 여부 확인
   - 재발 시: 단순 cooldown보다 order-fill 호출량 축소 설계 필요.

### 장외 P1

1. 6/8 data quality 약한 구간이 반복되는지 다음 거래일과 비교.
2. defensive buy-avoid 후보는 실제 주문 변경 없이 shadow 축적을 이어간다.
3. 4종목 mismatch는 broker fill 확인 전 자동 alignment 금지.

---

## 7. cowork에게 요청할 검토 범위

다음 리뷰는 바로 지금도 가능하지만, 정보량 대비 효율은 다음 거래일 장후가 더 높다.

필수 검토 질문:

1. 이번 runtime scope 테스트가 "분봉 생성기 중단 감지" 회귀 잠금으로 충분한가?
2. 6/5, 6/8, 6/9 data quality watch 해석에서 6/8을 별도 관찰 대상으로 둔 판단이 타당한가?
3. 다음 거래일 P0을 `watchdog 장중 유지`와 `EGW00201 재발 여부` 두 개로 좁혀도 충분한가?
