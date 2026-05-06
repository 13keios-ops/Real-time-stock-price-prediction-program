# docs/STATUS.md

생성일: 2026-05-06
스프린트: 04 Cybos 실제 분봉 기준선

## [2026-05-07 04:20] 실험 F-1 — Cybos 실제 분봉 bar-only 기준선

- 상황: `AGENTS.md`에 ML 실험 자율 범위를 추가한 뒤, Cybos 실제 15분봉 5년치 기준으로 LightGBM 기준선을 다시 측정했다.
- 가져갈 파일: `docs/STATUS.md`, `AGENTS.md`, `README.md`, `docs/Current-Implementation.md`, `docs/logbook.md`
- 판단: `source=cybos-historical`만 사용하고 `pykrx-daily-proxy`, `kis-ws`는 제외했다. Cybos 병합 데이터에는 과거 호가가 없으므로 `spread_bps`, `bid_ask_imbalance`, `mid_price`는 제외하고 bar-only 피처만 사용했다.
- 최종 조치: 자동 승격 금지 유지. 최고 결과인 F-1c도 walk-forward `trade_hit_rate=0.284987`, `cumulative_net_return_pct=-25.134498`로 완료 조건에는 못 미친다. 다만 F-1 -> F-1b -> F-1c 순서로 개선이 있어 `3회 연속 개선 없음` 보고 조건은 아니다.

### 데이터셋

| 항목 | 값 |
|---|---:|
| source | `cybos-historical` |
| symbols | 199 |
| trade_dates | 1,249 |
| source_rows | 6,283,279 |
| labeled_rows | 6,040,981 |
| 기간 | `2021-03-30T09:15:00+09:00..2026-05-04T15:15:00+09:00` |
| validation_start_date | `2025-04-23` |

라벨 분포:

| label | count | ratio |
|---|---:|---:|
| flat | 4,437,376 | 73.46% |
| down | 805,811 | 13.34% |
| up | 797,794 | 13.21% |

### 공통 설정

- 모델: LightGBM, `class_weight=balanced`
- split: 거래일 기준 tail 20% validation
- source filter: `cybos-historical` only
- 제외 source: `pykrx-daily-proxy`, `kis-ws`, `kis-rest-historical`, `synthetic`
- feature_names: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`
- 제외 feature: `mid_price`, `spread_bps`, `bid_ask_imbalance`
- gate/risk 기준: 변경 없음

### 실행 결과

| 실험 | train_rows | validation_accuracy | validation trades | validation trade_hit_rate | validation net pct | walk-forward overall_accuracy | walk-forward trades | walk-forward trade_hit_rate | walk-forward net pct |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-1 | 2,000 | 0.473329 | 51,992 | 0.180105 | -4,737.492793 | 0.546787 | 10,417 | 0.217913 | -1,041.554842 |
| F-1b | 10,000 | 0.487424 | 15,344 | 0.229797 | -1,333.702180 | 0.563363 | 1,161 | 0.282515 | -27.799564 |
| F-1c | 20,000 | 0.506736 | 18,541 | 0.233698 | -1,122.516600 | 0.576262 | 393 | 0.284987 | -25.134498 |

F-1c feature importance:

| rank | feature | importance |
|---:|---|---:|
| 1 | `avg_trade_size` | 2,795 |
| 2 | `hl_range_pct` | 2,401 |
| 3 | `return_1m_pct` | 2,015 |

판단 기준 대비:

- validation accuracy는 `0.6 이하`로 내려와 proxy 누수성 과대평가가 해소된 상태로 본다.
- walk-forward `trade_hit_rate`는 최고 `0.284987`로 `0.3` 기준에 아직 못 미친다.
- walk-forward 누적 순수익률은 최고 `-25.134498%`로 아직 음수다.
- 다음 자율 실험 방향은 데이터 소스나 risk/gate 변경 없이 bar-context 피처를 추가하는 것이다. 후보는 `close_position_pct`, `minute_slot`, `log_volume` 중심이다.

실행 명령:

```bash
python -m app --run-cybos-bar-only-experiment --horizon-min 15 \
  --cybos-experiment-train-max-rows 2000 \
  --cybos-experiment-walk-test-rows 2000 \
  --cybos-experiment-walk-step-rows 10000 \
  --cybos-experiment-walk-gap-rows 15 \
  --cybos-experiment-walk-max-folds 120

python -m app --run-cybos-bar-only-experiment --horizon-min 15 \
  --cybos-experiment-train-max-rows 10000 \
  --cybos-experiment-walk-test-rows 2000 \
  --cybos-experiment-walk-step-rows 20000 \
  --cybos-experiment-walk-gap-rows 15 \
  --cybos-experiment-walk-max-folds 80

python -m app --run-cybos-bar-only-experiment --horizon-min 15 \
  --cybos-experiment-train-max-rows 20000 \
  --cybos-experiment-walk-test-rows 2000 \
  --cybos-experiment-walk-step-rows 30000 \
  --cybos-experiment-walk-gap-rows 15 \
  --cybos-experiment-walk-max-folds 50
