# Rescue/Avoid 수익성 리뷰 후속 작업 ver.33

- 작성일: 2026-07-12
- 입력 리뷰: `2026-07-12-rescue-avoid-profitability-review-review_ver_32.md`
- 작업 성격: E6 검산, 해석 경계 보강, 관측 구간 추적, entry 모델 사전등록 초안

## 1. 리뷰 판정

리뷰의 핵심 사실은 수용한다. 현행 비용 `0.29%`를 적용한 E6의 행수, 분포, 판정과 broad KIS long-only 손익분기 참고 승률 h15 `0.724041`, h60 `0.624676`은 실제 산출물과 일치한다. E6는 같은 수치를 반복 재생성하는 실험으로 늘리지 않고 고정 진단 기준으로 유지한다.

다만 다음 해석은 그대로 채택하지 않았다.

1. 위 손익분기 승률과 현재 모델의 약 39% 수치를 직접 비교할 수 없다. 모집단, 행동, label, threshold가 서로 다르다. E6 값은 모든 미래수익을 long-only로 거래한다고 가정한 구조 참고값이고, 39%는 3분류 또는 방향 거래 평가다.
2. 실현 p75 수익률은 미래에 확정되는 값이라 entry 시점 필터로 쓸 수 없다. 이를 사용하면 미래 정보 누출이다.
3. 거래 빈도를 무작위로 4분의 1로 줄이면 총손실 규모는 줄 수 있지만 거래당 기대값은 개선되지 않는다. 저빈도 자체를 alpha로 보지 않는다.

따라서 고정 `62.5%+` 같은 단일 승격 기준을 만들지 않았다. 앞으로는 같은 실행 후보군에서 평균 이익, 평균 손실, 비용으로 동적 손익분기 승률을 계산한다.

## 2. 새로 확인한 데이터 경계

E6 리포트에 source/horizon별 실제 관측 시작과 종료 시각을 추가했다.

| 모집단 | h15 | h60 |
|---|---|---|
| KIS broad | 2026-06-11 08:30 ~ 2026-07-10 14:59 | 2026-06-11 08:30 ~ 2026-07-10 14:19 |
| KIS baseline-buy join | 2026-06-11 09:15 ~ 2026-07-10 14:59 | 2026-06-11 09:15 ~ 2026-07-10 14:19 |
| Cybos historical | 2021-01-04 09:00 ~ 2026-06-10 15:04 | 2021-01-04 09:00 ~ 2026-06-10 14:19 |

KIS broad는 `08:30`부터라 장전 행을 포함한다. 시장 구조 진단에는 쓸 수 있지만 실제 entry 모델의 실행 성과 모집단으로 바로 쓰면 안 된다. 실행 후보 평가는 regular-session decision episode, 완전한 model/feature lineage, 실제 의사결정 시점에 알 수 있던 값만 사용한다.

baseline-buy join의 손익분기 참고 승률은 h15 `0.748325`, h60 `0.646466`이다. broad KIS보다 오히려 높으므로 단순히 baseline 신호만 골라도 비용 문제를 해결하지 못한다.

## 3. 구현과 문서 조치

- `scripts/summarize_cost_horizon_diagnostics.py`: source/horizon와 baseline-buy join의 관측 구간 생성 및 Markdown 노출
- `tests/test_cost_horizon_diagnostics.py`: 관측 시작/종료와 baseline join 이전 행 제외 검증
- `docs/Model-Research-PreRegistration.md`: 동적 손익분기, 실행 모집단, 미래 p75 금지, no-trade coverage, random control, 동일 portfolio replay를 포함한 entry 모델 사전등록 초안
- 기준 문서와 운영 피드백: 현재 사실, 해석 경계, 동결 범위, 반복 방지 규칙 동기화

## 4. 검증

- 좁은 E6 테스트: `3 passed`
- 전체 pytest: `515 passed, 67 subtests passed`
- 전체 unittest: `Ran 515 tests ... OK`
- E6 실제 재생성: 기존 수치와 판정 불변, 관측 구간만 추가
- dashboard build 성공, server/API 응답 정상
- cleanup: `86개`, `94,231,041 bytes` 정리
- 주말 상태: live runtime 정상 정지, watchdog running/fresh, dashboard와 startup launcher 정상

## 5. Codex 의견과 다음 방향

이번 리뷰로 rescue/avoid가 수익 엔진이라는 근거가 새로 생긴 것은 아니다. 현재 h15 구조에서는 비용을 이길 entry 정보가 아직 증명되지 않았고, h60은 가격 변동 여유가 상대적으로 크지만 신호 정보량과 실제 portfolio 수익은 미검증이라는 경계가 더 명확해졌다.

다음 모델은 단순 정확도 경쟁보다 다음을 직접 검증해야 한다.

1. 진입 시점 정보로 비용 후 기대값이 양수인 소수 후보를 구분할 수 있는가.
2. no-trade 선택이 어느 정도이며 무작위 거래 축소보다 나은가.
3. 겹치는 15분/60분 표본을 독립 거래로 세지 않고 실제 포트폴리오 순이익과 최대낙폭이 개선되는가.
4. entry와 exit를 분리하고도 전체 lifecycle 결과가 양수인가.

2026-07-20 전에는 새 threshold/EV 탐색, h60 주문 정책, 종목별 주문 정책, active model/gate 변경을 하지 않는다. 다음 실질 작업은 사전등록된 E1/E5 한 라운드이며, 이후 동일 모집단의 entry/no-trade 후보 실험 진행 여부를 결정한다.

## 6. 다음 cowork 리뷰 시점

이 주제는 현재 추가 질문 없이 멈춰도 된다. 다음 cowork 리뷰가 필요한 시점은 2026-07-20 장후 E1/E5 결과와 완전 lineage decision ledger 상태를 함께 확보한 뒤다. 그 전에는 운영 장애, 데이터 lineage 누락, Phase 0 정합성 악화가 발견될 때만 예외적으로 재검토한다.

## 7. 안전 범위

모델 학습, threshold/EV tuning, h60 주문 정책, active model/gate, 실전 주문/취소, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, NAS 백업은 변경하지 않았다.
