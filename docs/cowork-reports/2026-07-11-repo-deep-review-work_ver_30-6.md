# E1/E5 사전등록 실행 준비와 장후 운영 마감 work_ver 30-6

## 1. 목적

review_ver_27은 2026-07-18 이후 첫 거래일 장후에 E1 신호 재측정과 E5 역발상 관찰을 한 라운드로 수행하도록 고정했다. 기존 상태는 일정과 판정 기준이 문서에만 있었고, 날짜 범위를 잘못 넣거나 개별 명령을 빠뜨릴 수 있었다.

이번 작업은 실제 결과를 미리 만들지 않고, 예정일 전 실행을 차단하는 단일 실행기와 회귀 테스트를 완성하는 데 목적이 있다. 동시에 늦어진 장후 운영 확인을 마감했다.

## 2. 장후 운영 확인과 조치

- 현재 장 상태: `weekend`
- live runtime: 정상 정지
- watchdog/dashboard/startup launcher: 정상
- 장후 ML: `status=ok`, `completed_at=2026-07-10 16:17:58 +0900`, `mode=quick-live-train`
- label refresh: `status=ok`, `completed_at=2026-07-10 16:50:42 +0900`
- active model: `baseline-h15-v1` 유지
- challenger: `keep_active`, `promotion_applied=false`, gate `needs_review`
- top challenger: 3분류 정확도 `0.314705`, 매수 적중률 `0.75`, 누적 순수익률 합 `+5.444049%p`, 거래 `4건`; 표본 부족이 우선이다.
- hold-rescue paper replay를 장외에 갱신했다. threshold `0.40`은 eligible `161` lots, 적용 `37` lots, `delta_cash_sum=-26,387원`으로 계속 `diagnostic_only_no_hold_rescue_candidate`다.
- runtime report와 dashboard snapshot을 갱신했다. dashboard는 `http://127.0.0.1:8765`에서 정상 응답한다.
- paper/KIS mismatch는 주말에 KIS endpoint를 반복 호출하지 않았다. 2026-07-10의 4종목 divergence 증거를 유지하며 다음 거래일 장후 1회 재확인한다.

장후 ML과 label refresh가 이미 정상 완료돼 있어 중복 학습은 실행하지 않았다.

## 3. 구현

### E1 날짜 고정 재측정

`scripts/summarize_signal_ic.py`에 아래를 추가했다.

- `--start-date`, `--end-date`
- `probability_flat` 전체 daily IC
- 후보 3건의 같은 종목·같은 방향·`abs(t_stat) >= 2.0` 재현성 판정
  - `005380 probability_up`, prior positive
  - `035420 probability_down`, prior negative
  - `105560 probability_down`, prior positive
- `105560`의 p_flat daily IC
- `105560`의 p_down/p_up 일별 IC pair와 Pearson 관계
- 사전등록 고정 구간 여부와 자동 정책 변경 금지 필드

### E5 날짜 고정 관찰

`scripts/summarize_lightgbm_defensive_shadow.py`에 아래를 추가했다.

- `--start-date`, `--end-date`
- E5 단독 측정에서 early-exit lifecycle을 읽지 않는 `--skip-early-exit`
- 요청 구간과 실제 포함 구간 기록

### 단일 fail-closed 실행기

신규 명령:

```bash
./scripts/run_preregistered_e1_e5_round.sh --execute
```

안전 경계:

- 기본 실행은 dry-run이다.
- `2026-07-20 15:30 KST` 이전에는 `--execute`도 snapshot 생성 전에 차단한다.
- `pre-open`과 `regular-session`에도 차단한다.
- `latest-post-close-label-refresh.json`이 `status=ok`, `maintenance_date>=2026-07-20`, `completed_at` 존재 조건을 만족하지 않으면 차단한다.
- 허용 시 기본적으로 D드라이브 research snapshot을 만들고 read-only로 측정한다.
- 고정 구간은 `2026-07-04~2026-07-18`, horizon은 h15, E5 threshold는 `0.40`이다.
- E1과 E5를 같은 snapshot·같은 라운드에서 수행한다.
- 성공한 완료 파일이 있으면 중복 실행하지 않는다. 표본 부족이면 완료로 잠그지 않아 장외 재측정이 가능하다.
- 학습, KIS 네트워크, 주문/취소, 정책, active model, gate 변경은 0건이다.

