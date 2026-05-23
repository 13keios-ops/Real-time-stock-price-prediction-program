# Claude cowork 리뷰 review_ver_7: live readiness 9개 check 확장 + 명시 DB 기록 옵션

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_7`
- 기준 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-4.md` + `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-5.md`
- 참고: 7-4와 7-5는 cowork 리뷰 사이에 들어온 연속 sub-work라 한 번의 review_ver_7로 묶어 답함
- cowork 직접 검증 파일: `app/services/live_phase_readiness.py`, `scripts/script_dispatch.sh`(`live_readiness_dry_run` 함수), `tests/test_live_readiness_dry_run_script.py`

## 요약

work_ver_7-4(9개 check 확장) + work_ver_7-5(`--record --database-path` 명시 옵션)는 review_ver_6의 "READINESS_CHECK_KEYS 6개 충분성 검토" 권장과 "운영 DB insert는 명시 승인 후" invariant를 정확히 흡수했다. 187개 전체 테스트 통과 + Codex CLI 운영 자동화 manifest와 결합한 premarket adapter 설계 + fixture-based fault injection 구조 — 모두 보수적 방향으로 잘 짜여 있다. 결론은 **그대로 사용 가능. 다음 단계는 `database` check를 SQLite smoke로 분리하면서 새 3개 check의 SQL 컬럼화 결정 라운드.**

핵심 발견 두 가지: (1) `LiveReadinessRun` dataclass와 `live_readiness_runs` 테이블 컬럼이 6개 그대로 유지된 채 새 3개 check(`disk_space`, `dashboard`, `storage_migration_state`)는 `checks_json` JSON 안에만 들어간다 — 영구 결정인지 임시 결정인지 명시 필요. (2) `--record --database-path` 구조가 매우 보수적으로 잘 짜여 있고 4개 회귀 테스트로 잠겨 있다.

## Q1: Phase 1 readiness 9개 check 확장이 보수적 기준에 맞는지

**맞다. 9개 모두 운영 안전 관점에서 필수 항목이고, fail-closed 정책(누락 fixture는 `not_verified`라 차단)이 일관된다.**

`live_phase_readiness.py` 13~23행의 `READINESS_CHECK_KEYS` 9개를 봤다:
- Phase 0/1 자체 안전: `database`, `disk_space`, `dashboard`, `storage_migration_state`(인프라/스토리지)
- KIS 연동 안전: `token_refresh`, `ws_recovery`, `account_snapshot`(외부 의존성)
- 시장 안전: `market_status`(미시 규칙)
- 운영 안전: `kill_switch`(긴급 차단)

review_ver_6 발견 항목("disk_space, dashboard, storage_migration_state 추가 후보")이 그대로 반영됐다. 9개가 운영 안전의 카테고리 분류(인프라 4 + KIS 3 + 시장 1 + 운영 1)로도 정합적이다. 누락 후보가 더 있는지 보면:
- `kis_credentials`(check_statuses에서는 보이지만 readiness key는 아님 — `token_refresh`로 묶임): OK
- `audit_chain_integrity`: 향후 Slice 7 audit 진입 시 추가 후보
- `network_egress_to_kis`: 일반 token_refresh로 간접 검증되므로 별도 검증 필수는 아님

따라서 **9개로 충분**. 향후 audit/order manager 진입 시 `audit_chain_integrity`나 `live_orders_recovery_complete` 같은 항목을 점진 추가하면 된다.

`build_fault_injection_dry_run_report`(208~269행)의 fail-closed 설계도 좋다. 누락 fixture는 `not_verified`로 status 잡고 `passed=False`. boolean fixture는 `ok/failed`로 normalize. dict fixture는 `status` 키 우선. 어떤 형태든 누락은 silent하게 통과하지 않는다.

## Q2: database와 storage_migration_state 중복 처리

**현재 중복은 운영자 가시성 측면에서 이점이 있어 적절하다. 단 다음 라운드에서 의미적 분리가 필요하다.**

