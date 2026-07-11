# Repository Deep Review Follow-up work_ver_30-8

## 1. 작업 목적

- Phase 1b 실전계좌 read-only 자격정보 blocker를 해소하고 bounded 관측을 실제 실행한다.
- 실제 주문 경로는 열지 않고 token/account shape/system clock만 검증한다.
- 사용자 입력 자격정보는 로컬 `.env`에만 두고 값·계좌번호·잔액·원문 응답을 산출물에 남기지 않는다.

## 2. 자격정보와 사전검사

- `restore_kis_env_interactive.sh --trading-mode live --include-account-fields --read-only-preparation`으로 live 조회 자격정보 네 항목을 준비했다.
- 최초 PowerShell GUI launcher는 `bash -lc` 뒤 인수를 script에 전달하지 못해 잘못된 `PAPER` 프롬프트를 열었다. 저장 전에 종료하고 preflight로 live 값 미저장을 확인했으며, `wsl --exec /bin/bash <script> <args...>` 직접 인수 방식으로 다시 열어 `LIVE` 프롬프트를 확인했다.
- network-free preflight 결과:
  - `live_quote_credentials_present=true`
  - `live_account_credentials_present=true`
  - `paper_account_credentials_present=true`
  - `paper_mode_preserved=true`
  - `live_orders_disabled=true`
  - `readonly_order_surface_absent=true`
- 자격정보 값은 출력하지 않았고 network call과 order method call은 모두 0이었다.

## 3. Phase 1b 실제 제한 관측

- 실행: `./scripts/run_phase1b_readiness_cycle.sh --execute --refresh-dashboard`
- 시각/장 상태: 2026-07-11 09:11 KST, weekend/off-session.
- 실행 모드: `bounded-live-readonly`.
- 네트워크 작업 4회:
  - live token refresh 1회.
  - paper account snapshot 최대 1페이지.
  - live account snapshot 최대 1페이지.
  - live current-price HTTP Date 기반 system clock 1회.
- 주문 메서드 호출: 0회.
- raw response, 계좌 식별자, 잔액 값 저장: 없음.

## 4. 결과

- token refresh: `ok`.
- live account snapshot: `ok`, position row 1개, summary row 1개.
- paper account snapshot: `ok`, position row 3개, summary row 1개.
- paper/live shape comparison: 필수 필드 누락 0, 타입 오류 0, shape difference 0.
- system clock: `ok`, skew `0.533151초`, 허용 상한 `2초`.
- Phase 1b readiness: `status=ok`, `passed=true`.
- dashboard snapshot과 API도 같은 결과로 갱신됐다.

## 5. 비차단 실패 해석

- `market_status=false`: 2026-07-10 수동 템플릿의 tradable 확인이 완료되지 않았고 현재는 다음 날 주말이라 fresh 증거가 아니다.
- `kill_switch=false`: 상태 파일이 stale이다.
- 두 실패는 조회 전용 Phase 1b의 optional check라 이번 관측을 차단하지 않는다.
- Phase 2/3 live-submit에서는 optional이 아니며 fresh market status와 유효한 kill switch 상태가 없으면 계속 fail-closed로 차단해야 한다.
- `ws_recovery`는 이번 Phase 1b에서 synthetic fault injection 증거다. 실제 주문 단계에서는 real evidence가 별도로 필요하다.

## 6. 자격정보 파일 보안 보강

- `.env`가 git ignore 상태임을 확인했다.
- 실제 파일 권한이 기존 `755`였으므로 즉시 `600`으로 제한했다.
- 이후 복구에서도 재발하지 않게 `restore_kis_env_interactive`가 입력 전과 저장 후 `chmod 600`을 실행하도록 수정했다.
- 테스트에 `.env` mode `0600` assertion을 추가했다.

## 7. 검증

- `bash -n scripts/script_dispatch.sh`: 통과.
- `python3 -m unittest tests.test_kis_env_restore_script -v`: 2 tests OK.
- 전체 unittest: `498 tests OK`.
- 전체 pytest: `498 passed, 67 subtests passed`.
- 전용 cleanup wrapper로 테스트 임시 산출물 85개, 89,897,638 bytes를 정리했고 `.tmp-tests/codex-ops`와 `app/risk`는 보존했다.
- Phase 1b cycle 6개 step 모두 `ok`: premarket, synthetic WS, observation, fixture, readiness, dashboard refresh.
- `.env` 현재 mode: `600`, git ignore 확인.

## 8. Codex 비판적 의견

Phase 1b의 핵심 질문은 실전 주문 가능 여부가 아니라 실전 자격정보로 조회 전용 client가 실제 응답을 받고, paper와 다른 계좌에서도 내부 계약이 깨지지 않는지였다. 이번 결과로 token, account shape, clock의 기술적 blocker는 해소됐다. 특히 live 계좌 position row 수가 paper와 달라도 shape equality가 아니라 계약 필드와 타입을 비교하도록 설계한 것이 맞았고 실제 비교도 통과했다.

다만 `passed=true`를 실전 운용 준비 완료로 확대 해석하면 안 된다. 계좌 정합성은 아직 `1/10`이고 mismatch 4종목이 남아 있으며, buy-avoid/rescue/hold-rescue는 주문 정책 후보가 아니다. 실제 WebSocket recovery evidence, 당일 market status, kill switch OFF, 비용 차감 양수 기대값도 없다. 따라서 Phase 2로 바로 이동하는 것은 근거가 부족하다.

이번에 발견한 `.env=755`는 기능 테스트만으로 놓치기 쉬운 운영 보안 결함이었다. 즉시 권한을 낮추는 데서 끝내지 않고 복구 스크립트와 회귀 테스트에 강제한 것이 필요하고 타당한 조치다.

## 9. 다음 방향

1. Phase 1b live token/account shape/system clock blocker는 완료로 닫는다.
2. 다음 거래일 장후 paper/KIS mismatch를 1회 재측정하고 10거래일 history 자동 누적을 확인한다.
3. 2026-07-20 장후에는 사전등록된 E1/E5 한 라운드만 실행한다.
4. 그 전에는 신규 threshold/EV tuning, 종목별 주문 정책, h60 정책, active model/gate 변경을 하지 않는다.
5. Phase 2는 Phase 0 정합성, 전략 기대값, real WS recovery, fresh market status, valid kill switch가 모두 충족된 뒤 별도 승인으로 시작한다.

## 10. 다음 cowork 리뷰 시점

- 이번 Phase 1b read-only 결과는 계약 차이나 안전 실패가 없어 즉시 cowork 재검토가 필수는 아니다.
- 다음 리뷰가 유용한 시점은 다음 거래일 mismatch 원인 분류가 바뀌거나, 2026-07-20 E1/E5 결과가 생성되거나, Phase 2 진입조건을 실제로 판정할 때다.

## 11. 안전 확인

- `TRADING_MODE=paper` 유지.
- `ALLOW_LIVE_ORDERS=false` 유지.
- 실전 주문·취소·계좌 align 없음.
- `app/risk/`, `config/`, `VERSION`, active model, gate, threshold 변경 없음.
- NAS 백업 없음.
