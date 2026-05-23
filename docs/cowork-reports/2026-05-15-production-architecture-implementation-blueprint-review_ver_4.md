# Claude cowork 리뷰 review_ver_4: Slice 1 보강 + Slice 2a 검증 강화 + Slice 3 + dry-run wrapper

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_4`
- 기준 작업본: `2026-05-15-production-architecture-implementation-blueprint-work_ver_4.md`
- cowork 직접 검증 파일: `app/services/market_status.py`, `tests/test_market_status.py`, `app/storage/contracts.py`(검증 강화), `scripts/script_dispatch.sh`(storage_migration_dry_run 함수), `scripts/run_storage_migration_dry_run.sh`, `tests/test_storage_migration_dry_run_script.py`, `app/brokers/kis_readonly.py`(주석 보강 확인)

## 요약

work_ver_4는 review_ver_3의 모든 보강 권장(factory call-time 검증, describe 시그니처, sub-field 타입, 빈 idempotency 가드, codex actor 명시, dry-run wrapper)을 흡수했고, Slice 3 market status 순수 로직도 깔끔하게 추가됐다. 134개 전체 테스트 통과는 회귀 안전 측면에서 신뢰할 만하다. 결론은 **그대로 사용 가능. Slice 4 (live_order_guard) 진입 권장.** Codex의 다음 slice 권장 순서(Slice 4 → Slice 2b → Slice 5)에 동의한다.

핵심 발견 세 가지: (1) `market_status.py`의 차단 사유 11개가 review_ver_2/3에서 지적한 국내장 미시 규칙 9개를 모두 cover하고 flag-based 구조라 확장이 쉽다. (2) `codex` actor 처리는 **주석만으로는 운영 안전 측면에서 약하다.** 명시적인 잠금 또는 enum 제거가 필요. (3) `dry-run` wrapper는 schema 적용 가능성 검증으로는 좋지만 운영 DB 실제 적용 시점의 lock/backup/rollback 절차는 별도 wrapper가 필요하다.

## Q1: market_status.py 차단 사유가 Phase 2 첫 20거래일 기준에서 빠뜨린 미시 규칙

**95% 충분. 핵심 9개는 모두 들어갔고, 추가 4개는 데이터 원천 결정 후 자연 확장 가능.**

`market_status.py`의 차단 사유 11개를 직접 확인했다 — `market_status_stale`, `market_session_not_allowed`, `symbol_status_missing`, `tradable_unknown`/`not_tradable`, `trading_suspended`, `management_issue`, `investment_warning`, `price_limit_blocked`(upper/lower/near 통합), `vi_active`(volatility_interruption 별칭 포함), `single_price_auction`(call_auction 별칭 포함), `corporate_action`. review_ver_2/3에서 지적한 9개 미시 규칙(상한가/하한가, 거래정지/관리/투자유의, 동시호가, 시간외 단일가, 권리락/배당락/액면분할/유상증자, VI)이 모두 cover된다. T+2 결제와 부분 체결과 시계 오차는 work_ver_4 본문 77행에서 별도 slice로 분리한다고 정직하게 명시됐다.

`_flag()` 헬퍼와 `_symbol_blocking_reasons()`의 flag-based 구조(89~108행)가 좋다. 새 차단 사유 추가가 한 줄로 가능하고, 별칭 키도 함께 받는다(예: `suspended/trading_suspended/halted` 셋이 모두 `trading_suspended`로 매핑). 데이터 원천이 KIS REST든 거래소 OpenAPI든 다른 키 이름을 줘도 별칭 추가로 흡수 가능.

`evaluate_market_status`의 `symbol_status` override 처리(48~49행 `if isinstance(symbol_status, dict) and "market_session" in symbol_status:`)도 잘 짜여 있다. 종목별로 세션이 다를 수 있는 상황(예: 단일가 매매 종목)을 자연스럽게 처리한다.

Phase 2 첫 20거래일에 추가로 보강 후보 4가지가 있다. 모두 데이터 원천 결정 후 sub-field로 흡수 가능하다.

첫째, **장 시작 직후 변동성 윈도우(09:00~09:05)**가 별도 카테고리로 명시되지 않았다. blueprint에서 09:15까지 신규 진입 금지 정책이 있는데, market_status는 시간 기반 판정을 하지 않는다. snapshot 데이터 원천이 `opening_volatility_window` 같은 sub-session을 주거나, 별도 시간 기반 게이트(예: `app/services/market_clock.py` 후보)와 결합해야 한다. 우선순위 중간.

둘째, **VI 종료 직후 grace 윈도우.** 현재 구조에서는 `vi_active=False`로 바뀌면 즉시 unblock된다. VI 해제 직후 1~2분간 호가 흐름이 불안정한 한국 시장 특성상 Phase 2 보수 모드라면 grace가 안전하다. snapshot data가 `vi_resolved_at` 시각을 주면 현재 함수에 한 줄로 추가 가능.

셋째, **종목별 가격 변동 폭(전일 종가 대비 ±5% 이상 변동)**. 가격제한 근접 외에도, 단일 종목이 장중 급등/급락 중이면 슬리피지 위험이 커진다. market_status보다는 risk gate 영역이지만, snapshot에 `current_change_pct` 또는 `intraday_volatility` hint가 있으면 양 layer에서 활용 가능.

넷째, **시초가/종가 동시호가의 sub-session 식별**. 현재는 `single_price_auction` 또는 `market_session_not_allowed`로 묶이는데, audit 시 "시초가 동시호가"인지 "종가 동시호가"인지 "시간외 단일가"인지 구분이 필요할 수 있다. 데이터 원천이 표준화된 값을 주면 sub-flag로 받으면 된다.

종합: 현 구조로 Phase 2 진입에 충분. 위 4개는 Slice 4 또는 후속에서 데이터 원천 결정 후 흡수.

## Q2: idempotency_key 빈 문자열 금지와 JSON sub-field type 검증이 storage layer 책임으로 충분한가

**충분하다. manager layer 중복 검증은 필요 없다.**

`contracts.py`를 직접 봤을 때 `_require_non_empty`(22~24행), `_require_type`(27~29행), `_require_keys`(16~19행) 세 헬퍼가 dataclass `__post_init__`에서 fail-fast로 raise한다. `LiveOrder.idempotency_key` 빈 문자열 금지(301행), `MarketStatusSnapshot.status_json` 3개 sub-field 타입 검증(261~265행), `LiveOrder.detail_json` 3개 sub-field 타입 검증(307~309행) 모두 instance creation 시점에 잡힌다. 잘못된 데이터가 dataclass instance가 되지 않고, 따라서 DB INSERT까지 도달하지 못한다.

manager layer 중복 검증이 필요한 경우는 두 시나리오뿐이다. 첫째, manager가 dataclass를 거치지 않고 raw dict를 직접 SQLite에 INSERT하는 코드 경로가 생기는 경우 — 이건 storage 우회로 그 자체가 안티패턴이라 isolation 테스트로 잠궈야 할 영역. 둘째, manager가 비즈니스 invariant(예: `qty > 0`, `limit_price`가 호가단위 정렬, idempotency 충돌 시 처리 정책)를 잠그는 경우 — 이건 manager의 본래 책임이고 storage layer가 아닌 별도 validation이다. 두 시나리오 모두 storage layer 검증의 중복이 아니라 추가 책임이다.

따라서 **현재 storage layer 검증이 충분하고, manager layer는 비즈니스 invariant만 담당하면 된다.**

다만 한 가지 일관성 보강 후보가 있다. **`_require_non_empty`가 `idempotency_key`에만 적용됐는데, 다른 NOT NULL TEXT 필드(`order_id`, `symbol`, `side`, `prediction_id`, `signal_id`, `target_id`, `gate_decision_id`, `market_status_snapshot_id`, `model_version`, `rule_version`)도 빈 문자열은 의미가 없다.** SQLite는 빈 문자열을 NULL과 다르게 처리하므로 NOT NULL 제약을 만족한다 — 의미 없는 빈 문자열이 통과하는 약점이 있다. `LiveOrder.__post_init__`에 한 줄 루프로 빈 문자열 체크를 추가하면 일관성이 잡힌다. 우선순위는 중간(현재 caller가 모두 dataclass를 통하므로 silent bug 위험은 낮음).

## Q3: run_storage_migration_dry_run.sh가 운영 DB 적용 전 safety net으로 충분한가

**70% 충분. 현재는 "schema 적용 가능성" 검증으로 좋지만, "실제 운영 적용" wrapper는 별도가 필요.**

`scripts/script_dispatch.sh`의 `storage_migration_dry_run()` 함수(646~744행)와 wrapper script를 직접 봤다. 동작은 다섯 단계: (1) source_db 사본을 work_dir로 복사(없으면 빈 DB 생성), (2) `SQLiteRuntimeStore(dry_db, initialize_schema=True)`로 schema 초기화 시도, (3) 필수 테이블 3개와 인덱스 5개 존재 확인, (4) JSON 리포트 저장, (5) 누락 시 exit 1. 좋은 점은 **운영 DB를 직접 건드리지 않고 사본에서 시도**하며 **work_dir/report_path를 저장소 루트 안으로 강제**해 path traversal을 막는 점(683~686행). `test_work_dir_must_stay_inside_repository`가 정확히 이 invariant를 잠근다.

`test_dry_run_initializes_live_tables_on_temp_copy`가 실제 subprocess로 wrapper를 호출해 status `ok`와 missing tables/indexes가 빈 리스트임을 검증한다. wrapper의 회귀 안전 측면에서 매우 좋은 잠금이다.

남은 약점 네 가지:

첫째, **운영 DB가 사용 중일 때(live runtime/dashboard가 connection 잡고 있을 때)의 lock 동작은 검증되지 않는다.** dry-run은 사본을 만들기 때문에 원본의 lock 위험을 직접 보지 못한다. 더 무거운 위험: `shutil.copy2(source_db, dry_db)` (696행)가 lock된 SQLite WAL/SHM 파일을 일관된 상태로 복사한다는 보장이 없다. 운영 적용 전에 live runtime/dashboard 정지가 선행되어야 안전한데, 그 절차가 wrapper에 없다.

둘째, **실제 백업 → 적용 → smoke → 롤백 절차가 별도 wrapper로 빠졌다.** dry-run은 "syntax 적용 가능성" 검증이고, 실제 운영 적용은 (a) live runtime 정지, (b) 백업 생성, (c) schema 적용, (d) smoke query, (e) 재기동의 5단계 wrapper가 필요. blueprint 274행에 같은 절차가 적혀 있는데 wrapper 자동화가 없다. `scripts/apply_storage_migration.sh` 같은 별도 스크립트가 Slice 2b 진입 전 만들어지면 좋다.

셋째, **기존 paper 데이터가 있는 DB 사본에서의 dry-run 케이스가 없다.** 현재 테스트는 source_db가 없는 케이스(missing-source.sqlite3)에서만 검증한다. 실제 운영 DB는 paper_orders/paper_fills 등 기존 테이블이 가득 차 있는 상태인데, 이런 상태에서 새 테이블 추가가 정상 동작하는지(트랜잭션 충돌, 기존 인덱스와의 이름 충돌 등)는 별도 검증이 필요. test fixture에 "기존 paper 테이블 시뮬레이션 후 dry-run" 케이스 한 개 추가가 안전.

넷째, **롤백 시나리오 정의 부재.** `CREATE TABLE IF NOT EXISTS`가 부분 실패 시(예: 테이블 1개는 만들어졌는데 다음 테이블 만들다가 디스크 부족) partial state를 남긴다. dry-run은 사본에서 하니 영향 없지만, 실제 운영 적용 wrapper에서는 DROP TABLE 또는 DB 복원 같은 롤백 절차가 정의되어야 한다.

종합: **현재 dry-run은 회귀 안전 측면에서 좋은 첫 단계.** Slice 2b 진입 전 (a) live runtime 정지를 포함한 적용 wrapper, (b) 기존 paper 데이터 있는 케이스 dry-run 테스트, (c) 롤백 절차 — 세 가지가 추가되면 충분한 safety net이 된다.

## Q4: 다음 slice = live_order_guard.py가 맞는가, 아니면 live_fills/positions/audit schema가 먼저인가

**Codex 권장(Slice 4 guard 먼저)에 동의한다.** 세 가지 이유.

첫째, **guard는 schema보다 더 큰 안전 invariant를 잠근다.** Slice 4 guard에서 `TRADING_MODE=live` + `ALLOW_LIVE_ORDERS=true` + kill switch off + market_status allowed + phase approval — 다섯 층의 검증이 한 곳에 모인다. 이 잠금이 없으면 후속 slice에서 schema가 있어도 실수로 live order가 나갈 위험이 잔존한다. 운영 안전 관점에서 "주문 호출 직전의 마지막 차단점"을 가장 빨리 잠그는 게 옳다.

둘째, **guard는 새 schema 의존성이 거의 없다.** kill switch 파일은 별도 메커니즘(`runtime-data/reports/live-risk/kill-switch.json` 후보 파일), market_status_snapshot은 이미 Slice 2a/3에 있다. fills/positions/audit schema가 없어도 guard 자체는 동작 가능. Slice 5 order manager에서 schema 필요성이 강해지는데, guard 작업과 schema 작업의 결합도가 낮다.

셋째, **Slice 2b는 운영 DB migration 위험이 크다.** 6개 테이블(`live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs`)을 운영 DB에 추가하는 작업은 Slice 2a의 3개 테이블보다 약 2배다. Slice 2a 운영 DB 적용 후 며칠 안정성을 본 다음 진행하는 게 안전. 위 Q3에서 적은 추가 wrapper(적용 wrapper, 기존 데이터 케이스 테스트, 롤백 절차)가 Slice 2b 진입 전 보강되면 좋다.

다만 한 가지 보완: **Slice 4 guard 구현 시 kill switch 파일 schema와 atomic write/read 메서드도 함께 만들어야 한다.** blueprint 596~603행의 `LiveKillSwitch` service interface가 정의되어 있다. guard가 kill switch state를 읽으려면 이 service가 필요하므로 사실상 함께 들어가야 한다. work_ver_3에서 kill switch schema는 이미 정해져 있다(blueprint 240~254행).

## Q5: codex actor를 fixture/migration 진단용 주석으로 남긴 결정이 충분한가

**불충분하다. 주석만으로는 운영 안전 측면에서 약하다.**

`contracts.py` 11~13행의 현재 처리:

```python
LIVE_ORDER_EVENT_ACTORS = {"system", "account_owner", "recovery", "kill_switch", "codex"}
# `codex` is for implementation-time fixtures and migration diagnostics, not
# for unattended live trading decisions.
```

주석은 의도 표명이지 코드 강제가 아니다. 운영 단계에서 누군가 codex actor로 audit event를 작성해도 통과한다. 운영 단계의 audit log에 codex actor가 섞이면 사후 추적 시 "이 결정이 사람/시스템/codex 중 누가 한 것인지"가 흐려진다. **운영 안전 측면에서 audit log의 actor는 강하게 잠겨야 한다.**

세 가지 옵션이 있다.

옵션 A (강한 잠금, cowork 권장): **enum에서 codex 제거, 테스트 전용 actor `test`를 추가.** fixture는 `actor="test"`로 수정. migration 진단 도구는 이미 enum에 있는 `system`을 쓰면 된다.
- 장점: 운영 코드에서 절대 codex actor가 들어가지 않는다. 실수 차단.
- 단점: 기존 테스트 fixture 한 줄 수정, migration 진단 도구가 codex 대신 system 또는 별도 actor 사용.

옵션 B (중간): codex actor를 enum에 두되, **운영 모드(`TRADING_MODE != paper`)일 때 codex actor 거부 검증 추가**.
- 장점: 진단 시 codex actor 사용 가능. 운영 시 차단.
- 단점: dataclass에 settings 의존성이 들어가야 함. 약간 복잡.

옵션 C (현재): 주석으로 의도 표명만.
- 장점: 단순.
- 단점: 강제력 없음.

**권장은 옵션 A.** 가장 단순하고 강한 잠금. 한 줄 변경으로 codex 제거 + test 추가:

```python
LIVE_ORDER_EVENT_ACTORS = {"system", "account_owner", "recovery", "kill_switch", "test"}
```

테스트 fixture는 `actor="system"`(현재 테스트는 이미 system 사용) 또는 `actor="test"`로 수정. 운영 코드에서 `actor="test"`가 들어가면 코드 리뷰에서 즉시 발견된다.

추가 보강: **운영 단계에서 audit log에 `actor="test"`가 0건이어야 한다는 invariant 테스트를 별도로 두면 더 강한 잠금이 된다.** Slice 7 audit chain 진입 시 함께 검토.

## 추가 발견 (코드 직접 본 결과)

work_ver_4 본문에는 명시되지 않은 미세 항목 세 가지를 코드에서 확인했다.

첫째, **`market_status.py`의 `_flag()` 헬퍼가 `is True`로만 매치한다(112행).** truthy 값(예: `vi_active=1`, `vi_active="yes"`)은 매치하지 않는다. 데이터 원천이 표준화되지 않은 boolean을 줄 수 있는데, 이 경우 차단이 silent하게 통과될 수 있다. 데이터 원천 결정 후 normalization layer(`MarketStatusService.build_snapshot`이 표준화 책임을 진다는 invariant)가 없으면 위험. 우선순위 중간.

둘째, **`evaluate_market_status`가 `status_json["symbols"]`에서 `symbol_status`를 가져올 때, `symbol_status`가 dict가 아니어도(예: `None`, `True`, 문자열) `symbol_status_missing` 차단으로 안전하게 떨어진다(56~58행).** 좋은 fail-safe. 단 `symbol_status`가 list 또는 다른 type이면 어떻게 되는지 명시적 테스트가 없다. 현재 fixture에서는 `{}`만 시험됨. 우선순위 낮음.

셋째, **`scripts/run_storage_migration_dry_run.sh`(5행) `exec`로 dispatch에 전달하는데, 인자 quoting이 `"$@"`로 정상 처리된다.** 공백 있는 경로도 안전. WSL 환경에서 자주 발생하는 경로 공백 처리가 정확. 좋은 패턴.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 market_status 차단 사유 | 95% | 09:00~09:05 변동성 윈도우, VI 종료 grace, 종목별 변동 폭, 동시호가 sub-session 식별 (Slice 4 또는 데이터 원천 결정 후) |
| Q2 storage layer 검증 충분성 | 100% | 다른 NOT NULL TEXT 필드도 `_require_non_empty` 일관성 보강 후보 |
| Q3 dry-run wrapper safety net | 70% | 적용 wrapper(live runtime 정지 + backup), 기존 paper 데이터 케이스 테스트, 롤백 절차 (Slice 2b 진입 전) |
| Q4 다음 slice 우선순위 | live_order_guard 먼저 | kill switch service도 같은 slice에 함께 |
| Q5 codex actor 주석 | 불충분 | enum에서 codex 제거, `test` actor 추가 권장 |

## 다음 단계 권장

1. **Slice 4 live_order_guard.py + LiveKillSwitch service**: work_ver_4 권장 그대로. kill switch state 파일 schema와 atomic write/read 함께. 5층 검증(TRADING_MODE, ALLOW_LIVE_ORDERS, kill switch, market_status, phase approval) 한 곳에 잠금.
2. **codex actor enum 처리 결정**: 옵션 A(제거 + test 추가) 권장. 1줄 변경.
3. **NOT NULL TEXT 빈 문자열 일관성 보강**: `LiveOrder.__post_init__`에 한 줄 루프 추가. 우선순위 중간.
4. **Slice 2b 진입 전 wrapper 보강**: 적용 wrapper 자동화, 기존 paper 데이터 dry-run 케이스, 롤백 절차 정의. Slice 4 작업과 병행 가능.
5. **데이터 원천 결정**(P1): market_status snapshot의 데이터 원천(KIS REST vs 거래소 OpenAPI vs 수동 calendar) 결정. Slice 3 외부 API 연결 진입 전 필요.
6. **운영자 결정 잔여**: 일일 손실 한도/슬리피지 budget 수치, audit hash chain anchor 방식 — 이 둘은 Slice 4 guard와 병행해서 결정 권장.

## 신뢰 수준 변화

work_ver_3에서 처음 코드가 들어왔고, work_ver_4는 그 코드를 더 단단하게 잠그면서 새 순수 로직(market_status)을 추가했다. **회귀 안전(134개 테스트 통과), 코드 자체 안전(fail-fast 검증), 운영 적용 준비(dry-run wrapper) 세 측면 모두 진보했다.** Codex가 cowork 리뷰 피드백을 흡수하는 속도와 정확도가 일관되게 높다. 다음 라운드부터는 (a) Slice 4 guard 코드 직접 검증, (b) kill switch 파일 schema/atomic write 검증, (c) Slice 2b 적용 wrapper 검증을 cowork이 같은 패턴으로 본다.
