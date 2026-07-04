# buy-avoid validation verification — review_ver_25

- 작성 시각: 2026-07-05 KST
- 작성자: cowork(Claude)
- 기준 작업본: `2026-07-05-buy-avoid-validation-verification-work_ver_25.md`
- 직전 리뷰: review_ver_24 (지적: 검증 실행 보고 누락, 문서 이중화) + 대안 계획서 Phase 1 (E1·E6)
- 리뷰 방식: E1/E6 JSON 원본 전수 대조, 신규 스크립트 2개 구현 검토, 판정 기준 적용 검산

---

## 1. 요약

1. **E1(IC)은 수치·구현·판정 모두 정확하다.** JSON의 일별 IC 17개를 직접 평균 내 mean_daily_ic 0.004754, t_stat 0.3673을 재계산으로 확인했다. Spearman 구현도 동순위 평균처리(average rank)가 올바르고, `preregistered_criteria`가 계획서 문구 그대로 하드코딩돼 있다. down 확률의 IC ≈ 0 판정과 "threshold 튜닝 중단" 결론은 타당하며, shadow에서 본 역선별(z +4.63)과도 정합한다 — down 신호가 사실상 노이즈라는 일관된 그림이다.
2. **E6(cost/horizon)은 산수는 맞지만 모집단 구성에 중대한 보강 필요가 있다.** breakeven 0.6355 검산 일치, h30 no_labels 처리도 계획 준수. 그러나 h15 rows 6,281,164는 `feature_labels` 전체이고, 이 중 약 96%가 Cybos 5년 historical(199종목)이다. 즉 **"h15 중위 변동이 비용을 못 넘는다"는 경고가 KIS live 표본이 아니라 Cybos 지배 표본에서 나온 것이다.** 전이성 리뷰 기준 KIS live는 non-flat 라벨 비중이 Cybos의 약 2배(≈50% vs 26%)라 KIS live만 떼면 중위 |변동|이 0.216을 넘을 가능성이 실재한다. 결론이 뒤집힐 수 있는 지점이므로 source별 분리 재계산 전까지 E6 경고를 "구조적 확정"으로 취급하면 안 된다.
3. **review_ver_24 미완(검증 보고)은 닫혔으나 절반만이다.** §2.1에 30 passed를 기록했지만 그 명령은 기존 테스트 3파일뿐이고, 신규 `test_signal_ic.py`·`test_cost_horizon_diagnostics.py`를 포함한 실행 결과는 보고에 없다.

## 2. 검증 상세

| work_ver_25 주장 | 판정 | 근거 |
|---|---|---|
| E1 표 수치 8개 | ✅ 전부 일치 | JSON 대조 + mean/t-stat 독립 재계산 |
| E1 판정 `signal_quality_insufficient`, E2/E3 중단 | ✅ 기준 정확 적용 | \|0.00475\|<0.02 → 계획서 기준 그대로 |
| E1 preregistered_criteria 하드코딩 | ✅ | JSON에 계획서 인용 포함 |
| E6 표 수치(h15/h30/h60) | ✅ 일치, breakeven 검산 일치 | (0.34242+0.108)/(0.36636+0.34242)=0.6355 |
| E6 판정 `filter_tuning_only_warning=true` | ⚠ 산식은 맞으나 모집단 문제 | 아래 §3 |
| 검증 실행 보고(30 passed 등) | ⚠ 절반 | 신규 테스트 2파일 실행 결과 미보고 |
| 문서 반영 4건 | ✅ | Execution-Plan 715행 등 확인 |
| 금지선 | ✅ | read-only, 공식/seed 무접촉 |

## 3. 핵심 보강 지시 — E6 모집단 분리 (다음 라운드 P0)

`_horizon_values()`가 source 구분 없이 `feature_labels` 전체를 집계한다. 정책 판단 대상은 KIS live인데 표본은 Cybos가 지배한다. 조치:

1. E6 리포트에 **source별 분리 표** 추가: (a) KIS live 심볼·기간 표본(가능하면 E1과 같은 baseline buy join 기준도 병기), (b) Cybos historical 표본, (c) 전체(현행, 참고용). feature_labels에 source 컬럼이 없으면 KIS live 심볼 10개 + 2026-06-11 이후 기간으로 근사 분리하고 근사 방식을 JSON에 기록.
2. 사전 등록 기준은 동일 공식을 KIS live 부분집합에 적용: `KIS live median_abs < 0.216` 여부가 정책 관련 판정이다. Cybos 표본 판정은 참고용으로 격하.
3. 결과가 어느 쪽이든 work_ver에 "표본 구성 비율"을 명기할 것.

## 4. 추가 발견 (Codex가 표로만 남기고 논의하지 않은 것)

**probability_up의 IC가 +0.0217, t=1.947로 기준(2.0)에 근소 미달이다.** down 신호는 노이즈지만 up 신호에는 올바른 방향의 약한 정보 흔적이 있다. 17일 표본에서 t 1.95는 우연일 수도 있으므로 지금 정책화하면 안 되지만, work_ver_25 §6의 "신호 품질 개선 트랙"에서 가장 싼 첫 실험 후보다: 07-04~07-18 구간이 닫히면 같은 사전 등록 기준(mean≥0.02, t≥2.0)으로 up IC만 재측정 — 새 코드 불필요, 기간 인자만.

## 5. 다음 단계 권장

- **Codex P0**: §3의 E6 source 분리 재계산 + 신규 테스트 포함 전체 pytest 결과 보고.
- **Codex P1**: 07-18 구간 마감 후 E1 재측정(up IC 재현성 포함, §4) + E5 역발상 관찰(계획서 Phase 3).
- **Codex P2**: h60 트랙 사전 등록 설계 초안(비용 구조는 유리하나 신호·체결·gate 전부 미검증임을 전제로) — 실행은 운영자 승인 후.
- **운영자 결정**: E6 분리 결과가 나올 때까지 "h15 구조적 흑자 불가" 결론의 대외 확정 보류.

## 6. 신뢰 수준

**중상.** 수치 정확성과 절차 준수는 이전 라운드들과 같은 수준으로 좋다. 다만 E6 모집단 구성은 결론의 적용 범위를 바꿀 수 있는 실질적 문제라, 이번 라운드의 "h15 필터 튜닝 무의미" 판단 중 IC 근거(E1)는 확정, 비용 구조 근거(E6)는 분리 재계산 대기 상태로 본다.
