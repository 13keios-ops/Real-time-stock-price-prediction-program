# buy-avoid validation verification — review_ver_23

- 작성 시각: 2026-07-05 KST
- 작성자: cowork(Claude)
- 기준 작업본: `2026-07-04-buy-avoid-validation-verification-work_ver_23.md`
- 직전 지시 문서: `2026-07-04-buy-avoid-validation-verification-and-codex-handoff.md` §4 (P0 실행·검증, P1 표현 격하)
- 리뷰 방식: work_ver_23의 수치 주장을 재생성된 JSON 원본, 코드, 로그 파일과 직접 대조

---

## 1. 요약

핵심 발견 3가지.

1. **work_ver_23의 수치 주장은 전수 대조 결과 전부 원본과 일치한다.** KIS shadow threshold 0.40의 random_control(expected -711.8525, excess +225.4772, z +4.6278, verdict `filter_worse_than_random_p95`, gate.passed=false, self_check_ok=true)과 Cybos aggregate 5개 target의 표(excess/z/verdict 15개 값)를 JSON에서 1건씩 확인했다. pytest "30 passed"도 테스트 개수 계산(신규 14 + shadow 1 + cybos 15 = 30)과 정합한다.
2. **Codex는 지시받은 범위를 정확히 지켰다.** 공식·seed(20260704)·z 경계(1.6449)·유한모집단 보정식이 원래 구현 그대로 남아 있음을 코드에서 확인했다. 금지선(app/risk/, config/, VERSION, gate) 접촉 흔적 없음. 이번 라운드는 "잘못할 확률" 우려가 실현되지 않은 라운드다.
3. **재생성 결과가 원래 가설보다 더 강한 결론을 보여준다.** KIS live에서는 5개 threshold 전부가 무작위 대조군을 이기지 못했고(0.40/0.45/0.50/0.54 = worse, 0.58 = indistinguishable), Cybos에서는 5개 target 전부가 통과했다(|z| 4.4~6.4). "Cybos에서는 작동, KIS live에서는 역작동"이 단일 threshold가 아니라 전 구간에서 재확인됐다.

## 2. handoff §4 지시 항목별 이행 확인

| 지시 | 이행 | 검증 근거 |
|---|---|---|
| P0-1 pytest 3개 파일 실행 | ✅ 30 passed | 테스트 수 계산 정합(14+1+15). 실패·수정 없음 = 수식 실행 검증 통과 |
| P0-2 shadow 재생성 + §7 anchor 대조 | ✅ | 새 JSON(generated_at 2026-07-04T22:41:34) 직접 확인 — anchor 8개 항목 전부 일치 |
| P0-3 Cybos proxy 재생성 | ✅ (약 31분) | 새 JSON(2026-07-05T02:27:46) 직접 확인, 로그 파일 2개 존재(0148 중단분, 0155 성공분 — "재시도" 서술과 정합) |
| P0-4 work_ver 기록 | ✅ | 이 문서의 대상 파일 |
| 공식/seed/부호 변경 금지 | ✅ | `buy_avoid_random_control.py`에서 DEFAULT_SEED_BASE=20260704, Z=1.6448536..., FPC 분산식 원형 확인 |
| P1 표현 소급 정리 | ⬜ 미이행 | Codex 스스로 "다음 작업 1"로 미룸. 다음 라운드 P0로 승격해야 함 |

## 3. 수치 대조 상세

### KIS shadow (threshold 0.40)

work_ver_23 §5 표의 9개 항목 전부 `latest-lightgbm-defensive-shadow-h15.json`과 일치. 추가로 z의 내부 정합성도 확인했다: excess 225.477 / z 4.6278 → 암묵적 σ(거래당) ≈ 0.695%로 15분물 net 수익률 분산으로 타당한 크기다.

work_ver가 언급하지 않은 사실: **나머지 threshold도 전부 미통과다.**

| threshold | z | verdict |
|---:|---:|---|
| 0.40 | +4.628 | worse_than_random |
| 0.45 | +3.860 | worse_than_random |
| 0.50 | +1.819 | worse_than_random (경계 근접) |
| 0.54 | +1.717 | worse_than_random (경계 근접) |
| 0.58 | +0.631 | not_distinguishable |

0.50/0.54는 z가 1.645 경계 바로 위라 methodology §9의 독립성 경고가 적용된다(단정 금지). 그러나 0.40/0.45는 경계에서 멀어 결론이 흔들리지 않는다.

