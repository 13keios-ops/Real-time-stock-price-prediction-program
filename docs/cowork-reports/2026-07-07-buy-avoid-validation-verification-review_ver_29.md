# buy-avoid validation verification — review_ver_29

- 작성 시각: 2026-07-07 KST
- 작성자: cowork(Claude)
- 기준 작업본: `2026-07-07-buy-avoid-validation-verification-work_ver_29.md`
- 직전 리뷰: review_ver_28 (P0: KIS probe 3종 원인 분리 + mismatch 연관 규명, P1: PreRegistration 보완 2건)
- 리뷰 방식: probe 산출물 JSON 3종·readiness 리포트·Runbook·PreRegistration 문서 직접 대조, 테스트 수 검산

---

## 1. 요약

1. **P0의 결론이 검증됐고, 상황 인식이 중요하게 바뀌었다.** probe 3종의 실제 산출물을 확인한 결과 전부 ok다 — token_refresh(만료까지 30,441초), account_snapshot(shape ok, 포지션 4행), system_clock(skew 0.0755초, quote endpoint 대신 account 응답의 HTTP Date 재사용). **즉 "KIS read-only 3종 실패"는 더 이상 Phase 1 blocker가 아니다.** 새 readiness(07-07 00:05 KST 생성)의 차단 사유는 ws_recovery(stale_evidence), market_status, kill_switch로 교체됐다 — work_ver 표와 JSON이 정확히 일치한다.
2. **account_snapshot probe와 mismatch의 관계 규명이 논리적으로 타당하다.** probe는 "API 호출과 응답 형태가 정상인가"를 보고, mismatch는 "같은 모의계좌에서 스냅샷 수량과 주문·체결 원장 순수량이 다르다"는 데이터 수준 현상이다. probe가 통과하면서 mismatch가 지속된다는 사실 자체가 "같은 실패가 아니다"의 증거이고, Runbook에 이 구분과 후속 관찰 조건(다음 장후에도 지속 시 KIS 모의계좌 snapshot 원천 차이/외부 체결 가능성 검토)이 명문화됐다.
3. **P1 보완도 기준 이상으로 됐다.** OB-1은 k=12에 t≥2.8, OB-2는 k=24에 t≥3.0 — 검정 수가 큰 쪽에 더 보수적 기준을 매긴 것은 다중 비교 원리를 정확히 적용한 것이다. 사전등록 밖 발견을 `exploratory_only`로 격리하는 규칙, h60의 z≥2.5 + 최소 표본(10일/5종목/100거래) 미달 시 `observe_more` 분류까지, 요구한 것보다 짜임새 있다.

## 2. review_ver_28 지시 매핑

| 지시 | 이행 | 검증 근거 |
|---|---|---|
| P0 probe 3종 원인 분리 | ✅ | probe JSON 3종 전부 ok 확인(수치 일치), Runbook에 error_category별 코드/자격증명/KIS서버 분류표 신설 확인 |
| P0 account_snapshot-mismatch 연관 명시 | ✅ | Runbook 133-137행 — "관련 있지만 같은 실패 아님" + 후속 관찰 조건 |
| P1 다중 비교 k 고정 | ✅ | OB-1 k=12/t≥2.8, OB-2 k=24/t≥3.0(구성까지 명시: 종목×방향×시간대×horizon) |
| P1 h60 수치 기준 확정 | ✅ | z≥2.5, empirical p 5% 밖, 최소 표본 3조건 |
| 금지선 | ✅ | read-only probe만 실행, 실험·정책·gate 무접촉 |

검증 보고: 관련 unittest 22개 통과 주장은 테스트 함수 수 검산(5+9+8=22)과 정합. 전체 pytest 생략은 문서 중심 라운드라 수용 가능.

## 3. 미세 지적

1. **§4 변경 파일 목록에 `review_ver_28.md`가 들어 있으나 실제로는 수정되지 않았다** (cowork가 파일 상태로 확인). git 미커밋 신규 파일이 목록에 섞인 것으로 보인다. 다음부터 "이번 라운드에서 내용을 바꾼 파일"과 "git status에 보이는 파일"을 구분할 것 — cowork 리뷰 문서를 Codex가 수정하는 것은 원칙적으로 금지이므로 이 구분은 중요하다.
2. probe ok의 checked_at이 모두 같은 시각(07-07 00:05 KST)의 단일 실행이다. "해결됨"의 확정은 **장전·장중 등 다른 시간대에서도 재현**되어야 한다 — 과거 실패가 rate limit성이었다면 호출량이 몰리는 시간대에 재발할 수 있다. 다음 장전 readiness 흐름에서 자연 확인될 것이므로 별도 작업은 불필요, 해석만 유보.
3. 남은 blocker 3종(ws_recovery/market_status/kill_switch)은 전부 fixture dry-run 기준이다. work_ver_29 §6의 신중론(市場status 수동 snapshot·kill switch 상태 파일은 live submit 정책과 닿으므로 별도 지시로) 동의 — **이건 운영자(Keios) 승인 사항으로 분류한다.**

## 4. 현재 지도 (운영자용)

이번 주 초 기준 Phase 1 진입을 막던 세 가지가 모두 움직였다: (1) KIS read-only 3종 → **해결됨(단일 시점 기준)**, (2) mismatch 5종목 → 원인 특정, KIS 모의계좌 스냅샷 쪽 divergence로 좁혀져 관찰 유지, (3) 남은 blocker → ws_recovery 증거 갱신, market_status 수동 snapshot, kill switch 상태 파일 3개로 교체. 연구 트랙은 07-20(월) 장후 E1/E5 재측정까지 동결이 유지되고 있고, 그 준비(사전등록 기준)는 완료 상태다.

## 5. 다음 단계 권장

- **운영자 결정 (이번 라운드의 실질 안건)**: market_status 수동 snapshot과 kill switch 상태 파일을 Phase 1 readiness 규격으로 준비하는 작업의 착수 승인 여부. 이 둘은 "live 주문을 내는" 작업이 아니라 "주문을 낼 수 있는 상태의 안전장치를 준비하는" 작업이지만, live submit 경로와 인접하므로 Codex가 별도 지시를 요청한 것은 옳다. 승인 시 fail-closed 원칙(파일 없으면 차단 유지) 그대로.
- **Codex P0 (승인 시)**: 위 두 blocker를 readiness 규격으로 준비 + 다음 장전 흐름에서 ws_recovery 실제 증거 재생성. probe 3종은 장전 시간대 재확인만.
- **예정 유지**: 07-20(월) 장후 E1 재측정 + E5 역발상 + 후보 3건 재현성 라운드.

## 6. 신뢰 수준

**높음.** 산출물 전수 대조 통과, 분류 논리 타당, 사전등록 보완은 요구 이상. 유보 1건(probe ok의 시간대 재현성)은 다음 장전에서 자연 해소된다. 이 topic의 리뷰 사이클은 이제 07-20 재측정 또는 readiness blocker 작업 착수 시점에 재개하면 된다.
