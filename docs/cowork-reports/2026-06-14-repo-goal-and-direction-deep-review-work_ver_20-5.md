# Codex Work Ver 20-5 - Cybos Rescue Full 12 Fold Result

- 작성 시각: 2026-06-14 05:05 KST
- 범위: `proxy_buy_rescue` full 12 fold report 생성 및 해석
- 상태: full 실행 완료. buy-rescue 는 fixed-grid 기준 미통과.

## 1. 실행

실행 명령:

```bash
python scripts/summarize_cybos_buy_avoid_proxy.py --horizon-min 15 --feature-set-name bar_context_momentum --trade-cost-pct 0.13
```

결과 파일:

- `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`
- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
- `runtime-data/reports/backtests/latest-cybos-regime-performance-h15.json`

실행 시간:

- `real 1723.25`초

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`

## 2. 핵심 결론

결론:

- `buy-avoid`는 여전히 follow-up 후보다.
- `buy-rescue`는 지금 KIS live shadow 로 추가하지 않는다.
- `hold-rescue`는 여전히 별도 lifecycle 설계 전에는 실행하지 않는다.

근거:

- buy-avoid decision: `follow_up_candidate_proxy_only`
- rescue decision: `buy_avoid_candidate_only`
- rescue recommended action: `Keep KIS buy-avoid shadow running; do not add KIS buy-rescue shadow yet.`

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.md`

## 3. Buy-Avoid 결과

KIS shadow 회피율에 맞춘 target skip `0.3665`:

- 실제 skip: `0.3617`
- baseline trades: `7,807`
- skipped trades: `2,824`
- baseline net: `-538.040362%p`
- kept net: `-170.325157%p`
- net improvement: `+367.715205%p`
- positive improvement folds: `12/12`

해석:

- Cybos 5년 proxy 에서도 하락 위험 후보를 피하면 손실이 줄어드는 구조는 반복됐다.
- 다만 kept net 도 음수라서 모델 승격, gate 변경, 주문 정책 변경 근거가 아니다.
- KIS live 에서는 기존 buy-avoid shadow 순차 관측을 유지한다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`

## 4. Buy-Rescue 결과

고정 target rescue grid:

| target_rescue | actual_rescue | rescued_trades | rescued_net | nonnegative_fold_share | conclusion |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0.05 | 0.0560 | 33,135 | -3,526.921975%p | 0/12 | `diagnostic_only_negative_net` |
| 0.10 | 0.1120 | 66,340 | -7,240.276049%p | 0/12 | `diagnostic_only_negative_net` |
| 0.20 | 0.2199 | 130,233 | -14,474.937432%p | 0/12 | `diagnostic_only_negative_net` |
| 0.30 | 0.3256 | 192,843 | -21,994.446349%p | 0/12 | `coverage_out_of_bounds` |

해석:

- buy-rescue 가 실패한 이유는 표본 부족이 아니다.
- 상위 상승확률 후보를 가상 매수해도 평균 기대수익이 거래비용 `0.13%`를 넘지 못했다.
- 따라서 KIS live 에 buy-rescue shadow 를 붙이면 관측 비용만 늘 가능성이 크다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`

## 5. Guardrail 유지

유지할 기준:

- Cybos 결과만으로 active model 승격 금지.
- Cybos 결과만으로 gate 기준 변경 금지.
- Cybos 결과만으로 paper/live 주문 정책 변경 금지.
- KIS live 는 buy-avoid shadow 를 먼저 최소 10거래일 순차 검증.
- buy-rescue 는 재검토 전까지 shadow 후보로 올리지 않음.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`

## 6. 다음 권장안

권장안:

1. KIS live buy-avoid shadow 를 계속 누적한다.
2. buy-rescue 는 현재 보류한다.
3. full 12 fold 실행이 약 28분 걸리므로 잦은 재실행이 필요해지면 성능 최적화를 먼저 한다.
4. hold-rescue 는 entry/hold/exit lifecycle 설계와 synthetic test 를 먼저 만든 뒤 별도 진행한다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`
