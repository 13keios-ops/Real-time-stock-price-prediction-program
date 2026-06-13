# repo-goal-and-direction deep review work_ver_19

작성 시각: 2026-06-13 KST
작성자: Codex
직전 리뷰: `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-review_ver_19.md`

---

## 1. 전달 목적

`review_ver_19`에서 새로 지적한 장외 P1-A, 즉 "bar builder lag가 dashboard 경고로 실제 노출되는지"를 확인하고 테스트로 잠근 결과를 정리한다.

---

## 2. 시작 상태

- KST 2026-06-13 17:26, 토요일 `weekend`.
- live runtime: `stopped`, `session_status=weekend`, `trading_mode=paper`.
- runtime watchdog: `running`, `live_runtime_should_run=false`, `errors=[]`, heartbeat fresh.
- dashboard: `http://127.0.0.1:8765` 서버/API 응답 중.
- git: `main...origin/main`, untracked `review_ver_19.md`만 존재.

금지 범위 준수:

- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 실전 주문/취소 없음.
- NAS 백업 실행 없음.

---

## 3. review_ver_19 조치 결과

### P1-A. dashboard bar builder lag 경고 노출 여부 확인

조치 완료.

확인한 현재 동작:

- dashboard status alert 함수는 live runtime 이 `running`이고, KIS session 이 `regular-session`이며, `latest_market_bar` freshness 가 `stale`이면 warning alert를 만든다.
- alert 제목은 `실시간 분봉 갱신이 지연되고 있습니다`다.
- message에는 stale note, 예를 들어 `23분 전 업데이트`가 들어간다.

추가한 회귀 테스트:

- `tests/test_dashboard.py::DashboardTests.test_status_alerts_warn_when_regular_session_minute_bars_are_stale`

이 테스트는 아래 조건을 재현한다.

- live runtime: running
- session: regular-session
- latest market bar: stale
- prediction/KIS/training/evaluation: fresh 또는 비차단

기대 결과:

- dashboard status alerts 안에 warning level의 `실시간 분봉 갱신이 지연되고 있습니다`가 포함된다.

검증:

- `python -m unittest tests.test_dashboard -q`: 23개 통과.
- `git diff --check`: 통과. 기존 CRLF 변환 경고만 출력.

기준 문서 반영:

- `docs/Current-Implementation.md`: dashboard status alert 회귀 잠금 설명 추가.
- `docs/Production-Transition-Progress.md`: 최신 cowork 기준을 `review_ver_19`, 통합 리포트를 `work_ver_19`로 갱신하고 P1-A 완료 상태 반영.
- `docs/logbook.md`: 이번 review_ver_19 조치 entry 추가.

---

## 4. 남은 항목

이제 `review_ver_19` 기준 장외에서 바로 닫을 수 있는 P1은 없다.

다음 거래일 P0:

1. **P0-4. 장중 watchdog heartbeat 유지 실측**
   - 정규장 중 `heartbeat_stale=false`, `last_checked_at` 갱신이 10분 이내로 유지되는지 read-only 확인.
2. **P0-broker. 장후 EGW00201 재발 여부 + 4종목 mismatch 해소**
   - 장후 order-fill sync에서 rate-limit 재발 여부 확인.
   - rate-limit 이 풀리면 `005380`, `035420`, `247540`, `373220` 체결 상태 확인.
   - mismatch 해소 또는 원인 명시 전까지 marker-only alignment 금지.

관찰 항목:

- 2026-06-08처럼 raw market symbol-minute 약한 구간이 다음 거래일에도 반복되는지 확인.
- 반복되면 해당 시각의 watchdog heartbeat, KIS WS frame, raw market/orderbook coverage를 함께 기록한다.

---

## 5. 다음 cowork 리뷰 권장 시점

다음 거래일 장후가 적절하다.

전달 묶음:

- P0-4 장중 watchdog heartbeat 실측 결과.
- P0-broker `EGW00201` 재발 여부와 4종목 체결 상태.
- P1-A dashboard warning 테스트 통과 결과.
