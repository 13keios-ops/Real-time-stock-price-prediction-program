# Claude cowork 리뷰 review_ver_8: database smoke 분리 + SQL column 정책 명시

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_8`
- 기준 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_8.md`
- cowork 직접 검증 파일: `app/services/codex_ops.py`(`_check_database_smoke`), `app/services/live_phase_readiness.py`(database vs storage_migration_state 분리 확인), `scripts/script_dispatch.sh`(`sqlite_readonly_smoke` 함수)

## 요약

work_ver_8은 review_ver_7의 최우선 권장 3가지(database check 분리, storage_migration_state 의미 분리, 새 3개 check의 SQL 컬럼 정책 명시)를 모두 정확히 흡수했다. 188개 전체 테스트 통과 + `PRAGMA quick_check`의 60초 timeout 위험을 실제 운영 DB로 확인해 가벼운 connectivity check로 낮춘 판단도 운영 안전 기준에 맞다. 결론은 **그대로 사용 가능. Slice 5 live order manager 진입 권장.**

핵심 발견: (1) database check가 의미적으로 분리됐다 — `live_phase_readiness.py` 179행이 `check_statuses.get("database") == "ok"`로 변경되어 storage_migration_state에서 독립. (2) `sqlite_readonly_smoke`가 `mode=ro` URI + timeout 2초 + 4개 가벼운 쿼리로 60초 timeout 위험을 회피한다. (3) JSON only 정책이 명시적 결정으로 잠겼다.

## Q1: database smoke를 quick_check 없이 가벼운 read-only 연결성 확인으로 낮춘 판단

**장중 안전 기준에 맞다. 60초 timeout 위험을 실제 측정으로 확인하고 회피한 결정이 정확.**

`script_dispatch.sh` 1485~1508행의 `sqlite_readonly_smoke`를 직접 봤다. 안전 측 설계 4가지:

1. **`mode=ro` URI 강제**(1491행): read-only 연결로만 열어 silent write 위험 0.
2. **timeout 2초**(1493행): lock 대기로 인한 wrapper 차단 시간을 강제로 짧게.
3. **4개 가벼운 쿼리만 수행**: `PRAGMA journal_mode`, `PRAGMA schema_version`, `sqlite_master`에서 1행 LIMIT, `SELECT 1`. 모두 O(1)에 가깝다.
4. **path traversal 방지**(1487~1488행): 저장소 외부 DB는 `blocked, database_path_outside_root`.

`PRAGMA quick_check` 제거는 옳다. quick_check는 DB 전체 페이지를 스캔해 무결성 검증하는데, 6.5GB+ 운영 DB에서 60초가 넘는다는 점이 실제 측정으로 확인됐다(work_ver_8 39행). premarket job이 매번 60초 차단되면 운영 불가다. integrity 검증이 필요하면 별도 less-frequent 작업(예: 주말 maintenance)으로 분리하는 게 맞고, premarket의 database check는 "연결되고 응답하는가" 수준이 적절하다.

`_check_database_smoke`(`codex_ops.py` 468~500행)의 status 분기도 정확:
- `ok` → severity=info
- `missing`/`unknown` → severity=warning (verify가 안 됐을 뿐 차단은 아님)
- 그 외 → severity=blocker (실제 SQLite error)

이는 review_ver_7 Q5 권장 옵션 A("read-only smoke")를 그대로 구현한 형태이고, 의도된 trade-off(가벼움 vs 무결성 검증)를 균형 있게 잡았다.

남은 미세 보강 후보 두 가지:
- **integrity 검증 별도 작업**: weekly maintenance 또는 post-close maintenance에 `PRAGMA integrity_check` 또는 `PRAGMA quick_check`를 시간 제한 없이 한 번 실행하는 작업이 향후 필요. 우선순위 낮음.
- **lock 대기 timeout 발생 시 분류**: 현재 `sqlite3.Error`로 잡혀 `blocked`로 떨어지는데, "lock 대기"와 "실제 손상"이 같은 분류라 운영 진단이 어려울 수 있다. timeout/lock 패턴은 `unknown` 또는 `transient_lock`으로 별도 분류하면 더 정확. 우선순위 중간.