```

산출물:

- `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.json`
- `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.md`
- `runtime-data/ml/models/lightgbm-cybos-bar-only-h15-v1.joblib`

## 🔴 [2026-05-07 02:55] 스프린트 04 재시작 — Cybos 병합 데이터 사전 확인

- 상황: Cybos 5년치 실제 15분봉 병합 완료 후 실험 F를 새 데이터 기준으로 재시작하려 했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: Cybos 분봉 자체는 main DB에 199종목 6,283,279행으로 병합됐지만, `raw_orderbook_ticks`에는 `source=cybos-historical` 행이 0개다. 따라서 `spread_bps`, `bid_ask_imbalance`를 Cybos 실제 호가 피처로 포함하는 실험 F 조건은 현재 DB로 충족되지 않는다.
- 최종 조치: `python -m app --build-feature-dataset`까지 실행하고, 학습/챌린저/walk-forward는 실행하지 않았다. 이 상태에서 학습하면 새 Cybos 실제 호가 기준선이 아니라 pykrx proxy 호가가 섞인 기준선이 된다.

### 사전 확인 1. source별 raw row 수

| source | symbol 수 | raw_market_ticks row | 기간 |
|---|---:|---:|---|
| `cybos-historical` | 199 | 6,283,279 | `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00` |
| `kis-ws` | 10 | 3,054,451 | `2026-04-28T09:00:13+09:00..2026-05-06T13:41:25+09:00` |
| `kis-rest-historical` | 10 | 4,200 | `2026-05-04T15:02:00+09:00..2026-05-06T15:30:00+09:00` |

호가 원천 확인:

| source | raw_orderbook_ticks row | 판단 |
|---|---:|---|
| `cybos-historical` | 0 | Cybos 실제 호가 피처 없음 |
| `kis-ws` | 2,245,513 | 실제 WebSocket 호가 |
| `pykrx-daily-proxy` | 332,228 | proxy 호가 |

### 사전 확인 2. 피처/라벨 재생성

실행 명령:

```bash
python -m app --build-feature-dataset
```

결과:

| 항목 | 값 |
|---|---:|
| features_written | 356,970 |
| labels_written | 647,510 |
| horizons | 15, 60 |
| feature symbols | 10 |
| feature range | `2021-01-04T09:00:00+09:00..2026-05-06T15:30:00+09:00` |

15분 라벨 기준 학습 가능 row:

| 기준 | row |
|---|---:|
| 전체 H15 labeled feature row | 343,807 |
| `cybos-historical` market source가 붙은 row | 243,993 |
| `kis-ws` market source가 붙은 row | 9,519 |
| `kis-ws` orderbook source가 붙은 row | 12,399 |
| `pykrx-daily-proxy` orderbook source가 붙은 row | 329,227 |

주의: `cybos-historical` market source row는 실제 Cybos 분봉 가격을 쓰지만, 같은 시각의 호가 source는 대부분 `pykrx-daily-proxy`다. 따라서 이 row에서 `spread_bps`, `bid_ask_imbalance`를 포함하면 Cybos 실제 호가가 아니라 proxy 호가를 학습하게 된다.

### 라벨 분포

전체 H15 labeled feature row 기준:

| label | count | ratio |
|---|---:|---:|
| flat | 258,339 | 75.14% |
| up | 42,591 | 12.39% |
| down | 42,877 | 12.47% |

`cybos-historical` market source row 기준:

| label | count | ratio |
|---|---:|---:|
| flat | 193,636 | 79.36% |
| up | 25,221 | 10.34% |
| down | 25,136 | 10.30% |

### 실험 F 상태

실험 F는 실행하지 않았다.

이유:

- 요구 조건은 `spread_bps`, `bid_ask_imbalance`를 Cybos 실제 호가 피처로 포함하는 것이다.
- 현재 Cybos 병합 데이터에는 실제 호가 테이블인 `raw_orderbook_ticks`의 `cybos-historical` 행이 없다.
- 현재 학습 로더를 그대로 쓰면 proxy row가 포함된 학습셋으로 판단되어 `mid_price`, `spread_bps`, `bid_ask_imbalance`가 제외된다.
- 반대로 제외 로직을 억지로 풀면 Cybos 실제 호가가 아니라 pykrx proxy 호가를 실제 호가처럼 학습하게 된다.

다음 선택지는 둘 중 하나다.

1. Cybos에서 과거 호가를 별도로 수집할 수 있는 TR을 찾아 `raw_orderbook_ticks source=cybos-historical`를 실제로 채운 뒤 실험 F를 재실행한다.
2. 실험 F를 “Cybos 실제 분봉 bar-only 기준선”으로 재정의하고, 피처를 `avg_trade_size`, `hl_range_pct`, `return_1m_pct` 중심으로 학습한다. 이 경우 `spread_bps`, `bid_ask_imbalance`는 포함하지 않는다.

## 🔴 [2026-05-06 20:10] 실험 E — 일봉 단위 train/validation split

- 상황: 실험 B/D에서 `mid_price`를 제거하고 horizon purge를 적용해도 validation_accuracy가 `0.911793`으로 유지됐다. 이번 실험은 같은 거래일의 proxy 15분 봉이 train과 validation에 동시에 들어가는 문제를 차단하기 위해 날짜 단위 80/20 split을 적용했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: validation_accuracy가 `0.921672`로 유지되어, 기존 `0.912`가 단순히 같은 날짜 train/validation 혼입 때문이었다는 가설은 확인되지 않았다. 다만 walk-forward는 여전히 실패권이므로 proxy 15분 라벨/보간 규칙 자체의 암기 가능성은 계속 높다.
- 최종 조치: 자동 승격 금지 유지. active model은 `baseline-h15-v1` 그대로 유지.

### 변경 내용

- `app/services/research.py`의 train/validation split을 행 단위 tail 80/20에서 거래일 단위 tail 80/20로 변경했다.
- 같은 날짜의 모든 row는 train 또는 validation 중 한쪽에만 들어간다.
- horizon purge는 유지한다. validation 시작 시각 기준으로 `train.event_time + horizon < validation_start_time`을 만족하지 않는 train row를 제거한다.
- 작은 synthetic fixture에서 날짜 split 또는 purge 후 `down/flat/up` 라벨 구성이 깨질 때만 기존 row-level split을 fallback으로 사용한다.
- 피처는 실험 B/D 상태 그대로 유지했다. `mid_price`, `spread_bps`, `bid_ask_imbalance`는 proxy 포함 학습셋 feature list에서 제외된다.

### split 확인

| 항목 | 값 |
|---|---:|
| split method | `trade_date_tail_20pct` |
| feature_names | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` |
| total labeled rows | 332,892 |
| train_rows | 254,350 |
| validation_rows | 78,542 |
| train_date_count | 1,047 |
| validation_date_count | 262 |
| last_train_date | `2025-04-08` |
| first_validation_date | `2025-04-09` |
| last_train_event_time | `2025-04-08T15:00:00+09:00` |
| first_validation_event_time | `2025-04-09T09:00:00+09:00` |
| train/validation date overlap | 0 |

