# 2026-07-12 Rescue/Avoid Profitability Review Work ver.34

## 1. 요청

- cowork `review_ver_33`을 실제 코드와 최신 산출물에 대조한다.
- 수익 모델이 되도록 검토되고 있는지, 현재 모델·rescue/avoid·운영 전환 상태를 전체 흐름으로 다시 판정한다.
- 안전하게 가능한 후속 조치를 구현하고 검증한다.

## 2. 첫 결론

현재 실제로 통과한 수익 후보는 `0개`다.

다만 프로그램이 정확도만 반복 학습하는 상태는 아니다. 현재 평가 정본은 `예측 -> 결정 episode -> 주문 가능성 -> 체결 -> 비용 -> 포트폴리오 손익`으로 옮겨졌고, 아래를 모두 통과해야 후보가 된다.

- 현행 왕복비용 `0.29%` 차감 후 절대 손익 양수
- 거래당 기대값 양수
- 같은 거래 수를 뽑은 random control보다 유의하게 우수
- 여러 거래일과 서로 겹치지 않는 시간구간에서 재현
- 모델 artifact와 prediction lineage 완전
- 현금, 보유한도, 중복진입, 강제청산을 포함한 portfolio replay 통과

현재 후보가 0개인 이유는 이 기준이 작동해서 손실 전략을 걸러냈기 때문이다. Phase 2 실제 주문으로 넘길 수익 증거는 아직 없다.

## 3. review_ver_33 비판적 판정

cowork가 검산한 E6와 rescue/avoid 핵심 수치, 기존 기각·보류 결론은 실제 파일과 일치했다. 그러나 `주제 완료`로 닫기에는 아래 3건이 남아 있었다.

1. standalone hold-rescue replay의 CLI 기본 거래비용이 과거 `0.13%`였다.
2. E6 legacy key `cybos_historical`은 이름과 달리 순수 Cybos가 아니었다.
3. 최신 walk-forward 리포트는 구형 왕복비용 `0.108%`로 생성돼 현행 수익성 증거가 아니었다.

세 문제 모두 잘못된 자동 승격을 일으키지는 않았다. 기존 gate가 이미 후보를 차단했기 때문이다. 그러나 향후 해석 오류를 막기 위해 코드와 문서를 보강했다.

## 4. 데이터와 학습 상태

- KIS live 데이터 품질: `ok`
- 최신 거래일: `2026-07-10`
- 감시 종목: `10`
- raw market coverage: `0.952685`
- orderbook coverage: `1.019693`
- minute/feature closed coverage: `0.95`
- KIS 누적 거래일: 문서 기준 약 `50거래일`
- 장후 ML: `2026-07-10 16:17:58 KST`, `status=ok`, `quick-live-train`
- label refresh: `2026-07-10 16:50:42 KST`, `status=ok`

학습과 라벨 갱신은 실제로 실행되고 있다. 문제는 학습 미실행이 아니라 현재 피처와 모델이 비용 후 양수 신호를 만들지 못한다는 점이다.

## 5. 현재 모델 비교

active는 `baseline-h15-v1`이고 추천 조치는 `keep_active`, `promotion_applied=false`다. active 유지란 가장 안전한 기준선을 보존한다는 뜻이지 수익성이 입증됐다는 뜻이 아니다.

| 모델 | 3분류 정확도 | 거래/가상 거래 | 비용 후 결과 | 판정 |
| --- | ---: | ---: | ---: | --- |
| fresh-centroid | 0.314705 | 실제 4건 | 누적 `-7,680%p` | 표본·손익 실패 |
| baseline active | 0.277934 | 33건 | 평균 `-0.848549%`, 누적 `-28.002104%p` | 수익성 실패 |
| linear-score | 0.399640 | 156건 | 평균 `-0.301488%`, 누적 `-47.032194%p` | 다수 클래스보다 낮고 손익 실패 |
| LightGBM | 0.346248 | 방향 53건 | 평균 `-0.348534%`, 누적 `-18.472324%p` | 수익성 실패 |

