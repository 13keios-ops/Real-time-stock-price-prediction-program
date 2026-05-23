# Claude cowork 리뷰 review_ver_5: Slice 4 (LiveOrderGuard + LiveKillSwitch) + apply_storage_migration wrapper

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_5`
- 기준 작업본: `2026-05-15-production-architecture-implementation-blueprint-work_ver_5.md` + `2026-05-15-production-architecture-implementation-blueprint-work_ver_5-1.md`
- 참고: `work_ver_5-7527ba4f.md`는 `work_ver_5.md`와 동일한 hash-suffix copy. cowork은 `work_ver_5` + `work_ver_5-1` 두 작업본을 한 번에 review.
- cowork 직접 검증 파일: `app/services/live_kill_switch.py`, `app/services/live_order_guard.py`, `tests/test_live_order_guard.py`, `scripts/apply_storage_migration.sh`, `scripts/script_dispatch.sh`(`storage_migration_apply` 함수), `tests/test_storage_migration_apply_script.py`

## 요약

work_ver_5 + work_ver_5-1은 review_ver_4의 핵심 보강 다섯 가지(Slice 4 guard, kill switch service, codex actor 제거, market status truthy normalization, apply wrapper)를 모두 흡수했고, apply wrapper의 plan-mode default와 path traversal 방지, runtime DB 보호 정책이 매우 안전하게 짜여 있다. 152개 전체 테스트 통과. 결론은 **그대로 사용 가능. Slice 2b 또는 Slice 5 진입 권장.**

핵심 발견 세 가지: (1) `LiveKillSwitchState.cancel_only_allowed`가 `True` 고정이라 cancel 정책의 미래 확장성이 약하지만 현재 의도된 fail-open-for-cancel 정책과는 일치한다. (2) `READONLY_PHASES` 집합이 하드코드라 phase 이름 오타 시 silent bypass 위험이 있다 — phase enum 정규화가 필요. (3) `apply_storage_migration.sh`의 rollback이 단순 file copy 기반이라 SQLite WAL/SHM 일관성 위험이 잠재한다 — work_ver_5-1 본문 70행에서 솔직하게 인정됨.

## Q1: ALLOW_LIVE_ORDERS=false에서도 cancel-only 허용 정책이 Phase 2 안전 관점에서 맞는가

**정책 자체는 합리적이지만, ALLOW_LIVE_ORDERS의 의미적 정의에 운영자 합의가 필요하다.**

`live_order_guard.py` 87~103행을 직접 봤을 때 `assert_can_cancel`은 (a) `_live_profile_reasons`(trading_mode + profile_mode == live), (b) `_base_phase_reasons`(phase 비어있지 않음), (c) `kill_switch_state.cancel_only_allowed`만 검증한다. **`allow_live_orders`는 검증하지 않는다.** 이건 "submit은 위험 증가니까 막고, cancel은 위험 감소(보호성)니까 허용"이라는 비대칭 정책의 의도다.

운영자 의도 두 가지 가능성:
- 시나리오 A — "ALLOW_LIVE_ORDERS=false = 신규 위험만 막고 기존 미체결 처리는 계속": **현재 정책이 맞다.** 운영자가 사고 의심으로 ALLOW_LIVE_ORDERS를 false로 내리면 새 주문은 막고 미체결만 정리하고 싶을 수 있다. 이 경우 cancel 허용은 안전 장치다.
- 시나리오 B — "ALLOW_LIVE_ORDERS=false = live 운용 자체 일시 정지, 모든 액션 차단": 이 경우 현재 정책은 부족하다. cancel도 막아야 한다.

**내 권장: 시나리오 A 채택 + 운영자 합의 명시.** 시나리오 B가 필요하면 별도 kill switch ON으로 처리하는 게 의미적으로 더 명확하다(`ALLOW_LIVE_ORDERS=false`는 "신규 차단 of intent", `kill switch ON`은 "전체 차단 of intent and protective action"으로 의미 분리).

다만 한 가지 주의할 점: **cancel-only가 ALLOW_LIVE_ORDERS=false에서도 허용되면, 누가 실수로 ALLOW_LIVE_ORDERS=false 상태에서 cancel을 트리거했을 때 KIS API로 실제 호출이 나간다.** 이건 ALLOW_LIVE_ORDERS 플래그의 의미를 약화시킬 수 있다. 보강 후보: cancel은 (a) ALLOW_LIVE_ORDERS=true이거나, (b) 별도 ALLOW_LIVE_CANCELS=true 플래그 또는, (c) 운영자 명시적 cancel-only flag(`ALLOW_PROTECTIVE_CANCELS=true`)에서만 허용. 이건 결정 항목이지 코드 결함은 아니다.

## Q2: kill switch missing/broken/stale에서 cancel-only 허용하는 fail-closed 설계가 충분히 보수적인가

**70% 보수적. submit fail-closed는 좋지만 cancel fail-open은 한 가지 위험을 남긴다.**

`live_kill_switch.py` 36~49행을 직접 봤다. `LiveKillSwitchState.submit_blocking_reason`은 status != "ok"이면 `kill_switch_state_{status}`를 반환해 submit을 막는다. 반면 `cancel_only_allowed`는 `True` 고정(48~49행). missing/broken/stale 상태에서도 cancel은 항상 허용된다.

**합리적인 부분**: kill switch 파일이 손상돼도 운영자가 "이미 broker에 들어간 미체결을 정리하지 못하면 더 위험"하다고 판단할 수 있다. 보호성 동작은 차단하지 않는다는 정책이 실전 운용 안전 측면에서 의미가 있다.

**남은 위험**: kill switch 파일이 broken/missing이라는 건 운영 시스템에 이상이 있다는 신호인데, 그 상태에서 자동 cancel 작업이 의도치 않게 실행되면(예: order manager의 stuck 처리 루틴이 자동 cancel 시도) **잘못된 cancel = 의도와 다른 포지션 변경**이 될 수 있다. cancel은 위험 감소가 아니라 "현재 포지션을 그대로 유지할지 닫을지"의 결정이라 항상 안전한 작업은 아니다.

**권장 보강**: kill switch broken/missing/stale 상태에서 cancel을 허용하되, 이 cancel은 (a) audit alert를 강제로 남기고, (b) 자동 cancel 루틴은 막고 명시적 사람 승인 cancel만 허용 — 이런 분기를 만들면 더 안전. 이건 guard 단계가 아니라 manager 단계 정책일 수 있어 Slice 5에서 검토.

또한 `LiveKillSwitchState.cancel_only_allowed`가 True 고정이라 **미래 확장성이 약하다**. 향후 "kill switch가 특정 종목만 ON된 경우, 다른 종목 cancel은 허용/차단" 같은 세밀 정책이 필요할 수 있는데 현재 구조에서는 변경이 어렵다. 우선순위 낮음(Slice 5 진입 시 검토).

## Q3: stale 기간 1일 default가 적절한가

**안전 측이지만 의미적 default가 더 좋다.**

`live_kill_switch.py` 98행: `resolved_stale_after = _as_aware(stale_after or (current_time + timedelta(days=1)))`. 명시 없으면 24시간.

운영 관점에서 1일 default의 의미:
- 운영자가 18:00에 사고로 ON → 다음날 18:00까지 유효 → 다음 거래일 정규장(09:00~15:30) 전체 ON 상태 유지 → 신규 주문 자동 차단 → **안전 측**
- 1일 default가 짧다고 하기는 어려움 — 사고 의심 상태에서 그날 하루는 막는 것이 보수적

**의문 한 가지**: 24시간 정확히가 의도인지 "다음 거래일까지"가 의도인지 모호.
- 금요일 18:00 ON → 토요일 18:00까지 유효 → 토/일은 휴장이라 무관 → 월요일 09:00에는 stale 됨(stale=submit 차단이라 안전)
- 월요일 18:00 ON → 화요일 18:00까지 유효 → 화요일 정규장 ON 유지 → 의도와 일치

대부분의 시나리오에서 1일 default는 안전 방향으로 작동한다. **결론: 1일 default 유지 권장**, 다만 docstring에 "stale_after 명시 안 하면 1일(=24시간 정확)이고, 다음 거래일 정규장에 자동 OFF가 필요하면 명시적으로 짧게 설정해야 함"을 적어두면 운영자 혼동을 줄인다.

장중 운용 전용 더 짧은 default(예: 8시간)는 **권장하지 않는다**. 짧은 default는 운영자가 ON 후 잊고 OFF 안 했을 때 자동 stale 되어 신규 주문이 풀리는 위험을 만든다. 그건 사고 의심 상태에서 가장 위험한 시나리오. **운영자 명시적 OFF가 안전**하고 그 사이 stale은 길게 두는 게 맞다.

대안 후보: stale_after를 "다음 거래일 16:00(post-close)까지" 같은 거래 캘린더 기반 의미적 default로 두면 한국 시장 운용에 더 정합적. 다만 이건 Slice 4의 영역이 아니라 향후 calendar service와 결합할 영역이라 우선순위 낮음.

## Q4: LiveOrder 빈 문자열 거부 대상에서 broker_order_no, broker_branch_no 제외 판단이 맞는가

**맞다.** state machine에서 broker 응답 전 단계(intent_created, blocked, submit_pending)에서는 broker_order_no가 빈 문자열일 수밖에 없다. NULL 허용보다 "" 사용이 일관성 있다.

`broker_branch_no`도 같은 정책이 적절. KIS 모의계좌의 경우 보통 같은 값(예: "01")이지만 응답 전에는 비어있다.

**Slice 5에서 추가로 잠가야 하는 invariant 두 가지**:

1. **state-aware 검증**: status가 `submitted` 이후로 전이할 때 broker_order_no가 채워졌는지 강제. state transition 함수에서 잠근다.
2. **broker_order_no UNIQUE 검증**: 같은 broker_order_no를 두 번 받으면 안 됨. SQLite 컬럼에 UNIQUE 제약을 추가하거나 application-level 검증. 단 빈 문자열은 UNIQUE 제약을 받으므로 (`NOT NULL UNIQUE`로 두면 빈 문자열도 unique 카운트에 들어감) intent_created 단계의 다중 주문이 모두 거부된다 — 이 경우 NULL 허용으로 되돌리거나 partial unique index가 필요.

**현재 결정 그대로 진행 가능.** Slice 5에서 위 두 가지를 함께 잠그면 완전.

## Q5: 다음 작업 = apply wrapper vs phase approval Slice 4-2 우선순위

**apply wrapper 우선이 맞다. work_ver_5-1에서 이미 수행한 결정이 정확.**

세 가지 이유:
1. **Slice 2b 진입 위험을 줄이는 안전 발판이 가장 먼저 필요**. apply wrapper 없이 Slice 2b를 운영 DB에 적용하면 lock/backup/rollback 절차가 매번 손으로 실행되어야 하고 사고 위험이 큼.
2. **phase approval은 Phase 1 read-only 진입 시점부터 실제로 사용됨**. 현재는 Phase 0에 머물러 있어 즉시 가치가 낮음. Phase 1 진입 작업(별도 slice)에 묶어서 함께 만드는 게 자연스럽다.
3. **apply wrapper는 이미 Slice 2a를 운영 DB에 안전하게 반영할 수 있게 해주므로 즉시 운영 가치가 있음**. plan mode default + path 검증 + 서비스 정지 검증 + backup/restore 자동화 — 모두 즉시 사용 가능.

## apply_storage_migration.sh wrapper 자체 평가 (work_ver_5-1)

코드 직접 본 결과 **매우 잘 짜여 있다.** 강점부터:

- **Plan mode default**(905~907행). 운영자가 의도 없이 적용을 못 함. 가장 큰 안전 장치.
- **`--apply` 명시 플래그**가 있어야 실제 적용. 명시성.
- **`runtime-data/dev.db`에 대해 `--skip-service-check` 거부**(868~869행). 운영 DB 보호 정책이 코드로 강제됨.
- **저장소 외부 경로 거부**(860~866행). path traversal 방지.
- **live runtime/dashboard running 시 차단**(909~912행). race condition 방지.
- **backup → schema 적용 → smoke check → 실패 시 backup restore**(918~937행). 자동 rollback.
- **테스트 4개**가 plan mode 비-mutation, apply 시 sentinel 보존 + live table 생성, 외부 경로 거부, runtime DB skip 거부 모두 잠금.

남은 약점 세 가지:

첫째, **rollback이 단순 `shutil.copy2`(932행)**. SQLite는 `.sqlite3` 본 파일 외에 `-wal`, `-shm` 파일을 동시에 쓸 수 있다. 만약 backup_path가 본 파일만 복사했다면 WAL 일관성 문제 가능. **확인 필요**: `SQLiteRuntimeStore.backup_database()`(920행)가 SQLite native backup API(`connection.backup()`)를 쓰면 안전하고, 단순 `shutil.copy2`라면 위험. SQLite native backup은 WAL을 자동으로 처리해서 일관성을 보장한다. work_ver_5-1 본문 70행에서 "WAL/SHM 고급 복구 정책은 별도 검토가 필요"로 솔직하게 인정됨. **Slice 2b 진입 전 backup_database() 구현 확인이 필요하다.**

둘째, **watchdog 정지 검증 부재**. work_ver_5-1 본문 68행에서 인정됨. dashboard와 live runtime은 정지 검증하지만 watchdog은 안 봄. watchdog이 살아있으면 schema 적용 중 dashboard 또는 live runtime을 다시 켤 수 있어 race condition 위험. `services_are_stopped`(823~834행)에 watchdog 검증 한 줄 추가하면 안전.

셋째, **smoke check가 schema 존재 + 인덱스 존재만 본다**(837~849행). 실제 insert/read 동작이 정상인지는 검증 안 됨. schema 적용 후 sample insert + select + delete 한 번이 더 강한 smoke check. 우선순위 중간.

## 추가 발견 (코드 직접 본 결과)

work_ver_5/5-1 본문에 명시되지 않은 미세 항목 다섯 가지.

첫째, **`READONLY_PHASES` 하드코드 위험**. `live_order_guard.py` 12행: `{"phase0", "phase0_paper", "phase1", "phase1_readonly", "read_only"}`. phase 이름 오타(예: `phase1_read_only`, `Phase1`, `phase 1`) 시 READONLY_PHASES에 없으므로 submit 가능 — silent bypass. **권장**: phase 정규화 함수(`_normalize_phase(value)`) 도입 또는 enum 잠금. Slice 5 진입 전 보강.

둘째, **`assert_can_submit`의 `phase_approved`가 boolean으로 단순**(50행). True/False만 받음. 누가 어떻게 승인했는지 audit 정보 없음. work_ver_5의 위험 항목에 "phase approval 저장소와 approval hash/audit chain은 아직 없습니다"로 인정됨. Slice 4-2에서 채워질 영역.

셋째, **`assert_can_cancel`이 market_status_decision을 받지 않음**(87~103행). 의도적 — cancel은 시장 상태와 무관. 다만 **VI 발동 중 또는 거래정지 중 cancel이 broker에서 어떻게 처리되는지 확인 필요**. KIS가 cancel을 reject할 가능성이 있다면 reject 처리 정책이 manager에 들어가야 함. 우선순위 낮음.

넷째, **`LiveOrderGuard.assert_*` 메서드가 raise + return 둘 다 함**(_raise_if_blocked 헬퍼). raise하면 caller가 catch 못 한 코드는 crash. return된 decision을 caller가 사용하려면 try/except로 받아야 함. fail-loud 디자인은 운영 안전 측면에서 좋지만, 일부 caller는 "blocked인지만 확인하고 alternative 실행"하고 싶을 수 있음 — 그런 경우 try/except 부담. 단 fail-loud가 더 안전해서 현재 디자인 OK.

다섯째, **`LiveKillSwitch.write_state()`의 atomic write가 잘 짜여 있음**(120~122행). `os.replace(tmp_path, self.path)`로 atomic. 좋은 패턴. 다만 tmp_path 명명(`f".{self.path.name}.tmp"`)이 hidden file로 시작해서 `ls`로 잘 안 보임 — 의도된 청결한 처리이지만 디버깅 시 헷갈릴 수 있음. 우선순위 매우 낮음.

## 요약 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 ALLOW_LIVE_ORDERS=false에서 cancel 허용 | 합리적 | ALLOW_LIVE_ORDERS의 의미적 정의 운영자 합의 |
| Q2 kill switch broken/missing/stale에서 cancel 허용 | 70% 보수적 | 자동 cancel vs 명시 승인 cancel 분기 (Slice 5) |
| Q3 stale 기간 1일 default | 적절 | docstring 명시 + 향후 거래 캘린더 기반 default 검토 |
| Q4 broker_order_no/branch_no 빈 문자열 허용 | 맞다 | Slice 5에서 state-aware 검증 추가 |
| Q5 다음 작업 = apply wrapper | 정확한 우선순위 | work_ver_5-1에서 이미 수행 |
| apply wrapper 자체 (work_ver_5-1) | 매우 안전 | backup_database() WAL 처리 확인, watchdog 정지 검증, insert/read smoke check |

## 다음 단계 권장

1. **`SQLiteRuntimeStore.backup_database()` 구현 확인**: SQLite native backup API(`connection.backup()`)를 쓰는지, 단순 `shutil.copy2`인지 확인. 후자면 WAL 일관성 위험이 있어 native backup으로 변경 필요. Slice 2b 진입 전 필수.
2. **apply wrapper에 watchdog 정지 검증 추가**: `services_are_stopped`에 watchdog 한 줄 추가.
3. **Slice 2b live fill/position/audit schema 진입**: apply wrapper의 `REQUIRED_TABLES`/`REQUIRED_INDEXES`에 Slice 2b 항목도 함께 추가.
4. **`READONLY_PHASES` 정규화 함수 도입**: Slice 5 진입 전 phase 이름 silent bypass 위험 차단.
5. **운영자 결정 잔여 항목**:
   - 일일 손실 한도/슬리피지 budget 수치 (P0, Phase 2 진입 차단 항목)
   - ALLOW_LIVE_ORDERS의 의미(시나리오 A vs B 합의)
   - kill switch ON/OFF CLI 도구 결정 (work_ver_5 7항 위험에서 인정됨)
6. **Slice 5 live order manager 진입 전 보강 항목**:
   - state-aware 검증 (broker_order_no UNIQUE + state 전이)
   - kill switch broken/missing/stale에서 자동 cancel 차단 정책
   - VI/거래정지 중 cancel이 broker에서 reject되는 경우 처리

## 신뢰 수준

work_ver_5는 review_ver_4의 보강 권장 다섯 가지를 모두 흡수했고, work_ver_5-1은 cowork 리뷰 없이 자율적으로 다음 권장 단계(apply wrapper)를 정확하게 구현했다. **Codex의 자율 작업 품질이 cowork 리뷰가 있던 라운드와 같은 수준으로 유지된다.** 152개 테스트 통과 + plan mode default + path 검증 + service stop 검증 + backup/restore 자동화 — 운영 안전 invariant가 코드와 테스트로 단단하게 잠겨가고 있다.

다음 라운드부터 cowork이 동일 패턴으로 본다: (a) 변경 파일 직접 읽기, (b) 운영 안전 invariant 잠금 확인, (c) 회귀 테스트 통과 확인, (d) 코드 강제 vs 의도 표명의 분리 검증.