### 실험 E 실행 결과

실행 명령:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
python -m app --run-challengers --horizon-min 15
```

학습 설정:

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506200645749446` |
| train_rows | 254,350 |
| validation_rows | 78,542 |
| validation_accuracy | 0.921672 |
| proxy_rows | 318,683 |
| source_counts | `pykrx-daily-proxy=318683`, `kis-ws=12388`, `unknown=1192`, `kis-rest-historical=554`, `synthetic=75` |

라벨 분포:

| 기준 | down | flat | up |
|---|---:|---:|---:|
| validation actual label | 7,311 | 63,643 | 7,588 |
| LightGBM validation predicted label | 6,231 | 65,923 | 6,388 |
| walk-forward actual label | 22,640 | 286,541 | 23,659 |
| walk-forward predicted label | 107,264 | 110,316 | 115,260 |

주요 결과:

| 지표 | LightGBM validation/challenger | Walk-forward |
|---|---:|---:|
| trades_taken | 5,911 | 111,223 |
| validation_accuracy / overall_accuracy | 0.921672 | 0.380246 |
| cumulative_net_return_pct | 2,026.652123 | -10,411.176412 |
| trade_hit_rate | 0.870919 | 0.104502 |
| win_rate | 0.889359 | 0.341638 |

실험 누적표:

| 실험 | split | feature_names | validation_accuracy | walk-forward overall_accuracy | walk-forward trade_hit_rate | walk-forward cumulative_net_return_pct | walk-forward trades_taken | 판단 |
|---|---|---|---:|---:|---:|---:|---:|---|
| C-1 | row tail 80/20 | `avg_trade_size`, `hl_range_pct`, `mid_price`, `return_1m_pct` | 0.911699 | 0.412748 | 0.101259 | -10,384.138893 | 104,327 | validation 과대, gate 실패 |
| B/D | row tail 80/20 + purge | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` | 0.911793 | 0.380246 | 0.104502 | -10,411.176412 | 111,223 | `mid_price` 단독 누수 아님 |
| E | date tail 80/20 + purge | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` | 0.921672 | 0.380246 | 0.104502 | -10,411.176412 | 111,223 | 같은 날짜 혼입 누수만으로 설명 안 됨 |

판단 기준 대비:

- `validation_accuracy`가 `0.7 이하`로 떨어지지 않았다. 따라서 기존 `0.912`가 같은 날짜 proxy 봉 혼입 때문이었다는 판단은 확인되지 않았다.
- `walk-forward trade_hit_rate`는 `0.104502`로 `0.3` 기준에 못 미친다. 실전 방향성 개선은 확인되지 않았다.
- 다음 단계는 proxy 15분 라벨을 학습/validation에서 제외하거나, proxy는 일봉 라벨용으로만 쓰고 실제 KIS 분봉만 15분 라벨 검증에 쓰는 방향이 더 타당하다.

