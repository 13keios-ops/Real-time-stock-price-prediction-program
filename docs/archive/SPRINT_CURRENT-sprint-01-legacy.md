# docs/SPRINT_CURRENT.md — 스프린트 01

> 완료 후: 이 파일을 `docs/SPRINT_01.md`로 복사하고 새 내용으로 교체한다.

---

## 목표

**LightGBM이 baseline을 이기지 못하는 원인을 진단하고 개선한다.**

| 항목 | 내용 |
|---|---|
| 시작일 | [Cowork가 Phase 1 실행한 날짜로 채움] |
| 현재 상태 | LightGBM shadow challenger < builtin baseline-h15-v1 |
| 목표 상태 | walk-forward 기준 LightGBM이 아래 완료 조건 충족 |

---

## 운영자 호출 조건

다음 상황에서 작업을 멈추고 운영자에게 보고한다.
Cowork는 아래 양식을 화면에 출력하고 `docs/STATUS.md` 상단에 기록한다.

```
🔴 운영자 판단 필요 — Claude.ai에 가져갈 내용
- 상황: [무슨 일이 생겼는지]
- 가져갈 파일: docs/STATUS.md
- 질문: [운영자가 결정해야 할 것]
```

| 트리거 | 담당 | 가져갈 것 | 질문 |
|---|---|---|---|
| Phase 1 완료 | Cowork | STATUS.md | 진단 수치 확인, 실험 순서 승인 |
| Synthetic 실패 | Cowork | logbook.md 오류 내용 | 코드 수정 방향 판단 |
| 실험 3회 연속 미달 | Cowork | STATUS.md 실험 결과 누적표 | 방향 전환 또는 전략 재검토 |
| 완료 조건 충족 | Cowork | STATUS.md 최종 수치 | LightGBM 승격 최종 승인 |
| 핑퐁 4회 감지 | Codex | logbook.md | 같은 파일 반복 수정 원인 판단 |

---



다음을 **모두** 충족해야 완료다. 운영자가 최종 확인한다.

1. **샤프지수**: LightGBM > baseline, 그리고 LightGBM 절대값 > 0.3
2. **MDD**: LightGBM MDD가 baseline보다 나쁘지 않음
3. **정확도**: LightGBM accuracy ≥ 52% (random 대비 유의미한 수준)
4. **원인 기록**: 개선된 원인이 `docs/STATUS.md`에 명확히 기록됨
5. **운영자 승인**: 운영자가 결과 확인 후 승인

> 샤프지수 0.3 미만이면 baseline이 이기더라도 전략 자체에 알파가 없을 수 있다.
> 이 경우 운영자에게 "전략 방향 재검토 필요"로 보고한다.

---

## 스프린트 범위

### 포함

- LightGBM 학습 파라미터 조정
- 피처 추가·제거 실험
- 학습 윈도우 크기 조정
- 레이블 정의 재검토
- 백테스트·walk-forward 실행 및 결과 분석

### 제외 (이번 스프린트에서 하지 않는 것)

- 대시보드 UI 수정
- 새 PowerShell 스크립트 추가
- 브로커 연동 수정
- watchdog / autoboot 수정
- 새 알림 채널 추가

---

## 작업 순서

### Phase 1 — 진단 [Cowork 담당]

- [ ] Synthetic 전체 흐름 오류 없음 확인
- [ ] Baseline walk-forward 수치 기록
- [ ] LightGBM walk-forward 수치 기록
- [ ] 피처 중요도 상위 10개 확인
- [ ] 결과를 `docs/STATUS.md`에 정리 후 Codex에 전달

### Phase 2 — 원인 분석 [Codex 담당]

Phase 1 수치를 받아 다음 항목을 코드에서 확인한다.

- [ ] 학습 데이터 행 수 확인 (60거래일 × 분봉 수 = 실제 row 수)
- [ ] 레이블 분포 확인 (상승/하락/중립 비율)
- [ ] Train accuracy vs Test accuracy 차이 (과최적화 여부)
- [ ] 피처 수 대비 학습 데이터 양 비율
- [ ] LightGBM 하이퍼파라미터 현재값 확인

분석 결과를 `docs/logbook.md`에 기록하고 원인 가설 1~2개를 명시한다.

### Phase 3 — 개선 실험 [Codex 작성 → Cowork 실행]

**한 번에 하나만 바꾼다.** 동시에 여러 개 바꾸면 원인을 알 수 없다.

Phase 2 진단 결과에 따라 실험 순서를 정한다.

```
학습 데이터 행 수 < 500       → 실험 A 먼저 (윈도우 확장)
Train acc >> Test acc (과최적화) → 실험 B 먼저 (피처 축소)
상승/하락 비율 차이 > 60:40    → 실험 C 먼저 (레이블 재정의)
위 해당 없음                  → 실험 D 먼저 (파라미터 튜닝)
```

| 실험 | 내용 | 상태 |
|---|---|---|
| 실험 A | 학습 윈도우 60 → 120거래일 | 대기 |
| 실험 B | 피처 수 축소 (중요도 하위 30% 제거) | 대기 |
| 실험 C | 레이블 기준 재정의 | 대기 |
| 실험 D | LightGBM n_estimators·learning_rate 조정 | 대기 |

상태값: 대기 / 진행 중 / 완료 / 취소

각 실험 후 walk-forward 수치를 `docs/STATUS.md`에 기록한다.
3회 연속 수치 개선 없으면 작업 멈추고 운영자에게 보고한다.

### Phase 4 — 운영자 판단

수치 개선이 확인되면 운영자에게 보고한다.
운영자가 LightGBM active model 승격 여부를 결정한다.

---

## 진행 로그

| 날짜 | 담당 | 작업 | 결과 요약 |
|---|---|---|---|
| | 운영자 | 스프린트 01 시작 | — |

---

## 현재 기준 수치

*Phase 1 완료 후 Cowork가 채운다.*

| 지표 | baseline | LightGBM |
|---|---|---|
| 수익률(연환산) | — | — |
| MDD | — | — |
| 샤프지수 | — | — |
| 정확도 | — | — |
| walk-forward 폴드 수 | — | — |

---

## 실험 결과 누적

*Phase 3에서 각 실험 후 Cowork가 채운다.*

| 실험 | 샤프지수 | MDD | 정확도 | baseline 대비 |
|---|---|---|---|---|
| baseline | — | — | — | 기준 |
| 실험 A | — | — | — | — |
| 실험 B | — | — | — | — |
| 실험 C | — | — | — | — |
| 실험 D | — | — | — | — |
