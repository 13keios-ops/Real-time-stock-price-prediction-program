# Repository Deep Review Follow-up work_ver_30-7

## 1. 작업 범위

- 이전 `work_ver_30-6`에서 준비한 2026-07-20 장후 E1/E5 사전등록 라운드는 그대로 유지했다.
- 이번 후속 작업은 지연된 2026-07-10 장후 상태를 마감하고, Phase 0 진행판에 남아 있던 `누적 paper-vs-broker 자동 집계와 dashboard 노출` 공백을 실제 구현으로 닫는 데 한정했다.
- 신규 ML 실험, E2/E3 threshold/EV tuning, 종목별 주문 정책, h60 정책, active model/gate 변경은 하지 않았다.

## 2. 장후 운영 상태

- 현재 시각은 주말 장외다.
- live runtime: `stopped`, session `weekend`.
- runtime watchdog: `running`, heartbeat fresh, errors 없음.
- dashboard: `http://127.0.0.1:8765`, server/API 모두 응답.
- 2026-07-10 post-close ML: `status=ok`, `completed_at=16:17:58 KST`, `mode=quick-live-train`.
- 2026-07-10 label refresh: `status=ok`, `completed_at=16:50:42 KST`.

## 3. 모델 및 rescue/avoid 판정

- active model은 `baseline-h15-v1`로 유지됐다.
- challenger 판정은 `keep_active`, `promotion_applied=false`다.
- top challenger 수치는 3분류 정확도 `0.314705`, 매수/거래 적중률 `0.75`, 누적 순수익률 합 `+5.444049%p`, 거래 `4건`이다.
- 4건 수익 표본은 승격 판단에 너무 작으므로 정확도와 함께 보더라도 승격 근거가 아니다.

### buy-avoid

- 관측 구간: 2026-06-11 09:15 ~ 2026-07-10 14:59.
- 연결 표본: `33,007`.
- threshold `0.40`: skip `9,002`, raw net delta `+846.0341%p`.
- random-control 비교: excess `+238.2658%p`, z-score `+4.1266`, verdict `filter_worse_than_random_p95`.
- 이 리포트의 부호 규칙에서 excess가 음수여야 무작위보다 나쁜 매수를 더 잘 골라낸다. 현재 양수이므로 실제 필터는 무작위 회피보다 나쁜 선택이다.
- 결론: 데이터 누적은 계속하지만 주문 정책이나 threshold 채택 근거로 쓰지 않는다.

### buy-rescue

- Cybos proxy 판정은 `buy_avoid_candidate_only`다.
- 고정 grid에서 buy-rescue가 통과하지 못했고, runtime baseline replay는 Cybos bar에 orderbook 피처가 없어 재현되지 않았다.
- KIS live no-trade ledger는 아직 없으므로 live buy-rescue 실패로 확정하지 않는다.

### hold-rescue

- paper-only lifecycle replay: eligible `161 lot`.
- threshold `0.40`: 적용 `37 lot`, `delta_cash_sum=-26,387원`.
- 판정: `diagnostic_only_no_hold_rescue_candidate`.
- 결론: 우선순위를 낮추고 주문 정책에 반영하지 않는다.

## 4. 구현한 누적 정합성

추가:

- `app/services/paper_reconciliation_history.py`
- `scripts/summarize_paper_reconciliation_history.py`
- `tests/test_paper_reconciliation_history.py`

연결:

- 실제 paper/KIS reconciliation이 끝날 때 sanitized 일별 기록을 자동 저장한다.
- 일별 파일: `runtime-data/reports/reconciliation/paper-account-history/YYYY-MM-DD.json`.
- 최신 집계: `runtime-data/reports/reconciliation/latest-paper-account-history.json/.md`.
- dashboard payload와 계좌 화면에 `10거래일 누적 정합성`, `거래일별 정합성` 카드를 추가했다.

유효 거래일 기준:

- `post-close`.
- KIS 브로커 계좌 조회 성공.
- 브로커 제출 이력 존재.
- 계좌 식별자와 KIS 원문 응답은 이력에 저장하지 않음.