현재 두 check의 의미가 겹친다. `create_readiness_run_from_premarket_report`(143~205행) 168행과 171행을 보면 둘 다 `check_statuses.get("storage_migration_state") == "ok"`에서 추론된다. 즉 **현재는 같은 값을 다른 이름으로 두 번 표시**하고 있다.

운영자 가시성 측면에서 두 칸이 있는 게 좋은 점:
- dashboard에서 "storage migration이 OK인가"와 "database 자체가 OK인가"가 분리되면 사고 분리 진단이 쉬워진다.
- storage migration은 스키마 적용 절차 자체이고, database는 SQLite 연결성/응답성. 의미적으로 다르다.

다만 **현재 구현은 두 의미를 같은 값으로 채우고 있어 진정한 분리가 아니다**. work_ver_7-5 다음 권장(`database` check를 실제 SQLite read/write smoke로 분리)이 정확한 방향이다.

권장: **다음 라운드에서 두 check를 의미적으로 분리**.
- `storage_migration_state`: `apply_storage_migration.sh` plan/apply 결과 status. 스키마 무결성 확인 책임.
- `database`: 실제 SQLite 연결 + 한 번의 read 성공 + WAL 상태 확인. 연결성 책임.

분리 후 둘 다 OK여야 통과 — 같은 의미 중복이 아니라 직교한 두 안전 invariant가 된다. Q5 답과 일치.

## Q3 (7-4 #3 + 7-5 #1): readiness DB 저장이 기본에서 제외 + `--record --database-path` 명시 구조의 보수성

**매우 보수적. 5층 잠금이 코드와 테스트로 모두 강제된다.**

`script_dispatch.sh` 1545~1672행의 `live_readiness_dry_run`을 직접 봤다. 5층 잠금:

1. **`--record`가 `--database-path` 없이는 실패**(1613~1614행): `--record requires --database-path`.
2. **database_path는 저장소 내부 강제**(1615~1616행): path traversal 방지.
3. **database_path 파일이 이미 존재해야 함**(1617~1618행): wrapper가 새 SQLite 파일을 silent하게 생성하지 않음.
4. **`--execute`/`--apply` 명시적 거부**(1563행): "supports dry-run only"로 raise.
5. **기본 동작은 JSON only**(1645행 `if record_db:` 가드 안에서만 insert).

테스트 잠금 4개(`tests/test_live_readiness_dry_run_script.py`):
- `test_record_requires_explicit_database_path`(146행)
- `test_record_database_path_must_stay_inside_repository`(159행)
- `test_record_database_path_must_already_exist`(178행)
- `test_record_writes_readiness_run_to_existing_sqlite_db`(198행)

**5층 잠금 + 4개 테스트** 조합으로 운영자가 의도 없이 운영 DB에 readiness run을 insert할 위험이 거의 0이다. 매우 좋은 보수적 설계.

다만 한 가지 운영 절차 권고: **`--record`가 가능한 명령이 됐으니 누가/언제 호출해야 하는지 runbook 합의 필요.** Codex 권장안(work_ver_7-5 6.1)인 "Phase 1 read-only 전환 직전까지는 수동 실행만"이 합리적. 자동 호출 경로(예: post-close maintenance, premarket-readiness job)에서 silent하게 `--record`가 들어가면 의도와 다르게 매일 readiness run이 누적될 수 있어 위험.

## Q4: `initialize_schema=False`로 insert만 시도하는 정책

**적절. 운영 DB 적용 전 안전 기준에 맞다.**

`script_dispatch.sh` 1666행: `store = SQLiteRuntimeStore(database_path, initialize_schema=False)`.

이 결정의 의미:
- wrapper가 schema 자동 생성을 하지 않으므로, **DB에 `live_readiness_runs` 테이블이 없으면 insert가 실패**한다(IntegrityError).
- 사용자가 의도하지 않은 DB(예: 빈 사본 또는 잘못된 경로의 SQLite 파일)에 schema를 silent하게 만들지 않는다.
- 운영 DB schema 적용은 별도 절차(`apply_storage_migration.sh`)로 분리되어 있고, 이 wrapper는 schema가 이미 적용된 DB만 받는다는 invariant.

