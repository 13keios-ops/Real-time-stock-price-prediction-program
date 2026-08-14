# 2026-08-15 Buy-Avoid Validation Verification Work ver.35

## 1. 요청과 범위

- `review_ver_27` §6에 사전등록된 E1/E5 고정 라운드를 26GB 운영 DB의 read-only snapshot에서 완결한다.
- E1 후보 3건의 재현성과 `105560` 확률 관계, E5 역선별의 두 번째 구간 재현성을 사전 기준으로 판정한다.
- threshold/EV, 종목별 주문 정책, h60 정책, active model/gate, 실전 주문은 변경하지 않는다.

## 2. 실행 증거

- 실행 시각: `2026-08-15T01:50:49+09:00`
- 실행 명령: `./scripts/run_preregistered_e1_e5_round.sh --snapshot-timeout-seconds 1800 --execute`
- 실행 횟수: 새 명시 승인 범위에서 정확히 1회
- 고정 구간: `2026-07-04~2026-07-18`
- 26GB snapshot: 830.5초, `quick_check=ok`
- 라운드 상태: `ok`
- 네트워크/주문/학습 호출: 각각 `0회`
- 자동 정책, active model, gate 변경: `false`

## 3. E1 결과

- joined rows: `14,004`
- usable trade days: `9`
- 사전등록 후보 재현: `0/3`
- 전체 `probability_down`: mean daily IC `-0.019927`, t-stat `-0.730524`
- 판정: `signal_quality_insufficient`, `proceed_to_e2_e3=false`
- `005380 probability_up`: mean IC `0.051887`, t `1.149023`, 방향은 같지만 기준 미달
- `035420 probability_down`: mean IC `+0.038837`, t `0.826049`, 원래 가설과 방향 반전
- `105560 probability_down`: mean IC `+0.008394`, t `0.193626`, 기준 미달
- `105560` p_down/p_up daily IC Pearson `0.897613`, same-sign `7/9일`; p_flat IC도 유의하지 않다.

## 4. E5 결과

- validated temporal lineage rows: `6,195`
- complete lineages/trade dates: `4/4`
- 고정 threshold: `0.40`
- random 대비 excess: `-96.7921%`
- z-score: `-3.4051`
- 판정: `reverse_selection_not_reproduced_second_interval`
- policy review eligible: `false`

## 5. Codex 비판적 의견

E1은 세 후보 모두 재현되지 않았고 E5는 random control보다 강하게 열위다. `105560`의 높은 p_down/p_up 양의 상관은 독립 방향 정보보다 세 class 확률 제약이나 공통 regime 영향 가능성을 강화한다. 이 결과를 threshold 또는 종목별 예외로 구제하면 사전등록 목적을 훼손하고 과적합 위험만 키운다.

따라서 기존 E1/E5 후보는 종료한다. 지금은 수익 후보가 0개인 상태가 올바른 fail-closed 결과다. Phase 2 주문으로 넘길 근거는 없다.

## 6. 다음 방향과 기준

1. orderbook×regime, 시간대, 변동성, source, horizon의 비교 조합과 다중 비교 수를 새로 사전등록한다.
2. entry 시점에 관측 가능한 피처만 사용하고 실현 p75 미래변동을 선별 변수로 쓰지 않는다.
3. current cost `0.29%`, 동일 초기 현금/체결/보유 제약의 portfolio replay, same-count random control을 고정한다.
4. 비중복 평가구간 최소 2개와 최소 표본을 통과하기 전에는 `research_candidate`로 올리지 않는다.
5. entry와 exit/hold 목적함수는 분리한다.

계속 진행 기준은 새 사전등록 후보가 절대 비용 후 기대값과 portfolio return 모두 양수이고 random control 및 비중복 구간을 통과하는 경우다. 보류 기준은 같은 방향의 새 사전등록 실험 3회 연속 개선 없음이다.

## 7. 구현과 검증

- 성공한 snapshot 뒤 partial SQLite의 `-journal/-wal/-shm` sidecar를 정리하도록 helper를 보강했다.
- 성공 경로 회귀 테스트를 추가했다.
- 주문 정책, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, NAS 백업은 변경하지 않았다.
- 다음 cowork 리뷰 시점은 이 결과 검산과 새 사전등록 범위 확정 시점이다.

## 8. 근거

- `runtime-data/reports/research/preregistered-e1-e5-20260718/latest-completed-round.json`
- `runtime-data/reports/research/preregistered-e1-e5-20260718/runs/20260815-015049-710415/preregistered-e1-e5-round.md`
- `runtime-data/research-snapshots/dev-20260815-015049.manifest.json`
- `docs/Model-Research-PreRegistration.md`
