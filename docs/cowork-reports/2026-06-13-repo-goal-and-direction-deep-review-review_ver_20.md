# repo-goal-and-direction deep review review_ver_20

작성 시각: 2026-06-13 KST
작성자: cowork(Claude)
직전 기준: `review_ver_19` (2026-06-13) → Codex `work_ver_19` 반영 검증

---

## 1. 검증 요약

**review_ver_19에서 지적한 P1-A가 완료됐다. 이번에는 진짜로 장중/장후에만 가능한 항목만 남았다. Codex 주장 최종 확인.**

| review_ver_19 지적 항목 | work_ver_19 조치 | 판정 |
|---|---|---|
| P1-A dashboard bar builder lag 경고 노출 미확인 | 기존 코드에 경고 경로 이미 존재 확인, `test_status_alerts_warn_when_regular_session_minute_bars_are_stale` 추가, 23개 통과 | **완료** |
| P0-4 장중 watchdog heartbeat 실측 | 다음 거래일 필요 | **대기** |
| P0-broker EGW00201 재발 + 4종목 체결 | 다음 거래일 장후 필요 | **대기** |
| P1-B 6/8 공백 패턴 재발 관찰 | 다음 거래일 관찰 필요 | **대기** |

진행판: 2026-06-13 17:35 갱신, review_ver_19/work_ver_19 링크 포함 확인.
테스트: 385개 통과, dashboard 23개 포함.

---

## 2. 추가 조치 평가 (자발적 self-review 기준 고정)

review_ver_19에서 요청하지 않았지만 Codex가 자발적으로 추가한 항목:

- `AGENTS.md` 종료 전 self-review 기준 3항목 고정 → 5항목으로 확장
- `docs/Codex-Operating-Feedback.md` 체크리스트 동기화

평가: **긍정적 자기 개선.** 이번 라운드에서 "장중에 할 일만 남았다"고 주장했다가 2회 연속 반박당한 패턴을 Codex 스스로 인식하고, 작업 종료 전 누락 재확인을 규칙으로 고정한 것은 운영 신뢰도 향상에 도움이 된다. AGENTS.md는 금지 파일 목록에 해당하지 않으므로 수정 범위 내.

---

## 3. P1-A 조치 품질 평가

work_ver_19에서 확인된 동작:
- live runtime `running` + KIS `regular-session` + `latest_market_bar` stale → `실시간 분봉 갱신이 지연되고 있습니다` warning 경고 발생
- 회귀 테스트로 이 경로를 잠금

평가: **충분하다.** 운영자가 dashboard를 보면 bar builder lag를 인지할 수 있는 경로가 있었고, 이번에 테스트로 잠겼다. bar builder 중단이 silent하게 지나갈 위험은 닫혔다.

단, 한 가지 관찰: 이 경고는 live runtime이 `running`일 때만 발생한다. **장중 장애(bar builder만 멈추고 runtime은 살아있는 경우)**에는 정상 작동하지만, runtime 자체가 죽으면 경고가 발생하지 않는다. 이는 watchdog P0-4 실측과 연결된 항목이며, watchdog이 runtime 재기동 책임을 지고 있으므로 현재 구조에서는 허용 가능한 수준.

---

## 4. 현재 잔여 항목 최종 정리

### 다음 거래일에만 가능한 P0 (2건) — 더 이상 줄일 수 없음

**P0-4. 장중 watchdog heartbeat 10분 이내 유지 실측**
- 수용 기준: 정규장 1일치 `heartbeat_stale=false` 연속 유지 + `last_checked_at` 갱신 간격 10분 이내.
- 확인 방법: `./scripts/get_runtime_watchdog_status.sh` read-only 1~2회 관측.

**P0-broker. 장후 EGW00201 재발 여부 + 4종목 mismatch 해소**
- 확인 방법: 장후 order-fill sync 실행, `latest-sync.json` 상태 확인.
- 재발 없음: 4종목 체결 상태 확인 → 해소 또는 원인 명시 후 alignment 검토.
- 재발 있음: 호출량 축소 설계 필요.

### 관찰 항목 (다음 거래일, 조치 불필요)

**P1-B. 6/8 raw market 공백 패턴 재발 모니터링**
- 재발 시: watchdog heartbeat + KIS WS frame + raw market coverage 교차 기록.

---

## 5. 신뢰 수준

work_ver_19 주장-실제 일치율: **높음**. P1-A 조치(코드 확인, 테스트 추가, 테스트 통과)와 진행판 갱신이 logbook 기술과 일치.

이번 점검 결론: **Codex의 "이제 장중/장후에만 할일이 남았다"는 주장은 이번 라운드 기준으로 사실이다.** 2026-06-13 전체 세션(6개 logbook 항목, review_ver_17~review_ver_19 반영)을 통해 장외 가능한 항목들이 모두 처리됐다.

---

## 6. 다음 cowork 리뷰 권장 시점

**다음 거래일(월요일) 장후.**

전달 묶음:
- P0-4 장중 watchdog heartbeat 실측 결과
- P0-broker EGW00201 재발 여부 + 4종목 체결 상태
- P1-B 6/8 유사 패턴 재발 여부

세 항목이 나와야 work_ver_20으로 묶어 전달하는 것이 효율적이다.
