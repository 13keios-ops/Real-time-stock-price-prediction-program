# Claude cowork 리뷰 review_ver_6: review_ver_5 보강 + Slice 2b + Codex CLI 운영 자동화 설계

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_6`
- 기준 작업본: `2026-05-15-production-architecture-implementation-blueprint-work_ver_6-3.md` (work_ver_6 + 6-1 + 6-2 통합본)
- cowork 직접 검증 파일: `app/storage/sqlite_store.py`(`backup_database`), `app/services/live_order_guard.py`(phase 정규화), `app/services/live_phase_readiness.py`, `scripts/script_dispatch.sh`(`storage_migration_apply` 보강분)

## 요약

work_ver_6-3는 review_ver_5의 보강 권고 다섯 가지(SQLite native backup, watchdog 정지 검증, sample smoke check, READONLY_PHASES 정규화, Slice 2b 테이블/인덱스 등록)를 모두 정확히 흡수했다. Slice 2b의 9개 테이블 + 15개 인덱스 + approval/readiness hash service까지 한 라운드에 들어갔는데 158개 전체 테스트 통과. 결론은 **그대로 사용 가능. Codex CLI 운영 자동화는 설계만 OK, 구현은 codex_ops.py manifest부터.**

이번 라운드의 cowork 질문 5개는 모두 Codex CLI 운영 자동화 설계 영역(섹션 4)이라 코드 검증보다 정책 검토가 큰 비중. 답을 한 줄씩 요약하면: (1) 격리 방향 OK, 코드 강제와 책임 범위 명문화 보강 필요. (2) 장중 보호 규칙과 충돌 없음, 일률 금지 표현 3곳을 sub-action별 분기로 정밀화 권장. (3) premarket → postclose → intraday 순서 옳음, 단 manifest 자체가 0번 슬라이스. (4) 위치 OK, codex/ 하위 디렉토리 정책 정리 + NAS 백업 포함 여부 명시 필요. (5) 위치 OK, 자동 cleanup 보호 한 줄 추가 권장.

## review_ver_5 보강 권고 흡수 검증 (코드 직접 본 결과)

먼저 코드 변경부터 확인했다. 다섯 가지 모두 정확히 반영됐다.

**(1) SQLite native backup**. `sqlite_store.py` 665~672행:

```python
def backup_database(self, backup_path: Path) -> Path:
    """Create a consistent SQLite backup, including committed WAL pages."""
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        backup_path.unlink()
    with closing(self._connect()) as source, closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)
    return backup_path
