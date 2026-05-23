# Claude cowork 리뷰 review_ver_15: work_ver_15 사실 검증 + review_ver_14 P0 closure 평가

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_15`
- 기준 작업본: `2026-05-22-production-architecture-implementation-blueprint-work_ver_15.md`
- 직전 리뷰: `review_ver_14`
- 리뷰 방식: 사실 검증 중심. 통합본 주장과 정본 저장소 코드/JSON을 1:1 대조하고, review_ver_14의 3개 P0와 1개 P1 closure 여부를 매핑.

## 요약

work_ver_15는 **review_ver_14의 P0 3개 중 2개를 코드 레벨로 완전 closure**(synthetic WS evidence guard 3겹, account snapshot shape drift 차단)했고, **P1의 manual market_status runbook + source enum 강제도 완전 closure**했다. 추가로 **요청하지 않은 evidence freshness 1시간 가드**까지 자발적으로 보강했다. 남은 P0는 **NAS 실제 drill 하나뿐**이며 이는 명시적으로 운영자 결정 슬라이스로 분리됐다. **그대로 사용 가능. Phase 1 진입 절차로 진행해도 안전.**

핵심 발견 세 가지: (1) synthetic ws_recovery 차단이 **3겹**으로 박혔다 — `live_phase_readiness._enforce_ws_recovery_evidence_for_phase`가 Phase 2/3에서 invalid_evidence로 재작성, `live_order_guard.assert_can_submit`이 submit 단계에서 `ws_recovery_real_evidence_required` 거부, `live_order_manager`가 둘을 wire-through. 단일 우회 경로 없음. (2) account snapshot의 `REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES` 튜플이 review_ver_14에서 권고한 5개 attribute와 정확히 일치하고, `hasattr` 누락 시 `shape_status=missing_required_attributes`로 차단. live 진입 전 shape drift 위험 차단됨. (3) latest-readiness.json의 system_clock skew가 0.166878초 → **0.002375초**로 수십 배 개선됐다. 이는 work_ver_15가 보고하지 않은 부수 효과로, 매 거래일 fresh probe 실행이 좋은 베이스라인을 만들고 있다는 증거.

## 사실 검증 — 항목별

### A. 통합본 3장 latest-readiness.json 변화 vs 실제 JSON

`runtime-data/reports/live-readiness/latest-readiness.json` 직접 확인 (trading_day=2026-05-22, work_ver_14 시점의 2026-05-21에서 갱신).

| 항목 | work_ver_15 주장 | 실제 JSON | 일치 |
|---|---|---|---|
| token_refresh | paper auth-only, 원문 미저장 | passed=true, evidence_age_seconds=84.311 | ✓ |
| ws_recovery | offline synthetic, network_called=false, evidence_type=synthetic_fault_injection | passed=true, evidence_type=synthetic_fault_injection, network_called=false, evidence_age_seconds=57.266 | ✓ |
| account_snapshot | paper read-only, 계좌번호/raw 미저장, shape_status=ok | passed=true, **shape_status=ok**, **required_attributes 5개 명시**, **missing_attributes=[]**, evidence_age_seconds=69.388 | ✓ |
| system_clock | KIS paper 1회, skew 약 0.002초 | passed=true, **skew_seconds=0.002375**, evidence_age_seconds=35.691 | ✓ |
| market_status, kill_switch | 여전히 false | passed=false 둘 다 | ✓ |
| blocking_reasons | market_status_not_verified, kill_switch_fault_dry_run_failed 두 개 | 동일 | ✓ |
| 전체 status | blocked | blocked | ✓ |

**결론: 6/6 일치.** 추가로 `account_snapshot.details`에 `required_attributes`, `missing_attributes`, `shape_status` 3개 신규 필드 + 4개 timestamp 증거에 `evidence_age_seconds` 신규 필드. 모두 work_ver_15가 약속한 그대로.

### B. 통합본 2장-A: Phase 2/3 WS recovery evidence guard

`app/services/live_phase_readiness.py`와 `app/services/live_order_guard.py` 코드 직접 검증.

**1겹 — readiness side (line 423~444):**
```
def _enforce_ws_recovery_evidence_for_phase(phase, check):
    if not passed or not _requires_real_ws_recovery_evidence(phase):
        return check  # Phase 1은 통과
    if evidence_type in REAL_WS_RECOVERY_EVIDENCE_TYPES:
        return check  # 진짜 증거면 통과
    # synthetic이면 status=invalid_evidence, passed=False로 재작성
    return {..., "status": "invalid_evidence", "passed": False,
            "summary": "ws_recovery synthetic evidence is not accepted for submit phases",
            "details": {..., "blocking_reasons": ["ws_recovery_real_evidence_required"]}}