### Cybos proxy (5개 target)

work_ver_23 §6 표의 값 전부 JSON과 일치(0.3665: actual -367.7152, expected -182.1662, excess -185.5490, z -6.3607). fold_verdict_counts = better 8 / indistinguishable 4로 특정 fold 지배 없음. `decision.status=follow_up_candidate_proxy_only`, `best_target_skip_rate=0.5` 일치.

methodology §7 anchor와의 관계도 work_ver의 설명이 맞다: 풀링 근사(-194.6)와 정식 fold 합산(-182.17)의 차이는 문서가 예고한 것이고, 부호 기대(excess<0)는 충족됐다.

## 4. 추가 발견 / 위험한 가정

1. **Cybos `decision.status`와 random_control이 이번엔 우연히 같은 방향이다.** conclusion 문자열 로직은 (호환성 때문에 의도적으로) random control을 반영하지 않는다. Cybos가 통과했기에 모순이 없지만, 만약 향후 미통과인데 `follow_up_candidate_proxy_only`가 찍히면 두 필드가 충돌한다. 소비자는 항상 random_control 쪽을 우선해야 한다 — 이 우선순위를 P1 표현 정리에 포함할 것.
2. **pytest를 `--user --break-system-packages`로 설치했다.** 저장소 변경은 아니지만 환경 변경이다. 기록돼 있으므로 문제 없음. 다만 재현성을 위해 requirements-dev 계열 파일이 없다면 다음 라운드에서 개발 의존성 명시를 고려할 만하다(운영자 결정 사항).
3. **KIS 0.58의 indistinguishable을 "덜 나쁨"으로 읽으면 안 된다.** n_skip=71뿐이라 검정력이 없는 것이지 선별력이 있다는 뜻이 아니다.
4. work_ver §8의 2번·3번 항목이 사실상 동일 문장(중복). 사소한 편집 문제.

## 5. 다른 thread와의 충돌 가능성

- 전이성 진단(`latest-cybos-kis-transfer-review.md`, source_stable_candidate 0개)과 이번 결론(Cybos 통과/KIS 미통과)은 같은 방향 — 충돌 없음.
- work_ver_22의 "buy-avoid는 손실 축소 후보로 유지" 표현은 이번 결과로 공식 폐기 대상 — P1이 끝나야 문서 간 모순이 사라진다.

## 6. 종합 표

| 항목 | 평가 | 보강 필요 |
|---|---|---|
| pytest 실행·결과 보고 | 정확 | 없음 |
| shadow anchor 대조 | 정확(전 항목 일치) | 없음 |
| Cybos 재생성·표 | 정확(전 항목 일치) | 없음 |
| 금지선 준수 | 준수 확인 | 없음 |
| 해석·표현 | 방법론 문서 준수 | KIS 전 threshold 미통과 사실을 명시하면 더 완전 |
| P1 소급 정리 | 미이행 | **다음 라운드 P0** |

## 7. 다음 단계 권장

- **Codex P0**: 문서/대시보드에서 buy-avoid 표현을 "재검증 필요, 무작위 대조군 대비 우위 미확인"으로 소급 통일. 이때 "conclusion 문자열보다 random_control 필드가 우선"이라는 해석 우선순위도 함께 명문화.
- **Codex P1**: KIS-Cybos를 같은 random-control 정의로 나란히 놓는 비교 요약 1장(방법론 차이 — 고정 threshold vs fold 보정, cost 0.108 vs 0.13 — 각주 포함).
- **Codex P2**: IC 계산 → EV 필터 → regime 조건부 실험 순서 유지. 각 실험에도 random-control 필드 필수.
- **운영자 결정**: 07-04~07-18 관측 구간에서 KIS 역선별 패턴 재현 여부 확인 전까지 buy-avoid 관련 어떤 정책 반영도 보류(현행 유지).

## 8. 신뢰 수준

**높음.** 이번 라운드는 수치 주장 전수 일치 + 지시 범위 정확 준수 + 금지선 무접촉으로, 최근 라운드 중 가장 깨끗하다. 남은 리스크는 구현이 아니라 표현 정리(P1)와 KIS 패턴의 재현성 확인이며, 둘 다 다음 라운드에서 닫을 수 있는 크기다.