## Q2: 새 3개 check를 checks_json에만 두고 SQL column 승격을 후속 결정으로 남기는 권장안

**동의. review_ver_7의 권고(영구/임시 결정 명시)가 정확히 이행됐다.**

work_ver_8 6.2 권장안 "당장은 JSON only를 유지하고, dashboard/리포트에서 SQL filter가 필요해지는 시점에 migration으로 승격"이 YAGNI 원칙에 맞다. 장점:

1. **schema migration 위험을 후속으로 미루는 안전한 선택.** 매번 새 check 추가마다 ALTER TABLE을 하면 schema 변경이 누적되어 운영 DB 안정성에 누적 영향. 필요할 때만 한 번에 승격하는 게 보수적.
2. **JSON only도 기능적으로 충분.** `checks_json["checks"]["disk_space"]`로 접근 가능하고 dashboard에서 단일 readiness run의 9개 check를 모두 표시 가능.
3. **결정 시점이 명확.** "SQL filter가 필요해지는 시점"이 기준이라 운영자가 dashboard query를 작성하다가 명시적으로 필요성을 발견할 때 의사결정.

단점: dashboard나 후속 분석에서 "최근 N개 readiness run 중 `disk_space=False`인 것만 필터"가 필요해지면 JSON parsing 비용이 누적된다. SQLite의 JSON1 extension(`json_extract`)으로 인덱싱 가능하지만 native column보다 느림. 다만 readiness run이 매일 1~5개 수준이라 누적량이 작아 실용적으로 문제 없을 가능성이 높다.

권장 추가 조치 한 가지: **JSON only 결정을 blueprint 또는 contracts.py docstring에 명시.** 코드 읽는 사람이 "왜 새 3개는 SQL 컬럼이 아닌가"를 ad-hoc 파악하지 않고, 의도된 결정임을 명시로 확인할 수 있어야 한다. work_ver_8 본문에는 명시됐지만 코드 안에 docstring 한 줄이 있으면 완전.

## Q3: Slice 5 live order manager 진입 vs --record runbook 먼저 잠그기

**Slice 5 진입 권장. `--record` runbook은 parallel하게 합의해도 충분.**

Slice 5 진입 가능한 이유:
1. **storage layer 준비 완료**: Slice 2a/2b로 `market_status_snapshots`, `live_orders`, `live_order_events`, `live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs` 모두 추가됨.
2. **guard 준비 완료**: `LiveOrderGuard.assert_can_submit()` + `assert_can_cancel()`가 5층 invariant(trading_mode, profile_mode, ALLOW_LIVE_ORDERS, phase_approved, market_status + kill_switch)를 검증.
3. **kill switch service 준비 완료**: fail-closed read/write가 있고 atomic write 보장.
4. **market status 준비 완료**: 11개 차단 사유 분류 + flag truthy normalization.
5. **readiness service 준비 완료**: 9개 check + premarket adapter + dry-run only.
6. **migration apply wrapper 준비 완료**: plan mode default + service stop check + native backup + sample smoke check.

Slice 5 order manager가 위 6개를 활용하는 첫 caller로 자연스럽게 들어간다. order manager가 만들 핵심 메서드:
- `create_intent(signal, target, gate_decision, market_status)`: intent_created 상태로 LiveOrder 생성
- `submit(intent)`: LiveOrderGuard.assert_can_submit + KIS broker adapter 호출 직전
- `request_cancel(order_id, reason)`: LiveOrderGuard.assert_can_cancel
- `recover_open_orders()`: 재시작 시 unknown 상태 처리
- `mark_unknown(order_id, reason)`: timeout/DB lock 등에서 fail-safe

`--record` runbook은 운영 절차 합의 영역이고 Slice 5 코드 작업과 의존성이 없다. parallel 진행 가능하다. 단 다음 두 가지가 Slice 5 진입 전 또는 진입 직후 결정되어야 한다:

a) **운영자가 `apply_storage_migration.sh --apply`를 한 번 실행해 `live_orders` 등 9개 테이블을 운영 DB에 만들어야** Slice 5의 첫 LiveOrder insert가 가능. apply 시점 합의가 Slice 5 첫 실전 테스트보다 먼저.

