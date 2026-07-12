# rescue/avoid profitability review — review_ver_30-11

- 작성 시각: 2026-07-11 KST
- 작성자: cowork(Claude)
- 기준 작업본: `2026-07-11-rescue-avoid-profitability-review-work_ver_30-11.md` (work_ver_30~30-11 통합)
- 리뷰 방식: 신규 shadow JSON(계좌 기준)·hold-rescue·challenger·leaderboard 수치 전수 대조, `portfolio_replay.py`·sqlite schema·lineage 마이그레이션 코드 직접 확인

---

## 1. 요약

1. **수치 주장 전수 일치.** 33,007행/15,711 episode/22거래일, baseline 계좌수익 -16.4010%(-1,434,798원), filtered -15.3384%(-1,341,838원), 차이 +1.0626%p(≈93,000원 절감·134만원 잔여 손실), 평균 거래 -0.10134%, 비음수 거래일 9.09%, status `rejected_random_control`, hold-rescue 161/37/-26,387원/13:22:2/21.43%, linear-score 156건·누적 -18.6402·평균 -0.11949(나눗셈 검산 일치), 전 challenger `promotable=false`·"No promotable challenger" — 전부 원본과 일치한다.
2. **이번 개편의 방향은 이 프로젝트에서 지금까지 중 가장 중요한 교정이다.** "겹치는 신호 수익률의 합(-3975%p)"과 "계좌 수익률(-16.4%)"을 분리하고, 리포트에 `sum_of_overlapping_signal_pct_points_not_account_return`이라는 자기 경고 라벨까지 박았다. 후보 판정을 fail-closed 게이트 사슬(표본→절대수익→기대값→일관성→delta→random control 2종→lineage)로 바꾼 것, no-trade ledger를 backfill 없이 0행에서 시작한 것, 결론("수익 후보 없음")을 숨기지 않은 것 모두 옳다.
3. **데이터가 말하는 핵심을 리뷰 관점에서 한 줄 추가한다: 신호의 비용 전 기대값이 사실상 0이다.** 평균 거래 순수익 -0.105%는 왕복 비용 0.108%와 거의 정확히 일치한다 — 즉 총(비용 전) 기대값 ≈ +0.003%/거래로, E1의 "IC ≈ 0" 결론과 정합한다. 여기에 turnover 31,585%/22일(하루 자본 ~14회전)이 곱해져 손실이 비용 지배 구조가 된다. **다음 연구의 최우선 지렛대는 threshold가 아니라 거래 빈도 축소(신호→episode 정의 강화)와 신호 자체의 정보량이다.** work_ver §5-§6의 방향 제시와 일치하며, 이 관찰이 그 근거를 정량화한다.

## 2. work_ver §7 확인 요청에 대한 답

| 질문 | 답 | 근거/조건 |
|---|---|---|
| portfolio replay 비용·현금·보유 제약 충분한가 | **대체로 충분, 조건 2개** | 다음 분봉 시가 체결·정수 수량·최대 비중/동시 보유·수수료/매도세/양방향 슬리피지 확인. 조건: (a) `sell_tax_rate=0.00018`(0.018%)의 근거를 문서화할 것 — 현행 국내 거래세·농특세 구조 및 KIS 모의 체결 비용과 일치하는지 검증 필요. 세율이 낮게 잡혔다면 현재의 적자 결론은 더 강해질 뿐이지만, 향후 후보 **통과** 판정 때는 치명적이 된다. (b) 부분체결·주문거부 미모델링은 리포트 limitations에 이미 명시됨 — Phase 2 전 canary 실측과 대조 필수 |
| buy-rescue eligibility가 safety/allocator 제약을 보존하는가 | **설계상 타당** | `signal_blocked`만 모집단, 현금/한도/pending/risk 차단 불가역 명시. 단 ledger 0행이라 실데이터 검증은 미완 — 10거래일 조기 진단 때 "차단 사유별 행 분포"를 첫 검증 항목으로 넣을 것 |
| lineage 없는 과거 예측의 진단 전용 제한 | **타당** | 33,007행 전부 legacy → 후보 판정 배제 옳다. 참고: 07-20 E1/E5 재측정도 legacy 구간 데이터를 쓰지만 E1/E5는 원래 진단이므로 모순 없음. 재측정 리포트에 "legacy lineage 구간" 명기만 하면 됨 |
| challenger promotion gate 과도/누락 | **방향 옳음, 누락 1** | 최소 30거래·클래스 5%·다수클래스 초과·비용 후 양수·portfolio 양수는 합리적. 누락: **재현성 조건** — 단일 평가에서 모든 기준을 우연히 넘는 후보를 막으려면 "연속 2회 재평가에서 promotable 유지" 같은 시간축 조건을 추가 검토(다중 비교는 후보 수가 늘수록 커진다) |
| 07-20 전 동결 + ledger 축적 범위 | **적절** | 사전등록 라운드와 충돌 없음 |

