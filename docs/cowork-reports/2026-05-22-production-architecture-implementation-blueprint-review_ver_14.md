# Claude cowork 리뷰 review_ver_14: work_ver_14 시리즈 통합본 사실 검증 + Phase 1 진입 잔여 평가

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_14`
- 기준 작업본: `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-6.md` (work_ver_14 + 14-1 ~ 14-5 통합본)
- 직전 리뷰: `review_ver_13`
- 리뷰 방식: 통합본 주장(파일 경로/JSON 수치/sanitization/검증 결과)을 정본 저장소에서 1건 1건 확인하는 사실 검증 중심. work_ver_14, 14-1, 14-2, 14-5 본문 대조까지 포함.

## 요약

work_ver_14 시리즈는 review_ver_13 잔여 P0 3가지 중 **(a) system_clock 자동 주입은 코드 경로 + KIS paper 실증까지 완료**, **(b) live account header shape는 paper 경로 + 코드 closure로 부분 진전**, **(c) NAS 실제 drill은 손도 대지 않음** — 즉 P0 3개 중 1.5개 closure다. 동시에 review_ver_13에서 추가 권고였던 P1(WS 노출, HTTP Date timezone 강건성, operator-decision 묶기) 중 **timezone과 WS readiness 노출은 추가로 closure**됐다. **그대로 사용 가능. 다만 NAS drill 미진행과 live account live 미실행 두 항목은 별도 운영자 결정 슬라이스로 명확히 분리해야 한다.**

핵심 발견 세 가지: (1) 정본 readiness JSON과 통합본 표의 10개 check가 **완전히 일치**(skew 0.166878 ↔ 문서 "약 0.167"까지). 통합본은 사실 보고에 충실하다. (2) probe 6개와 script 5개가 **모두 sanitization을 코드 레벨에서 강제**한다 — 특히 `kis_account_probe.py`는 row count + `*_present` 불리언만 노출하고 raw 값은 전혀 안 남긴다. (3) **synthetic ws_recovery=true가 readiness에 `passed=True`로 들어가는 구조**는 의도된 것이지만, Phase 2 submit guard 단계에서 이 true가 silent하게 재사용되지 않도록 **호출자 분리 가드**가 readiness 외부 어딘가에 있어야 한다. 현재 통합본에 명시 안 됨.

## 사실 검증 — 항목별

### A. 정본 readiness JSON vs 통합본 3장 표

`runtime-data/reports/live-readiness/latest-readiness.json` 직접 확인:

| check | 문서 주장 | 실제 JSON | 일치 |
|---|---|---|---|
| token_refresh | true, paper auth-only, token 원문 없음 | passed=true, mode=paper, token_type=Bearer, expires_at만 저장 | ✓ |
| ws_recovery | true, synthetic | passed=true, evidence_type=synthetic_fault_injection, network_called=false | ✓ |
| account_snapshot | true, paper, 계좌번호/raw 없음 | passed=true, mode=paper, position_row_count=1, *_present 불리언만 | ✓ |
| market_status | false, snapshot 증적 없음 | passed=false, status=not_verified, summary="fixture was not provided" | ✓ |
| system_clock | true, HTTP Date, skew 약 0.167초 | passed=true, source=kis_rest_http_date, **skew_seconds=0.166878** | ✓ |
| kill_switch | false, missing | passed=false, state_status=missing | ✓ |
| database | true | passed=true, schema_version=48, journal_mode=wal | ✓ |
| disk_space | true | passed=true, free_bytes ≈ 893GB | ✓ |
| dashboard | true | passed=true, running=true | ✓ |
| storage_migration_state | true | passed=true, status=planned, apply=false | ✓ |

blocking_reasons: 문서 `market_status_not_verified_by_fault_dry_run`, `kill_switch_fault_dry_run_failed` ↔ JSON 동일. ✓

전체 status: `blocked`. ✓

**결론: 10/10 일치. 통합본의 수치 보고는 정확.**

### B. 통합본 5장 "보안/안전 경계" vs 실제 probe 코드

`app/services/`의 6개 probe 파일 모두 존재 확인:

- `system_clock_probe.py`, `kis_token_probe.py`, `kis_account_probe.py`, `kis_ws_recovery_probe.py`, `market_status_probe.py`, `live_readiness_fixture.py`

세부 sanitization 코드 검증:

1. **`kis_account_probe.py`**: details에 들어가는 필드는 `mode`, `checked_at`, `position_row_count`, `summary_row_count`, `cash_balance_present`, `stock_evaluation_present`, `total_asset_present` — 전부 메타데이터. **실제 cash/stock 금액, 계좌번호, raw response는 코드 상 어디에도 노출 경로 없음.** 예외 처리도 `error_type: type(exc).__name__`만 (메시지 본문 안 잡음). ✓

2. **`kis_token_probe.py`**: token 객체에서 `token_type`(예: "Bearer"), `expires_at`, `seconds_to_expiry`만 추출. **access_token 문자열 자체를 dict에 절대 안 넣음.** 예외도 type만. ✓

3. **`kis_ws_recovery_probe.py`**: `network_called: False` **하드코딩**. `evidence_type: "synthetic_fault_injection"` 명시. `_safe_snapshot`이 `last_error`를 무조건 `"synthetic"`으로 덮어씀(원본 메시지 leakage 차단). ✓

4. **`market_status_probe.py`**: 외부 호출 0건. repo 내부 payload 파싱만. snapshot_id, source, trading_day, market_session 같은 메타데이터만 details에 넣음. ✓

**결론: 통합본 5장의 5가지 sanitization 주장은 모두 코드로 강제됨.**

### C. 통합본 6장 "검증" 명령

- 119 테스트 인용: 16개 테스트 파일 전부 정본 `tests/` 폴더에 존재 확인. (`test_market_status_probe`, `test_market_status`, `test_kis_ws_recovery_probe`, `test_kis_ws_reconnect_metrics`, `test_live_readiness_fixture_snapshot`, `test_live_readiness_dry_run_script`, `test_kis_account_probe`, `test_kis_token_probe`, `test_kis_clock_reference_probe`, `test_live_phase_readiness`, `test_live_kill_switch`, `test_live_readonly_guard`, `test_system_clock`, `test_live_client_isolation`, `test_kis_http_clients`, `test_live_order_manager`) ✓
- 119 카운트 자체는 본 리뷰에서 재실행 안 함. work_ver_14-5 본문에 동일 명령으로 119 통과 기록 있음.
- 7개 shell 스크립트(`probe_market_status_snapshot.sh`, `probe_kis_account_snapshot.sh`, `probe_kis_ws_recovery.sh`, `probe_kis_token_refresh.sh`, `probe_kis_clock_reference.sh`, `build_live_readiness_fixture_snapshot.sh`, `script_dispatch.sh`, `run_live_readiness_dry_run.sh`) 전부 정본 `scripts/`에 존재. ✓

### D. 통합본 9장 "주의" 불변 금지선

- `app/risk/`: 파일 목록 확인 — `__init__.py`, `gates.py` 두 개만. work_ver_14 시리즈 어느 본문에도 이 경로 수정 언급 없음. ✓
- `VERSION`: `0.2.0`. 통합본 6장 `git diff -- app/risk config VERSION` "출력 없음" 주장과 부합. ✓
- `ALLOW_LIVE_ORDERS`, gate 기준값: work_ver_14~14-5 본문 어디에도 수정 언급 없음. ✓
- 자동 commit/push: 통합본 명시적으로 안 했다고 적음, 본문에 git push 명령 흔적 없음. ✓

### E. 직전 review_ver_13 P0/P1 잔여 매핑

| review_ver_13 항목 | 분류 | work_ver_14 시리즈 처리 | 평가 |
|---|---|---|---|
| 자동 주입 (system_clock decision/check) | P0 | work_ver_14: `--system-clock-check-path` 옵션 + work_ver_14-1: `probe_kis_clock_reference.sh` + paper 1회 실증 | ✓ **closure** (코드 경로 + paper 증적) |
| NAS 실제 package/복구 drill | P0 | 시리즈 어느 작업본에도 진행 없음 | ✗ **미처리** |
| live account header shape 확인 | P0 | work_ver_14-4: paper account snapshot probe + paper 1회 실증. live 실행은 운영자 승인 대기 | △ **부분 closure** (paper만) |
| HTTP Date timezone 강건성 테스트 | P1 | work_ver_14: timezone 누락/알 수 없는 timezone을 `ValueError`로 차단 + 테스트 추가 | ✓ closure |
| WS reconnect snapshot readiness 노출 | P1 | work_ver_14-4: synthetic ws_recovery check가 readiness JSON에 `passed=true`로 노출, `to_dict()` 결과 details에 포함 | ✓ closure (readiness 측). dashboard 노출은 별도 |
| operator-decision 묶기 | 행정 | 통합본 8장 "🔴 운영자 판단 필요" 3개로 묶음 | ✓ closure |

**P0 점수: 3개 중 1 완전 closure + 1 부분 closure + 1 미처리.** P1은 둘 다 closure.

---

## Q1: Phase 1 readiness에서 `market_status`를 수동 snapshot으로 시작해도 되는가

**임시 증거로 허용 가능. 단 운영 절차로 두 가지 가드 필요.**

세 가지 이유:

1. **자동 원천 결정에 시간이 더 필요하고, 그 동안 readiness가 false 유지로 차단되는 것은 안전 측 동작**. work_ver_14-5가 "snapshot이 없으면 not_verified"로 fail-closed를 유지한 것은 정합. KIS REST와 한국거래소 자동 원천 비교는 자체로 별도 slice 분량(API 신뢰도, rate limit, 휴장일 처리 등).
2. **`market_status_probe.py` 코드가 stale_after, source_generated_at, market_session을 details에 모두 남기므로 운영자가 사후 검증 가능**. 즉 수동 snapshot이라도 "누가 언제 어떤 source로 만들었나"가 readiness JSON에 그대로 박힘.
3. **수동 snapshot은 매 거래일 갱신이 필수**. 안 갱신하면 stale로 자동 차단되도록 `stale_after` 필드를 강제하는 구조라 운영자 부주의가 silent 통과로 이어지지 않음.

**미세 약점 두 가지**:

a) **수동 snapshot 생성 운영 절차가 통합본에 없다**. "누가, 매 거래일 몇 시까지, 어떤 양식으로" 만드는지 — 이 절차가 logbook/runbook에 명시되지 않으면 한 거래일이라도 빠뜨리면 즉시 차단. 운영자 1인 운용 환경에서 단일 실패점.

b) **수동 snapshot의 `source` 필드 값 규약이 없다**. `source="manual"` 같은 명시 enum이 강제되지 않으면 "Naver", "거래소수동입력", "kakao_news" 같은 자유 문자열이 들어갈 수 있고, 후속 자동 원천 연결 시 source 마이그레이션 부담.

**결론: 임시 증거 허용 OK. 다만 runbook의 수동 snapshot 생성 절차와 source 값 규약 둘 다 work_ver_15-x에서 닫아야 함.**

## Q2: 자동 market status 원천을 KIS REST, 한국거래소, 수동 snapshot 중 어떤 순서로 붙이는 게 안전한가

**한국거래소 > KIS REST > 수동 백업** 순서가 안전.

세 가지 이유:

1. **한국거래소가 1차 원천**. KIS는 거래소 신호의 중계자이므로 KIS REST를 1차로 쓰면 KIS 자체 장애가 곧 market_status 장애가 됨. 거래소 데이터가 우선 닿으면 KIS 인프라 장애에도 readiness가 살아남음.
2. **KIS REST는 우리가 이미 다른 probe에서 의존성을 사용**(token_refresh, account_snapshot, clock reference). market_status까지 KIS에 묶으면 KIS 단일 장애가 readiness 전체를 막는 비대칭 의존이 생김.
3. **수동 snapshot은 자동 원천 2개의 백업으로 두는 게 자연스러움**. "거래소 + KIS 둘 다 응답 불능"이라는 드문 상황에만 발동.

**미세 약점 한 가지**: 한국거래소 공개 API가 무료 SLA로 어디까지 안정한지 별도 조사 필요. 비공식 endpoint를 쓰면 약관/안정성 둘 다 위험. KRX 공식 시장 데이터 시스템(KRX MDS 등)을 먼저 확인하고, 없으면 KIS 1차 + 수동 백업으로 후퇴하는 분기 결정이 work_ver_15-x에서 필요.

**결론: 우선순위 한국거래소 → KIS → 수동. 단 거래소 공식 API 가용성 확인을 P0로 선행.**

## Q3: kill switch missing fail-closed를 Phase 1 직전까지 유지하고, 직전 승인 때만 OFF 파일을 생성하는 판단

**적절하다.** review_ver_13에서도 같은 결론, 본 라운드에서도 유지.

세 가지 이유:

1. **kill switch는 "사고 발생 시 즉시 차단"의 최후 가드**. 미리 OFF로 두면 가드를 자발적으로 풀어두는 셈. fail-closed가 의도된 기본값.
2. **OFF 파일 생성 명령(`scripts/set_live_kill_switch.sh --disable --apply --confirm-disable`)이 `--confirm-disable` 플래그로 명시적 confirmation을 요구**하는 구조 — 자동 스크립트나 무심한 명령으로 풀리지 않게 한 설계. 통합본 권장안과 정합.
3. **현재 readiness가 다른 두 항목(market_status, kill_switch)로 blocked인 점이 오히려 안전망**. 한 항목만 막혀 있으면 운영자가 "거의 다 됐다"는 압박에 OFF 파일을 미리 만들 유혹이 생기지만, 두 항목 동시에 막혀 있으면 그 압박이 약함.

**미세 약점**: "Phase 1 직전 승인"의 정의가 통합본에 없다. 누가(계좌 소유자 = Keios 본인) + 어떤 형식으로(operator-decision 파일?) + 언제(직전 N시간 이내?) 승인하는지가 운영자-decision 슬라이스로 묶여야 함.

**결론: 적절. operator-decision 양식만 work_ver_15-x에서 보강.**

## Q4: synthetic `ws_recovery`를 Phase 1 readiness check로는 허용하되 Phase 2 submit guard 기준으로 쓰지 않는 경계

**의도는 정확. 다만 코드 레벨 경계 가드가 통합본에 명시되지 않았다.**

`kis_ws_recovery_probe.py` 검토 결과:

- `evidence_type: "synthetic_fault_injection"`이 details에 명시되어 있음 ← 사람이 보면 구분 가능
- `network_called: False`도 details에 있음 ← 사람이 보면 구분 가능
- **그러나 readiness `override_checks["ws_recovery"] = true`로 들어가는 boolean 값은 동일**

문제는 Phase 2 submit guard 코드가 `override_checks["ws_recovery"]`만 읽으면 synthetic과 real을 구분 못 한다는 것. 통합본 7장 Q4가 정확히 이걸 짚고 있는데 답이 아직 없다.

세 가지 보강 필요:

1. **submit guard에서 `ws_recovery` 통과 시 `evidence_type` 검사 필수화**. `evidence_type == "real_kis_ws_observed"` 같은 명시 enum이 아니면 submit guard가 거절하도록 코드 가드 추가.
2. **synthetic 통과를 Phase 1 readiness에서만 허용하고, Phase 2 readiness fixture는 synthetic을 절대 받지 않도록 fixture loader에서도 차단**. fail-closed 두 겹.
3. **Phase 1 진입 후 첫 5~10거래일 동안 실제 KIS WS 관측 데이터로 baseline 수집** — 이건 review_ver_13에서 이미 합의된 항목이고 통합본도 유지. 이 baseline 없이는 Phase 2로 못 넘어가는 게 맞다.

**결론: 경계 의도는 OK. 코드 레벨 가드(evidence_type 강제, fixture loader 차단) 2가지가 work_ver_15 P0.**

## Q5: live account read-only probe Phase 1 승인 뒤 1회 실행으로 충분한가

**Phase 1 승인 후 첫 주문 전 1회 실행 + shape 자동 검증이 필요. 그냥 1회 실행만으로는 부족.**

세 가지 이유:

1. **paper와 live 계좌의 응답 shape 차이 가능성이 검증되지 않았다**. work_ver_14-4의 paper account snapshot은 `position_row_count=1, summary_row_count=1` 등으로 통과했지만, KIS live 계좌는 (a) 다른 endpoint를 쓸 수 있고 (b) 같은 endpoint라도 응답 필드 이름/타입이 다를 수 있음. `getattr(snapshot, "position_row_count", 0)`이 0으로 silent fallback할 위험.
2. **shape 검증을 자동화해야 운영자 1인 부담이 안정**. live snapshot이 paper와 같은 dataclass attribute를 전부 채우는지 확인하는 단위 테스트가 readiness 자체에 들어가야 함. "shape_check" 같은 sub-check를 account_snapshot details에 박는 게 자연스러움.
3. **1회 실행 뒤 다음 거래일에도 동일 shape가 유지되는지 모름**. KIS API 마이너 업데이트가 응답 shape를 흔들 수 있음. 매 거래일 readiness가 shape 변화를 감지하는 게 안전.

**미세 약점**: 1회 실행 시점에 운영자가 어떤 정보를 보고 통과 판단할지 가이드가 통합본에 없다. "summary_row_count >= 1이면 OK"는 paper 기준 통과 조건이고, live에서 이게 0이면 즉시 차단되는 것이 정상 동작이지만 운영자가 "왜 0이지?"를 추적할 양식이 필요.

**결론: 1회 실행만으로는 부족. (a) shape 자동 검증 sub-check 추가, (b) 매 거래일 shape drift 감지, (c) 운영자 확인 양식 — 셋이 work_ver_15 P0.**

---

## 추가 발견 / 위험한 가정

1. **NAS 실제 package/복구 drill 미진행**: review_ver_13에서 P0로 잡았던 3가지 중 이 항목은 work_ver_14 시리즈에서 손도 안 댔다. work_ver_14-6 8장 "🔴 운영자 판단 필요"에도 NAS drill은 빠져 있다(직전 review_ver_13에서는 권장됐는데 통합본이 운영자 결정 항목에서 누락). **이는 통합본의 운영자 결정 묶음 누락이며, work_ver_15-x에서 반드시 다시 노출시켜야 한다.** repo 56GB, runtime-data 45GB 환경에서 부분 백업/전체 백업 정책 결정도 미진.

2. **synthetic ws_recovery=true의 silent leakage 위험**: Q4에서 짚은 그대로. readiness JSON의 `override_checks["ws_recovery"] = true`만 보는 Phase 2 호출자가 있을 가능성. 본 리뷰에서 `app/services/live_phase_readiness.py`와 submit guard 코드는 별도 검증 안 했으므로 work_ver_15-x에서 (a) 호출 경로 추적, (b) evidence_type 강제 둘 다 필요.

3. **수동 market_status snapshot의 운영 단일 실패점**: Q1에서 짚은 그대로. 운영자 1인 환경에서 매 거래일 수동 입력은 위험. 자동 원천이 늦어지면 readiness 차단이 잦아짐. 차단이 잦아지면 운영자가 익숙해져서 잘못된 snapshot도 통과시킬 위험(alert fatigue).

4. **`probe_kis_clock_reference.sh`가 KIS paper에 의존**: HTTP Date를 paper endpoint에서 가져온다는 점은 work_ver_14-1이 명시. paper와 live의 시각 동기화가 동일한지 (KIS 인프라가 단일 시각 동기화를 보장하는지) 별도 확인 권장. 만약 paper 서버 시각만 사용해서 live 주문 시각 검증이 어긋날 가능성이 0.001%라도 있으면 위험. KIS 공식 문서에 명시 없으면 work_ver_15-x에서 live HTTP Date도 비교 측정.

5. **`live_readiness_fixture.py`의 stale 위험**: work_ver_14-2가 명시한 대로, premarket report가 stale인 상태에서 fixture를 만들면 stale 증거가 통과해버림. wrapper 실행 전 premarket report 갱신을 강제하는 가드(예: 갱신 시각 차이가 N분 이상이면 fixture 생성 거부)가 없으면 운영자 부주의에 취약.

## 다른 thread와 충돌 가능성

이번 라운드 변경 영역:
- `app/services/`: 6개 probe 파일 신규 (system_clock_probe, kis_token_probe, kis_account_probe, kis_ws_recovery_probe, market_status_probe, live_readiness_fixture)
- `app/brokers/kis_readonly.py`: `last_response_headers` 노출 추가 (work_ver_14-1)
- `app/services/system_clock.py`: HTTP Date timezone strict 처리 (work_ver_14)
- `scripts/`: probe_*.sh 5개, build_live_readiness_fixture_snapshot.{sh,py}, run_live_readiness_dry_run.sh (--system-clock-check-path 옵션)
- `scripts/script_dispatch.sh`: 신규 wrapper 연결
- `tests/`: 신규 test_*_probe.py 5개, 기존 회귀 추가

post-close ML maintenance thread, KIS WS verification thread와 충돌 위험:
- **`app/brokers/kis_readonly.py`의 `last_response_headers` 노출은 read-only wrapper 표면적 변경**. KIS 호출자 측 다른 thread가 동시에 wrapper를 확장 중이라면 attribute 충돌 가능. work_ver_14-1이 명시적으로 "주문/취소 메서드는 계속 노출 안 함" 보장은 했으나 다른 thread의 wrapper 확장과 git merge 필요할 수 있음.
- **`run_live_readiness_dry_run.sh --system-clock-check-path` 옵션 추가**. 기존 readiness dry-run 호출자가 옵션 누락 케이스를 backward-compat로 처리하는지(work_ver_14가 그렇게 짰다고 주장) 정본 코드 직접 추적 권장.

이번 라운드는 다른 thread 충돌 위험 낮음. 다만 readonly wrapper 변경은 broker 측 다른 작업과 머지 시 주의.

## 종합

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| 통합본 수치 보고 정확성 | 10/10 일치, 매우 정확 | 없음 |
| probe 6개 sanitization 코드 강제 | 모든 probe에서 코드 레벨로 강제 확인 | 없음 |
| review_ver_13 P0 closure | 1 완전 + 1 부분 + 1 미처리 (3개 중 1.5) | NAS drill 재노출, live account shape 검증 자동화 |
| 불변 금지선 (app/risk/, VERSION 등) | 변경 없음 주장 정합 | 없음 |
| Q1 수동 market_status 임시 허용 | 적절 | runbook 생성 절차 + source enum 규약 |
| Q2 자동 원천 우선순위 | 거래소 > KIS > 수동 | KRX 공식 API 가용성 선행 조사 |
| Q3 kill switch fail-closed 유지 | 적절 | operator-decision 양식 |
| Q4 synthetic ws_recovery 경계 | 의도 OK, 코드 가드 미명시 | evidence_type 강제, fixture loader 차단 (P0) |
| Q5 live account 1회 실행 | 부족 | shape 자동 검증 + 매일 drift 감지 + 운영자 양식 (P0) |

## 다음 단계 권장

**Codex 작업 (P0)**:
1. **NAS 실제 package/복구 drill 재진행 또는 별도 slice로 분리**. review_ver_13 P0의 잔여 항목인데 work_ver_14에서 누락. work_ver_15-x에서 (a) 부분 백업 정책, (b) 복구 drill 시점, (c) 용량/경로 제한을 운영자 결정으로 묶어 다시 노출.
2. **submit guard의 `ws_recovery` evidence_type 강제**. readiness JSON의 `ws_recovery=true`를 Phase 2 submit caller가 그대로 신뢰하지 않도록 (a) details.evidence_type 확인 코드 추가, (b) Phase 2 readiness fixture loader가 synthetic을 거부. 코드 한 곳에서 두 겹 가드.
3. **live account snapshot shape 자동 검증**. `kis_account_probe.py`에 (a) 필수 attribute 5개(`position_row_count`, `summary_row_count`, `cash_balance`, `stock_evaluation_amount`, `total_asset_amount`) 존재 여부 sub-check, (b) live 첫 실행 시 shape baseline 기록, (c) 다음 실행에서 drift 감지.

**Codex 작업 (P1, Phase 1 진입 직후)**:
4. **수동 market_status snapshot 생성 runbook 추가**. `docs/runbook/manual_market_status.md` 양식 + source 값 enum + 매 거래일 생성 절차 + stale 알람.
5. **WS reconnect snapshot의 dashboard 노출**. readiness에는 들어갔지만(synthetic), 운영자가 실제 KIS WS baseline 관측 시 dashboard에서 확인할 카드가 없음. Phase 1 첫 5~10거래일 baseline 수집 시작 직전 필수.
6. **HTTP Date paper/live 동기화 비교 측정**. KIS paper 서버 시각과 live 서버 시각 동기화 가정의 사실 확인. 1거래일 측정.

**운영자 결정**:
1. **NAS 실제 drill 시점과 백업 정책** (review_ver_13에서 이미 권장됐고 work_ver_14가 누락). 부분 백업 vs 전체 백업, 용량 제한, 복구 시점.
2. **Phase 1 직전 kill switch `OFF` 파일 생성 시점**. 운영자(계좌 소유자) 단독 결정.
3. **live account read-only probe 첫 실행 허용**. 운영자 승인 후 1회. shape 자동 검증 코드가 준비된 뒤 실행 권장.
4. **수동 market_status snapshot 운영 책임자와 양식**. 운영자 1인 단일 실패점 완화안 동반.
5. **KRX 공식 API vs 비공식 endpoint 사용 정책**. 자동 market_status 원천 결정 전제.

## 신뢰 수준

work_ver_14 시리즈는 review_ver_13 P0 3개 중 1.5개를 closure했다. 통합본 자체의 사실 보고는 정본 저장소 대조 결과 매우 정확하다(readiness JSON 10/10 일치, sanitization 코드 강제 확인). **신뢰도 높음**. 다만 (a) NAS drill 누락이 review_ver_13 시점부터 그대로 미해결인 점, (b) Phase 2 submit guard 측의 evidence_type 가드가 readiness 외부 코드 어딘가에 필요한데 통합본에 미명시인 점 — 이 두 가지가 work_ver_15-x로 넘어가는 잔여 부채.

다음 라운드(review_ver_15 예상)에서 cowork이 (a) submit guard evidence_type 가드 코드 검증, (b) live account shape 자동 검증 코드 검증, (c) NAS drill 운영자 결정 양식 검토 — 세 단계로 본다. 이 셋이 끝나면 Phase 1 read-only 진입 가능. **Phase 2 진입은 (b)의 baseline 수집 5~10거래일 + (c) live WS 실측 baseline까지 완료 후.**

리뷰자 메모: 본 리뷰에서 (a) `python -m unittest`로 119 테스트 재실행, (b) `git diff` 직접 실행, (c) `app/services/live_phase_readiness.py`와 submit guard 코드 직접 검토는 하지 않았다. 통합본의 수치 보고가 정확함을 다른 항목들로 cross-check해 신뢰도 확보. 다음 라운드 또는 사용자 요청 시 추가 검증 가능.
