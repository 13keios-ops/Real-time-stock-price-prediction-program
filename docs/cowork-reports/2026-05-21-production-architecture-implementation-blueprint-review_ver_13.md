# Claude cowork 리뷰 review_ver_13: KIS HTTP Date 기반 system_clock + WS reconnect metric 보강 + NAS dry-run + overnight 라벨 정정

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `review_ver_13`
- 기준 작업본: work_ver_13 + 13-1 ~ 13-8 통합본 (Codex 토큰 절약형 단일 전달)
- 리뷰 방식: 통합본 기준 정책/구조 판단 중심. 라인 단위 코드 리뷰는 cowork이 별도 요청 시 진행.

## 요약

work_ver_13 시리즈는 review_ver_12 잔여 P0 중 (a) reference clock 원천 결정(KIS HTTP Date), (b) WS metric timestamp 보강(observed_at/last_reconnect_at/last_stable_at/storm_active_since), (c) NAS recovery dry-run 명령 검증, (d) `overnight`/`pre-open` 라벨 오판 수정 — 4가지를 코드 단위로 전진. 결론은 **그대로 사용 가능. Phase 1 진입 차단 잔여 3개 P0(자동 주입 + 실제 NAS package drill + live account header shape)에 동의.** Codex 권장 우선순위 OK.

핵심 발견 세 가지: (1) HTTP Date를 reference clock으로 쓰는 결정은 **표준 + 자동 + 안정**의 3박자라 NTP/외부 시각 서버보다 운영 리스크 낮음. (2) `overnight` 라벨 정정은 사용자 지적 그대로 옳은 수정이고 watchdog/dashboard 의미가 명확해짐. (3) WS reconnect metric은 Phase 1 관측 도구로만 두고 Phase 2 submit guard 연결은 첫 5~10거래일 실측 후 결정이 안전.

## Q1: HTTP Date header reference clock + raw header 미저장 정책

**Phase 1/2 안전 기준에 충분하다.** 다섯 가지 이유.

1. **HTTP Date는 RFC 7231 표준 + KIS가 안정 제공**: work_ver_13-5에서 paper quote 응답에 `date` 헤더 존재 확인. 별도 KIS API 없이 모든 REST 응답에 자동으로 따라오므로 운영 의존성 추가 0. NTP/외부 시각 서버 의존보다 안정성 우위.
2. **KIS 서버 시각 = KIS 주문 timestamp 검증 기준에 정합**: KIS가 주문 timestamp를 검증할 때 같은 서버 시각을 기준으로 본다(추정). 우리 로컬을 KIS 서버 시각에 맞추는 것이 의미상 정확. 외부 시각 서버(NTP)를 쓰면 KIS-NTP 사이에 추가 drift 가능성이 들어옴.
3. **raw header 미저장 + sanitized check 저장**(work_ver_13-6): source, skew, local/reference time, blocking reasons만 audit/리포트에 기록. authorization, set-cookie, custom KIS 헤더 같은 민감 정보 노출 0. NAS 백업 정책(비밀값 제외)과 정합.
4. **fresh 조회 보장**(work_ver_13-2): 요청 시작 시 `last_response_headers` 비우고 성공 응답에서만 갱신. 이전 응답 헤더가 silent하게 재사용되어 stale skew로 잘못 판정될 위험 차단.
5. **system_clock helper 자체가 순수 함수**(review_ver_12에서 확인): network 호출 없음. Phase 1 readiness check는 fixture/dry-run, Phase 2 submit는 실제 KIS 조회 직후 decision 주입 — 단계적 강화가 정합.

**미세 약점 두 가지**:

a) **HTTP Date timezone 표준 가정**: RFC 7231은 `GMT` 명시를 요구하지만 일부 서버는 그 외 timezone 또는 timezone 누락으로 줄 수 있음. Python `email.utils.parsedate_to_datetime`(또는 `imap_lib`) 등 표준 parser를 쓰면 안전하지만, KIS가 정확히 RFC 7231 준수하는지 확인 필요. 만약 timezone이 누락되거나 형식이 다르면 parser가 silent하게 0으로 해석 후 ±2초 skew 차단 → false negative 안전 측. 다만 명시 확인 권장.

b) **HTTP Date 정밀도 1초**: HTTP Date는 초 단위라 우리 skew 한도 ±2초 대비 reference 정밀도가 1초. 실측 skew에 ±0.5초 정도 noise 가산. 실용상 문제 없지만 운영자 인지/문서 명시 필요.

두 미세점 모두 Phase 1 readiness runner 연결 시 docstring/테스트로 잠그면 OK. **본 결정 자체는 매우 안전.**