def _requires_real_ws_recovery_evidence(phase):
    normalized = phase.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized.startswith("phase2") or normalized.startswith("phase3")
```
- `REAL_WS_RECOVERY_EVIDENCE_TYPES = {"real_kis_ws_observed", "real_kis_ws_recovery", "kis_ws_observed"}` — 3개 enum (line 56)
- phase 정규화가 hyphen/underscore/space에 모두 안전
- Phase 1 readonly는 `_requires_real_ws_recovery_evidence`가 False라 통과 — 의도된 동작 (latest JSON에서 synthetic이 통과한 이유)

**2겹 — submit guard side (live_order_guard.py line 23, 113~118):**
```
REAL_WS_RECOVERY_EVIDENCE_TYPES = {...}  # 동일 enum 재정의
LIVE_SUBMIT_PHASES = {"phase2", "phase2_conservative", "phase3", "phase3_daily_limits"}

if require_real_ws_recovery_evidence is None:
    require_real_ws_recovery_evidence = normalized_phase in LIVE_SUBMIT_PHASES
if require_real_ws_recovery_evidence:
    evidence_type = (ws_recovery_evidence_type or "").strip()
    if evidence_type not in REAL_WS_RECOVERY_EVIDENCE_TYPES:
        reasons.append("ws_recovery_real_evidence_required")
```
- Phase 2/3 자동 적용. caller가 명시 안 하면 phase 기반 기본값.
- `ws_recovery_evidence_type=None`이면 빈 문자열로 정규화 후 enum 매칭 실패 → 차단.

**3겹 — order manager wire-through (line 262~278):**
- `ws_recovery_evidence_type`, `require_real_ws_recovery_evidence` 두 파라미터를 받아 `assert_can_submit`으로 전달. 매니저 자체 우회 경로 없음.

**결론: 3겹 방어 완벽. 단일 우회 불가.** 단, 작은 우려 한 가지:
- enum 값이 두 파일에 중복 정의됨 (`live_phase_readiness.py`, `live_order_guard.py` 둘 다 `REAL_WS_RECOVERY_EVIDENCE_TYPES = {...}`). 향후 enum 확장 시 한 곳 갱신하고 다른 곳 빼먹으면 silent 분기 발생. **단일 소스로 묶는 게 좋음** (P1).

### C. 통합본 2장-B: Account snapshot shape drift

`app/services/kis_account_probe.py` 직접 검증.

```
REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES = (
    "position_row_count",
    "summary_row_count",
    "cash_balance",
    "stock_evaluation_amount",
    "total_asset_amount",
)  # line 9~15
```

- 정확히 review_ver_14 Q5 권고와 일치하는 5개 attribute.
- `missing_attributes = [a for a in REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES if not hasattr(snapshot, a)]` (line 42~46) — hasattr 기반.
- `passed = summary_count >= 1 and position_count >= 0 and not missing_attributes` (line 49) — 누락이 있으면 무조건 차단.
- summary 메시지가 분기됨: missing_attributes 있으면 "shape invalid", summary_count < 1이면 "missing summary row", 둘 다 OK면 "refreshed".
- details에는 raw 값이 여전히 없음. cash_balance, stock_evaluation_amount, total_asset_amount는 `*_present` boolean으로만 노출.
- `shape_status`, `required_attributes`, `missing_attributes` 3개 신규 필드 추가 — JSON에서 확인됨.

**결론: 정확히 review_ver_14 권고대로 구현. live 진입 전 shape drift 차단 완료.**

### D. 통합본 2장-C: Readiness evidence freshness 1시간 가드

`app/services/live_phase_readiness.py` 직접 검증.

```
DEFAULT_READINESS_EVIDENCE_MAX_AGE_SECONDS = 3600.0  # line 48
READINESS_FRESH_EVIDENCE_KEYS = {
    "token_refresh", "ws_recovery", "account_snapshot",
    "market_status", "system_clock"
}  # line 49~55

