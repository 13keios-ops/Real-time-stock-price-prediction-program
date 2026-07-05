# buy-avoid validation verification — review_ver_26

- 작성 시각: 2026-07-05 KST
- 작성자: cowork(Claude)
- 기준 작업본: `2026-07-05-buy-avoid-validation-verification-work_ver_26.md`
- 직전 리뷰: review_ver_25 (P0: E6 source 분리 재계산 + 전체 pytest 보고)
- 리뷰 방식: 재생성 JSON 전수 대조, split SQL 구현 직접 확인, breakeven 검산

---

## 1. 요약

1. **P0가 정확히 이행됐고, 결론 정정도 옳다.** source split 표의 24개 수치(4 source × h15/h60)를 JSON과 전수 대조해 일치를 확인했다. KIS live 근사 h15 중위 |변동| 0.3614%는 2×비용 0.216%를 넘고, breakeven 0.5672도 검산과 일치한다. **review_ver_25가 우려한 대로 결론이 실제로 뒤집혔다** — "h15 구조적 흑자 불가"는 Cybos 지배 표본(99.02%)의 착시였고, Codex가 이를 숨기지 않고 §7 self-review에서 자기 정정한 점은 높이 평가한다.
2. **전체 pytest(443 passed, 59 subtests)와 신규 테스트 3개 보고로 review_ver_24부터 끌던 검증 보고 문제가 완전히 닫혔다.**
3. **현재 상태 정리가 명확해졌다: 병목은 비용 구조(E6, 해소)가 아니라 신호 정보량(E1, 미해소)이다.** E2/E3 보류 유지 판단은 계속 타당하다.

## 2. review_ver_25 지시 매핑

| 지시 | 이행 | 검증 근거 |
|---|---|---|
| P0 E6 source 분리 (KIS live/Cybos/전체 + baseline join 병기) | ✅ | JSON `source_summaries` 4종, 근사 방식·source 컬럼 부재 명시(§2.1 지시 그대로) |
| P0 표본 구성 비율 명기 | ✅ | share_of_all_rows 0.98%/99.02% 기록 |
| P0 전체 pytest 보고 | ✅ | 443 passed + 신규 테스트 3 passed 별도 보고 |
| KIS live 기준 판정으로 격하/승격 | ✅ | `decision.policy_source=kis_live`, 전체 표본은 reference로 격하 |
| 금지선 | ✅ | read-only, 공식/seed 무접촉, schema 변경 없음(후보로만 제안) |

## 3. 수치 검증 상세

- KIS live h15: rows 61,527, median_abs 0.3614 > 0.216 → `covers_2x_cost` ✓. breakeven (0.5362+0.108)/(0.5995+0.5362)=0.5672 ✓.
- KIS live h60: median_abs 0.7173, breakeven 0.5261 — 비용 여유는 h60이 더 크다는 서술과 정합.
- Cybos h15 median 0.1883 — 기존 "전체" 결과(0.1894)가 사실상 Cybos였음을 확인. review_ver_25의 가설(KIS live는 non-flat 비중이 높아 중위 변동이 더 클 것)이 데이터로 확인됨(KIS live flat 비중 7.3% vs Cybos 22.5%).

## 4. 추가 발견 (다음 라운드에서 확인할 것)

1. **baseline buy join(64,173행)이 kis_live 근사(61,527행)보다 크다.** 매수 신호는 분봉의 부분집합이어야 하므로 순수하게는 역전이 불가능하다. SQL은 DISTINCT 처리가 돼 있으므로 중복 조인은 아니고, 가장 유력한 설명은 **baseline join에 날짜 하한이 없어 2026-06-11 이전(5월 등) 신호 구간이 포함**되는 것이다(kis_live는 06-11 이후로 자름). 오류라기보다 두 "KIS live 근사"의 기간 창이 다른 문제다. 조치: baseline join에도 `event_time >= 2026-06-11` 필터를 넣거나, 기간 차이를 method 문구에 명시할 것. 두 표본 모두 0.216을 넘어 이번 결론에는 영향 없다.
2. **preregistered_criteria 문구가 work_ver_25 버전에서 변경됐다** (primary_question이 KIS live 기준으로). 이번에는 결과를 보기 전에 리뷰(review_ver_25 §3)가 지시한 변경이므로 사전 등록 원칙 위반이 아니다. 다만 원칙 확인: **기준 변경은 항상 "결과를 보기 전 + 리뷰 문서에 근거"가 있어야 하며, JSON에 변경 이력 한 줄(`criteria_revision`)을 남기는 것을 권장**한다.
3. source lineage schema 제안(§6.2)은 합리적이나 운영 DB schema 변경 금지선에 걸리므로 별도 안전 검토 라운드로 분리한 판단이 맞다.

## 5. 현재 지도 (운영자용 한 문단)

지금까지의 실험으로 확정된 것: (1) down 신호로 거래를 걸러내는 buy-avoid는 KIS live에서 무작위만도 못하다(확정). (2) 그 원인은 threshold 선택이 아니라 down 신호 자체에 정보가 없기 때문이다(E1, 확정). (3) 15분 지평의 가격 변동폭 자체는 비용을 감당할 수 있다(E6 정정, KIS live 기준 확정). 즉 **구조는 살아 있고 신호가 죽어 있다.** 다음 승부처는 신호 품질이다 — up 신호의 약한 흔적(IC +0.022, t 1.95), orderbook 피처, 시간대/모멘텀 분해가 그 후보다.

## 6. 다음 단계 권장

- **Codex P0**: E1 신호 분해 — down IC ≈ 0의 원인을 시간대(open_early/midday/close)·종목·변동성 구간별 daily IC로 분해. up IC도 같은 분해 병기. 사전 등록: "어느 부분집합이든 |mean IC| ≥ 0.03 & |t| ≥ 2.5(다중 비교 보정, 부분집합 k≈9)를 넘는 곳만 후속 후보".
- **Codex P1**: §4-1의 baseline join 기간 필터 정합 + method 문구 갱신 (5분 작업).
- **Codex P2**: 07-18 마감 후 E1 재측정(up IC 재현성) + E5 역발상 관찰 — 기존 계획서 그대로.
- **운영자 결정**: h60 트랙 설계 착수 여부(비용 여유는 크지만 라벨·신호·체결 전부 미검증 — 신호 분해 결과를 본 뒤가 순서상 안전).

## 7. 신뢰 수준

**높음.** 수치 전수 일치, 자기 정정 투명, 지시 정확 이행. 유일한 잔여 의문(§4-1 행수 역전)은 결론에 영향 없는 기간 창 문제로 보이며 다음 라운드 P1로 닫으면 된다. 이 topic은 이제 "검증 방법론 정착" 단계를 끝내고 "신호 품질 개선" 단계로 넘어간다.