## Q2: Phase 1 진입 전 P0 3가지 (자동 주입 + NAS 실제 drill + live account header shape)

**3가지 정확하다.** review_ver_12 Phase 1 P0 4가지의 잔여 항목과 정확히 정합.

review_ver_12 시점 4가지 → 현재 진행:
- WS keepalive + reconnect metric: ✓ 완료 (work_ver_12-1)
- KIS 응답 fixture 검증: ✓ paper 완료, **live 미완료** → P0 (c)
- NAS 복구 drill: △ self-test/dry-run 명령 ✓, **실제 package/복구 미완료** → P0 (b)
- reference clock 원천 결정: ✓ HTTP Date 결정 (work_ver_13-2/3/4/5), **자동 주입 미완료** → P0 (a)

즉 review_ver_12 잔여 3가지가 정확히 work_ver_13 Codex P0 3가지와 매핑된다.

**추가 권고 2가지 (P0가 아닌 P1)**:

첫째, **WS reconnect snapshot의 readiness/dashboard read-only 노출**. work_ver_13에서 timestamp 4개 필드 + `to_dict()`까지 보강 완료했는데 노출 경로가 없으면 운영자가 측정 데이터를 못 봄. Q4와 연결. P0는 아니지만 **Phase 1 read-only 진입 직후 첫 P1**으로 자연스러움. work_ver_13 9장 권장 4번 다음 또는 병행 진행.

둘째, **operator-decision 잔여 결정 항목 묶기**. P0 (b) NAS 실제 drill 시점과 P0 (c) live account 조회 허용은 모두 운영자 작업/결정 영역이고 코드 작업과 의존성 있음. 별도 operator-decision 문서로 정리해서 운영자 결정을 한 묶음으로 가속 권장. work_ver_13 마지막 "🔴 운영자 판단 필요" 두 항목이 그 자리.

**결론: 3가지 P0 정확.** WS 노출은 P1, operator-decision 정리는 별도 행정.

## Q3: overnight 라벨 정정 + legacy PowerShell 경로

**라벨 분리 해석 정확. legacy PowerShell은 Phase 1 진입 차단 항목 아니지만 정리 권장.**

라벨 분리 4단계가 의미적으로 옳다:
- `overnight`: 새벽/야간 (정규장 시작 60분 이상 전 또는 장 종료 후 한참). live runtime이 켜질 이유 없는 시간.
- `pre-open`: 정규장 시작 60분 전부터 개장 전. live runtime warmup 대상.
- `regular-session`: 09:00~15:30.
- `post-close`: 정규장 종료~다음 거래일 pre-open 전.

이 분리가 옳은 이유 3가지:

1. **사용자 지적이 정확했다**: 새벽 1시는 운영자 입장에서 분명 overnight지 pre-open이 아님. 라벨이 의미와 일치해야 운영자 인지가 정확. dashboard "지금이 pre-open이라고? 왜 watchdog이 should_run=false지?"라는 silent 혼란 차단.
2. **dashboard 정보 정확화**: `kis_verification.py`에서 overnight는 market data expected=false, `dashboard.py`에서 정규장 장애가 아니라 장외 안내로 처리. 운영자가 잘못된 alert에 반응하는 위험 차단.
3. **watchdog 동작 명확화**: `live_runtime_should_run`이 overnight에서 false인 이유가 자명. `live_runtime_action=off_session_hold_overnight` 라벨이 watchdog 상태에 정확히 반영(work_ver_13 3장) — 의도된 동작.

legacy PowerShell 경로:
- 현재 정본 운용은 WSL 정본 저장소 기준(work_ver_13 9장 권장 4).
- 만약 운영자가 Windows PS1 경로를 계속 쓴다면 같은 라벨 분리가 필수.
- 사용 안 하면 문서로만 `deprecated` 또는 `legacy` 표시 + Windows 진입 차단.
- **Phase 1 진입 차단 항목은 아님**(정본 WSL이 라벨 정합).
- 다만 **legacy PS1을 어떻게 정리할지(완전 제거 vs 라벨 정합 vs deprecated 문서화) 운영자 결정**이 필요. 운영 혼란 방지.

**결론: 라벨 분리 해석 정확. legacy PowerShell 정리 방식은 운영자 결정 항목으로 묶기.**

## Q4: WS reconnect metric Phase 1 관측만, Phase 2 submit guard 연결은 false positive 관측 후

**적절하다. review_ver_12 Q1 답과 정합.**