def _enforce_evidence_freshness(key, check, *, checked_at):
    if key not in READINESS_FRESH_EVIDENCE_KEYS or not passed:
        return check  # legacy bool/non-fresh keys 무시
    evidence_time = _evidence_time_from_details(key, details)
    if evidence_time is None:
        return check  # timestamp 없는 legacy fixture 무시
    age_seconds = (checked_at - evidence_time).total_seconds()
    if age_seconds <= DEFAULT_READINESS_EVIDENCE_MAX_AGE_SECONDS:
        details["evidence_age_seconds"] = round(age_seconds, 3)
        return check  # 통과 + age 기록
    # stale → status=stale_evidence, passed=False, blocking_reasons=["readiness_evidence_stale"]
```

- 5개 fresh key 정확히 명시.
- legacy bool/no-timestamp 호환 OK (work_ver_15 2장-C 주장 그대로).
- `_evidence_time_from_details`가 key별로 다른 필드 사용: `system_clock`은 `local_time`, `ws_recovery`는 `checked_at` 우선 → `stable.observed_at` fallback, 나머지는 `checked_at`. **각 probe의 timestamp 필드와 매칭 정합.**
- 통과 케이스에도 `evidence_age_seconds` 기록 — 사후 리뷰 가능.
- 호출은 `build_readiness_run_from_dry_run` 안의 `fixture_checks` 빌드 시점에 자동 적용 (line 263). 모든 호출 경로에서 갱신됨.

**결론: 사양 그대로. 1시간 임계값은 hardcoded이므로 Q3 답변에서 짚는다.**

### E. 통합본 4장: Manual Market Status Runbook + source enum

`docs/Manual-Market-Status-Runbook.md` 직접 확인:

- 6개 섹션 구성: 목적과 경계, Source Enum, Snapshot 양식, 장전 절차, 권장안, 관련 경로.
- 2장 Source Enum 표가 review_ver_14 Q1 미세 약점 (b) "source 값 규약 없음"을 정확히 닫는다. 3개 enum 각각의 의미와 사용 조건 명시.
- 4장 장전 절차 7단계가 review_ver_14 Q1 미세 약점 (a) "운영 절차 없음"을 닫는다.
- 5장 권장안에 "🔴 운영자 판단 필요: 매 거래일 장전 수동 snapshot을 누가 언제까지 만들지" — review_ver_14에서 짚은 운영자 1인 단일 실패점이 명시적으로 운영자 결정으로 묶임.

`app/services/market_status_probe.py` 검증:

```
ALLOWED_MANUAL_MARKET_STATUS_SOURCES = (
    "manual_operator_snapshot",
    "manual_krx_snapshot",
    "manual_kis_snapshot",
)  # line 12~16

def market_status_snapshot_from_payload(payload):
    source = _required_str(payload, "source")
    if source not in ALLOWED_MANUAL_MARKET_STATUS_SOURCES:
        allowed = ", ".join(ALLOWED_MANUAL_MARKET_STATUS_SOURCES)
        raise ValueError(f"source must be one of: {allowed}")  # line 26~28
