# WORKFLOW.md — Codex + Cowork 협업 운영 기준

## 이 문서의 역할

Codex와 Cowork가 같은 저장소를 공유하며 번갈아 작업할 때의
역할 분리, 인수인계, 판단 권한을 정의한다.

AGENTS.md(Codex용), COWORK_GUIDE.md(Cowork용)와 함께 읽는다.

---

## 최초 배치 시 체크리스트

이 파일들을 저장소에 처음 올릴 때 확인한다.

- [ ] 기존 `AGENTS.md` → 이 패키지의 새 `AGENTS.md`로 교체
- [ ] `WORKFLOW.md`, `COWORK_GUIDE.md` → 저장소 루트에 배치
- [ ] `docs/SPRINT_CURRENT.md` → `docs/` 폴더에 배치
- [ ] `docs/STATUS.md` 없으면 → Cowork가 빈 파일로 생성

---

## 핵심 원칙

**방향 판단은 사람이 한다.**
"무엇을 만들지", "전략을 바꿀지"는 운영자가 결정한다.
Codex와 Cowork는 지시받은 범위 안에서만 일한다.

**Codex는 코드를 만들고, Cowork는 결과를 확인한다.**
역할이 겹치는 작업은 이 문서의 역할 표를 기준으로 한쪽에만 맡긴다.

**스프린트 단위로 작업한다.**
기능 추가는 현재 스프린트 완료 후 다음 스프린트에서만 한다.

---

## 역할 분리

| 작업 | 담당 | 금지 |
|---|---|---|
| 코드 작성·수정·리팩토링 | **Codex** | Cowork 직접 수정 금지 |
| 테스트 코드 작성 | **Codex** | — |
| 백테스트·walk-forward 실행 | **Cowork** | Codex는 명령만 제시 |
| 실행 결과·로그 읽기 | **Cowork** | — |
| 수치 기록 (`docs/STATUS.md`) | **Cowork** | — |
| 인수인계 기록 (`docs/logbook.md`) | **Codex** | — |
| 스프린트 완료 여부 판단 | **운영자** | AI 단독 판단 금지 |
| 다음 스프린트 목표 설정 | **운영자** | — |
| 운영 문서 갱신 | **운영자 지시 후 Codex** | — |

---

## 세션 시작 규칙

### Codex 세션 시작 시

```
1. docs/SPRINT_CURRENT.md 읽기
2. docs/logbook.md 읽기  ← Cowork 마지막 결과 확인
3. docs/STATUS.md 읽기   ← 최신 수치 확인
4. 스프린트 범위 밖 요청 → 거절 후 운영자에게 알림
```

### Cowork 세션 시작 시

```
1. docs/SPRINT_CURRENT.md 읽기
2. docs/STATUS.md 읽기 (없으면 빈 파일 생성)
3. docs/logbook.md 읽기  ← Codex 인수인계 확인
4. git log --oneline -5   ← 최근 변경 확인
5. COWORK_GUIDE.md 지시 실행
```

---

## 인수인계 프로토콜

### Codex → Cowork 인수인계

Codex 작업 완료 시 `docs/logbook.md` **상단**에 추가한다.

```markdown
## [YYYY-MM-DD] Codex → Cowork

- 변경 파일:
- 변경 내용:
- 실행 요청 명령:
  ```
  [명령어 그대로]
  ```
- 확인할 수치:
- 예상 결과 (성공 기준):
```

### Cowork → Codex 인수인계

Cowork 실행 완료 시 `docs/STATUS.md` **상단**에 추가한다.

```markdown
## [YYYY-MM-DD HH:MM] Cowork → Codex

- 실행 명령:
- 수익률:
- MDD:
- 샤프지수:
- 정확도:
- baseline 대비: 우위 / 동등 / 열세
- 다음 요청:
- 운영자 판단 필요: 예 / 아니오 — [이유]
```

---

## Git 커밋 규칙

**커밋 주체는 Codex다.**
Cowork는 `docs/STATUS.md`와 `docs/logbook.md`만 수정하며,
이 파일들도 원칙적으로 Codex가 다음 세션에 일괄 커밋한다.

불가피하게 Cowork가 문서만 커밋할 때:
```
docs: cowork 실행 결과 기록 [sprint-01]
```

Codex 커밋 형식:
```
feat(models): LightGBM 윈도우 60→120일 확장 [sprint-01]
fix(features): 노이즈 피처 15개 제거 [sprint-01]
docs: codex 인수인계 기록 [sprint-01]
```

---

## 핑퐁 방지 규칙

- 같은 파일이 한 스프린트에서 **4회 이상** 수정되면 멈추고 운영자에게 보고
- "이전 방식으로 되돌린다"는 변경은 운영자 승인 없이 하지 않는다
- 3회 연속 실험에서 수치 개선이 없으면 방향 전환 전 운영자에게 보고

---

## 스프린트 파일 구조

```
docs/
├── SPRINT_CURRENT.md   ← 진행 중 스프린트
├── SPRINT_01.md        ← 완료 후 이동
├── logbook.md          ← Codex 인수인계 기록 (기존 파일 유지)
└── STATUS.md           ← Cowork 수치 기록 (없으면 신규 생성)
```

---

## 공통 금지 사항

- 스프린트 범위 밖 기능 추가 금지
- `.env` 파일 읽기·수정·출력 금지
- `runtime-data/` 실제 거래 데이터 삭제 금지
- `--mode live` 실매매 실행 금지
- 운영자 승인 없이 리스크 한도 변경 금지