이는 **정확히 옳은 분리**다. schema apply와 record insert가 같은 wrapper에 묶이면 silent하게 새 schema를 만들 위험이 있는데, 분리되어 있어 운영자가 두 단계를 명시적으로 수행해야 한다. apply_storage_migration의 plan-mode default + record의 initialize_schema=False가 결합해서 "schema 적용 → insert 가능"의 두 단계가 명확히 잠긴다.

부수: **`runtime-data/dev.db`에 처음 `--record`를 시도하기 전 반드시 `apply_storage_migration.sh --apply`가 한 번 실행되어 있어야 한다.** 이게 runbook에 명시되어야 운영자가 처음 readiness record를 시도할 때 헷갈리지 않는다.

## Q5: 다음 라운드에서 `database` check를 SQLite read/write smoke로 분리

**동의. 우선순위 가장 높은 다음 작업 후보.**

현재 `database`와 `storage_migration_state`가 같은 값에서 추론되어 두 칸이 같은 의미를 가지는 약점은 Q2에서 적었다. 분리 방향 두 가지:

옵션 A (Codex 권장): **`database` = 실제 SQLite read/write smoke**. 연결 + sample insert + sample read + sample delete + WAL 상태. apply_storage_migration의 `run_sample_smoke_check`와 같은 패턴이지만 read-only로 변형(insert/delete 대신 read만).

옵션 B: **`database` = 연결성만, `storage_migration_state` = 스키마 무결성**. 두 의미를 더 좁게 정의.

옵션 A가 더 강한 검증이지만 매번 read/write를 일으킨다. premarket 시점에 sample insert가 되어도 안전하지만 `live_readiness_runs` 테이블에 dummy row가 누적되면 안 됨 — 따라서 read-only smoke(예: `SELECT 1` 또는 PRAGMA quick_check)가 안전.

권장 구현:
- `database` check = `SQLiteRuntimeStore`를 열어 `PRAGMA integrity_check` 실행 + 최근 insert 가능한 테이블 한 개에 read 시도
- `storage_migration_state` check = `apply_storage_migration.sh` plan 결과의 `status == "planned"` 또는 마지막 apply의 `status == "ok"`

이 분리로 두 check가 직교한 의미를 갖는다.

## 추가 발견 (코드 직접 본 결과)

work_ver_7-4/7-5 본문에 명시되지 않은 미세 항목 두 가지.

첫째, **`LiveReadinessRun` dataclass와 `live_readiness_runs` SQL 컬럼이 6개 ok flag로 그대로 유지된다**. `live_phase_readiness.py` 120~140행의 `create_readiness_run`은 9개 check를 받지만 `LiveReadinessRun(...)` 생성자에는 6개(`token_refresh_ok`, `ws_recovery_ok`, `account_snapshot_ok`, `market_status_ok`, `kill_switch_ok`, `database_ok`)만 넘긴다. 새 3개(`disk_space_ok`, `dashboard_ok`, `storage_migration_state_ok`)는 `checks_json["checks"]` JSON 안에만 들어간다.

장단점:
- 장점: schema migration 불필요. dataclass와 SQL 컬럼 그대로 유지. 회귀 위험 0.
- 단점: SQL 인덱싱 불가. 향후 dashboard에서 `disk_space_ok=False`인 readiness run을 빠르게 조회하려면 JSON parsing 필요. group by/filter 비효율.

**이 결정이 영구인지 임시인지 명시 필요.** 영구라면 향후 모든 새 check도 JSON only로 들어간다는 합의. 임시라면 다음 schema migration 라운드에 SQL 컬럼화하는 계획이 있어야 한다. 현재 work_ver_7-4 본문에 이 결정의 의미가 적혀 있지 않다. **권장**: 다음 라운드 또는 코멘트로 결정 명시.

둘째, **`create_readiness_run_from_premarket_report`의 4개 fail-by-default check**(`ws_recovery`, `account_snapshot`, `market_status`, `kill_switch`)는 premarket report로는 verify할 수 없어 무조건 false가 된다(167~170행). override 없으면 readiness가 항상 blocked.

