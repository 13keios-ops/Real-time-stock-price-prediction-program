# Claude cowork 리뷰 review_ver_12: WS reconnect metric + Phase 2 max_order_qty=1 + KIS fixture mapper + NAS recovery self-test

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_12`
- 기준 작업본: work_ver_12-1 + work_ver_12-2 + work_ver_12-3 통합 (cowork 리뷰 사이에 들어온 3개 sub-work)
- cowork 직접 검증 파일: `app/brokers/kis_quote_ws.py`(`KisWebSocketReconnectMetrics`/`Snapshot`), `app/services/live_order_manager.py`(`PHASE2_DEFAULT_MAX_ORDER_QTY=1` + `_pre_submit_blocking_reasons`), `scripts/export_kis_paper_fixture_candidates.py`(read-only DB + redaction + fail-on-findings)

## 요약

work_ver_12 시리즈는 review_ver_11의 Phase 1 진입 전 P0 4가지 중 3가지를 처리했다(WS reconnect metric ✓, KIS 실제 응답 fixture 검증 ✓, NAS recovery self-test ✓ + 실제 drill △). 4번째 reference clock 원천 결정은 미진행. 추가로 review_ver_11 Q2 보강 권장(`max_order_qty=1`)도 정확히 closure. 39+38+11=88개 좁은 묶음 테스트 통과. 결론은 **WS metric + 1주 제한 + fixture 검증 그대로 사용 가능. NAS 실제 dry-run 1회 + reference clock 원천 결정이 Phase 1 진입의 남은 P0 차단 항목.**

핵심 발견 세 가지: (1) `KisWebSocketReconnectMetrics`가 cumulative/consecutive 분리 + stable_connection reset + storm 자동 해제까지 잘 짜여 Phase 1 측정 충분. **단 timestamp 부재로 dashboard "마지막 reconnect N분 전" 표시가 별도 시간 기록 필요.** (2) `PHASE2_DEFAULT_MAX_ORDER_QTY=1` + context dict 기록이 review_ver_11 Q2 권장과 일치. (3) NAS recovery는 self-test만 통과, 실제 dry-run은 WSL sandbox approval timeout으로 미완료 — **운영자 장외 시간 1회 실행이 Phase 1 진입 전 필수**.

## Q1: WS reconnect metric이 Phase 1 전 P0 검증에 필요한 최소 관측값을 제공하는가

**제공한다. 7개 snapshot 필드 + 4개 state가 reconnect storm 식별에 충분.**

`kis_quote_ws.py` 161~218행을 직접 봤다. snapshot 7 필드:

```python
class KisWebSocketReconnectSnapshot:
    state: str  # connected/stable/disconnected
    cumulative_reconnects: int
    consecutive_reconnects: int
    frames_seen_total: int
    frames_since_connect: int
    stable_connection_seen: bool
    reconnect_storm: bool
    last_error: str = ""
