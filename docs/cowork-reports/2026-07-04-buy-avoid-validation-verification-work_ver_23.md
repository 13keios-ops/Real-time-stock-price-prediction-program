# 2026-07-04 buy-avoid validation verification - work_ver_23

## 1. 작업 범위

사용자 지시와 handoff §4에 따라 이번 라운드는 새 구현 없이 실행 검증과 anchor 대조만 수행했다.

필독 문서:

- `docs/cowork-reports/2026-07-04-buy-avoid-validation-verification-and-codex-handoff.md`
- `docs/Buy-Avoid-Random-Control-Methodology.md`
- `docs/cowork-reports/2026-07-04-buy-avoid-validation-methodology-review.md`

금지/제한:

- buy-avoid 공식, seed, 부호 규약 변경 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 임계값 변경 없음.
- 모델 승격, 주문 정책 변경, KIS live shadow 확장 없음.
- handoff 금지선에 따라 자동 commit/push 없음.

## 2. 시작 상태

- KST: 2026-07-04 22:35, 토요일/주말.
- live runtime: stopped, `current_session_status=weekend`.
- runtime watchdog: running, `errors=[]`, `live_runtime_should_run=false`.
- git status 시작 기준: cowork 구현 파일이 uncommitted 상태로 존재했다.

대상 변경 파일은 cowork가 이미 저장소에 반영한 아래 항목이다.

- `scripts/buy_avoid_random_control.py`
- `scripts/summarize_lightgbm_defensive_shadow.py`
- `scripts/summarize_cybos_buy_avoid_proxy.py`
- `tests/test_buy_avoid_random_control.py`
- `docs/Buy-Avoid-Random-Control-Methodology.md`
- `docs/cowork-reports/2026-07-04-buy-avoid-validation-methodology-review.md`
- `docs/cowork-reports/2026-07-04-buy-avoid-validation-verification-and-codex-handoff.md`

## 3. pytest 실행 결과

handoff §4 P0의 첫 검증 명령을 실행했다.

```bash
python3 -m pytest tests/test_buy_avoid_random_control.py tests/test_lightgbm_defensive_shadow.py tests/test_cybos_buy_avoid_proxy.py -q
```

결과:

```text
30 passed in 1.65s
```

참고:

- 기본 `python3`와 `/usr/local/bin/python`에는 `pytest`가 없었다.
- `python3 -m pip install --user --break-system-packages pytest`로 사용자 영역에 `pytest`만 설치했다.
- pip cache와 실패한 임시 venv 산출물은 `.tmp-tests/` 아래에서 정리했다.

## 4. KIS live defensive shadow 재생성

실행 명령:

```bash
python3 scripts/summarize_lightgbm_defensive_shadow.py --horizon-min 15
```

결과:

```text
{"ok": true, "json_path": "/home/keios/projects/Real-time-stock-price-prediction-program/runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json", "markdown_path": "/home/keios/projects/Real-time-stock-price-prediction-program/runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.md"}
```

새 리포트 생성 시각:

- `generated_at=2026-07-04T22:41:34+09:00`

## 5. methodology §7 anchor 대조

대상 파일:

- `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`

threshold `0.40` 결과:

| 항목 | 실제 값 | methodology §7 기대 | 판정 |
|---|---:|---:|---|
| joined_rows | `25,198` | `25,198` | 일치 |
| skip count | `6,694` | `6,694` | 일치 |
| actual_skipped_cumulative_net_pct | `-486.3753108301879` | 약 `-486.3753` | 일치 |
| expected_random_skipped_sum_pct | `-711.8525316480927` | 약 `-711.85` | 일치 |
| excess_vs_random_pct | `+225.47722081790482` | 약 `+225.48` | 일치 |
| z_score | `+4.62776791142487` | 양수, 통과 아님 | 일치 |
| verdict | `filter_worse_than_random_p95` | `filter_better_than_random_p95`가 절대 아님 | 일치 |
| random_control_gate.passed | `false` | `false` | 일치 |
| simulation self_check_ok | `true` | true 필요 | 일치 |

해석:

- KIS live threshold `0.40`은 baseline 대비 손실을 줄여 보이지만, 같은 수량을 무작위로 제거하는 대조군보다 못하다.
- 부호 규약상 `excess>0`이므로 좋은 선별이 아니라 역선별 방향이다.
- 따라서 현재 표준 표현은 `재검증 필요, 무작위 대조군 대비 우위 미확인`이다.
- `random_control_gate.passed=false`이므로 buy-avoid를 정책 후보나 손실 축소 후보로 승격해서 표현하면 안 된다.

## 6. Cybos proxy full 재생성 재시도 결과

사용자 추가 지시에 따라 Cybos proxy full 재생성을 다시 시도했다. 이번에는 foreground wrapper 로 실행 시간을 추적했고 정상 완료했다.

실행 명령:

```bash
python3 scripts/summarize_cybos_buy_avoid_proxy.py --horizon-min 15
```

실행 결과:

