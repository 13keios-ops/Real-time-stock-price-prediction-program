# Phase 1b 통합 readiness cycle work_ver 30-5

## 1. 목적

Phase 1b 실제 관측을 하려면 local premarket 점검, synthetic WebSocket recovery, bounded live read-only 관측, fixture snapshot, 전용 readiness, dashboard 갱신을 순서대로 실행해야 했다. 개별 명령은 모두 구현됐지만 수동 순서를 틀리거나 서로 다른 시점의 증거를 섞을 위험이 남아 있었다.

이번 작업은 이 절차를 장외 한 명령으로 고정하고, 기본 실행과 실제 관측 실행의 안전 경계를 코드와 테스트로 잠그는 작업이다.

## 2. 구현

- 신규 명령: `scripts/run_phase1b_readiness_cycle.sh`
- 기본 실행:
  - local premarket readiness 갱신
  - network-free synthetic WS recovery 갱신
  - Phase 1b network-free preflight
  - local fixture snapshot
  - Phase 1b preflight readiness
  - 외부 KIS 네트워크 호출 0회
- `--execute` 실행:
  - 위 local 증거를 같은 판정 시점에 다시 만든다.
  - 기존 bounded live token/account/clock 관측만 추가한다.
  - 주문/취소 메서드는 호출하지 않는다.
- `--refresh-dashboard`는 `--execute`와 함께만 허용한다.
- `pre-open`과 `regular-session`에서는 첫 step 전에 cycle 전체를 차단한다.
- subprocess 실패 시 stdout/stderr 원문을 summary에 넣지 않아 token, 계좌정보, raw 오류 본문 유출을 막는다.
- 실제 네트워크 시도 수를 `network_calls_executed=0..4`로 기록하고, 0회이면 `execution_started=false`로 유지해 마지막 실제 관측 증거를 덮지 않는다.

## 3. 증거 파일 보존

단순 preflight가 마지막 실제 관측을 덮지 않도록 파일을 분리했다.

- 기본 cycle: `latest-cycle-preflight.json`
- 실행 요청 cycle: `latest-cycle-execute.json`
- 기본 readiness: `latest-readiness-preflight.json`
- `--execute`를 줬지만 관측 미시작: `latest-readiness-attempt.json`
- bounded 관측 시작 후 readiness: `latest-readiness.json`

실제 관측의 성공 여부와 무관하게 네트워크 관측이 시작된 결과만 `latest-readiness.json`을 갱신한다. 단순 자격정보 부족이나 protected session 차단은 마지막 실제 관측 증거를 덮지 않는다.

## 4. 실제 주말 기본 cycle 결과

- 실행 시각: `2026-07-11T01:34:39.973498+09:00`
- 장 상태: `weekend`
- mode: `network-free-preflight`
- observation network calls: `0`
- order method calls: `0`
- synthetic WS: fresh, `ok`, `network_called=false`
- local premarket/database/disk/dashboard/storage migration: `ok`
- Phase 1b status: `blocked`
- 남은 필수 blocker:
  - live token refresh 미검증
  - live account snapshot/shape 미검증
  - live system clock 미검증
- 비차단:
  - `market_status`
  - `kill_switch`

기존 stale WS blocker는 같은 cycle 안에서 fresh synthetic 증거를 다시 만들면서 제거됐다. 이 증거는 30분 freshness 기준이 있으므로 영구 해소가 아니라, 실제 `--execute` cycle이 같은 판정 시점에 자동 재생성하도록 만든 것이 핵심이다.

### 실제 `--execute` attempt

- 실행 시각: `2026-07-11T01:48:42.641579+09:00`
- `execution_requested=true`
- `observation_execution_started=false`
- `observation_network_calls_executed=0`
- `order_method_calls=0`
- attempt: `latest-phase1b-readonly-attempt.json`
- readiness: `latest-readiness-attempt.json`
- 차단 원인: live quote credentials와 live account credentials 미준비

즉 `--execute` 코드 경로까지 실제로 검증했지만 자격정보 preflight에서 외부 호출 전에 멈췄다. 이는 Phase 1b 성공이 아니라, 자격정보가 없을 때 안전하게 0회 호출로 차단된 증거다.

## 5. 검증

- cycle 전용 테스트: `5 tests OK`
- Phase 1b 관련 테스트: `70 tests OK`
- 전체 unittest: `490 tests OK`
- 전체 pytest: `490 passed, 67 subtests passed`
- Python compileall: 통과
- bash parse: 통과
- `git diff --check`: 통과

검증한 주요 회귀 조건:

- 기본 cycle에 `--execute`가 들어가지 않는다.
- 실제 실행 요청에서만 bounded observation command에 `--execute`가 들어간다.
- dashboard refresh는 명시 실행 없이는 거부된다.
- protected session에서는 subprocess가 한 건도 시작되지 않는다.
- preflight/attempt/actual readiness 경로가 분리된다.
- step 실패의 stdout/stderr 비밀값이 summary에 남지 않는다.

## 6. Codex 의견

이 변경은 Phase 1b를 통과시킨 것이 아니다. 실계좌 자격정보가 없으므로 실제 live token/account/clock 증거는 여전히 없다. 다만 자격정보 입력 뒤 사람이 여러 명령을 정확한 순서로 이어야 했던 운영 위험은 제거했다.

현재 코드 추가보다 더 필요한 것은 실제 자격정보를 로컬 비밀 저장소에 준비한 뒤 장외에서 `./scripts/run_phase1b_readiness_cycle.sh --execute --refresh-dashboard`를 1회 실행하는 것이다. 이 실행 전에는 Phase 1b 통과나 Phase 2 진입을 주장하면 안 된다.

## 7. 다음 방향

1. 실전 KIS 조회 자격정보를 `--read-only-preparation`으로 입력한다.
2. 장외에 통합 cycle을 `--execute --refresh-dashboard`로 1회 실행한다.
3. paper/live account shape, token, clock, 주문 호출 0건을 확인한다.
4. 다음 거래일 장후 4종목 mismatch를 1회 제한 wrapper로 재확인한다.
5. 2026-07-20 장후 E1/E5 사전등록 라운드를 실행한다.

다음 cowork 리뷰는 실제 bounded 관측 결과 또는 2026-07-20 E1/E5 결과가 나온 뒤 요청하는 것이 효율적이다.

## 8. 변경하지 않은 항목

- 실전 주문/취소
- `app/risk/`
- `config/`
- `VERSION`
- `ALLOW_LIVE_ORDERS`
- active model/gate/threshold
- 신규 모델 실험
- NAS 백업