2026-07-11 실제 dry-run은 `before_preregistered_not_before`로 차단됐고, 신규 research snapshot과 실제 E1/E5 결과 파일은 생성되지 않았다.

## 4. 검증

- E1/E5 관련 단위 테스트: `9 tests OK`
- 전체 unittest: `495 tests OK`
- 전체 pytest: `495 passed, 67 subtests passed`
- Python compileall: 통과
- 새 bash wrapper parse/help: 통과
- `git diff --check`: 통과
- 생성 산출물 dry-run 확인 후 `.tmp-tests`/`__pycache__` 92개, 약 `2.28GB`를 전용 cleanup wrapper로 정리했다. `runtime-data/`, 운영 DB, 모델, 수집 데이터, `app/risk/`, `.tmp-tests/codex-ops/`는 삭제 대상이 아니었다.

추가 회귀 검증:

- 2026-07-03 행은 고정 구간에서 제외된다.
- 합성 E1 후보 3건은 각각 등록된 종목·방향으로만 판정된다.
- `105560` p_flat 및 p_down/p_up 관계가 JSON/Markdown에 남는다.
- E5 early-exit은 날짜 고정 관찰에서 실행되지 않는다.
- dry-run은 D드라이브 snapshot을 생성하지 않는다.

## 5. Codex 의견

이 작업은 단순 편의 기능이 아니라 필요한 누락 보완이다. 문서에 “07-20 장후 실행”만 적어둔 상태에서는 날짜 범위, 후보 방향, `105560` 보합 확률, E5 threshold 가운데 하나를 빠뜨릴 가능성이 있었다. 실행기와 테스트로 기준을 잠근 지금부터 예약 작업을 재현 가능하다고 볼 수 있다.

아직 E1/E5 결과는 없다. 이번 구현 통과를 신호 품질 개선이나 역발상 가설 재현으로 해석하면 안 된다.

실측 해석은 아래처럼 제한해야 한다.

1. E1 후보가 같은 방향으로 재현되지 않으면 해당 종목 후보를 폐기한다.
2. E5가 두 번째 구간에서도 `excess>0`, `z>=1.6449`이면 역선별 가설만 수립한다.
3. E5 두 번째 구간이 미통과면 역발상 가설을 폐기한다.
4. E5가 통과해도 주문 반전이나 threshold 변경은 금지한다. 정책 검토에는 세 번째 독립 구간과 계좌 소유자의 명시 승인이 추가로 필요하다.

## 6. 다음 방향

1. 다음 거래일 장후에 paper/KIS mismatch 4종목을 single-call wrapper로 1회 재확인한다.
2. 다음 정규장에는 dashboard/watchdog/live runtime 장시간 상태를 read-only로 관찰한다.
3. Phase 1b actual read-only는 live 조회 자격정보 준비 뒤 통합 cycle을 장외에 1회 실행한다.
4. 2026-07-20 장후 label refresh 완료 뒤 E1/E5 단일 실행기를 1회 실행한다.
5. 실제 E1/E5 결과가 나온 work_ver에서 cowork 리뷰를 요청한다.

다음 cowork 리뷰는 지금이 아니라 실제 2026-07-20 E1/E5 결과가 나온 시점이 가장 효율적이다.

## 7. 변경하지 않은 항목

- 실전 주문/취소
- `app/risk/`
- `config/`
- `VERSION`
- `ALLOW_LIVE_ORDERS`
- active model/gate/threshold
- 신규 모델 학습 실험
- NAS 백업
