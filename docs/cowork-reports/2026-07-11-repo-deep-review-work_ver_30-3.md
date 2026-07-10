# 저장소 심층리뷰 후속 작업 보고서 work_ver_30-3

- 작성 시각: 2026-07-11 00시대 KST
- 기준 리뷰: `2026-07-07-buy-avoid-validation-verification-review_ver_29.md`
- 직전 작업본: `2026-07-10-repo-deep-review-work_ver_30-2.md`
- 범위: Phase 1b 실전계좌 read-only 실행 절차의 fail-closed 구조화

## 1. 이번에 해결한 공백

직전 작업에서 주문 메서드 없는 KIS 조회 client, live 자격정보 안전 준비 옵션, paper/live account shape 비교 도구까지는 준비됐지만 실행 순서가 여러 명령으로 흩어져 있었다. 이 상태에서는 사람이 순서를 잘못 실행하거나, 실패 뒤 다음 호출을 계속하거나, 차단된 시도가 마지막 유효 증거를 덮을 수 있었다.

이번 작업은 이 절차를 하나의 wrapper로 묶되 기본 실행은 네트워크 0회로 두었다.

## 2. 구현 내용

- `app/services/phase1b_readonly_observation.py`
  - `TRADING_MODE=paper` 확인
  - `ALLOW_LIVE_ORDERS=false` 확인
  - paper/live 자격정보는 값이 아니라 존재 여부만 확인
  - read-only client에 주문/취소 메서드가 없는지 확인
  - 앞 단계 실패 시 뒤 네트워크 호출을 실행하지 않는 fail-closed orchestration
  - `pre-open`/`regular-session`의 `--execute`를 네트워크 시작 전에 차단
  - system clock 기준 시각을 앞선 probe 시작 시각이 아니라 quote 직전 UTC로 분리
- `scripts/run_phase1b_readonly_observation.py`
  - 기본: 네트워크 없는 preflight
  - `--execute`: 승인된 작업에서만 제한된 read-only 관측
  - 출력 경로를 preflight, blocked attempt, actual observation으로 분리
- `scripts/run_phase1b_readonly_observation.sh`
  - 기존 dispatcher에 등록한 repo-local wrapper
- `tests/test_phase1b_readonly_observation.py`
  - 자격정보 누출 방지
  - 주문 메서드 호출 부재
  - token/client 생성 실패 sanitization
  - preflight 차단 시 profile/account/quote 호출 0회
  - 성공 시 제한된 호출 횟수
  - CLI 기본 실행의 네트워크 0회 보장

## 3. 제한된 실행의 정확한 범위

`--execute`가 허용하는 네트워크 작업은 아래 네 종류뿐이다.

1. live token refresh 1회
2. paper account snapshot 최대 1페이지
3. live account snapshot 최대 1페이지
4. live current price를 이용한 system clock 확인 1회

`pre-open`과 `regular-session`은 `protected_market_session`으로 먼저 차단한다. token 단계가 실패하면 account/current-price는 실행하지 않는다. live account가 실패하면 live clock은 실행하지 않는다. 주문·취소 함수 호출은 항상 0건이다.

위 목록은 wrapper가 직접 계획하는 업무 단계다. 실제 전송 요청 수는 token manager의 cache 상태와 인증 처리까지 패킷 단위로 계측한 값이 아니므로, wire-level 요청 횟수로 해석하지 않는다.

산출물에는 raw response, token, app key/secret, 계좌번호, 상품코드를 넣지 않는다.

## 4. 실제 사전검사 결과

2026-07-10 23:59 KST에 기본 사전검사를 다시 실행했다.

- 실행 모드: `network-free-preflight`
- 네트워크 호출: 0회
- 통과:
  - paper mode 유지
  - live 주문 비활성
  - paper 계좌 자격정보 존재
  - 주문 메서드 미노출
- 차단:
  - live quote 자격정보 미준비
  - live account 자격정보 미준비
- 보고서:
  - `runtime-data/reports/live-readiness/phase1b/latest-phase1b-readonly-preflight.json`

따라서 Phase 1b는 구조와 사전검사는 완료됐지만 실제 live account 관측은 아직 통과하지 않았다. 이번 작업에서는 KIS live 네트워크를 호출하지 않았다. 자격정보가 없는 상태에서 `--execute` 경로도 실행해 봤으며 `execution_started=false`와 `phase1b_preflight_blocked`로 별도 attempt 파일에 안전하게 종료됐다.

## 5. 검증

- 관련 단위 테스트: 34개 통과
- 전체 unittest: 480개 통과
- 전체 pytest: 480개 + subtest 67개 통과
- Python compileall: 통과
- bash parse: 통과
- 기본 CLI preflight: 네트워크 0회 재현
- 실전 주문/취소, active model/gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, NAS 백업: 변경 또는 실행하지 않음
- E1/E5 전 실험 동결: 유지

## 6. Codex 비판적 의견

이 wrapper는 Phase 1b를 통과시키는 기능이 아니라, Phase 1b 증거를 잘못 만드는 방법을 줄이는 기능이다. 실전 자격정보와 실제 응답이 없으므로 account shape, T+2 필드, 예수금 의미, live HTTP Date는 아직 검증되지 않았다.

또한 paper/live shape가 같다는 결과가 나와도 금액의 의미와 정산 규칙까지 같다는 뜻은 아니다. shape 비교는 parser 호환성 증거이고, 회계 의미의 정합성 증거는 아니다. 또한 현재 operation budget은 보장하지만 wire-level 요청 수 telemetry까지 구현한 것은 아니다.

`--execute`를 12시간 자동화나 watcher에 넣는 것은 권장하지 않는다. 자격정보 준비와 해당 작업 승인 뒤 1회 실행하고, 이후에는 freshness가 필요한 probe만 별도 운영 기준으로 관리하는 편이 안전하다.

## 7. 다음 진행 방향

1. 계좌 소유자가 WSL 대화형 입력으로 live 조회 자격정보를 준비한다.
   - `./scripts/restore_kis_env_interactive.sh --trading-mode live --include-account-fields --read-only-preparation`
2. Codex가 기본 preflight를 다시 실행해 차단 0건을 확인한다.
3. 승인된 범위에서 `./scripts/run_phase1b_readonly_observation.sh --execute`를 1회 실행한다.
4. paper/live account shape, live system clock, 주문 호출 0건을 함께 판정한다.
5. 실제 증거가 생기면 cowork에게 안전 경계와 응답 해석을 리뷰 요청한다.
6. paper/KIS mismatch 4종목은 다음 거래일 장후 새 단일 호출 정책으로 1회만 재확인한다.
7. E1/E5 모델 라운드는 2026-07-20 장후까지 동결한다.
8. sanitized NAS drill은 사용자가 명시적으로 “NAS 백업/드릴 실행”을 지시한 작업에서만 진행한다.

## 8. cowork 리뷰가 필요한 시점

현재는 코드 경계와 회귀 테스트가 명확해 즉시 리뷰할 필요가 낮다. 실제 Phase 1b live observation JSON과 paper/live shape 비교 결과가 생성된 시점에 리뷰하는 것이 권장안이다. 그때는 “호출이 안전했는가”와 “응답 차이를 올바르게 해석했는가”를 함께 검토해야 한다.