- 시작: 2026-07-05 01:56:55 KST
- 종료: 2026-07-05 02:27:55 KST 부근
- 소요 시간: 약 31분
- 종료 코드: 0
- 로그: `runtime-data/logs/research/cybos_buy_avoid_proxy_full_20260705_0155.log`
- 갱신 파일: `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`
- `generated_at=2026-07-05T02:27:46.310251+09:00`

스크립트 요약:

- `buy_avoid_decision.status=follow_up_candidate_proxy_only`
- `best_target_skip_rate=0.5`
- `recommended_action=Keep KIS live buy-avoid shadow running; do not promote model or gate from Cybos proxy alone.`
- `rescue_decision.status=buy_avoid_candidate_only`

random-control aggregate 확인:

| target_skip_rate | actual_skip_rate | net_improvement_pct | expected_random | actual_skipped | excess | z_score | verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.20 | 0.195722 | 199.271435 | -93.969360 | -199.271435 | -105.302075 | -4.431154 | `filter_better_than_random_p95` |
| 0.30 | 0.301780 | 335.449884 | -159.885201 | -335.449884 | -175.564683 | -6.263590 | `filter_better_than_random_p95` |
| 0.3665 | 0.361727 | 367.715205 | -182.166161 | -367.715205 | -185.549044 | -6.360742 | `filter_better_than_random_p95` |
| 0.40 | 0.394262 | 379.728875 | -209.868893 | -379.728875 | -169.859982 | -5.693569 | `filter_better_than_random_p95` |
| 0.50 | 0.491610 | 429.544640 | -254.099292 | -429.544640 | -175.445348 | -5.782148 | `filter_better_than_random_p95` |

methodology §7 anchor 대조:

- target `0.3665`의 `actual_skipped_cumulative_net_pct=-367.715205`는 기존 anchor `≈ -367.72%p`와 일치한다.
- 정식 fold aggregate 기준 `expected_random_skipped_sum_pct=-182.166161`로, methodology 문서의 풀링 근사값 `≈ -194.6%p`와 크기는 다르지만 부호와 결론은 일치한다. 문서가 명시한 대로 정식 계산은 fold별 기대 합산이다.
- `excess_vs_random_pct=-185.549044`, `z_score=-6.360742`, verdict `filter_better_than_random_p95`로 Cybos proxy 에서는 필터가 무작위보다 나쁜 거래를 실제로 골라냈다.

해석:

- Cybos proxy random-control 기준은 통과한다.
- KIS live threshold `0.40`은 반대로 `filter_worse_than_random_p95`다.
- 따라서 현재 결론은 “Cybos 장기 proxy 에서는 buy-avoid 구조가 작동했지만, KIS live 2026-06-11~07-03 구간에서는 같은 방식이 무작위보다 나빴다”이다.
- 이 차이는 Cybos-KIS 전이성 진단의 `source_stable_candidate=0` 결론과 맞다.
- Cybos 결과만으로 KIS live 주문 정책, gate, active model 을 바꾸면 안 된다.

## 7. Codex 판단

이번 검증으로 cowork 구현의 핵심 수식/테스트는 실행 기준에서 통과했다.
가장 중요한 변화는 buy-avoid의 상태 표현이다.

이전 표현:

- `손실 축소 후보 유지`

검증 후 안전한 표현:

- `재검증 필요, 무작위 대조군 대비 우위 미확인`

이유는 단순하다. threshold `0.40`에서 실제 회피 거래 합계는 `-486.38%p`인데, 같은 수량을 무작위로 회피했을 때 기대값은 `-711.85%p`다. 즉 LightGBM이 고른 회피 대상이 무작위보다 덜 나빴고, 남겨진 거래가 더 나빠졌다.

따라서 buy-avoid는 지금 당장 버릴 연구 주제는 아니지만, 현재 KIS live 2026-06-11~07-03 구간에서는 정책 후보라고 부를 수 없다.

## 8. 다음 작업 권장

1. 문서/대시보드 표현을 `재검증 필요, 무작위 대조군 대비 우위 미확인`으로 소급 정리한다.
2. Cybos proxy full 재생성은 2026-07-05에 완료됐으므로, 다음에는 KIS와 Cybos를 같은 random-control 정의로 비교 정리한다.
3. 그 뒤 Cybos와 KIS를 같은 random-control 정의로 다시 비교한다.
4. IC, EV 기반 필터, regime 조건부 필터는 random-control 표현 정리가 끝난 뒤 진행한다.

## 9. 검증/안전 체크

- `pytest`: 30개 통과.
- KIS live defensive shadow 리포트 재생성 성공.
- KIS threshold `0.40` anchor 대조 완료.
- Cybos proxy full 재생성 재시도 완료. target `0.3665` fold aggregate 는 `excess=-185.549044`, `z=-6.360742`, `filter_better_than_random_p95`.
- 코드 구현 수정 없음.
- 공식/seed/부호 규약 변경 없음.
- 실전 주문/취소 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 임계값 변경 없음.
- 자동 commit/push 없음.