## 3. 방법론 문서 개정 필요 (다음 라운드 P0)

이번 라운드는 코드가 문서를 앞질렀다. `docs/Buy-Avoid-Random-Control-Methodology.md`는 여전히 signal-row 해석적 random control(§2)과 구창(06-11~07-03, 25,198행) anchor(§7)만 기술한다. 개정 항목:

1. **portfolio random control(episode-level, 시뮬레이션 기반)을 §5.5로 추가**: 200회 시행, 같은 veto 개수 무작위 episode 제외, p95 판정, 그리고 **사용 seed를 리포트에 기록**(현재 기록 여부 확인 후 없으면 추가 — 재현성 원칙은 signal-row와 동일해야 한다).
2. **§7 anchor 갱신**: 새 형식 기준 anchor 추가 — 06-11~07-10, 33,007행, baseline 계좌수익 -16.4010%, threshold 0.40 filtered -15.3384%, status `rejected_random_control`. 구 anchor는 "구형식(신호합 기준) 이력"으로 격하 보존.
3. §6에 후보 게이트 사슬(§3.2의 9개 조건) 요약 반영.

문서의 자기 규칙("공식 변경은 문서 먼저") 위반은 아니다 — 기존 공식·seed·부호는 불변임을 코드에서 확인했다. 그러나 새 검증 계층이 문서 밖에 있는 상태는 다음 Codex가 실수할 공간이므로 즉시 닫을 것.

## 4. 미세 지적

1. work_ver §8 "전체 pytest 508 passed" — 이번 라운드 신규 테스트(portfolio_replay, decision ledger 등) 추가와 정합하는 증가폭(+54)이나, cowork 환경에서 실행 불가라 수치 자체는 자기 보고 수용. 다음 라운드 서두에서 재보고 관례 유지.
2. 30~30-9는 `repo-deep-review` topic으로 별도 존재한다(별도 대화창 리뷰 이력으로 이해). 이 리뷰는 통합본 30-11의 주장을 저장소 실물로 검증한 것이며, 통합본과 실물 간 불일치는 발견되지 않았다.
3. early-exit "같은 bar close → 다음 분봉 시가" 교정은 look-ahead 제거로 옳다. 과거 early-exit 결과(z 등)와의 단절을 리포트에 한 줄 명시하면 이력 추적이 쉬워진다.

## 5. 운영자용 현재 지도

이번 라운드로 "덜 잃는 것"과 "버는 것"의 구분이 시스템에 박혔고, 그 기준으로 보면 **현재 수익 전략은 없다**가 공식 상태다. 시스템이 정직해진 것이지 나빠진 것이 아니다 — 이전 기준이었으면 후보로 보였을 것들이 전부 걸러졌다. 다음 관문 세 개: (1) 다음 정규장부터 lineage 완전한 예측 + no-trade ledger 축적(새 출발선), (2) 07-20 장후 사전등록 E1/E5 라운드(동결 유지), (3) 방법론 문서 개정(§3). 수익 탐색의 지렛대 순서는 거래 빈도 축소 → 신호 정보량(orderbook·h60 사전등록 트랙) → entry/exit 분리다.

## 6. 신뢰 수준

**높음.** 대규모 cross-cutting 변경임에도 수치 전수 일치, 안전선 준수(주문·gate·risk·VERSION 무접촉 확인), 자기 비판이 정확하다. 잔여 리스크는 방법론 문서 격차(§3)와 sell_tax 근거(§2) — 둘 다 다음 라운드에서 닫을 수 있는 크기다.
