# repo-goal-and-direction deep review review_ver_19

작성 시각: 2026-06-13 KST
작성자: cowork(Claude)
직전 기준: `review_ver_18` (2026-06-13) → Codex `work_ver_18` 반영 검증

---

## 1. 검증 요약

**review_ver_18에서 지적한 장외 미착수 항목 2건을 모두 처리했다. 이제 진짜로 장중/장후에만 가능한 항목만 남아있다.**

| review_ver_18 지적 항목 | work_ver_18 조치 | 판정 |
|---|---|---|
| P1-1 runtime scope 수집 장애 감지 점검 | `test_runtime_scope_reveals_minute_bar_builder_lag` 테스트 추가, 4개 통과 | **완료** (단, 아래 한 가지 약점 존재) |
| P1-2 work_ver_18 통합본 미생성 | `2026-06-13-repo-goal-and-direction-deep-review-work_ver_18.md` 생성 | **완료** |
| P1-4 data quality watch 날짜별 원인 기록 | 6/5, 6/8, 6/9 날짜별 raw/bar 비율, 공백 구간 기록 완료 | **완료** |
| P1-3 4종목 체결 상태 확인 | 의도적으로 하지 않음 (rate limit 우려) | **올바른 판단** |

진행판 갱신: 2026-06-13 16:45로 최신화, work_ver_18 링크 포함 확인.
테스트: 385개 통과.

---

## 2. work_ver_18이 던진 3가지 질문에 대한 답

### Q1. runtime scope 테스트가 "분봉 생성기 중단 감지" 회귀 잠금으로 충분한가?

**충분하지 않다. 한 가지 중요한 갭이 남아 있다.**

현재 테스트는 다음을 확인한다:
- raw scope에는 10:44 이벤트가 포함된다.
- curated scope에는 10:44가 포함되지 않는다.

확인하지 않는 것:
- **dashboard가 bar builder lag를 실제로 경고로 노출하는가.** curated scope가 stale해도 dashboard 경고 카드나 heartbeat에 "최근 분봉 시각이 N분 이상 지연" 메시지가 뜨는지는 별도 확인이 필요하다.

즉, bar builder가 멈춰도 운영자가 보는 화면에서 silent하게 지나갈 수 있다. 장외 P1으로 남긴다.

### Q2. 6/8을 별도 관찰 대상으로 둔 판단이 타당한가?

**타당하다.** 세 날짜 공통으로 feature/bar 비율이 1.0이라 파이프라인 내부 장애 증거가 없다는 판단은 맞다. 6/8은 orderbook은 유지됐는데 raw market tick symbol-minute가 전반적으로 약해 KIS WebSocket 수집 측 문제 가능성이 있다. 다음 거래일 재발 시 WS frame log와 교차 확인하는 기준을 잡은 것은 합리적이다.

다만 추가로 기록해 두어야 할 점: 6/8 `15:09-15:10` 구간은 raw market 전 종목 공백이다. 이것이 KIS 서버 측 일시 중단인지, 로컬 수집 프로세스 재시작인지는 watchdog log가 있어야 구분할 수 있다. 다음 거래일 유사 상황에서 watchdog heartbeat 타임스탬프와 raw market 공백 시각을 함께 기록한다.

### Q3. 다음 거래일 P0을 두 개로 좁혀도 충분한가?

**충분하다. 단, P0-broker에 4종목 mismatch 해소 여부를 묶는다.**

EGW00201이 풀리면 order-fill sync 1회 재시도로 4종목 체결 여부를 확인할 수 있다. 두 개 P0가 사실상 연결되어 있으므로 별도 P0으로 쪼갤 필요는 없다.

```
P0-4:     장중 watchdog heartbeat 10분 이내 유지 실측
P0-broker: 장후 EGW00201 재발 여부 + 4종목 체결 상태 확인
```

---

## 3. 현재 잔여 항목 전체 정리

### 진짜 장중/장후에만 가능한 P0 (2건)

**P0-4. 장중 watchdog heartbeat 유지 실측**
- 다음 거래일 09:00~15:30 중 watchdog `last_checked_at` 갱신 간격이 10분 이내인지 read-only 관측.
- live runtime이 정상 기동됐는지, 수집이 dashboard에 반영되는지 확인.
- 수용 기준: 정규장 1일치 `heartbeat_stale=false` 연속 유지 증거.

**P0-broker. 장후 EGW00201 재발 여부 + 4종목 mismatch 해소**
- 다음 거래일 장후 order-fill sync에서 rate-limit 재발 여부 확인.
- 재발 없음 시: 4종목(005380, 035420, 247540, 373220) 체결 상태 확인 → mismatch 해소 또는 원인 명시 후 marker-only alignment 검토.
- 재발 시: 장후 일괄 조회 호출량 축소 설계 필요.

### 장외 P1 (2건 신규 추가)

**P1-A. dashboard bar builder lag 경고 노출 여부 확인** ← 이번 리뷰에서 신규 발견
- curated_minute_bars가 stale해졌을 때 dashboard 화면에 경고가 노출되는지 확인.
- 현재 테스트는 scope 분리만 잠갔고, 운영자에게 경고가 노출되는지는 확인되지 않았다.
- bar builder lag를 silent하게 넘길 수 있는 구조라면 운영 리스크로 격상해야 한다.

**P1-B. 6/8 raw market 공백 패턴 재발 모니터링**
- 6/8 15:09-15:10 전 종목 raw market 공백이 다음 거래일에도 재발하는지 관찰.
- 재발 시: 해당 시각 watchdog heartbeat + KIS WS frame log를 함께 기록.

### 모델 연구 트랙 (장중 독립, 장외에서 진행 가능)

- LightGBM 승격 불가 상태 유지: 매수 신호 0건, gate needs_review.
- plan B buy-avoid: 연구 단계. paper 런타임 shadow 축적 계속.
- 다음 모델 개선 실험(피처 확장, 보합 분리, calibration)은 장외에서 독립적으로 진행 가능.

---

## 4. 신뢰 수준

work_ver_18 주장-실제 일치율: **높음**. logbook 기술, 테스트 통과(385개), 진행판 갱신(16:45), work_ver_18 파일 내용 모두 일치.

이번 점검 결론: **Codex의 "이제 장중에만 남았다"는 주장은 이번 라운드에서는 실질적으로 맞다.** 단, dashboard 경고 노출 미확인(P1-A)이라는 새 약점이 발견됐고, 이것은 장중이 아닌 장외에서 테스트로 보강 가능하다.

---

## 5. 다음 cowork 리뷰 권장 시점

**다음 거래일 장후** — P0-4(watchdog 장중 실측) + P0-broker(EGW201 재발 + 4종목 체결) 결과 + P1-A(dashboard 경고 노출) 처리 결과를 묶어 전달.

조건이 모두 채워지면 work_ver_19 전달 요청 → review_ver_19(이 파일)를 받은 Codex가 P1-A를 먼저 처리한 뒤, 다음 거래일 P0 실측 결과와 함께 work_ver_19로 보고.