```

- enum 밖 source는 `ValueError`로 즉시 차단. 자유 문자열 금지.
- runbook의 enum 표와 코드 enum이 완전 일치.

**결론: review_ver_14 Q1의 두 미세 약점 모두 완전 closure. runbook 품질 양호.**

### F. 통합본 5장 검증 명령

- 119 → 143 테스트 통과 (24개 증가). 새로 추가된 테스트가 `test_live_order_guard`, `test_live_order_manager`, `test_kis_live_order_adapter` 영역 — 위 A/B/C 변경 검증 테스트로 정합.
- 본 리뷰에서 테스트 재실행 안 함. 통합본 본문에 동일 명령 + 통과 기록 있음.
- `bash -n` 검증 8개 스크립트 통과.
- `git diff -- app/risk config VERSION`: 출력 없음 → 불변 금지선 유지 ✓
- VERSION 직접 확인: `0.2.0` 유지.

### G. review_ver_14 P0/P1 closure 매핑

| review_ver_14 항목 | 분류 | work_ver_15 처리 | 평가 |
|---|---|---|---|
| NAS 실제 package/복구 drill | P0 | 명시적으로 운영자 결정으로 묶음 (work_ver_15 6장). 코드 작업 안 함. | ✗ **미처리 (의도된 punt)** |
| submit guard의 ws_recovery evidence_type 강제 | P0 | 3겹 방어로 완전 구현 | ✓ **완전 closure** |
| live account snapshot shape 자동 검증 | P0 | REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES + shape_status 차단 | ✓ **완전 closure** |
| 수동 market_status runbook + source enum | P1 | runbook 추가 + ALLOWED_MANUAL_MARKET_STATUS_SOURCES enum 강제 | ✓ **완전 closure** |
| WS reconnect snapshot dashboard 노출 | P1 | 통합본에 명시적 처리 없음. readiness JSON 노출은 이미 있음 (work_ver_14-4). | △ **dashboard 측은 미언급** |
| HTTP Date paper/live 동기화 비교 | P1 | 처리 안 됨 | ✗ **미처리** |
| Readiness evidence freshness | (review_ver_14에 없었던 추가 보강) | 1시간 가드 + evidence_age_seconds 기록 | ✓ **bonus closure** |

**P0 점수: 3개 중 2 완전 closure, 1 의도된 punt (운영자 결정).** P1은 3개 중 1 완전 closure, 1 부분, 1 미처리.

---

## Q1: Phase 2/3 synthetic WS evidence 차단이 readiness와 live submit guard 양쪽에서 충분한가

**3겹 방어로 충분하다. 단 enum 단일 소스화는 P1로 보강 필요.**

세 가지 이유:

1. **3겹 방어가 서로 독립적**. (a) readiness 빌드 시점에 invalid_evidence 재작성, (b) order_guard.assert_can_submit에서 evidence_type 검사, (c) order_manager가 두 경로를 wire-through. 어느 한 곳을 우회해도 다른 두 곳이 잡음. **단일 실패점 없음.**

2. **phase 정규화가 안전**. `_requires_real_ws_recovery_evidence`가 hyphen/underscore/space를 모두 처리하고 `startswith("phase2")` / `startswith("phase3")`로 매칭. `phase2_conservative`, `phase3-daily-limits`, `phase 2 cautious` 등 모든 변형이 잡힘.

3. **default require_real_ws_recovery_evidence 자동 적용**. caller가 `require_real_ws_recovery_evidence=None`을 넘기면 phase 기반 기본값으로 자동 활성화. caller가 명시 안 하면 안전 측 동작.

**미세 약점 두 가지**:

a) **enum 중복 정의**. `REAL_WS_RECOVERY_EVIDENCE_TYPES = {"real_kis_ws_observed", "real_kis_ws_recovery", "kis_ws_observed"}`가 `live_phase_readiness.py` line 56과 `live_order_guard.py` line 23 두 곳에 동일하게 박혀 있음. 향후 enum 확장 시 (예: 실제 KIS WS 관측 probe가 새 evidence_type을 추가하면) 한 파일 갱신하고 다른 파일 빼먹으면 silent 분기 발생. **공통 모듈(예: `app/services/ws_recovery_evidence.py`)에 단일 정의 후 두 곳이 import하도록 리팩토링 권장.** P1.

b) **enum 3개 값의 차이가 통합본/코드 어디에도 설명 없음**. `real_kis_ws_observed` vs `real_kis_ws_recovery` vs `kis_ws_observed` — 셋 다 동의어로 보이는데 왜 3개인지? 실제 KIS WS 관측 probe가 구현될 때 어느 값을 쓸지가 결정되어야 함. **runbook 또는 코드 docstring에 enum별 의미 명시 권장.** P1.

**결론: 차단 자체는 충분. 다음 라운드에서 enum 단일 소스화 + 의미 문서화.**

## Q2: account snapshot shape 검증의 필수 attribute 5개가 live read-only 진입 전 기준으로 충분한가

**기본 시작점으로는 충분. 단 live 첫 실행 후 보강이 필요할 가능성 높음.**

세 가지 이유:

1. **5개 attribute가 KIS 계좌 응답의 핵심 골격을 덮음**. position 행 수, summary 행 수, 현금잔고, 주식평가, 총자산 — KIS 계좌가 정상 응답하면 무조건 존재해야 하는 필드들. 누락이 있으면 KIS API 변경 또는 wrapper 버그의 강한 신호.

2. **`hasattr` 기반이라 attribute 이름 변경에 안전 측 동작**. KIS가 응답 필드명을 silent하게 바꿔도 우리 wrapper의 dataclass attribute가 안 따라가면 즉시 차단. live 진입 전 첫 실행에서 가장 큰 위험인 "필드명 drift"를 잡음.

3. **5개 중 하나라도 누락이면 `passed=False`로 fail-closed**. paper와 live 응답 shape 차이가 1 attribute라도 있으면 즉시 readiness 차단. 운영자가 "왜 막혔지?" 추적 가능 (`missing_attributes` 리스트가 readiness JSON에 그대로 박힘).

**미세 약점 세 가지**:

a) **value 타입 검증 부재**. `hasattr(snapshot, "cash_balance")`은 attribute 존재만 확인. 값이 `None`이거나 `""`이거나 `Decimal`/`int`/`str` 타입 변화 시 catch 못 함. live가 paper와 같은 attribute 5개를 가지지만 cash_balance가 `Decimal`이 아니라 `str`로 오는 케이스가 있다면 silent 통과 후 후속 코드에서 깨질 수 있음. **`*_present`는 `not None` 검사를 하지만 type 검사는 없음.** 보강 권장.

b) **`pending_orders`, `withdrawable_cash` 같은 submit 직전 필수 정보 누락**. 5개는 readiness 골격에는 충분하지만, 실제 submit 시점에 "주문 가능 현금이 얼마인가" 확인하려면 더 많은 attribute가 필요. Phase 2 submit guard 단계에서 별도 shape 검증을 추가하는 게 자연스러움. P1.

c) **shape baseline 기록 + drift 감지 미구현**. review_ver_14에서 권고한 "live 첫 실행 시 shape baseline 기록, 다음 실행에서 drift 감지" 부분이 work_ver_15에 미언급. 현재 코드는 "5개 있나"만 확인하고, "live 첫 실행 때와 동일한 shape인가"는 안 봄. live 첫 실행 후 KIS가 새 필드를 추가하거나 기존 필드를 제거해도 5개만 있으면 통과. **첫 실행 baseline + 후속 drift 감지를 work_ver_16-x에서 P1로 보강.**

**결론: 기본 시작점으로 충분. live 첫 실행 직후 (a)(b)(c) 모두 보강 필요.**

## Q3: timestamped evidence freshness 기본 1시간이 Phase 1 장전 readiness 기준으로 너무 짧거나 길지 않은가

**짧은 편. 30분~90분 사이가 안전대이고, 1시간은 그 안에 들지만 운영자 실수 여유가 빠듯. 운영 절차와 함께 평가 권장.**

세 가지 측면:

1. **장전 readiness 운영 시나리오 가정**. 운영자가 장 시작 09:00 기준으로 (a) 08:00 수동 market_status snapshot 생성, (b) 08:30 fresh probe 실행 (token/account/ws/clock), (c) 08:45 final readiness dry-run. 이 경우 (b)의 증거 age는 15분 ≪ 1시간. **정상 동작에서는 여유 있음.**

2. **운영자 부주의 시나리오**. (a) 07:30 probe 실행 후 다른 일 처리, (b) 09:15 readiness 다시 돌리려 함 → token age 105분 → stale 차단. 운영자가 probe 다시 돌려야 함. **실수 1회에 readiness 차단 → 매 거래일 5~10분 추가 부담.** 1시간이 빠듯한 측면.

3. **반대로 너무 길면 안 됨**. token expiry는 보통 24시간이라 토큰 자체는 유효해도, system_clock skew는 시간이 지나면 0.002초 → 0.5초로 drift 가능. 1시간 안에는 안전한 측정. **1시간 이상은 system_clock 신뢰도 측면에서 위험.**

**미세 약점 두 가지**:

a) **`DEFAULT_READINESS_EVIDENCE_MAX_AGE_SECONDS = 3600.0`이 module-level constant라 per-phase/per-check 조정 불가**. Phase 1 장전(여유) vs Phase 2 실시간(엄격)이 같은 임계값을 씀. **per-key dict 또는 per-phase factory로 분리 권장.** 예: `system_clock`은 30분, `token_refresh`는 4시간(만료까지 여유), `market_status`는 stale_after 필드 직접 사용 등.

b) **stale 차단의 운영 UX 미흡**. stale로 차단되면 운영자가 어느 probe를 다시 돌려야 할지 readiness JSON의 `evidence_age_seconds`와 `max_evidence_age_seconds`로 알 수는 있지만, "지금 09:15, 다시 돌리려면 무엇을 다시 돌리고 다시 readiness 실행" 절차가 runbook에 없음. **runbook에 stale 회복 절차 추가 권장.**

**결론: 1시간 자체는 합리적 시작점. (a) per-key/per-phase 조정 가능 구조 + (b) runbook 보강 두 가지가 work_ver_16-x P1.**

---

## 추가 발견 / 위험한 가정

1. **enum 중복 정의 (Q1-a)**: `REAL_WS_RECOVERY_EVIDENCE_TYPES`가 두 파일에 중복. 단일 모듈로 추출 필요.

2. **freshness 임계값 hardcoded (Q3-a)**: per-phase/per-key 조정 불가. system_clock과 token_refresh는 운영 특성이 다른데 같은 임계값.

3. **manual market_status snapshot의 `symbol_set_hash` 자동화 미완**: runbook 3장이 "수동 절차에서는 snapshot 대상 종목 묶음을 식별하는 사람이 읽을 수 있는 값으로 두고, 자동화 전환 시 hash 계산 helper를 별도 구현한다"고 명시. **현재는 자유 문자열 가능 → 사람 실수로 같은 hash 재사용 시 다른 종목 묶음을 같은 snapshot으로 오인할 위험.** 작은 helper로 sorted symbol list → SHA256 prefix 같은 결정적 hash 생성을 work_ver_16-x에서 closure.

4. **system_clock skew 0.002초의 정밀도 의문**: HTTP Date는 초 단위라 reference 정밀도가 1초인데 측정 skew가 0.002초? `local_time`과 `reference_time` JSON에서 보면 둘 다 같은 초(`13:58:42`)인데 local_time은 `.002375` 마이크로초 포함, reference_time은 마이크로초 0. 즉 **현재 skew는 "내 시계의 마이크로초 부분"을 측정 중**이며 진짜 KIS 시각과의 skew는 0~1초 사이 어딘가 (HTTP Date 정밀도 한계 때문에 더 정확히 알 수 없음). review_ver_13 미세 약점 (b)에서 짚었던 1초 정밀도 이슈가 그대로. 사실상 "1초 이내"가 우리가 측정 가능한 최선이며, 0.002초는 marketing-friendly 수치이지 진짜 정밀도 아님. **runbook에 "표시되는 skew는 HTTP Date 초 정밀도 한계로 실제 ±1초 이내를 의미한다" 명시 권장.**

5. **kill_switch는 freshness 가드 대상이 아님**: READINESS_FRESH_EVIDENCE_KEYS에 kill_switch가 없음. kill switch 파일 자체에 `updated_at` 필드가 있어 별도 stale_after 검사를 하지만, freshness 가드와는 분리됨. 의도된 설계로 보이지만 work_ver_15 본문에 명시 없음. **runbook 또는 docstring에 "kill_switch는 자체 stale_after 메커니즘으로 검사" 명시 권장.**

6. **review_ver_14 P1 중 누락**: (a) WS reconnect snapshot dashboard 노출, (b) HTTP Date paper/live 동기화 비교 — 두 항목이 work_ver_15에 미언급. 의도된 deferral인지 단순 누락인지 통합본에 안 적힘. **work_ver_16-x에서 명시적으로 잡거나 운영자 결정 슬라이스로 묶어야.** 누락이 누적되면 ping-pong 패턴(매번 새 작업으로 덮으면서 옛 권고가 silent하게 흘러감) 위험.

## 다른 thread와 충돌 가능성

이번 라운드 변경 영역:
- `app/services/live_phase_readiness.py`: enum, freshness 가드, ws evidence 가드 (대규모 변경)
- `app/services/live_order_guard.py`: enum 중복, assert_can_submit signature 확장
- `app/services/live_order_manager.py`: signature wire-through
- `app/services/kis_account_probe.py`: shape 검증 추가
- `app/services/market_status_probe.py`: source enum 강제
- `docs/Manual-Market-Status-Runbook.md`: 신규 runbook
- `tests/test_live_order_guard.py`, `tests/test_live_order_manager.py`, `tests/test_live_phase_readiness.py`, `tests/test_kis_account_probe.py`, `tests/test_market_status_probe.py`: 회귀 테스트 보강

post-close ML thread, KIS WS verification thread 충돌:
- **`assert_can_submit` signature 확장**: `ws_recovery_evidence_type`, `require_real_ws_recovery_evidence` 두 파라미터가 keyword-only로 추가됨. 기존 caller는 None 기본값이라 backward-compat OK. 단 다른 thread가 `assert_can_submit` 호출 코드를 동시 수정 중이라면 merge 시 keyword 충돌 가능. **Phase 2 진입 코드 작성 thread와 조율 필요.**
- **`kis_account_probe.py` shape 검증**: 다른 thread가 KIS account dataclass에 attribute 추가/제거 중이면 즉시 영향. 단 `hasattr` 기반이라 attribute 추가는 안전, 제거만 위험. broker thread와 KIS account contract 변경 조율.

이번 라운드는 충돌 위험 중간. 특히 `LiveOrderGuard.assert_can_submit`은 submit 경로의 핵심이라 다른 thread와 머지 충돌 시 주의.

## 종합

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| latest-readiness.json 신규 필드 정확성 | 6/6 일치 | 없음 |
| Phase 2/3 WS evidence guard 3겹 방어 | 단일 우회 불가 | enum 단일 소스화 (P1), enum 의미 문서화 (P1) |
| Account snapshot shape 검증 | 5개 attribute 정확, fail-closed 동작 | value 타입 검증, 추가 attribute (P1), drift baseline (P1) |
| Evidence freshness 1시간 가드 | 사양 그대로 + bonus | per-key/per-phase 조정 가능 구조 (P1), runbook stale 회복 절차 (P1) |
| Manual Market Status Runbook + source enum | review_ver_14 Q1 두 약점 완전 closure | 없음 |
| review_ver_14 P0 closure | 3개 중 2 완전 + 1 의도된 punt | NAS drill 운영자 결정 진행 |
| 불변 금지선 (app/risk, VERSION) | 변경 없음 정합 | 없음 |
| Q1 WS evidence 차단 충분성 | 3겹 방어로 충분 | enum 단일화 |
| Q2 account shape 5개 충분성 | 시작점 충분, live 후 보강 필요 | type 검증, drift 감지 |
| Q3 freshness 1시간 임계 | 시작점 합리적 | per-phase 조정, runbook 보강 |

## 다음 단계 권장

**Codex 작업 (P1, Phase 1 진입 직후)**:
1. **`REAL_WS_RECOVERY_EVIDENCE_TYPES` 단일 소스화**. `app/services/ws_recovery_evidence.py` 또는 기존 모듈 한 곳에 정의 후 `live_phase_readiness.py`, `live_order_guard.py`가 import. enum 3개 값의 의미(docstring 또는 runbook)도 명시.
2. **`DEFAULT_READINESS_EVIDENCE_MAX_AGE_SECONDS` per-key 조정 가능 구조**. dict 또는 dataclass로 `{system_clock: 1800, token_refresh: 14400, ws_recovery: 1800, account_snapshot: 3600, market_status: 3600}` 같이. 또는 phase별 factory.
3. **manual market_status `symbol_set_hash` 결정적 hash helper**. sorted symbol list → SHA256 prefix 등. runbook 3장의 placeholder를 자동화로 교체.
4. **review_ver_14 P1 누락 두 항목 재노출**. (a) WS reconnect snapshot dashboard 노출, (b) HTTP Date paper/live 동기화 비교 — work_ver_16에서 명시적으로 다루거나 운영자 결정 슬라이스로 묶기. ping-pong 패턴 방지.
5. **system_clock 정밀도 표시 명시화**. HTTP Date 초 정밀도 한계로 표시 skew가 실제로 ±1초 의미인 점을 runbook 또는 docstring에 명시.

**Codex 작업 (P1, Phase 2 진입 전)**:
6. **account snapshot value 타입 검증**. `*_present`만으로는 부족. attribute 값 타입을 dataclass 또는 별도 검증 함수로 확정.
7. **account snapshot baseline + drift 감지**. live 첫 실행 시 shape baseline 기록 → 후속 실행에서 비교.
8. **submit 직전 account shape 보강**. Phase 2 submit guard 단계에서 `pending_orders`, `withdrawable_cash` 등 추가 필수 attribute.

**운영자 결정**:
1. **NAS 실제 package/복구 drill 시점**: review_ver_13부터 누적된 잔여 항목. work_ver_15는 명시적으로 운영자 결정으로 묶음. 부분 백업 정책, 용량 제한, 복구 drill 시점.
2. **Phase 1 직전 kill switch OFF 파일 생성**: 당일 승인 절차 (`--disable --apply --confirm-disable`).
3. **live account read-only probe 첫 실행 허용**: shape guard가 들어간 지금, 운영자 승인 후 1회.
4. **매 거래일 manual market_status snapshot 운영 책임자와 양식**: runbook 5장에서 명시적 운영자 결정 항목으로 묶임. 위임 가능 여부, 백업 운영자 등.

## 신뢰 수준

work_ver_15는 review_ver_14의 P0 2개를 코드 레벨로 완전 closure하고, P1 1개도 완전 closure했다. 추가로 요청하지 않은 evidence freshness 1시간 가드까지 자발적 보강. **신뢰도 매우 높음.** 통합본의 모든 코드 주장이 정본 저장소 검증과 일치하며, sanitization 정책은 review_ver_14에서 검증한 그대로 유지(account 5 attribute가 늘었지만 raw 값은 여전히 비노출).

남은 부채:
- (a) NAS drill 미진행: review_ver_13부터 누적, 의도된 운영자 결정
- (b) review_ver_14 P1 누락 2건: dashboard 노출, paper/live 시각 비교
- (c) Q1/Q2/Q3 답변에서 도출된 P1 7건

다음 라운드(review_ver_16 예상)에서 cowork이 (a) enum 단일 소스화 + freshness per-key 조정 검증, (b) live account read-only 첫 실행 결과 검증(운영자 승인 시), (c) NAS drill 운영자 결정 양식 검토 — 세 단계로 본다. **Phase 1 read-only 진입은 이번 라운드 closure를 근거로 진행 가능.** Phase 2 진입은 live 첫 실행 후 shape baseline + 실제 KIS WS 관측 baseline까지 완료 후.

리뷰자 메모: 본 리뷰에서 `python -m unittest` 143 테스트 재실행은 안 했다. 통합본 본문에 동일 명령 + 통과 기록 있음. `live_phase_readiness.py`와 `live_order_guard.py`의 evidence guard 코드는 직접 검증. `kis_account_probe.py`의 shape 검증 코드도 직접 검증. 다음 라운드 또는 사용자 요청 시 테스트 실행 및 다른 thread 머지 영향 검토 가능.