b) **kill switch 파일 ON/OFF CLI**: work_ver_5의 잔여 위험 항목. 운영자가 kill switch를 안전하게 ON/OFF할 CLI가 없으면 Slice 5의 kill switch 검증이 사실상 코드 path만 잠근 형태. 실전 진입 전 보강 필요.

종합: **Slice 5 진입 권장. (a)/(b) 두 가지가 Slice 5 코드 작업과 parallel하게 진행되면 더 안전.**

## 추가 발견 (코드 직접 본 결과)

work_ver_8 본문에 명시되지 않은 미세 항목 두 가지.

첫째, **`sqlite_readonly_smoke`의 `timeout=2.0`이 하드코드**(1493행). 운영 DB가 정상 상태라면 2초로 충분하지만, 운영 DB lock이 일시적으로 발생하는 시간대(예: post-close maintenance 시작 직후)에 premarket job이 false negative `blocked`를 받을 수 있다. 운영 환경별로 조정 가능한 environment variable 또는 인자가 있으면 좋다. 우선순위 낮음.

둘째, **`_check_database_smoke`의 `missing`/`unknown` 분기는 둘 다 `severity=warning`으로 동일**(486~493행). 의미적으로는 다르다 — `missing`은 DB 파일이 없음(설정 문제), `unknown`은 smoke 결과를 가져오지 못함(데이터 누락). 분류는 같지만 details에서 구분 가능하니 dashboard 표시에서 구분 가능. 우선순위 낮음.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 database smoke 가벼운 connectivity | 장중 안전 기준 적합 | weekly integrity_check 별도 작업 (낮음), lock timeout 별도 분류 (중간) |
| Q2 새 3개 check JSON only 결정 | 동의 | docstring으로 결정 의도 명시 |
| Q3 Slice 5 진입 vs --record runbook | Slice 5 진입 권장 | apply 실행 + kill switch CLI parallel |
| sqlite_readonly_smoke 추가 발견 | 충분 | timeout 하드코드 → 환경별 조정 가능 |

## 다음 단계 권장

1. **Slice 5 live order manager 진입**: order manager가 `LiveOrderGuard` 첫 caller로 들어감. 상태머신 + idempotency + 재시작 복구 + stuck/unknown 처리.
2. **Parallel 작업 1**: 운영자가 `apply_storage_migration.sh --apply`로 9개 live 테이블을 운영 DB에 적용. Slice 5 첫 실전 테스트 전에 필요.
3. **Parallel 작업 2**: kill switch ON/OFF CLI 도구 (work_ver_5 잔여 위험). 운영자가 안전하게 kill switch를 변경할 수 있어야 Slice 5 검증이 실전 의미.
4. **Slice 5 진입 시 검증 패턴**: order manager 구현 라운드에서 cowork이 (a) LiveOrderGuard 호출 패턴 검증, (b) idempotency_key 생성과 unique 충돌 처리 검증, (c) 재시작 복구 로직 검증, (d) state transition 금지 invariant 검증.
5. **JSON only 결정 명시**: `live_phase_readiness.py` 또는 blueprint에 "새 3개 check는 SQL 컬럼 승격 보류, dashboard/리포트에서 SQL filter 필요해지는 시점에 migration" 한 줄 추가.
6. **운영자 결정 잔여**:
   - 일일 손실 한도/슬리피지 budget 수치 (P0, Phase 2 진입 차단 항목, 지속 잔여)
   - `--record` 자동화 시점 (Phase 1 read-only 관측 기간 후로 미루는 Codex 권장안)

## 신뢰 수준

work_ver_8은 review_ver_7의 핵심 3개 권장을 정확히 흡수했고, `PRAGMA quick_check` 60초 timeout 위험을 실제 측정으로 확인해 가벼운 connectivity check로 낮춘 결정도 운영 안전 측면에서 옳다. **Codex의 cowork 권장 흡수 정확도가 일관되게 높다.** 188개 테스트 통과, 5층 운영 안전 잠금이 모두 코드와 테스트로 유지됨.

다음 라운드(review_ver_9, 예상)에서 cowork이 Slice 5 live order manager를 본다. 검증 단계는 위 다음 단계 권장 4번 그대로.
