# 2026-07-05 buy-avoid validation verification work_ver_26

## 1. 이번 입력과 결론

- 입력 리뷰: `docs/cowork-reports/2026-07-05-buy-avoid-validation-verification-review_ver_25.md`
- P0 지시:
  - E6 cost/horizon 을 KIS live / Cybos source 별로 분리 재계산한다.
  - 신규 테스트를 포함한 전체 `pytest` 결과를 보고한다.
  - E6 분리 결과가 나오기 전까지 E6 분리 전에는 h15 비용 구조 결론을 확정하지 않는다.
- 결론:
  - review_ver_25의 지적은 타당했다.
  - 기존 E6 전체 h15 표본은 Cybos historical 이 99% 이상을 차지해 KIS live 정책 결론으로 직접 쓰면 안 됐다.
  - source split 후 KIS live 근사 h15는 `median_abs=0.361446%`로 `2 * trade_cost_pct=0.216%`를 넘었다.
  - 따라서 h15 비용 구조 확정 배제 결론은 폐기한다. 현재 병목은 E6 비용 구조 확정 문제가 아니라 E1 신호 정보량 부족이다.

## 2. 구현 변경

- 변경 파일:
  - `scripts/summarize_cost_horizon_diagnostics.py`
  - `tests/test_cost_horizon_diagnostics.py`
  - `docs/Current-Implementation.md`
  - `docs/Execution-Plan.md`
  - `docs/logbook.md`
- 산출물:
  - `runtime-data/reports/research/latest-cost-horizon-diagnostics.json`
  - `runtime-data/reports/research/latest-cost-horizon-diagnostics.md`

### 2.1 Source split 방식

현재 DB schema 확인 결과 `feature_labels`와 `curated_minute_bars`에 `source` 컬럼이 없다. 따라서 review_ver_25 지시에 따라 근사 분리했다.

| source_key | 역할 | 분리 기준 |
|---|---|---|
| `all` | 참고 전체 표본 | 전체 `feature_labels` distinct row |
| `kis_live` | 정책 판단 표본 | serving runtime 심볼 + `event_time >= 2026-06-11` |
| `cybos_historical` | 참고 과거 표본 | `event_time < 2026-06-11` |
| `kis_live_baseline_buy_join` | baseline buy 신호 진단 표본 | `serving_trade_signals side=buy allowed=1`과 `feature_labels` join |

KIS live 근사에 사용된 runtime 심볼은 다음 10개다.

`000660`, `005380`, `005930`, `035420`, `068270`, `086520`, `105560`, `207940`, `247540`, `373220`

Codex 의견: source 컬럼이 없는 이상 이 분리는 엄밀한 원천 분리가 아니라 운영 판단용 근사다. 다만 review_ver_25가 지적한 “Cybos 지배 표본을 KIS live 결론으로 오독하는 문제”는 이번 분리로 해소됐다. 다음 schema 개선 후보는 label 생성 시 source lineage 를 함께 저장하는 것이다.

## 3. E6 source split 결과

`python3 scripts/summarize_cost_horizon_diagnostics.py --horizons 15 30 60` 재실행 결과다.

| source | horizon | rows | share_all | median_abs | mean_abs | below_2x_cost |
|---|---:|---:|---:|---:|---:|---|
| all | 15 | 6,281,164 | 100.00% | 0.189394 | 0.274966 | true |
| kis_live | 15 | 61,527 | 0.98% | 0.361446 | 0.524817 | false |
| cybos_historical | 15 | 6,219,637 | 99.02% | 0.188324 | 0.272494 | true |
| kis_live_baseline_buy_join | 15 | 64,173 | 1.02% | 0.311365 | 0.458613 | false |
| all | 60 | 5,527,234 | 100.00% | 0.341880 | 0.507622 | false |
| kis_live | 60 | 54,215 | 0.98% | 0.717274 | 1.039417 | false |
| cybos_historical | 60 | 5,473,019 | 99.02% | 0.339847 | 0.502354 | false |
| kis_live_baseline_buy_join | 60 | 56,819 | 1.03% | 0.615174 | 0.918086 | false |

`h30`은 기존과 동일하게 label 이 없어 `no_labels`다.

### 3.1 판정 변경

