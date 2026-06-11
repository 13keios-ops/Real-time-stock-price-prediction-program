# 저장소 핵심목표 · 방향성 · 진행상태 심층 리뷰 (2026-06-11)

- 리뷰어: cowork(Claude)
- 리뷰 방식: 정본 저장소 직접 확인 (README, logbook, Production-Transition-Progress, work_ver_16, runtime-data 최신 리포트 JSON)
- 성격: 특정 work_ver 리뷰가 아니라 저장소 전체 방향성 점검

## 1. 핵심 목표 (확인 결과)

README 기준 이 저장소의 목표는 "바로 돈 버는 단일 모델"이 아니라 다음 반복 루프를 가진 로컬 투자 연구·운영 시스템이다.

`데이터 수집 -> 전략 후보 생성 -> 비용 반영 검증 -> walk-forward 검증 -> paper 운용 -> 소액 실전 검증 -> 리스크 제한 운용 -> 일일 분석 -> 승격/폐기`

안전 원칙: fail-closed(증거 없으면 통과 금지), kill switch, phase gate, `ALLOW_LIVE_ORDERS=false` 유지. 수익 목표는 "손실일을 작게, 유리한 장세에서 기회 확대"이며 월 +50%는 장기 stretch target으로만 기록.

## 2. 현재 위치 (사실 검증 완료)

| 항목 | 확인된 사실 | 출처 |
|---|---|---|
| Phase 0 (paper + 브로커 미러링) | 진행 중. 2026-06-10 정합성 `needs_review` (로컬에만 373220 1주) | `latest-paper-dual-account-match.json` |
| Phase 1a (모의계좌 read-only 리허설) | 2026-05-28 1회 통과. 단 fixture dry-run + synthetic WS 증거 | `latest-readiness.json` (`source=fixture-dry-run`) |
| Phase 1b (실전 계좌 read-only) | 대기. 실전 credentials 미준비 | Production-Transition-Progress |
| Phase 2/3 (실전 주문) | 미시작. 모델 승격 기준 미충족이 명시적 blocker | 동일 문서 |
| Active 모델 | `baseline-h15-v1` 유지, 최신 challenger `keep_active` | `latest-challengers-h15.json` |
| 장후 자동화 | 2026-06-11 quick maintenance `status=ok` | `latest-post-close-ml.json` |
| 테스트 | 375개 통과 (2026-06-11 logbook 기준) | logbook |
| cowork 리뷰 루프 | **work_ver_16(5-23) 이후 리뷰 없음.** 6월 작업은 logbook에만 기록 | cowork-reports 폴더 파일 목록 |

## 3. 방향성 평가 — 잘 가고 있는 것

1. **안전 설계가 문서가 아니라 코드로 존재한다.** read-only client, per-key evidence freshness, kill switch missing=차단, holdout mismatch 시 승격 차단 등은 실제 구현·테스트되어 있고, 5-23 readiness 재실행에서 stale 증거가 실제로 차단된 것은 fail-closed가 작동한다는 증거다.
2. **자기기만을 줄이는 지표 분리가 진행 중이다.** 예측 정확도 vs 수익률 분리(6-10), 3분류 지표·혼동행렬 도입(6-11), LightGBM shadow serving(승격 없이 비교만) — 모두 올바른 방향이다.
3. **운영 자동화가 실제로 매일 돈다.** 장전 readiness, 장후 maintenance/label refresh, watchdog 심박 체크가 상태 파일로 검증 가능하게 남는다.

## 4. 비판적 발견 (중요도 순)

### F-1. 예측력(알파)이 목표 대비 가장 뒤처져 있는데, 작업 비중은 인프라에 치우쳐 있다 — P0급 구조 문제

- active baseline의 3분류 정확도 **26.6%** — 무작위(약 33%)보다 낮다.
- LightGBM challenger는 36.1%이지만 `holdout_window_mismatch`로 승격 불가 상태가 지속된다.
- 실제 성과: KIS 모의계좌 누적 **-6.98%**(6-09 화면 기준), 신호 replay 가상 수익률 **-9.07%**, 실제 paper FIFO 청산익 +10,687원(+0.075%).
- 즉 "예측이 비용 차감 후 돈을 벌 수 있다"는 핵심 가설이 아직 한 번도 입증되지 않았다. 반면 5~6월 작업의 대부분은 대시보드/운영/readiness 인프라였다. 인프라 성숙도는 Phase 2급인데 알파는 Phase 0 통과 수준에도 못 미친다. Phase 2 진입 조건에 모델 성능 선행 게이트가 문서화된 것(work_ver_16 E)은 옳지만, **게이트를 통과할 모델을 만드는 연구 작업 자체가 로드맵에서 우선순위를 잃고 있다.**

### F-2. `virtual_direction_cumulative_net_return_pct` 오독 위험 — P0급 해석 문제