LightGBM은 하락 적중률 `0.550897`이 상대적으로 높지만 보합 `0.216391`, 상승 `0.308530`이고 전체 성과가 낮다. threshold `0.66`에서 누적 `+4.525659%p`가 보였지만 거래가 9건뿐이라 우연 가능성이 크며 후보가 아니다.

최신 walk-forward는 119 folds, 5,952,343행, 3분류 정확도 `0.414466`이다. 다수 클래스 정확도 약 `0.418268`에도 못 미친다. 더구나 이 산출물은 비용 `0.108%`인 과거 증거이므로 현행 수익성 판정에는 사용하지 않는다.

## 6. Buy-Avoid

구조는 baseline의 매수 허용 순간에 LightGBM이 하락 위험을 높게 보면 해당 진입을 가상으로 제외하는 방어 필터다.

- 관측: `22거래일`, joined rows `33,007`
- threshold `0.40`: `9,002`행 제외, skip rate `27.273%`
- baseline portfolio return: `-38.1734%`
- filtered portfolio return: `-36.3645%`
- 차이: `+1.8089%p`
- 평균 거래: `-0.285710%`
- 비음수 거래일: `0/22`
- random-control: `filter_worse_than_random_p95`, z `+4.1266`

손실이 조금 줄었지만 여전히 큰 손실이고, 같은 수만 무작위로 뺀 경우보다 나쁜 행을 잘 골라낸 것도 아니다. 현재 판정은 `rejected_random_control`이며 주문에 적용하면 안 된다.

## 7. Buy-Rescue

buy-rescue는 baseline이 진입하지 않은 순간 중 상승 가능성이 높은 후보를 되살리는 가설이다.

- Cybos proxy의 고정/정밀 grid 전부 비용 후 평균이 음수다.
- 예: coverage `0.001`은 727건, 평균 총수익 `+0.005543%`, 비용 후 `-0.124457%`다.
- coverage `0.01`도 평균 총수익 `+0.047194%`, 비용 후 `-0.082806%`다.
- KIS live `serving_decision_ledger`는 아직 0행이다. 기능이 마지막 거래일 이후 구현돼 2026-07-13 정규장부터 진짜 no-trade 결정이 쌓인다.
- 과거 33,007행은 모델 lineage가 없어 정확한 live buy-rescue 원장으로 소급 변환하지 않는다.

따라서 실패 확정이 아니라 KIS live 평가는 아직 시작 전이다. Cybos 결과는 약하고, live 원장이 쌓인 뒤에만 다시 판정한다.

## 8. Hold-Rescue

hold-rescue는 기존 청산 시점을 LightGBM 상승 지속 확률로 조금 늦추는 별도 lifecycle 가설이다.

- replay 가능 lot: `161`
- threshold `0.40` 적용: `37`
- 현금손익 변화: `-26,387원`
- 개선: `13`
- 악화: `22`
- 비음수 거래일 비율: `21.4%`
- 최대 낙폭: `-3.05742%`
- 판정: `diagnostic_only_no_hold_rescue_candidate`

standalone CLI 기본 비용을 현행 `0.29%`로 고치고 리포트를 다시 만들었다. baseline과 rescue 양쪽에 같은 비용을 빼므로 delta 수치는 같았지만, 이제 리포트가 어떤 비용 세대를 사용했는지 숨기지 않는다.

## 9. E6와 Cybos/KIS 해석

- KIS h15 중위 절대변동: `0.376648%`, 보수적 2배 비용 기준 `0.58%` 미달
- KIS h60 중위 절대변동: `0.739523%`, `0.58%` 초과
- baseline-buy h15/h60: `0.365344%` / `0.718133%`

이는 h60이 비용을 이길 가격 움직임의 공간이 더 크다는 구조 진단일 뿐, h60 신호가 돈을 번다는 증거는 아니다.