- 이전 work_ver_25 표현: 전체 h15 `median_abs=0.189394`가 비용 기준보다 작으므로 h15 비용 구조가 불리하다.
- review_ver_25 반영 후 정정:
  - 전체 h15 경고는 사실이지만, 그 전체 표본은 Cybos historical 이 `99.02%`라 KIS live 정책 결론으로 확정하면 안 된다.
  - 정책 판단 표본인 KIS live 근사 h15는 `decision=kis_live_h15_median_move_covers_2x_cost`다.
  - 따라서 E6는 h15를 즉시 배제하는 근거가 아니다.
  - 다만 E1 Signal IC가 `signal_quality_insufficient`였으므로 E2/E3 threshold/EV 필터 튜닝은 계속 보류한다.

Codex 의견: 이번 결과는 좋은 소식과 나쁜 소식이 섞여 있다. 좋은 소식은 KIS live h15 자체의 변동폭이 비용을 넘을 가능성이 확인되어 “시간지평이 구조적으로 죽었다”는 결론은 성립하지 않는다는 점이다. 나쁜 소식은 모델 신호가 그 변동을 유리하게 고르는 능력, 즉 E1이 아직 부족하다는 점이다. 그래서 다음 방향은 h15 포기가 아니라 신호 품질 개선과 source lineage 보강이다.

## 4. 테스트와 검증

| 검증 | 결과 |
|---|---|
| `python3 -m py_compile scripts/summarize_cost_horizon_diagnostics.py tests/test_cost_horizon_diagnostics.py` | 통과 |
| `python3 -m pytest tests/test_cost_horizon_diagnostics.py -q` | `3 passed` |
| `python3 scripts/summarize_cost_horizon_diagnostics.py --horizons 15 30 60` | 통과, report 재생성 |
| `python3 -m pytest -q` | `443 passed, 59 subtests passed in 34.96s` |

## 5. 반영 문서

- `docs/Current-Implementation.md`
  - E6 설명을 source split 기준으로 정정했다.
  - h15 비용 구조 확정 배제 해석을 제거했다.
- `docs/Execution-Plan.md`
  - Phase 1 구조 진단 문단을 KIS live / Cybos 분리 결과로 갱신했다.
  - E6는 h15 배제 근거가 아니며, E1 신호 정보량 부족이 현재 우선 병목이라고 정리했다.
- `docs/logbook.md`
  - review_ver_25 대응과 검증 결과를 신규 entry 로 남겼다.

## 6. 다음 방향

### 계속 진행

1. E1 신호 정보량 부족 원인을 우선 본다.
   - `probability_down`이 미래 수익률과 올바른 음의 상관을 내지 못한 이유를 피처/시간대/종목/장세별로 분해한다.
2. source lineage 저장 설계를 별도 후보로 둔다.
   - 지금처럼 날짜/심볼 근사로 source 를 나누면 장기적으로 해석이 흐려진다.
   - label 생성 시 원천을 저장하는 schema 후보가 필요하지만, 운영 DB schema 변경은 별도 안전 검토 뒤 진행한다.
3. KIS live 30/60거래일 checkpoint는 계속 같은 기준으로 관측한다.
   - E6는 KIS live 표본 기준으로 갱신한다.
   - buy-avoid random-control은 기존처럼 무작위 대조군 대비 우위가 확인될 때까지 주문 정책에 반영하지 않는다.

### 보류

1. E2/E3 threshold/EV 필터 튜닝은 계속 보류한다.
2. h15 비용 구조만으로 확정 배제하는 문구는 쓰지 않는다.
3. h60 주문 정책 전환은 별도 gate/label/체결 검증 전까지 만들지 않는다.
4. active model, gate, threshold, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`는 바꾸지 않는다.

### 다음 cowork 리뷰 필요 시점

- E1 신호 품질 개선 분해 결과가 나온 뒤.
- source lineage schema 변경을 실제로 설계하기 전.
- 30거래일 checkpoint에서 KIS live 표본 기준 buy-avoid/random-control 재평가가 닫힌 뒤.

## 7. self-review

- 누락한 작업: review_ver_25의 P0인 source split, 신규 테스트, 전체 pytest 결과 보고를 완료했다.
- 잘못 진행한 부분: 기존 전체 E6 결과를 KIS live 결론처럼 읽은 것은 잘못이었다. 이번 work_ver_26에서 정정했다.
- 결과 판단: KIS live h15는 비용 기준을 넘지만, E1 신호 품질이 부족하므로 threshold/EV 튜닝을 진행하지 않는 판단이 맞다.
- 코드 오류점검: source split 테스트 3개와 전체 pytest를 통과했다.
- 기타 리뷰: source 컬럼 부재를 JSON/Markdown에 명시했고, 근사 분리라는 한계를 숨기지 않았다.