Challenger 최종 판단:

- best_candidate: `latest_lightgbm`
- recommended_action: `review_required`
- recommended_model_version: `lightgbm-h15-v1`
- walk_forward_gate_status: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.3802).`
- active_model_version_after_run: `baseline-h15-v1`

검증:

- `python -m py_compile app/services/research.py`: 통과
- `python -m unittest discover -s tests -p "test_*.py"`: `Ran 85 tests in 11.904s`, `OK`

## 🔴 [2026-05-06 18:23] 긴급 누수 점검 — 실험 B/D(mid_price 제거)

- 상황: C-1에서 LightGBM validation `0.911699`와 walk-forward `0.412748`의 격차가 너무 커서, pykrx proxy 라벨 구조와 train/validation split 누수를 먼저 점검했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: `mid_price` 단독 누수가 주원인이라는 가설은 지지되지 않는다. `mid_price`를 제거하고 horizon purge를 적용해도 validation_accuracy는 `0.911793`으로 유지됐고, walk-forward는 `0.380246`으로 더 낮아졌다. 현재 1차 의심은 `pykrx-daily-proxy`의 같은 일봉 OHLC 보간 경로 자체와 그 경로에서 만든 15분 라벨이다.
- 최종 조치: 자동 승격 금지 유지. active model은 `baseline-h15-v1` 그대로 유지.

### 확인 1. pykrx proxy 라벨 생성 구조

구현 위치:

- `app/collectors/historical.py`
- `app/services/research.py`

확인 결과:

- `pykrx-daily-proxy`는 일봉 OHLCV 1개를 거래일당 26개 15분 봉으로 변환한다.
- 가격 anchor는 아래처럼 하루 전체 OHLC를 이미 알고 있는 상태에서 정한다.
  - 상승/보합일: index `0=open`, `6=low`, `18=high`, `25=close`
  - 하락일: index `0=open`, `6=high`, `18=low`, `25=close`
- 각 proxy bar의 close는 위 anchor 사이 선형 보간값이다.
- 라벨 생성은 현재 봉 `bar.close`와 `bar_time + horizon` 이후 같은 날짜 첫 future bar의 `future_bar.close` 차이로 `future_return_pct`를 만든다.
- 따라서 proxy 데이터의 15분 라벨은 대부분 같은 일봉 OHLC에서 보간된 현재 proxy close와 미래 proxy close의 차이다.

판단:

- 코드가 시간순 배열 밖의 임의 미래 row를 잘못 join하는 형태의 직접 누수는 아니다.
- 하지만 proxy의 하루 경로가 당일 OHLC를 모두 사용해 사후적으로 만들어지므로, 같은 일봉 안에서 만든 15분 라벨은 일봉 OHLC 패턴을 모델이 외우기 쉬운 구조다.
- 특히 `hl_range_pct`, `return_1m_pct`, `avg_trade_size`만 남긴 뒤에도 validation이 유지됐기 때문에, 누수성 신호가 특정 `mid_price` 하나에만 묶여 있지 않다.

### 확인 2. train/validation split horizon purge

확인 결과:

- 기존 `_split_dataset`은 시간순 80/20 tail split만 수행했고, train 마지막 row의 label horizon이 validation 시작 구간에 닿는지 제거하지 않았다.
- 이번 작업에서 `app/services/research.py`의 split을 아래 방식으로 보강했다.
  - validation 시작 시각과 같은 timestamp row는 모두 validation 쪽으로 보낸다.
  - `horizon_min > 0`이면 `train.event_time + horizon < validation_start_time`을 만족하지 않는 train row를 제거한다.
  - 아주 작은 synthetic test fixture에서 purge 후 `down/flat/up` 라벨 구성이 깨질 때만 기존 train split을 유지한다.
- 실제 5년치 학습 데이터에서는 purge가 적용됐고, split은 아래처럼 확인됐다.

| 항목 | 값 |
|---|---:|
| feature_names | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` |
| total labeled rows | 332,892 |
| train_rows | 266,300 |
| validation_rows | 66,582 |
| train_end | `2025-06-20T13:45:00+09:00` |
| validation_start | `2025-06-20T14:15:00+09:00` |
| purge gap | 30분 |

### 확인 3. 실험 B/D — mid_price 제거 후 재학습

처리 방식:

- proxy 포함 학습셋에서는 기존 제외 피처 `spread_bps`, `bid_ask_imbalance`에 더해 `mid_price`도 학습 피처 목록에서 제외했다.
- 실험 B/D feature_names: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`
- `source=kis-ws` row의 저장 피처는 수정하지 않았다. 학습 로더에서 proxy 포함 학습셋 feature list만 조정했다.

실행 명령:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
python -m app --run-challengers --horizon-min 15
```