```

설계 강점 5가지:

1. **cumulative vs consecutive 분리**: cumulative는 운용 전체 누적, consecutive는 안정 연결 사이 연속 reconnect(현재 storm 식별). 두 지표가 운영 분석에 모두 필요.
2. **stable_connection_seen 자동 reset**(192~196행): `stable_frame_reset_threshold=5` frame 받으면 안정 인정 → consecutive_reconnects=0. **짧은 hiccup이 storm으로 잘못 분류되지 않는다.**
3. **storm 자동 해제**: stable_connection 인정 시 consecutive=0 → storm=False. 의도된 cycle.
4. **last_error 보존**: 사후 분석에 핵심. KIS API 변경 또는 네트워크 이슈 식별.
5. **callback 예외 흡수**(449~452행): `metrics_callback` 예외를 warning으로 흡수해 **관측 실패가 quote stream을 끊지 않는다**. fail-safe.

`reconnect_storm_threshold=3` 기본값도 보수적 적절. 2026-05-18 WS 이슈 같은 상황을 식별 가능.

미세 약점 세 가지:

첫째, **timestamp 부재**. snapshot에 `last_reconnect_at`, `last_stable_at`, `snapshot_created_at` 같은 시각 필드가 없음. dashboard에서 "마지막 reconnect 5분 전, 마지막 stable 7분 전" 같은 시간 기반 표시를 하려면 callback 수신 측에서 별도로 시각을 기록해야 함. **권장**: snapshot에 `observed_at: datetime` 추가. 우선순위 중간.

둘째, **storm 지속 시간 측정 부재**. storm=True가 얼마나 지속됐는지(예: 30초인지 5분인지)가 snapshot에서 안 보임. consecutive_reconnects 카운트로 추정 가능하지만 시간 단위 표시는 어려움. Phase 2 submit guard에 storm을 차단 조건으로 쓰려면 "storm이 60초 이상 지속되면 차단" 같은 시간 기반 정책이 필요할 텐데 현 구조로는 어려움. **권장**: `storm_active_since: datetime | None` 추가. 우선순위 중간.

셋째, **reconnect_backoff(5초)×storm_threshold(3회) = 약 15초** 안에 storm 판정. KIS WS 정상 reconnect가 평균 5~15초라면 false positive storm 가능. Phase 1 측정 도구로는 적절하지만 **Phase 2 submit guard에 직접 연결하면 정상 reconnect도 차단 위험**. work_ver_12-1에서는 readiness 카드 노출까지만 권장하고 submit guard 연결은 후속으로 분리 — 적절한 의사결정.

종합: **Phase 1 측정·관측에 충분.** Phase 2 submit guard 연결은 timestamp 보강 후 false positive 검증을 거치는 게 안전.

## Q2: Phase 2 기본 max_order_qty=1이 실전 canary 안전 기준으로 적절한가

**적절. review_ver_11 Q2 권장이 정확히 closure됐다.**

`live_order_manager.py` 24, 110, 505~510, 703~705행 확인:
- `PHASE2_DEFAULT_MAX_ORDER_QTY = 1` 모듈 상수
- `LivePreSubmitPolicy.max_order_qty` 필드
- Phase 2일 때 default 적용
- `parent_order_id` 없는 신규 주문에만 적용 (자식 주문 우회 차단)
- `qty > 1`이면 `phase2_order_qty_limit_exceeded` blocking reason + context dict 기록(current/limit)
- `order_policy.max_order_qty` 또는 `max_qty`로 override 가능

review_ver_11 Q2에서 cowork이 정확히 권장한 패턴 그대로 구현됐다. 다음 4가지 invariant가 모두 잠겨 있다:

1. **canary 본질에 맞다**: 1일 1주문 + 1주 = lifecycle 검증 단위로 최소화. 수익 극대화 의도와 분리.
2. **silent 다주 방지**: 5만원 종목에서도 한도 내 2주 시도가 차단됨. 운영자가 의도하지 않은 다주 주문이 silent하게 나가지 않는다.
3. **명시적 override 가능**: 운영자가 2주 테스트를 의도하면 `order_policy.max_order_qty=2`를 명시. 의사결정이 audit에 남는다.
4. **context dict 기록**(507~510행): blocking_reasons + context의 current/limit 둘 다 기록되어 사후 분석 시 "왜 차단됐는지"가 명확.

미세 약점: 없음. canary 단계에서 가장 보수적인 형태로 잠겨 있다.

추가 확인 한 가지: **`int(request.qty)` 변환**(505행)이 정수가 아닌 qty(float, string)를 안전하게 처리. JSON 직렬화 시에도 안전.

종합: **closure 완벽.** Phase 3 진입 시 운영자가 `max_order_qty=N`으로 명시 완화 — 자연스러운 경로.

## Q3 (work_ver_12-2 자체 검증): KIS fixture mapping과 redaction이 안전한가

**Phase 1 진입 전 단계에서 안전. 다만 paper vs live shape 비교가 read-only 연결 후 필수 후속.**

`scripts/export_kis_paper_fixture_candidates.py`를 직접 봤다. 안전 잠금 4가지:

1. **read-only DB 연결**(69행 `_connect_read_only`): silent write 위험 0.
2. **repo 내부 경로 강제**(53~54행 `_resolve_inside_repo`): path traversal 방지.
3. **redaction findings 자동 차단**(46~48, 63~64행 `--fail-on-redaction-findings`): 민감 키가 남아 있으면 exit non-zero.
4. **실제 KIS API 호출 없음**: 기존 `runtime-data/dev.db`만 사용. work_ver_12-2 본문 명시.

확인된 KIS field shape 15개(work_ver_12-2 3장: ord_dt, ord_gno_brno, odno, orgn_odno, pdno, sll_buy_dvsn_cd, sll_buy_dvsn_cd_name, ord_qty, tot_ccld_qty, rmn_qty, avg_prvs, cncl_cfrm_qty, rjct_qty, cncl_yn, excg_id_dvsn_cd)가 `snapshot_from_kis_daily_order_fill` 매핑과 일치 — 테스트로 잠금.

미세 약점 두 가지:

첫째, **2026-05-15 KIS paper row shape 기준 fixture가 영구는 아님**. KIS가 응답 필드명을 바꾸면 테스트가 차이를 잡지만, fixture 재export 절차가 자동화되어야 함. **권장**: fixture 갱신 절차(`scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings` 실행 후 git diff 확인)를 runbook 또는 정기 점검 항목에 명시. 우선순위 중간.

둘째, **paper vs live shape 차이 미검증**. 현재 fixture는 paper. 실제 live 계좌 daily order/fill 응답 shape가 paper와 일치한다는 가정. work_ver_12-2 본문 5장에서 "live 계좌 조회 결과를 같은 redaction helper로 저장해 paper/live field shape 차이를 비교" 권장으로 인지됨. **Phase 1 read-only 연결 직후 첫 작업으로 live shape 비교가 필수.**

종합: **현 단계 안전, Phase 1 read-only 진입 후 live shape 비교가 필수 후속.**

## Q4 (work_ver_12-3 자체 검증): NAS drill self-test 통과 + 실제 drill 미실행이 Phase 1 진입에 충분한가

**불충분. Phase 1 진입 전 최소 1회 실제 dry-run이 필수.** Codex 본인도 work_ver_12-3 4장에서 같은 판단("self-test passed / actual drill not verified. Phase 1 진입 전에는 최소 1회 실제 dry-run 또는 로컬 export drill이 필요하다").

self-test가 잠근 것:
- 5개 새 경로(`alerts/`, `live-risk/`, `live-approvals/`, `ops/`, `ml/registry-backups/`) 포함 검증
- 비밀값(root `.env`, KIS cache, runtime logs, `*.pem`, `*.key`, `id_rsa*`) 제외 검증
- `tests.test_wsl_ops` 11개 통과

self-test가 잠그지 못한 것:
- 실제 tar export 명령이 정상 종료되는지
- 실제 생성된 package가 self-test 가정 구조와 일치하는지
- 실제 NAS 공유 mount + 쓰기 권한 (포함될 경우)
- 실제 복구 시 모든 경로가 정상 복원되는지

WSL sandbox approval timeout으로 dry-run 미완료(work_ver_12-3 본문). 이건 코드 검증으로 해결할 수 없는 운영자 작업이다.

**review_ver_11 Q10 합의와의 정합 검토**: review_ver_11 Q10에서 cowork은 "Phase 1 진입 전 1회 + Phase 2 진입 전 1회, 총 2회" drill을 권장. 첫 drill이 schema apply 후 첫 readiness record 생성 전 빈 schema 복구 가능성 검증 목적. 현재 self-test만으로는 이 첫 drill을 갈음할 수 없음 — schema apply 자체가 안 됐고 빈 readiness records도 없음.

**권장**: 운영자가 장외 시간에 `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run` 1회 완료 확인 → 생성된 package에서 비밀값 제외와 live 운영 경로 포함 수동 표본 확인 → Phase 1 진입 결정.

이건 Phase 1 차단 항목. **운영자 결정 필요**.

## review_ver_11 Phase 1 진입 전 P0 4가지 진행 상황

| 항목 | 상태 | work_ver | 비고 |
|---|---|---|---|
| WS keepalive + reconnect metric | ✓ 완료 | 12-1 | Q1 답변; timestamp/storm duration 보강 후속 |
| KIS 실제 응답 fixture 검증 | ✓ 완료 | 12-2 | Q3 답변; paper vs live 비교 후속 |
| NAS 복구 drill | △ 부분 | 12-3 | self-test ✓, 실제 dry-run 미완료 (Phase 1 차단) |
| reference clock 원천 결정 | ✗ 미진행 | 없음 | 운영자 결정 필요 (Phase 1 차단) |

**Phase 1 진입 차단 항목 2개 남음**: NAS 실제 dry-run + reference clock 원천 결정.

## 추가 발견 (코드 직접 본 결과)

work_ver_12 시리즈 본문에 명시되지 않은 미세 항목 세 가지.

첫째, **`KisWebSocketReconnectMetrics`의 `record_frame()`이 매 frame마다 호출**(189~197행). 정규장 활성 종목은 초당 수십 frame이라 매 호출이 가벼워야 함. 현재 구현은 단순 카운트 + threshold 검사 + snapshot 생성(stable 도달 시점만)으로 가볍다. 다만 callback이 호출되는 stable 시점에 dashboard write/audit insert 같은 무거운 작업이 들어가면 quote stream에 지연 발생 가능. **권장**: callback 측에서 동기 무거운 작업 회피 (async queue 또는 별도 thread). work_ver_12-1에는 명시 없음.

둘째, **`KisWebSocketQuoteClient.listen()` 시그니처에 `metrics_callback` optional 추가**(306행). 기본값 None이라 기존 호출 호환. 좋은 backward compatibility.

셋째, **`PHASE2_DEFAULT_MAX_ORDER_QTY=1`가 default이지만 `order_policy.max_order_qty=10` override가 work_ver_12-2 본문 16행에서 테스트 helper에 명시**적으로 사용. 운영 default와 테스트 fixture가 명확히 분리되어 silent override 위험 없음.

## 위험한 가정

`KisWebSocketReconnectMetrics`의 callback이 동기 호출이라는 가정:
- 코드(449~452행)는 callback을 직접 호출하고 예외만 warning으로 흡수.
- callback이 무거운 작업(DB write, network call, file I/O)을 동기 수행하면 quote stream이 지연됨.
- 정규장 초당 수십 frame 환경에서 callback이 30ms 걸리면 누적 지연이 stream 안정성에 영향.
- **권장 보강**: callback docstring에 "동기 호출, 가벼운 in-memory 기록만 권장. DB/network은 별도 worker로" 명시.

`PHASE2_DEFAULT_MAX_ORDER_QTY=1`이 manager 내부 default 하드코드:
- review_ver_10에서 지적했던 "수치 한도는 별도 risk/live gate로 분리" 약속과 미세하게 어긋남.
- max_order_qty 자체는 작은 값이라 위험 영향 작지만, max_parent_orders_per_day, max_order_notional, max_order_allocation_pct, max_order_qty 4개 수치가 모두 manager hardcode인 상태가 누적.
- Phase 3 진입 전 별도 settings/gate config로 분리하는 작업이 필요(review_ver_10/11에서도 같은 권장).

## 보강 필요 테스트

1. **`KisWebSocketReconnectMetrics` callback 예외 흡수 회귀 테스트** — `tests/test_kis_ws_reconnect_metrics.py`에 "callback이 raise해도 listen()이 중단되지 않음" 케이스 명시 잠금. work_ver_12-1 본문에 callback 예외 흡수 언급되어 이미 잠겼을 가능성 높으나 명시 확인.
2. **`KisWebSocketReconnectMetrics`의 stable_connection 자동 reset 시점 테스트** — 4 frame까지는 stable=False, 5번째 frame에서 stable=True + consecutive=0 reset 검증.
3. **`PHASE2_DEFAULT_MAX_ORDER_QTY=1` override 테스트** — `order_policy.max_order_qty=2` 명시 시 정상 통과, 미명시 시 qty=2 차단. work_ver_12-2 본문 16행 패턴이 이미 적용.
4. **`export_kis_paper_fixture_candidates.py`의 redaction findings 자동 차단 테스트** — 가상 sensitive key가 redaction을 우회하면 exit non-zero. 회귀 안전망.
5. **NAS recovery 실제 dry-run 자동화 테스트** — 가능하면 self-test에 `scripts/export_recovery_snapshot.sh --dry-run` 실제 호출을 묶어 sandbox에서 자동 검증. WSL approval timeout 회피.

## 문서 보강 필요

1. **`docs/Production-Implementation-Blueprint.md`** — Phase 1 진입 전 P0 4가지 진행 상황표(위 표) 반영. 차단 항목 2개 명시.
2. **`docs/Production-Architecture.md`** — `max_order_qty=1` 기본 정책 명문화 + override 방법.
3. **WS metric runbook** — `runtime-data/reports/codex/ops/`에 `ws-reconnect-metrics-snapshot.json` 같은 read-only 노출 경로 후보를 dashboard 카드 추가와 함께 명시.
4. **`docs/cowork-reports/operator-decision-template`** — reference clock 원천 결정 항목 추가(후보: KIS API 응답 시각 헤더 / NTP / 수동). 운영자 결정 양식.

## 종합

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 WS reconnect metric | Phase 1 측정 충분 | timestamp 추가, storm duration, Phase 2 guard 연결은 후속 |
| Q2 Phase 2 max_order_qty=1 | review_ver_11 Q2 권장 그대로 closure | 없음 |
| Q3 KIS fixture mapper + redaction | 현 단계 안전 | paper vs live shape 비교 후속 |
| Q4 NAS recovery self-test | 불충분 | **Phase 1 진입 전 실제 dry-run 1회 필수** |
| Phase 1 진입 전 P0 진행 | 4중 3 완료 | NAS 실제 drill + reference clock 결정 |

## 다음 단계 권장

1. **Phase 1 진입 차단 P0 2가지 (운영자 작업)**:
   - **NAS 실제 dry-run 1회**: 장외 시간 `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run` 완료 확인.
   - **reference clock 원천 결정**: KIS API 응답 시각 헤더(가장 자동화 가능) / NTP / 수동 sync 중 결정 후 system_clock에 연결.
2. **Phase 1 진입 전 보강 (코드 작업)**:
   - `KisWebSocketReconnectMetrics` snapshot에 `observed_at` 추가 → dashboard "마지막 reconnect N분 전" 표시 가능.
   - WS reconnect snapshot을 readiness `ws_recovery` check에 read-only 연결 (work_ver_12-1 다음 권장).
3. **Phase 1 read-only 진입 직후 P1**:
   - **paper vs live KIS shape 비교** (work_ver_12-2 후속).
   - **Phase 2 진입 전 NAS dry-run 2번째** (review_ver_11 Q10).
4. **Phase 3 진입 전 P2 (지속 누적)**:
   - manager hardcode 4개 수치 한도(`max_parent_orders_per_day`, `max_order_notional`, `max_order_allocation_pct`, `max_order_qty`)를 별도 settings/gate config로 분리.

## 신뢰 수준

work_ver_12 시리즈는 review_ver_11 권장의 4중 3을 정확히 closure하고, review_ver_11 Q2 권장(`max_order_qty=1`)까지 함께 closure. **Codex의 권장 흡수 정확도가 일관되게 높다.** 다만 NAS 실제 dry-run과 reference clock은 운영자 작업/결정 영역이라 코드만으로 해결 불가 — Phase 1 진입 차단 잔여 2건이 운영자 결정 큐에 올라간다.

다음 라운드(review_ver_13 예상)에서 cowork이 (a) reference clock 원천 결정 후 system_clock 연결 검증, (b) WS reconnect snapshot이 readiness/dashboard에 노출되는 코드 검증, (c) NAS dry-run 결과 검토 — 세 단계로 본다. 이 셋이 끝나면 Phase 1 read-only 진입 가능.