E6의 `cybos_historical`은 source column이 없는 표를 `2026-06-11` 전후로 나눈 호환용 key다. 순수 Cybos 5년 데이터가 아니라 pre-KIS 혼합 근사치이며, 별도의 Cybos proxy 리포트와 구분해야 한다. 리포트에 이 사실을 명시했다.

## 10. 운영 전환 상태

- Phase 1b live read-only observation: 통과
- 의미: live token/account/system clock을 주문 없이 읽을 준비가 됐다는 뜻
- 의미하지 않는 것: 수익성 통과, 주문 허용, Phase 2 승인
- Phase 0 paper/KIS 정합성: `1/10`, 정합 0일, 불일치 1일
- mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 현금 차이: `714,840.96원`
- 총자산 차이: `1,346,940.96원`

Phase 2는 양수 비용 후 전략, Phase 0 정합성, real WS recovery, fresh market status, 유효 kill switch가 모두 충족될 때까지 시작하지 않는다.

## 11. 구현 조치

- `scripts/summarize_hold_rescue_paper_replay.py`: 공통 비용 정본 기본값 및 비용 메타데이터 추가
- `scripts/summarize_cost_horizon_diagnostics.py`: mixed pre-KIS identity와 legacy warning 추가
- `app/services/research.py`: 향후 walk-forward 결과에 `cost_model_version` 추가
- 관련 회귀 테스트 3개 파일 보강
- 현행 비용으로 hold-rescue와 E6 실제 리포트 재생성

주문 정책, threshold, active model, gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, NAS 백업은 변경하지 않았다.

## 12. 검증

- Python compile: 통과
- 좁은 관련 테스트: 통과
- 전체 unittest: `Ran 515 tests ... OK`
- 전체 pytest: `515 passed, 67 subtests passed`
- `git diff --check`: 통과
- JSON 구문 검사: 통과
- dashboard snapshot 재생성 및 server/API 응답: 통과
- cleanup helper: `86개`, `95,144,239 bytes` 정리, 보존 예외 확인

## 13. Codex 의견과 다음 방향

수익 모델을 만들기 위한 검토 방향은 맞게 바뀌었다. 정확도만 높아 보이는 모델, losing baseline보다 덜 잃는 필터, 작은 표본의 양수 threshold를 수익 후보로 오인하지 않도록 평가 정본이 강화됐다.

하지만 현재 피처/모델로 돈을 벌 수 있다는 증거는 없다. 계속 threshold를 바꾸면 과적합만 늘어난다. 다음 순서는 아래처럼 고정한다.

1. 2026-07-13부터 완전 lineage decision ledger와 Phase 0 유효일을 누적한다.
2. 2026-07-20 장후 사전등록된 E1/E5 한 라운드로 신호 재현성과 buy-avoid 역선별 부호를 확인한다.
3. 신호가 재현되면 h15 저빈도 entry와 h60을 동일 초기자금, 비용, 다음 실행 가능 가격, 보유한도, 강제청산 조건으로 비교한다.
4. 후보는 서로 겹치지 않는 시간구간 2개에서 모두 비용 후 양수여야 한다.
5. E1/E5가 실패하면 threshold 탐색을 멈추고 orderbook/시간대/변동성/원천 차이와 horizon 가설을 새로 사전등록한다.
6. exit/hold는 entry 확률을 재사용하지 않고 별도 목적함수와 lifecycle 데이터가 준비될 때 다시 설계한다.

다음 cowork 리뷰가 유효한 시점은 2026-07-20 E1/E5 결과가 나온 뒤다. 그 전에는 runtime 장애, lineage 미기록, Phase 0 증거 누락이 생길 때만 즉시 재검토한다.

## 14. 운영자 판단

현재 추가 운영자 결정은 없다. 정규장 데이터 수집과 paper-only 관측을 유지하며 실전 주문은 계속 차단한다.