최신 challenger 리포트의 후보별 값: +14.9% / **+111.0%** / -303.3% / **-1792.5%**. -1792%는 복리 수익률로는 물리적으로 불가능하므로 이 지표는 거래별 수익률 단순 합산이다. 매도 신호를 가상 숏으로 치환한 연구용 방향 지표이며 체결·비용 현실성이 없다. LightGBM의 +111%를 "수익 가능"으로 읽으면 안 된다. 대시보드/리포트에 "단순 합산, 연구용, 실거래 불가 수치" 경고를 지표 옆에 고정 표기할 것을 권장한다.

### F-3. cowork 리뷰 루프가 3주째 끊겨 있다 — P1

work_ver_16(5-23)에 대한 review_ver_16이 없고, 6월의 대규모 변경(shadow serving 저장 경로, 3분류 지표, 예측흐름 표 개편, broker sync 보강, wsl_ops 검증 변경)은 모두 무리뷰로 누적됐다. "Phase 1b 구체화 후 리뷰" 규칙이 의도였더라도, 결과적으로 **주문·계좌 정합성에 닿는 코드 변경이 검증 루프 밖에서 쌓이는 빈틈**이 됐다. 6월 변경 통합 리뷰(review_ver_16) 1회를 권장한다.

### F-4. 진행판·readiness 증거가 실상보다 오래됐다 — P1

- `latest-readiness.json`은 2026-05-28 fixture dry-run 그대로 2주 stale. per-key freshness 기준으로는 이미 전부 만료 상태다(문서 스냅샷의 "status=ok, passed=true" 인용은 당시 사실이지만 현재는 무효).
- Production-Transition-Progress "마지막 갱신 2026-06-09" — 이후 이틀치 변경 미반영.
- Phase 1a의 `ws_recovery` 증거는 여전히 synthetic이며, 실제 KIS WS 증거 요구는 Phase 2부터로 미뤄져 있다 — 의도된 설계지만, Phase 1b 진입 전 실 WS 증거 1회 확보가 안전하다.

### F-5. 같은 운영 이슈가 반복 봉합되고 있다 — P1

- KIS `EGW00201` rate limit: 6-02, 6-04, 6-05, 6-08, 6-09, 6-10 — 사실상 매 거래일 반복. 매번 marker-only alignment로 수동 봉합 중. 근본 원인(장후 조회 호출량/간격 설계) 해결이 필요하다.
- KIS live data quality `watch`: 6-05, 6-08, 6-09 반복(최신일 coverage 미달, h15 label coverage 주의). 원인 조사 항목이 blocker 목록에 있으나 미착수.
- 6-10 정합성 `needs_review`(373220 local-only 1주) 미해소 상태로 확인됨.

### F-6. 월 +50% stretch target 문구 — 운영자 인지 위험

README에 "보장 아님"이라는 단서가 있으나, 현실(paper -6.98%)과의 격차가 너무 크다. 비전공 운영자에게 닻(anchor)으로 작용해 위험 결정을 유도할 수 있다. "비용 차감 후 양수 + 최대낙폭 제한"처럼 검증 가능한 목표로 바꾸는 것을 권장한다.

## 5. 권장 다음 단계

| 우선순위 | 항목 |
|---|---|
| Codex P0 | 373220 local-only mismatch 해소 + EGW00201 rate limit 근본 대책(호출 간격/배치/캐시 설계) |
| Codex P0 | virtual direction 지표에 "단순 합산·연구용" 경고 고정 표기, 게이트 워크포워드 리포트를 새 3분류 포맷으로 정본 재생성(현재 보류 상태 해소) |
| Codex P1 | data quality `watch` 반복 원인 조사, 진행판 6-11 기준 갱신 |
| cowork | 6월 누적 변경 통합 리뷰 (review_ver_16) |
| 운영자 결정 | (a) 월 +50% 문구를 검증 가능한 목표로 교체할지, (b) 알파 연구(모델 성능)와 인프라 작업의 비중 재배분 — 향후 N라운드는 모델/피처/비용 모델 연구 중심으로 둘지 |

## 6. 종합 판단

방향 자체는 목표와 일치한다 — 안전 게이트는 진짜로 작동하고, 실전 주문은 한 줄도 열리지 않았으며, 지표 정직성도 개선 중이다. 그러나 **시스템의 존재 이유인 "비용 차감 후 양수 예측력"은 아직 증거가 0건**이고, 작업 에너지는 그 증거를 만드는 쪽보다 운영 편의 쪽에 더 쓰이고 있다. 지금 단계의 최대 리스크는 사고가 아니라 "안전하게 영원히 Phase 0에 머무는 것"이다. 리뷰 루프 재개와 알파 연구 우선순위 회복이 핵심이다.