review_ver_12 Q1에서 cowork이 "Phase 1 측정 충분, Phase 2 submit guard 연결은 timestamp 보강 후 false positive 검증 거치는 게 안전"이라 권장. work_ver_13이 timestamp 4개(`observed_at`, `last_reconnect_at`, `last_stable_at`, `storm_active_since)`와 `to_dict()` 추가로 보강 완료. **따라서 Phase 1 관측 → 실측 baseline 수집 → Phase 2 연결 순서가 정합적**.

3가지 이유:

1. **false positive 위험 실측 필요**: reconnect_backoff 5초 × storm_threshold 3회 = 약 15초 안에 storm 판정. 정상 KIS WS reconnect가 5~15초 범위라 실측 데이터 없이는 threshold가 적절한지 모름. Phase 2 submit guard에 바로 연결하면 정상 reconnect도 차단 위험.
2. **Phase 1 측정으로 baseline 확보**: 실제 운용 환경(WSL2, 네트워크 환경, KIS 서버 응답성)에서 reconnect 빈도/duration/storm 빈도 측정 → threshold 조정 → Phase 2 연결.
3. **storm 자동 해제 cycle 검증 시간 필요**: 코드상 stable_connection_seen(5 frame)으로 자동 해제되지만 실측 환경에서 정상 작동하는지 관찰. 만약 일부 종목이 5 frame 도달 전 다시 disconnect 되면 storm이 의도와 다르게 지속 가능.

추가 보강 후보 (Q2 추가 권고 1번과 연결):
- **dashboard/readiness 노출이 Phase 1 진입 직후 첫 P1**. 노출 없으면 측정 자체가 보이지 않아 baseline 수집 의미 없음.
- 노출 후 첫 5~10거래일 동안 reconnect 빈도/duration 측정 → "storm이 60초 이상 지속되면 차단" 같은 시간 기반 임계로 정밀화 → Phase 2 연결.

**결론: 적절. Phase 2 submit guard 연결 결정은 Phase 1 첫 5~10거래일 baseline 수집 후.**

## 추가 발견 / 위험한 가정

1. **HTTP Date timezone parsing 강건성** (Q1 미세 약점 a): work_ver_13-1의 HTTP Date parser가 어떤 lib을 쓰는지 확인 권장. Python 표준 `email.utils.parsedate_to_datetime`은 RFC 5322 호환이라 안전. 직접 strptime을 쓰면 timezone 누락 시 silent fail 위험. **권장 보강**: parser 함수에 비표준 timezone 케이스 테스트 추가(예: 'Mon, 21 May 2026 01:23:45 KST', timezone 없음).

2. **`overnight` 상태에서 watchdog/dashboard가 alert 안 띄우는 정확성** (work_ver_13 3장): kis_verification.py와 dashboard.py 변경으로 정규장 장애 alert가 안 뜨도록 됐는데, 동시에 **overnight 중에 발생한 실제 장애(예: 새벽 dashboard down)는 어떻게 잡히는지** 명시 필요. 운영자가 overnight 상태에서 "장애가 없다"가 아니라 "장 외이므로 정상 alert 기준이 다르다"를 이해해야 함.

3. **`overnight` 라벨 정정 후 reverse 호환성**: 기존 dashboard 카드, runtime report, audit 기록 등에 `pre-open`으로 기록된 과거 데이터가 있을 수 있음. 라벨 변경 후 과거 데이터 조회/분석 시 의미 혼동 위험. **권장 보강**: 라벨 변경 시점 표시 또는 과거 데이터 "당시 라벨 기준" 주석.

4. **legacy PowerShell 라벨 미정정의 운영 위험**: 운영자가 PS1을 무심코 쓰면 overnight 상태인데 PS1이 pre-open으로 보여 watchdog 동작과 mismatch. **권장 보강**: PS1 진입 시점에 "WSL 정본 권장" warning 또는 PS1 자체에 라벨 정합 패치.

5. **sanitized clock check의 정합성**: source, skew, local/reference time, blocking reasons만 기록한다는 결정은 좋은데, **만약 분쟁 시 "raw Date header가 무엇이었는지" 증거가 필요해지면 재현 불가**. NTP/외부 시각 서버는 같은 시각에 재조회하면 다른 값이 나오니 증거력이 약함. **권장 보강**: 운영자 결정 항목으로 "raw Date header를 별도 short-retention(7일) 암호화 저장소에 두고 기본은 sanitized check만 audit에 두는" 옵션 검토.

## 다른 thread와 충돌 가능성

이번 라운드 변경 영역:
- `app/utils/time.py`, `scripts/wsl_ops.py`, `scripts/common_process_helpers.sh` (overnight 라벨)
- `app/services/system_clock.py`, `app/services/live_phase_readiness.py`, `app/services/live_order_guard.py` (HTTP Date)
- `app/brokers/kis_quote_rest.py` (last_response_headers)
- `app/brokers/kis_quote_ws.py` (WS metric timestamp)
- `app/services/kis_verification.py`, `app/services/dashboard.py` (overnight 표시)

post-close ML 유지보수 thread(2026-05-18-post-close-ml-maintenance review)와의 충돌:
- **dashboard.py 동시 수정**: 이번 thread가 overnight 안내 카드 추가, ML thread가 quick-live-train 카드 추가. 카드 위치 다르면 git merge OK이지만 status_alerts 리스트와 payload schema 추가 시 조율 필요.
- **session_status 사용**: ML thread의 `runtime_autoboot`이 `market_session_status`를 read해 quick_maintenance 진행 여부 판단. **overnight 추가 후 기존 `pre-open` 분기에서 overnight를 어떻게 처리하는지 확인 필요**. work_ver_13에서 `script_dispatch.sh`/`common_process_helpers.sh`도 라벨 정합 반영했다고 했으나 모든 분기점 확인 권장.

이번 라운드는 ML thread 충돌 위험 낮음. 다만 session_status 분기 처리는 두 thread 모두에서 명시 확인 필요.

## 종합

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| Q1 HTTP Date reference clock + raw 미저장 | Phase 1/2 안전 충분 | timezone parsing 강건성 테스트, 정밀도 1초 명시 |
| Q2 Phase 1 진입 전 P0 3가지 | 정확 | WS 노출은 P1으로 추가, operator-decision 묶기 |
| Q3 overnight/pre-open 라벨 정정 | 해석 정확 | reverse 호환성 명시, legacy PS1 정리 방식 결정 |
| Q4 WS metric Phase 1 관측만 | 적절 | dashboard/readiness 노출이 Phase 1 첫 P1 |

## 다음 단계 권장

**Codex 작업 (P0)**:
1. **runtime caller/readiness runner의 system_clock decision/check 자동 주입** (Codex 9장 권장 1번). KIS read-only 조회 직후 sanitized check 생성 → readiness report 병합. Phase 2 submit caller에서는 fresh decision 없으면 차단.
2. **HTTP Date parser timezone 강건성 테스트**(`tests/test_system_clock.py` 또는 `tests/test_kis_http_clients.py`)에 비표준 timezone/누락 케이스 추가.

**Codex 작업 (P1, Phase 1 진입 직후)**:
3. **WS reconnect snapshot의 readiness/dashboard read-only 노출**. dashboard 카드 1개 + readiness check 1개. 첫 5~10거래일 baseline 수집 시작.
4. **live account read-only header shape 확인** (P0 (c)). 운영자 승인 후 한 번 실행.

**운영자 결정**:
1. **NAS 실제 package/복구 drill 시점 + 용량/경로 제한** (work_ver_13 마지막 운영자 판단 1번). repo 56GB, runtime-data 45GB 상태에서 전체 백업은 큰 작업. 부분 백업 정책 결정 필요.
2. **Phase 1 read-only에서 live account header shape 확인 허용** (work_ver_13 마지막 운영자 판단 2번).
3. **legacy PowerShell 경로 처리 방식**: 완전 제거 / 라벨 정합 패치 / deprecated 문서화 중 선택. WSL 정본 사용이 정착되어 있으면 deprecated 문서화로 충분.
4. **raw Date header short-retention 저장 옵션** (cowork 추가 발견 5): 분쟁 대비 7일 retention 별도 암호화 저장 여부.

## 신뢰 수준

work_ver_13 시리즈는 review_ver_12 잔여 P0 4가지 중 (reference clock 원천, WS metric 보강) 2가지를 closure했고 (자동 주입, NAS 실제 drill, live header) 3가지가 잔여. 그 외 사용자 지적의 `overnight` 라벨 정정까지 정확히 흡수. **8개 sub-work를 9장 문서 1개로 통합 전달하는 운용 방식이 cowork 토큰 소비를 효과적으로 줄였다** — 향후 같은 패턴 권장.

다음 라운드(review_ver_14 예상)에서 cowork이 (a) runtime caller/readiness runner의 자동 주입 코드 검증, (b) WS reconnect snapshot 노출 검증, (c) NAS 실제 drill 결과 검토 — 세 단계로 본다. 이 셋이 끝나면 Phase 1 read-only 진입 가능.