이 정책은 매우 보수적이고 옳다. 다만 **override를 누가 어떤 fixture로 주입하는지가 명시되지 않았다**. 현재 구조에서는 `build_fault_injection_dry_run_report`가 fixture를 받지만, 운영 단계에서 실제 ws_recovery/account_snapshot/market_status/kill_switch를 verify하는 별도 runner가 필요하다. 단순 fixture가 아니라 실제 fault injection runner. 이건 향후 slice(예: Slice 8 fault injection runner) 작업 영역이라 우선순위는 낮지만 **현재 구조에서 4개 check는 dry-run에서만 통과 가능하고 실전 readiness는 영원히 blocked**라는 점이 명시되어야 운영자가 혼동하지 않는다.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 readiness 9개 check 보수성 | 맞음 | 없음 |
| Q2 database vs storage_migration_state 중복 | 가시성 측면 OK | 다음 라운드에서 의미 분리 (Q5와 결합) |
| Q3 readiness DB 저장 기본 제외 + --record 명시 | 매우 보수적 | runbook 합의 (누가 언제 --record 호출) |
| Q4 initialize_schema=False 정책 | 적절 | runbook에 "apply 먼저, record 나중" 두 단계 명시 |
| Q5 database를 SQLite smoke로 분리 | 동의 | 옵션 A(read-only smoke) 권장 |
| LiveReadinessRun SQL 컬럼 6개 유지 (cowork 발견) | 결정 명시 필요 | 영구/임시 명시, 임시면 schema migration 계획 |
| 4개 fail-by-default check (cowork 발견) | 보수적 정책 옳음 | 실전 fault injection runner 향후 slice 명시 |

## 다음 단계 권장

1. **`database` check를 SQLite read-only smoke로 분리**: PRAGMA integrity_check + 최근 read 가능 테이블에 SELECT 1. `storage_migration_state`는 apply 결과 status 추적으로 의미 분리. Q5/Q2 동시 해소.
2. **LiveReadinessRun SQL 컬럼 결정 명시**: 새 3개 check가 JSON only인 게 영구인지 임시인지. 임시면 다음 schema migration에 컬럼 추가 계획. 영구면 docstring/코멘트로 명시.
3. **runbook 합의**: (a) `--record` 호출 주체와 시점(Codex 권장: Phase 1 전환 직전까지 수동만), (b) `apply_storage_migration --apply` 한 번 후 `--record` 가능한 두 단계 절차.
4. **Slice 5 live order manager 진입 가능**: storage layer + readiness + guard + market status + kill switch 모두 준비됨. order manager가 `LiveOrderGuard`를 호출하는 첫 caller로 자연스럽게 들어갈 수 있음.
5. **Slice 8 fault injection runner 후속**: 4개 fail-by-default check(ws_recovery, account_snapshot, market_status, kill_switch)를 실전 검증할 runner. 우선순위는 Slice 5 다음.

## 신뢰 수준

work_ver_7-4와 work_ver_7-5는 cowork 리뷰 없이 진행한 연속 sub-work인데도 review_ver_6의 권장(`READINESS_CHECK_KEYS` 6개 충분성, "운영 DB insert는 명시 승인 후" invariant)을 정확히 흡수했고, 5층 잠금 + 4개 회귀 테스트로 운영 DB 보호도 단단하다. **Codex 자율 작업 품질이 cowork 리뷰 라운드와 같은 수준으로 일관되게 유지된다.** 이번 라운드 결과물 187개 테스트 통과 + 새 코드의 fail-closed 설계 + 명시 옵션 분리 — 모든 면에서 안전 측.

다음 라운드부터 cowork이 (a) `database` check 분리 구현 검증, (b) Slice 5 live order manager 진입 시 `LiveOrderGuard` 호출 패턴 검증, (c) LiveReadinessRun SQL 컬럼 결정 라운드 검증 — 세 단계로 본다.
