# buy-avoid validation verification — review_ver_28

- 작성 시각: 2026-07-06 KST (장후)
- 작성자: cowork(Claude)
- 리뷰 대상: `2026-07-05-buy-avoid-validation-verification-work_ver_28.md` + logbook 기준 07-05~07-06 운영 작업 일체(mismatch recheck wrapper, 주말 차단, `docs/Model-Research-PreRegistration.md`, 07-06 장후 체크)
- 리뷰 방식: work_ver_28 주장 + logbook 4개 entry의 산출물(JSON/스크립트/테스트)을 직접 대조

---

## 1. 요약

1. **work_ver_28(P1)은 정확하다.** 전체 pytest 454 passed 보고로 review_ver_27의 마지막 잔여 항목이 닫혔고, 테스트 증가분(443→454, +11)의 출처도 확인했다 — 새로 추가된 mismatch recheck 관련 테스트(`test_paper_kis_mismatch_recheck.py` 등)다. "07-18은 토요일이므로 이후 첫 거래일 장후로 재측정을 옮긴다"는 자체 판단도 옳다(2026-07-18 실제 토요일).
2. **work_ver 없이 진행된 운영 작업 3건도 전부 실물 확인됐다.** (a) mismatch 장후 재확인 wrapper(`recheck_paper_kis_mismatch.py/.sh`, 장중·주말 차단, align 미수행) + 테스트, (b) `docs/Model-Research-PreRegistration.md` — Cybos-KIS 격차 가설 5개, orderbook 피처 가설 4개(OB-1~4), h60 트랙 사전 등록 초안까지 갖춘 좋은 문서다, (c) 07-06 장후 체크 — 장후 학습 ok(16:15), label refresh ok(16:49), challengers keep_active(top challenger는 trades=2라 표본 무의미 — 과대 해석 안 한 서술 정확), hold-rescue replay 20:42 갱신(`diagnostic_only_no_hold_rescue_candidate`).
3. **mismatch 5종목이 단일 원인으로 수렴·지속되고 있다.** 07-06 재확인 결과 5종목(005380/035420/086520/105560/247540) 전부 `kis_account_snapshot_vs_order_fill_ledger_divergence` — 로컬 paper 수량은 주문·체결 원장과 일치하는데 KIS 계좌 스냅샷만 다른 패턴이다. 원인이 좁혀진 것은 진전이며, 자동 align을 하지 않고 관찰 유지한 판단도 안전 원칙에 맞다.

## 2. 검증 상세

| 주장 | 판정 | 근거 |
|---|---|---|
| 전체 pytest 454 passed | ✅ 정합 | +11 증가분 = recheck 테스트 신규 추가와 일치, logbook 2건에서 동일값 재보고 |
| 07-18 토요일 → 첫 거래일 장후 이동 | ✅ 달력 확인 | 재측정 조건이 Execution-Plan 309-310행과 PreRegistration §4에 명문화됨 |
| 07-06 mismatch recheck | ✅ | `latest-paper-kis-mismatch-recheck.json`: 5종목·root cause 5×동일·assessment `needs_review`·broker_open_order_count=1 전부 일치 |
| 07-06 장후 학습/label refresh ok | ✅ | `latest-post-close-ml.json` status=ok, 2026-07-06 완료 확인 |
| challengers: keep_active, top challenger 표본 2건 | ✅ | centroid-challenger 0.298914 / trades_taken=2 확인 |
| hold-rescue replay 07-06 | ✅ | generated_at 2026-07-06T20:42, `diagnostic_only_no_hold_rescue_candidate` |
| 금지선 (align/주문/gate/config 미접촉) | ✅ | recheck 리포트에 align 미수행 기록, 문서 서술 일관 |

## 3. Model-Research-PreRegistration.md 평가

전반적으로 계획서(2026-07-05 alternative plan)의 원칙을 정확히 계승했다. 특히 (1) 후보 3건 재현성 관문에 review_ver_27 기준(같은 종목·같은 방향·|t|≥2.0)을 그대로 박은 점, (2) 105560 p_flat 병기 지시 반영, (3) h60 금지선(비용 여유가 보여도 주문 정책 금지) 명시가 좋다.

보완 2가지 (07-18 전 문서 수정만, 실험 아님):

1. **orderbook 가설(OB-1, OB-2)의 다중 비교 수를 사전 고정할 것.** "decile별·종목별·시간대별"로 열어두면 검정 수가 수십 개로 늘어난다. 실험 전에 "이번 라운드에서 보는 조합 수 k"를 문서에 숫자로 박고, k에 맞는 t 기준(계획서 공통 규칙 3)을 정해야 한다.
2. **h60 초안의 "사전 기준 통과" 문구에 구체 수치를 넣을 것.** daily IC 기준은 있으나 순손익 random-control의 z 기준, 최소 거래일 수가 빠져 있다. 실행 승인 전에 확정하면 된다.

## 4. 남은 구멍 — KIS read-only probe 3종 (다음 라운드 P0 후보)

07-04 이후 리포트 기준 live-readiness는 여전히 token_refresh/account_snapshot/system_clock `KisApiError`로 blocked였는데, 이번 주 작업 목록에 이 원인 분리·해결의 흔적이 없다. mismatch의 root cause가 "KIS 계좌 스냅샷 쪽 divergence"로 좁혀진 지금, **account_snapshot probe 실패와 mismatch가 같은 뿌리(모의계좌 스냅샷 API의 신뢰성)일 가능성**도 점검할 가치가 있다. Phase 1a 진입의 실제 차단자는 07-18 재측정이 아니라 이쪽이다.

## 5. 다음 단계 권장

- **Codex P0**: KIS read-only probe 실패 3종의 원인 분리(§4). probe별 에러 상세(HTTP 코드, 토큰 상태, 발생 시각 패턴)를 수집해 "코드 문제 / 자격증명 문제 / KIS 모의서버 문제"로 분류. account_snapshot 건은 mismatch root cause와의 연관 여부 명시.
- **Codex P1**: §3의 PreRegistration 문서 보완 2건(다중 비교 k 고정, h60 수치 기준 확정).
- **예정대로**: 07-20(월) 장후 — E1 재측정 + E5 역발상 관찰 + 후보 3건 재현성 라운드.
- **운영자**: 특별 결정 사항 없음. 현행 동결 유지.

## 6. 신뢰 수준

**높음.** 이번 주 작업은 전부 "동결 기간에 해도 되는 일"의 범위 안에 있었고, 수치·산출물·금지선 모두 검증을 통과했다. 리뷰 관점의 유일한 아쉬움은 work_ver_28에 운영 작업(wrapper, PreRegistration 문서)이 목록으로 안 묶여 있어 logbook을 따로 추적해야 했다는 점 — 다음부터 work_ver에 "이번 라운드 변경 파일 전체 목록"을 한 표로 넣으면 리뷰가 더 빨라진다.