판정:

- 유효 기록 없음: `no_history`.
- 불일치 없음, 10일 미만: `insufficient_history`.
- 한 날이라도 불일치: 거래일 수와 무관하게 `needs_review` 우선.
- 최근 유효 10거래일 모두 정합: `ready`.

## 5. 실제 최초 기록

- 기존 2026-07-10 장후 reconciliation을 네트워크 호출 없이 backfill했다.
- 현재 `1/10`, 정합 `0일`, 불일치 `1일`, 연속 정합 `0일`.
- mismatch 4종목: `035420`, `086520`, `105560`, `247540`.
- 예수금 절대 차이: `714,840.96원`.
- 총자산 절대 차이: `1,346,940.96원`.
- 상태는 `needs_review`다.

## 6. 검증

- 관련 테스트: 30개 통과.
- 전체 unittest: `498 tests OK`.
- 전체 pytest: `498 passed, 67 subtests passed`.
- runtime report 재생성 완료.
- dashboard snapshot 재생성 완료, server/API 응답 확인.
- 전체 검증 후 전용 cleanup wrapper로 테스트 임시 산출물 85개, 약 142.2MB를 정리했다. `.tmp-tests/codex-ops`와 `app/risk`는 보존했다.
- 구현 후 실제 report와 dashboard JSON에서 `days_available=1`, `required_days=10`, `latest_mismatch_count=4`를 확인했다.

## 7. Codex 의견

이번 공백은 단순 대시보드 편의 기능이 아니라 Phase 0 통과 증거의 자동성 문제였다. 최신 한 번의 정합 결과만 보는 구조로는 10거래일 연속 안정성을 증명할 수 없고, 사람이 과거 파일을 골라 합치면 판정이 흔들릴 수 있다. 따라서 일별 sanitized 증거와 고정 10일 집계를 reconciliation 경로에 직접 연결한 방향이 맞다.

다만 구현 완료를 Phase 0 완료로 읽으면 안 된다. 현재 첫 증거부터 4종목 불일치이며, 계좌 snapshot과 order/fill 원장 divergence가 해소되지 않았다. 자동 집계는 문제를 닫은 것이 아니라 앞으로 문제를 숨기지 않고 측정할 수 있게 만든 것이다.

모델 쪽에서도 raw buy-avoid delta만 보면 좋아 보이지만 random-control에서 반대 결론이 나온다. 현 단계에서 LightGBM은 주문 필터가 아니라 실패 가설을 검증하는 shadow 진단 도구로 두는 것이 타당하다.

## 8. 다음 방향과 cowork 리뷰 시점

1. 다음 거래일 장후 `recheck_paper_kis_mismatch.sh`를 한 번만 실행한다.
2. 성공한 reconciliation이 일별 history에 자동 누적되는지 확인한다.
3. 현재 4종목 divergence가 유지되면 자동 align하지 않고 account snapshot과 order/fill 원장 원인을 계속 분리한다.
4. 2026-07-20 장후에는 기존 사전등록 범위만으로 E1/E5 한 라운드를 실행한다.
5. 그 전에는 신규 threshold/EV/model/order 정책 실험을 늘리지 않는다.

다음 cowork 리뷰가 유용한 시점은 둘 중 먼저 오는 때다.

- 다음 거래일 장후 4종목 mismatch의 원인 분류가 바뀌거나 자동 이력 연결에 오류가 발견될 때.
- 2026-07-20 E1/E5 사전등록 라운드가 실제 완료됐을 때.

현재 구현 자체는 전체 회귀 테스트를 통과했고, 즉시 추가 리뷰가 없더라도 안전하게 다음 거래일 증거를 기다릴 수 있다.

## 9. 안전 확인

- KIS 추가 네트워크 호출 없음.
- 계좌 align 없음.
- 실전 주문/취소 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, active model, gate, threshold 변경 없음.
- NAS 백업 없음.
