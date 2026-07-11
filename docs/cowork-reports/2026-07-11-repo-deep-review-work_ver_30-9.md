# Repository Deep Review Follow-up work_ver_30-9

## 1. 작업 목적

- Phase 0 paper/KIS 계좌 정합성 `1/10`과 mismatch 4종목을 실제 증거로 재확인한다.
- 주말을 유효 거래일로 잘못 세지 않고 다음 거래일 장후 재확인을 자동화한다.
- 다음 KIS 주문/체결 조회에서 mismatch 원인을 더 좁힐 수 있는 sanitized 진단값을 준비한다.

## 2. 현재 증거

- 최신 유효 거래일: 2026-07-10 장후.
- 누적: `1/10`, 정합 `0일`, 불일치 `1일`.
- mismatch: `035420`, `086520`, `105560`, `247540` 4종목.
- 현금 차이: `714,840.9593원`.
- 총자산 차이: `1,346,940.9593원`.
- 네 종목 모두 로컬 position 수량과 현재 KIS order-fill 원장 순수량은 같다.
- 다른 값은 KIS 계좌 snapshot 수량이므로 현재 root cause scope는 `kis_account_snapshot_vs_order_fill_ledger_divergence`다.

## 3. 주말 재확인 결과

- `./scripts/recheck_paper_kis_mismatch.sh` 실행은 `non_trading_day`로 차단됐다.
- KIS 네트워크 호출, reconciliation 기록, history 분모 증가 모두 없었다.
- 따라서 `2/10`이 아니라 `1/10` 유지가 정확하다.
- 차단 JSON 뒤 dispatcher가 `No bash implementation registered`를 잘못 출력하던 문제를 발견해 top-level 전용 분기로 옮겼다.
- wrapper가 비정상 보조 메시지 없이 구조화 JSON만 반환하는 subprocess 회귀 테스트를 추가했다.

## 4. mismatch 원인 분리 보강

broker paper sync와 mismatch trace에 아래 count-only 진단을 추가했다.

- `order_fill_lookback_days`
- `broker_rows_returned`
- `broker_rows_linked_to_submissions`
- `broker_rows_unlinked_to_submissions`
- `exact_matched_orders`
- `fallback_matched_orders`
- `ambiguous_fallback_key_count`

계좌번호, 주문번호, 토큰, raw response는 기록하지 않는다. 다음 거래일 해석은 다음 기준으로 사전 고정한다.

1. unlinked 행이 있으면 수동/외부 주문 또는 로컬 제출 원장 누락 후보다.
2. fallback/ambiguous 값이 있으면 날짜 경계 또는 주문번호 보조 매칭 문제를 먼저 본다.
3. 세 값이 모두 0이고 로컬 수량과 order-fill 순수량도 같으면 계좌 snapshot 원천 차이 가능성이 더 커진다.
4. 어떤 결과도 자동 align이나 `SyncInitialCash`로 연결하지 않는다.

## 5. 다음 거래일 자동 실행

- Windows 작업 스케줄러 `RealTimeStockRuntime_PostCloseOps`:
  - 다음 실행 2026-07-13 16:40 KST.
  - 최근 실행 결과 0.
  - 장후 학습, label refresh, paper dual-account reconciliation, dashboard/local setup을 실행한다.
- Codex 운영 자동화:
  - 20:25 KST 장후 체크에서 당일 유효 history를 먼저 확인한다.
  - 당일 유효 기록이 있으면 broker sync를 중복 호출하지 않는다.
  - 실제 거래일 장후인데 기록이 없을 때만 통합 recheck를 한 번 실행한다.
  - mismatch trace만 오래됐으면 KIS 호출 없이 offline trace만 갱신한다.
  - `--allow-non-trading-day`, `AlignToBroker`, `SyncInitialCash`는 사용하지 않는다.

## 6. 검증

- 정합성/broker sync/dashboard 관련 51개 테스트: 통과.
- 전체 unittest: `499 tests OK`.
- 전체 pytest: `499 passed, 67 subtests passed`.
- `bash -n scripts/script_dispatch.sh`: 통과.
- `git diff --check`: 통과.
- 전용 cleanup wrapper: 테스트 임시 산출물 85개, 111,523,766 bytes 정리. `.tmp-tests/codex-ops`와 `app/risk` 보존.

## 7. Codex 비판적 의견

이번 단계에서 주말 재실행으로 숫자를 늘리는 것은 진행이 아니라 증거 오염이다. `1/10`을 유지한 것이 맞다. 더 중요한 것은 월요일에 같은 mismatch가 반복됐을 때도 단순히 "또 다르다"고 보고하지 않고, KIS 조회 행이 로컬 제출 원장 밖에서 생겼는지와 날짜 없는 보조 매칭이 개입했는지를 구분하는 것이다.

현재 증거만으로 KIS 계좌 snapshot이 잘못됐다고 확정할 수는 없다. order-fill lookback 밖의 오래된 주문, 수동/외부 주문, 로컬 제출 기록 누락 가능성도 남아 있다. 새 진단값이 이 세 가능성을 좁히지만, 계좌 snapshot과 KIS 주문/체결 원장 자체가 계속 다르면 KIS 모의계좌 원천 차이를 문의할 수 있는 sanitized 근거 묶음이 필요하다.

## 8. 다음 방향과 보류 기준

- 계속 진행: 2026-07-13 장후 유효 reconciliation 생성과 count-only 진단 확인.
- 보류: 주말/휴장일 강제 실행, 반복 endpoint 호출, 계좌 자동 align, 초기 현금 재동기화.
- mismatch가 0이면 그 날을 첫 정합일로 누적하되 과거 mismatch 1일은 지우지 않는다.
- mismatch가 유지되고 unlinked/fallback/ambiguous가 0이면 account snapshot 원천 차이 검토를 강화한다.
- unlinked 또는 ambiguous가 나오면 자동 조치 없이 해당 원장 경로를 먼저 추적한다.

## 9. 다음 cowork 리뷰 시점

- 2026-07-13 장후 새 유효 증거가 생성된 뒤가 가장 유용하다.
- 특히 root cause scope가 바뀌거나 unlinked/fallback/ambiguous 진단이 0이 아니면 즉시 리뷰 가치가 있다.
- 결과가 기존과 동일하고 새 계약 문제가 없으면 10거래일 checkpoint 또는 2026-07-20 E1/E5 라운드까지 묶어 리뷰할 수 있다.

## 10. 안전 확인

- 실전/모의 주문·취소 없음.
- KIS 계좌 align, `SyncInitialCash` 없음.
- `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false` 유지.
- `app/risk/`, `config/`, `VERSION`, active model, gate, threshold 변경 없음.
- NAS 백업 없음.