```

`source.backup(target)`이 SQLite 표준 backup API라서 WAL/SHM 일관성을 자동으로 처리한다. 단순 `shutil.copy2` 위험이 사라졌다. 정확한 구현.

**(2) watchdog 정지 검증**. `script_dispatch.sh` 839~854행의 `services_are_stopped`에 `watchdog_status = status_payload(root, "get_runtime_watchdog_status.sh")`와 `watchdog_running` 검증 추가. 세 서비스 모두 정지일 때만 True 반환. race condition 방지.

**(3) sample smoke check**. `run_sample_smoke_check`(862행)가 새로 추가되어 schema 적용 후 실제 insert/read/delete 한 번 수행. table/index 존재만 보던 것에서 실제 동작 검증으로 강화됨.

**(4) Slice 2b 테이블/인덱스 등록**. `REQUIRED_TABLES` 9개(`market_status_snapshots`, `live_orders`, `live_order_events`, `live_fills`, `live_positions`, `live_portfolio_snapshots`, `ops_live_audit_events`, `live_phase_approvals`, `live_readiness_runs`), `REQUIRED_INDEXES` 15개. apply wrapper가 Slice 2b까지 한 번에 잠근다.

**(5) READONLY_PHASES 정규화**. `live_order_guard.py` 124~136행의 `_normalize_phase`(re.sub로 공백/대시 정규화 + alias 처리) + `_phase_reasons`(`KNOWN_PHASES`에 없으면 `phase_unknown`). silent bypass 위험 차단. 좋은 구현. 다만 `KNOWN_PHASES`에 새 phase 추가 시 코드 수정이 필요한 trade-off는 의도된 strict 정책.

review_ver_5 보강 권고가 모두 코드로 잠겼다. 이 부분은 100% 흡수.

## Q1: Codex CLI를 운영 보조 에이전트로 격리하는 방향이 충분히 보수적인지

**방향은 옳지만 "격리"가 정책 표명에 머무르고 코드 강제가 약하다.** 네 가지 보강 후보.

첫째, **격리가 합의인지 코드 강제인지 명시 안 됨.** 본문 4.1의 "Codex CLI는 ... 운영 보조 에이전트로 격리해야 한다"는 의도 표명이지 코드 invariant가 아니다. Codex CLI는 본질적으로 명령을 실행할 수 있는 에이전트라 "이건 안 한다"는 합의에 의존하면 운영 단계에서 새 작업자나 새 job이 추가될 때 silent breach 위험이 있다. **`codex_ops.py`의 job manifest에 허용/금지 액션을 명시적 enum으로 잠그는 코드 강제가 필요하다.** 다음 단계 권장 7장 첫째 항목과 일치.

둘째, **현재 Codex 작업 범위와 운영 자동화 범위의 차이가 모호하다.** AGENTS.md에서 Codex는 이미 코드/문서/테스트 변경 + commit/push 자율을 가지고 있고 work_ver_6-3까지 모든 라운드가 그 자율 안에서 진행됐다. 운영 자동화에서 "운영 보조"로 격리한다는 것은 이 자율을 운영 단계에서는 좁힌다는 뜻. **두 모드(개발 자율 vs 운영 보조)의 구분 메커니즘이 명시되어야 한다.** 가능한 구분: (a) 환경 변수(`CODEX_OPS_MODE=runtime`), (b) job manifest의 mode 필드, (c) 실행 wrapper가 자동 감지(장 시간/장 상태 기준).

셋째, **금지 항목 4개(주문 submit/cancel, ALLOW_LIVE_ORDERS 변경, gate 기준값 변경, app/risk/ 변경)는 잘 명시됐다. 단 한 가지 누락**: **운영 DB schema apply도 자동 작업 범위 밖**에 둬야 한다. 현재 4.1에 명시되지 않음. apply_storage_migration.sh가 이미 plan-mode default와 `--apply` 명시 플래그를 요구하므로 silent apply는 막혀 있지만, Codex CLI job이 `--apply`를 자동 추가할 수 있는지의 정책이 명시되어야 한다. **권장: 운영 DB schema apply는 운영자 명시 승인 후에만, Codex CLI job은 plan-mode만 자동 실행.**

넷째, **"운영 보조"의 책임 범위가 일관되지 않다.** 4.1 추상 표현은 "운영 보조"인데 4.7 incident triage에서는 "patch 초안" 제시까지 들어간다. patch 초안 작성은 보조보다 한 단계 더 능동적이다. **두 가지를 명시적으로 분리**: (a) read-only 분석 + report 생성(가장 보수), (b) patch 초안 제시(중간), (c) 자동 적용(가장 위험, 금지). 4.4 표의 "허용" 칸을 이 세 단계로 다시 정리하면 명확.

종합: **방향 OK, 격리 강제와 책임 범위 명문화가 codex_ops.py 구현 전 필요.**

## Q2: 장 상태별 권한 모델이 장중 수집 보호 규칙과 충돌하지 않는지

**충돌은 없다. 다만 일률 금지 표현 3곳을 sub-action별 분기로 정밀화하면 더 정확.**

본문 4.4 표를 AGENTS.md/README.md/blueprint의 장중 보호 규칙과 비교하면 큰 충돌 없다. "장중 heavy research 금지", "장중 cleanup 금지", "장중 schema 변경 금지"가 모두 4.4 표의 "pre-open / regular" 금지 칸과 일관된다. 좋은 정합.

세 가지 미세 사각:

첫째, **"runtime restart" 일률 금지가 모호.** 장중 dashboard가 stale로 죽었을 때 dashboard restart는 수집 회복 자체를 위한 안전 조치고 watchdog이 자동으로 한다. Codex CLI도 같은 작업을 할 수 있는지, watchdog만 가능한지 경계가 모호. **권장 분기**: (a) Codex CLI는 runtime restart를 직접 하지 않음(추천만), (b) watchdog은 정책대로 자동 restart, (c) 운영자가 수동 restart 수행. 이 셋이 명시되면 충돌 없음.

둘째, **"full test" 일률 금지가 일부 안전한 케이스를 막는다.** unit test는 mock 기반이라 운영 DB나 KIS 호출에 영향 없다. 단순 import 테스트도 안전. 의도가 "test 실행 자체가 CPU/IO를 먹어 장중 운영을 흔들지 마라"라면 명시. 의도가 "장중에는 어떤 테스트도 돌리지 마라"라면 그대로 일률 금지. **권장**: "장중 unit test는 허용하되 integration/storage/network 테스트는 금지" 또는 "장중에는 어떤 test도 자동 실행하지 않음" 둘 중 하나로 명시.

셋째, **`python -m app ...` 일률 금지**가 일부 read-only 명령까지 막는다. `python -m app --build-runtime-report`는 read-only이고 장중에도 안전(이미 watchdog quick maintenance가 호출). `python -m app --train-lightgbm`은 heavy라서 장중 금지가 맞다. **권장**: app sub-command별 허용/금지 표를 codex_ops.py manifest에 두고, 장중에는 read-only/light sub-command만 허용.

종합: **장중 보호 규칙 충돌 없음. 일률 금지 3곳을 manifest의 sub-action 분기로 정밀화.**

## Q3: premarket-readiness → postclose-research → intraday-incident-triage 순서가 맞는지

**순서 옳음. 단 0번 슬라이스로 codex_ops.py manifest가 먼저.**

세 가지 이유로 순서 동의:

1. **premarket-readiness는 위험이 가장 작다.** 입력이 모두 status 파일/snapshot, 출력이 report. 운영 안전 영향 거의 0. 첫 job으로 적합. 본문 7장 둘째 권장(`live_phase_readiness.py`를 사용해 dry-run report만)과 일치.
2. **postclose-research는 격리된 snapshot DB만 사용**한다고 명시됐다. live DB heavy read/write 금지(본문 7장 셋째 권장). 위험 중간. Slice 2b 진입 후 안정화 후 진행이 자연스러움.
3. **intraday-incident-triage가 가장 위험.** 장중 시점에 분석 + patch 초안. 잘못된 patch가 운영자에게 잘못된 조치 유도 위험. 마지막 배치가 맞다.

추가 권고: **0번 슬라이스로 `app/services/codex_ops.py`의 job manifest + 권한 모델을 순수 함수로 먼저 구현하고 테스트한다는 본문 7장 첫째 권장이 가장 중요.** 이게 없으면 premarket job 구현부터 권한 검증이 ad-hoc으로 들어가게 된다. manifest 자체가 위험 0이고 후속 3개 job 모두의 안전 잠금이 된다.

따라서 정확한 순서는: **0. codex_ops.py manifest → 1. premarket-readiness → 2. postclose-research → 3. intraday-incident-triage.** work_ver_6-3 다음 단계 권장 그대로.

postclose-maintenance-review와 cowork-handoff job은 어디에 들어가는지 명시 안 됨. 우선순위 후순위로 — 위 4단계 후 검토.

## Q4: Codex CLI job 결과 저장 위치 runtime-data/reports/codex/ops/

**위치 적절. 두 가지 보강 권고.**

기존 정책과의 정합을 보면:
- AGENTS.md: `runtime-data/`는 실행 로그, 리포트, 캐시, 모델 산출물
- 기존 codex 하위: `runtime-data/reports/codex/automation/` (hourly audit 산출물)
- 제안 신규: `runtime-data/reports/codex/ops/`(운영 자동화), `.tmp-tests/codex-ops/`(장중 격리 작업)

`runtime-data/reports/codex/` 하위에 `ops/` + `automation/` + (이전 단계의) `action-items/` 세 디렉토리가 자연스러움. 정책 일관성 좋다.

첫째 보강 권고, **codex/ 하위 디렉토리 정책 정리.** README.md 또는 AGENTS.md에 codex 하위 구조와 각 디렉토리 책임을 한 표로 정리. cowork-reports/는 이제 docs/cowork-reports/로 이동됐으니 codex/action-items/는 deprecated 또는 다른 용도. 명시 정리가 필요.

둘째 보강 권고, **NAS 백업 정책과의 정합.** 현재 NAS 백업은 root `.env*`, KIS 토큰 캐시, runtime logs, private key 계열을 제외한다. **`runtime-data/reports/codex/ops/`에 들어갈 job report가 NAS 백업 포함 범위인지** 명시 필요. 실전 운용 audit log는 NAS 백업 포함되어야 한다는 invariant(review_ver_3부터)와 일치하는지 검증. 운영자 결정이 필요하지만 Codex 권장안: **premarket-readiness/postclose-research/postclose-maintenance-review report는 백업 포함**, **intraday-incident-triage의 patch 초안은 백업 제외**(임시 영역, 운영자 승인 후 적용된 것만 다른 경로로 이동).

## Q5: 장중 incident patch 초안 위치 .tmp-tests/codex-ops/로 제한

**위치 OK. 자동 cleanup 보호 한 줄 추가가 필수.**

기존 정책 (AGENTS.md 8장):
- `.tmp-tests/`: 임시 테스트 산출물 위치, 검증 뒤 **삭제 가능**

여기에 patch 초안을 두면 다음 cleanup에서 silent하게 삭제될 수 있다. patch 초안은 운영자 승인 전까지 보존이 필요하므로:

**권장 보강 1**: `.tmp-tests/codex-ops/`만 자동 cleanup 대상에서 명시적으로 제외. AGENTS.md 8장에 한 줄 추가 또는 cleanup 스크립트가 이 경로를 skip하도록 코드 강제.

**권장 보강 2**: patch 초안의 적용 절차 명시. 운영자가 어떻게 review하고 어떤 시점에 적용하는지(장후 자동? 운영자 수동? cowork 리뷰 후?). 이건 incident triage job 구현 시 정의될 영역이지만, **"장중 patch 초안은 장중 적용하지 않는다"**는 invariant가 codex_ops.py manifest에 들어가야 한다.

**권장 보강 3**: 별도 git worktree 옵션은 본문 7장에서 제안됐지만 **장중에는 worktree 생성/삭제가 git lock을 잡을 수 있어 0이 아닌 운영 영향**. `.tmp-tests/codex-ops/` 안에 unified diff 형식 텍스트로만 두는 게 가장 안전. worktree는 장후에만.

종합: **위치 OK, 자동 cleanup 보호 + 적용 절차 + worktree 장후 제한 — 세 가지 invariant가 manifest에 들어가야 안전.**

## 추가 발견 (코드 직접 본 결과)

work_ver_6-3 본문에 명시되지 않은 미세 항목 네 가지.

첫째, **`live_phase_readiness.py`의 `READINESS_CHECK_KEYS` 6개 (token_refresh, ws_recovery, account_snapshot, market_status, kill_switch, database)가 잘 정리됐다.** 다만 `_hash_payload`(135~137행)가 `sort_keys=True`로 결정론적 hash를 만드는 점이 좋다. dict 순서 차이로 hash가 달라지는 함정 차단.

둘째, **`create_phase_approval`의 `expires_at`이 운영자 입력으로만 결정**된다(28행). default 없음. 운영자가 매번 정해야 하는데 시간 단위 결정 부담이 큼. 장 시간 기준 default(예: 다음 거래일 16:00)를 함수 default로 두는 것을 검토 후보로 둘 만함. 우선순위 낮음.

셋째, **`live_phase_readiness.py`에 active approval 조회 함수가 본문 2.3 표에 명시됐는데 코드에 직접 없음.** create 함수만 있고 fetch/lookup 함수는 별도일 가능성. 본문에서 "active approval 조회"라고 명시했는데 cowork이 직접 확인하지 못함. Slice 5 진입 시 검증 필요.

넷째, **`apply_storage_migration` wrapper의 `services_are_stopped`가 watchdog까지 검증하지만, `services_are_stopped` 호출이 plan mode에서도 일어남**(script_dispatch.sh 887~889행 부근). plan mode는 DB 변경이 없으므로 service 상태 무관하게 plan을 만들 수 있어야 효율적. 현재 구조는 plan mode에서도 service 상태를 호출하는데, 결과를 차단에 안 쓰고 report에만 넣음. 안전 측이지만 실행 시간 증가. 우선순위 낮음.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| review_ver_5 보강 흡수 (5건) | 100% | 없음 |
| Q1 격리 방향 | 옳음 | 코드 강제 + 책임 범위 명문화 |
| Q2 장 상태별 권한 모델 | 충돌 없음 | runtime restart / full test / `python -m app` 일률 금지 → sub-action 분기 |
| Q3 구현 순서 | 옳음 | 0번 슬라이스 = codex_ops.py manifest |
| Q4 저장 위치 | OK | codex/ 하위 정책 정리, NAS 백업 포함 여부 명시 |
| Q5 patch 초안 위치 | OK | 자동 cleanup 보호 한 줄, 적용 절차 명시, worktree 장후 제한 |

## 다음 단계 권장

1. **codex_ops.py 0번 슬라이스 (job manifest + 권한 모델)**: job별 manifest 구조 + 허용/금지 액션 enum + 장 상태별 권한 모델을 순수 함수로 구현. 테스트 fixture 기반. 위험 0.
2. **manifest에 5개 invariant 잠금**: (a) 운영 DB schema apply 자동 금지, (b) `.tmp-tests/codex-ops/` 자동 cleanup 보호, (c) 장중 patch 초안은 장중 적용 금지, (d) NAS 백업 포함 정책, (e) sub-action 별 허용/금지.
3. **READINESS_CHECK_KEYS 운영 의미 한 번 검토**: 6개 키(token_refresh/ws_recovery/account_snapshot/market_status/kill_switch/database)가 Phase 1 readiness에 충분한지. 추가 후보로 `disk_space`, `dashboard`, `storage_migration_state` 등이 있을 수 있음. premarket-readiness job 구현 전 결정.
4. **codex 하위 디렉토리 정책 표**: README.md 또는 AGENTS.md에 codex/ops/, codex/automation/, (필요하면) codex/action-items/ 책임 정리.
5. **운영자 결정 잔여**:
   - Codex CLI job 실행 주체 (Codex 권장: watchdog 자동 분석 요청까지, 적용은 운영자 승인)
   - 장중 incident patch 적용 시점/절차 (Codex 권장: 장후 또는 명시 승인 후)
   - NAS 백업 포함 범위 (Codex 권장: report 포함, patch 초안 제외)
6. **Slice 5 live order manager 진입 가능**: review_ver_5 보강 + Slice 2b까지 끝났으므로 order manager가 사용할 storage layer는 모두 준비됨. codex_ops.py manifest와 병행 가능(서로 의존성 없음).

## 신뢰 수준

work_ver_6-3는 review_ver_5 보강 다섯 가지를 100% 정확히 흡수했고, Slice 2b 6개 dataclass + 6개 테이블 + approval/readiness hash service까지 한 라운드에 들어갔는데 158개 테스트 통과 + service stop 검증 강화 + native backup + sample smoke check까지 모두 코드와 테스트로 잠궜다. **Codex 자율 작업 품질이 cowork 리뷰 라운드와 같은 수준으로 일관되게 유지된다.**

이번 라운드의 cowork 리뷰는 코드 검증 비중이 작고 정책 검토(Codex CLI 운영 자동화) 비중이 컸다. Codex CLI 운영 자동화는 새로운 책임 영역이라 첫 manifest 구현 라운드(review_ver_7 예상)에서 cowork이 (a) manifest 코드 직접 검증, (b) 권한 모델 잠금 확인, (c) 장 상태별 invariant 잠금 확인 — 세 단계로 보겠다.