학습 설정:

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506181808816399` |
| class_weight | `balanced` |
| train_rows | 266,300 |
| validation_rows | 66,582 |
| validation_accuracy | 0.911793 |
| proxy_rows | 318,683 |
| source_counts | `pykrx-daily-proxy=318683`, `kis-ws=12388`, `unknown=1192`, `kis-rest-historical=554`, `synthetic=75` |

라벨 분포:

| 기준 | down | flat | up |
|---|---:|---:|---:|
| validation actual label | 6,533 | 53,113 | 6,936 |
| LightGBM validation predicted label | 5,421 | 55,419 | 5,742 |
| walk-forward actual label | 22,640 | 286,541 | 23,659 |
| walk-forward predicted label | 107,264 | 110,316 | 115,260 |

주요 결과:

| 지표 | LightGBM validation/challenger | Walk-forward |
|---|---:|---:|
| trades_taken | 5,113 | 111,223 |
| validation_accuracy / overall_accuracy | 0.911793 | 0.380246 |
| cumulative_net_return_pct | 1,816.829656 | -10,411.176412 |
| trade_hit_rate | 0.889693 | 0.104502 |
| win_rate | 0.895951 | 0.341638 |

판단 기준 대비:

- `validation_accuracy`가 `0.912 → 0.6 이하`로 떨어지지 않았다. 따라서 `mid_price`가 누수의 주원인이라는 판단은 보류한다.
- `walk-forward trade_hit_rate`가 `0.3 이상`으로 오르지 않았다. 실제 결과는 `0.104502`로 C-1의 `0.101259`와 거의 같은 실패권이다.
- validation과 walk-forward 격차가 계속 크므로, 다음 실험은 proxy 15분 label 자체를 제거하거나 일봉 단위 split/검증으로 바꾸는 방향이 우선이다.

Challenger 최종 판단:

- best_candidate: `latest_lightgbm`
- recommended_action: `review_required`
- recommended_model_version: `lightgbm-h15-v1`
- walk_forward_gate_status: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.3802).`
- active_model_version_after_run: `baseline-h15-v1`

검증:

- `python -m py_compile app/services/research.py`: 통과
- `python -m unittest discover -s tests -p "test_*.py"`: `Ran 85 tests in 12.835s`, `OK`

## 🟠 [2026-05-06 17:24] 스프린트 04 — proxy 호가 피처 제외 + C-1 5년치 재실행

- 상황: 스프린트 03 품질 점검에서 `pykrx-daily-proxy`의 `spread_bps`, `bid_ask_imbalance`가 실제 KIS 호가와 의미가 다르다고 확인되어, proxy 포함 학습에서는 두 피처를 학습 피처 목록에서 제외했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: LightGBM C-1은 validation 기준으로 크게 개선됐지만, walk-forward gate는 아직 `needs_review`이므로 승격 금지 유지.

### 사전 작업. 호가 피처 제외 처리

- 구현 위치:
  - `app/services/research.py`
  - `app/storage/sqlite_store.py`
- 처리 방식:
  - `feature_model_inputs`의 저장된 `values_json`은 수정하지 않는다.
  - 학습 데이터 로더가 `raw_orderbook_ticks`/`raw_market_ticks`의 source를 함께 읽어 row source를 판정한다.
  - `pykrx-daily-proxy` row가 포함된 학습셋에서는 `spread_bps`, `bid_ask_imbalance`를 학습 feature_names에서 제외한다.
  - `mid_price`는 유지한다.
  - C-1 학습 feature_names: `avg_trade_size`, `hl_range_pct`, `mid_price`, `return_1m_pct`
- 성능 보강:
  - source lookup이 느려지지 않도록 `raw_market_ticks(symbol,event_time)`, `raw_orderbook_ticks(symbol,event_time)` index를 추가했다.
  - 33만 labeled row 로딩 확인: 약 `13.11s`
- 단위 테스트:
  - `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: `Ran 85 tests in 13.796s`, `OK`

### 실험 C-1. class_weight=balanced 5년치 재실행

실행 명령:

```bash
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
python -m app --run-challengers --horizon-min 15
```

학습 설정:

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506171325113244` |
| class_weight | `balanced` |
| train_rows | 266,313 |
| validation_rows | 66,579 |
| validation_accuracy | 0.911699 |
| proxy_rows | 318,683 |
| source_counts | `pykrx-daily-proxy=318683`, `kis-ws=12401`, `synthetic=75`, `unknown=1733` |

라벨 분포:

| 기준 | down | flat | up |
|---|---:|---:|---:|
| 전체 actual label | 22,656 | 286,577 | 23,659 |
| validation actual label | 6,533 | 53,110 | 6,936 |
| LightGBM validation predicted label | 5,563 | 55,420 | 5,596 |
| walk-forward predicted label | 100,902 | 127,608 | 104,330 |

주요 결과:

| 지표 | LightGBM validation/challenger | Walk-forward |
|---|---:|---:|
| trades_taken | 5,328 | 104,327 |
| validation_accuracy / overall_accuracy | 0.911699 | 0.412748 |
| cumulative_net_return_pct | 1,807.293048 | -10,384.138893 |
| trade_hit_rate | 0.863176 | 0.101259 |
| win_rate | 0.877252 | 0.336260 |

Challenger 최종 판단:

- best_candidate: `latest_lightgbm`
- recommended_action: `review_required`
- recommended_model_version: `lightgbm-h15-v1`
- walk_forward_gate_status: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.4127).`
- active_model_version_after_run: `baseline-h15-v1`

### 병행 작업. KIS REST 1년치 실제 분봉 수집 코드

- 구현 위치:
  - `app/brokers/kis_quote_rest.py`
  - `app/collectors/historical.py`
  - `app/__main__.py`
- CLI:

```bash
python -m app --collect-kis-historical --start 2025-05-06 --end 2026-05-06
```

- TR: `FHKST03010200`
- source: `kis-rest-historical`
- 저장:
  - 기존 `curated_minute_bars`에 OHLCV upsert
  - 기존 `raw_market_ticks`에 close/volume tick을 `source=kis-rest-historical`로 적재
  - 기존 DB 테이블 구조는 변경하지 않음
- rate-limit 처리:
  - `EGW00201` 발생 시 backoff 재시도
  - 종목별 실패는 summary error로 기록하고 다음 종목 진행

실행 결과:

| 항목 | 값 |
|---|---:|
| requested_days | 366 |
| bars_written | 4,200 |
| raw_ticks_written | 4,200 |
| per-symbol records_written | 420 |
| earliest_bar_time | `2026-05-04T15:02:00+09:00` |
| latest_bar_time | `2026-05-06T15:30:00+09:00` |
| report | `runtime-data/reports/historical/latest-kis-rest-historical-collection.{json,md}` |

제한 사항:

- 공식 KIS 샘플 기준 `FHKST03010200`은 주식당일분봉조회 성격이며, 1회 최대 30건과 전일자 분봉 제한이 있다.
- 실제 실행에서는 요청 기간 366일 중 최근 일부 구간만 반환됐다. 따라서 1년 전체 실제 분봉 백필은 이 TR만으로는 완료되지 않았다.
- 다음 단계에서는 `FHKST03010200` 반복 조회 한계와 별개로, KIS가 제공하는 다른 장기 분봉 TR 또는 외부 실제 분봉 소스를 검토해야 한다.

## 🟠 [2026-05-06 16:18] 스프린트 04 전 점검 — pykrx 프록시 분봉 품질 확인

- 상황: 스프린트 03에서 적재한 `pykrx-daily-proxy` 15분 프록시 분봉이 실제 KIS WebSocket 기반 분봉과 같은 DB 구조로 들어가지만, 호가 기반 피처의 의미가 실제 호가와 크게 다르다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: 스프린트 04 학습/검증에 프록시 데이터를 그대로 쓸 수는 있으나, `spread_bps`, `bid_ask_imbalance` 같은 호가 기반 피처는 source 별 분포 차이가 커서 별도 처리 필요.

### 확인 1. pykrx 프록시 분봉 구조

구현 위치: `app/collectors/historical.py`

- 거래일당 26개 봉을 만든다. `_market_times()`는 09:00부터 15분 간격으로 시각을 만들기 때문에 마지막 프록시 봉은 15:15다.
- 가격 경로는 일봉 OHLC를 선형 보간한다.
  - 상승일 또는 보합/상승일: index `0=open`, `6=low`, `18=high`, `25=close`
  - 하락일: index `0=open`, `6=high`, `18=low`, `25=close`
  - 각 봉의 open은 직전 프록시 close, close는 보간값이다.
  - high/low는 기본적으로 open/close 사이 값이며, 보간 close가 일봉 high/low anchor와 같을 때만 해당 일봉 high/low를 반영한다.
- 거래량은 전체 일봉 거래량을 U자형 가중치로 26개 봉에 나눈다. 장 초반과 장 후반에 더 큰 weight가 붙고, 마지막 봉에서 반올림 잔여량을 보정한다.
- 프록시 호가는 각 프록시 close 기준으로 `bid=close-tick`, `ask=close+tick`을 만들고, `bid_size=ask_size=max(1, volume//2)`로 채운다.
- 따라서 raw proxy orderbook 기준:
  - `mid_price`는 사실상 프록시 close와 같다.
  - `spread_bps`는 실제 호가 스프레드가 아니라 가격대별 tick size로 만든 기계적 값이다.
  - `bid_ask_imbalance`는 bid/ask size를 같게 넣기 때문에 항상 `0.0`이다.
- 구조 호환성: `MinuteBar`, `OrderbookSnapshot`, `curated_minute_bars`, `raw_orderbook_ticks`, `feature_model_inputs`, `feature_labels`를 그대로 쓰므로 KIS WebSocket 분봉과 스키마는 호환된다. 다만 실제 호가 압력, 체결 강도, 장중 변동 경로를 재현한 데이터는 아니다.

### 확인 2. KIS 실제 호가 vs pykrx 프록시 피처 분포

비교 기준 DB: `runtime-data/dev.db`

| 항목 | `kis-ws` | `pykrx-daily-proxy` |
|---|---:|---:|
| raw orderbook rows | 2,245,513 | 332,228 |
| raw 기간 | 2026-04-28 09:00 ~ 2026-05-06 13:41 | 2021-01-04 09:00 ~ 2026-05-06 15:15 |
| exact feature samples | 12,521 | 332,228 |
| proxy/KIS exact overlap minutes | - | 798 |

주요 feature 분포:

| feature | `kis-ws` median / mean | `pykrx-daily-proxy` median / mean | 판단 |
|---|---:|---:|---|
| `mid_price` | 221,250 / 478,689 | 172,500 / 295,257 | 기간과 종목 가격대 차이 영향이 커 직접 비교 지표로는 제한적 |
| `spread_bps` | 12.83 / 14.74 | 37.92 / 42.31 | 프록시가 실제보다 약 3배 높게 형성되어 분포 차이 큼 |
| `bid_ask_imbalance` | 0.0418 / 0.0337, p05=-0.8056, p95=0.8500 | 0.0 / 0.0, zero_ratio=100% | 프록시는 호가 불균형 정보가 완전히 사라짐 |

### 결론과 스프린트 04 권장 조치

- `pykrx-daily-proxy`는 5년치 가격/라벨 볼륨을 확보하는 목적에는 유효하다.
- 단, 실제 KIS WebSocket 기반 학습/추론과 같은 의미로 호가 피처를 쓰면 분포 이동이 크다.
- 스프린트 04에서는 아래 중 하나를 먼저 정해야 한다.
  1. proxy source 학습에서는 `spread_bps`, `bid_ask_imbalance`를 제외하거나 neutral 처리한다.
  2. feature에 `data_source` 또는 `is_proxy` 계열 구분값을 추가해 모델이 source 차이를 학습하게 한다.
  3. 실제 KIS 데이터만으로 짧은 기간 검증을 할 때와 proxy 장기 데이터 검증을 분리해 평가 리포트를 따로 낸다.
- 현재 상태에서 LightGBM 중요도 상위에 `mid_price`, `spread_bps`, `bid_ask_imbalance`가 들어간 것은 proxy/actual 분포 차이 또는 가격수준 의존 가능성을 함께 의심해야 한다.

## 🔴 [2026-05-06 05:22] 운영자 판단 필요 — Phase 1 Windows 직접 실행 완료

- 상황: Windows 로컬 환경에서 작업 1 단위 테스트 통과 후 Phase 1 명령 3개를 순서대로 직접 실행 완료. LightGBM은 validation 정확도와 누적 손실 폭에서는 baseline보다 좋아 보이나, 실제 매수 신호가 3건뿐이라 challenger 판단은 `keep_active`이며 walk-forward gate도 `needs_review`.
- 가져갈 파일: `docs/STATUS.md`
- 질문: 아래 Phase 1 수치를 기준으로 Codex가 Phase 2 원인 분석(거래 수 부족, walk-forward 정확도 미달, LightGBM 신호 희소성)을 진행해도 되는지 확인 필요.

### 실행 명령과 결과

| 단계 | 명령 | 결과 |
|---|---|---|
| 작업 1 검증 | `python -m unittest discover -s tests -p "test_*.py"` | `Ran 85 tests in 25.449s`, `OK` |
| baseline/참조 walk-forward | `python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40` | `exit 0` |
| LightGBM 학습 | `python -m app --train-lightgbm --horizon-min 15` | `exit 0` |
| Challenger 비교 | `python -m app --run-challengers --horizon-min 15` | `exit 0` |

### Phase 1 핵심 수치

> MDD와 샤프지수는 현재 리포트 원 필드가 아니라, 거래별 또는 fold별 `net_return_pct` 단순누적 시퀀스로 계산한 참고값이다.

| 지표 | baseline / active | LightGBM latest | baseline 대비 |
|---|---:|---:|---|
| validation rows | 2303 | 2303 | 동일 |
| trades_taken | 1013 | 3 | LightGBM 신호가 과소 |
| 누적 순수익률 | -51.599478% | -0.113131% | LightGBM 손실 폭 우위 |
| MDD | -58.734863% | -0.177832% | LightGBM 손실 폭 우위 |
| 샤프지수 | -0.163627 | -0.203249 | baseline 우위 |
| 정확도 | 0.108120 | 0.816761 | LightGBM 우위 |
| win_rate | 0.358342 | 0.333333 | baseline 우위 |
| baseline 대비 판정 | 기준 | 정확도/순수익률은 우위이나 거래 수 3건으로 승격 불가 | `recommended_action=keep_active` |

### Walk-forward 참조 수치

| 항목 | 값 |
|---|---:|
| model_version | `walk-forward-centroid-h15-v1` |
| folds | 1147 |
| rows_evaluated | 11470 |
| trades_taken | 3126 |
| overall_accuracy | 0.438710 |
| trade_hit_rate | 0.197377 |
| win_rate | 0.442738 |
| 누적 순수익률 | -14.115270% |
| MDD(폴드 순수익 단순누적 기준) | -160.630188% |
| 샤프지수(폴드 순수익 기준) | -0.010281 |
| gate | `needs_review` — `Walk-forward overall accuracy is too low (0.4387).` |

### LightGBM 학습 수치

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506052213057306` |
| train_rows | 9212 |
| validation_rows | 2303 |
| validation_accuracy | 0.816761 |
| activation_applied | `false` |

### 피처 중요도 상위 5개

| 순위 | 피처 | importance |
|---:|---|---:|
| 1 | `mid_price` | 1450 |
| 2 | `spread_bps` | 1110 |
| 3 | `bid_ask_imbalance` | 1077 |
| 4 | `avg_trade_size` | 986 |
| 5 | `hl_range_pct` | 853 |

### 다음 요청

- Codex Phase 2 원인 분석 후보:
  - LightGBM validation 정확도는 높지만 `up` 신호가 3건뿐이라 거래 커버리지가 부족한 이유 확인.
  - walk-forward 정확도 0.438710으로 gate 0.55 기준 미달 원인 확인.
  - `mid_price`, `spread_bps`, `bid_ask_imbalance` 중심 중요도 편중이 데이터 누수/가격수준 의존인지 점검.
- 운영자 판단 필요: 예 — Phase 2 원인 분석 착수 승인 필요.

## 🔴 [2026-05-06 두 번째 호출] 운영자 판단 필요 — Codex 패치 후에도 Synthetic 미통과

- 상황: Codex 커밋 `eb3949f`(WAL→DELETE journal fallback) 적용 후 재실행했으나, virtiofs FUSE 환경에서는 `journal_mode=DELETE` 단독으로도 SQLite 가 `disk I/O error` 로 실패. 단위 테스트 85 발견(개수 일치) 중 40건이 동일 오류로 실패. Synthetic 도 같은 원인으로 진입 직후 실패.
- 가져갈 파일: `docs/logbook.md` (상단 "Cowork 후속 검증" 섹션에 pragma 조합별 실험표 포함)
- 질문: Codex 에 다음 중 어떤 추가 조치를 지시할지 결정 필요
  1. **`DELETE` 선택 시 `PRAGMA locking_mode=EXCLUSIVE` 함께 설정** — 실험에서 동작 확인. 단일 프로세스 운영(Cowork synthetic, 단위 테스트)에는 영향 없으나 동시 접속이 필요한 대시보드/감시기 동시 운영 시 영향 검토 필요.
  2. **DELETE 실패 시 `journal_mode=MEMORY` 로 한 단계 더 fallback** — 가장 단순. 정전·크래시 시 DB 무결성 약간 저하 가능. Cowork 샌드박스 한정 적용 권장.
  3. **Phase 1 진단을 운영자가 Windows 로컬에서 직접 실행** — Cowork 환경 자체를 우회. 가장 빠르지만 자동화 흐름 깨짐.

### 사전 정리(이번 세션 적용 사항 — 다음 세션에 영향 없음)
- 작업트리 `app/storage/sqlite_store.py` 가 FUSE 동기화 중 1074→964줄로 절단된 채 도착해 `SyntaxError`. `git show HEAD:` 로 정본 1074줄 복원함(코드 변경 아님, 정본 복원).
- Cowork 샌드박스 Python 3.10.12 ↔ 프로젝트 요구 ≥3.12 갭은 `tomli` 백포트를 `tomllib` shim 으로 메움.
- 누락 패키지(`lightgbm`, `scikit-learn`, `websockets`, `joblib`, `tomli`, `scipy`, `threadpoolctl`) 설치 완료.

### 핵심 실험표 (logbook.md 상세)

| pragma 조합 | 결과 |
|---|---|
| `journal_mode=DELETE` | FAIL: disk I/O error |
| `journal_mode=DELETE` + `synchronous=NORMAL` (현재 코드) | FAIL: disk I/O error |
| `journal_mode=DELETE` + `synchronous=OFF` | FAIL: disk I/O error |
| `journal_mode=DELETE` + `locking_mode=EXCLUSIVE` | OK |
| `journal_mode=MEMORY` | OK |
| `journal_mode=OFF` | OK |

### Phase 1 결과
- Step 1 Synthetic 흐름 검증: **여전히 실패** (Codex 1차 패치로는 미해결)
- Step 2~5: 미실행 (가이드의 "Synthetic 통과 전 Step 2 보류" 규칙)

### 다음 단계
운영자 결정 후 Codex 재작업 또는 Windows 직접 실행 결정. 결정 전까지 추가 실행 없이 대기.
