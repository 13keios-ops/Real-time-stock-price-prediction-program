# COWORK_GUIDE.md — Cowork 작업 기준

## Cowork 시작 프롬프트

Cowork를 열면 아래 문장을 그대로 붙여넣어 시작한다.

```
저장소 루트의 COWORK_GUIDE.md를 읽고, 세션 시작 순서대로 작업을 시작해줘.
현재 스프린트는 docs/SPRINT_CURRENT.md에 있어.
```

---

## 기본 원칙

**웬만한 문제는 스스로 해결하고 멈추지 않는다.**
환경 오류, 패키지 누락, SQLite 모드 문제는 아래 자가 해결 절차를 먼저 시도한다.
3번 시도해도 안 되는 경우에만 운영자에게 보고한다.

**운영자를 호출하는 경우는 딱 두 가지다.**
1. 자가 해결을 3회 시도해도 실패한 경우
2. 스프린트 완료 조건을 충족한 경우 (승인 요청)

---

## 역할

| 할 것 | 하지 말 것 |
|---|---|
| 명령 실행·결과 기록 | `app/risk/` 코드 수정 |
| 환경 문제 자가 해결 | `.env` 내용 읽거나 출력 |
| 패키지 설치 | `runtime-data/` 거래 데이터 삭제 |
| `docs/STATUS.md` 수치 기록 | `--mode live` 실행 |
| `docs/logbook.md` 결과 요약 | Codex 코드 임의 되돌리기 |

---

## 세션 시작 순서

```
1. docs/SPRINT_CURRENT.md 읽기
2. docs/STATUS.md 읽기 (없으면 빈 파일 생성)
3. docs/logbook.md 읽기
4. git log --oneline -5
5. 환경 자가 점검 실행
6. 스프린트 작업 시작
```

---

## 환경 자가 점검 및 해결

세션 시작 시 아래를 순서대로 실행한다. 문제가 생기면 즉시 해결하고 다음으로 넘어간다.

### 1단계. 패키지 확인 및 설치

```bash
python -m app --version
```

`ModuleNotFoundError`가 나면 누락 패키지를 설치하고 다시 시도한다.

```bash
pip install --break-system-packages [누락된 패키지명]
# 또는 전체 재설치
pip install --break-system-packages -r requirements.txt
```

### 2단계. SQLite 환경 감지

Cowork 샌드박스(FUSE/virtiofs)에서는 SQLite WAL 모드가 실패할 수 있다.
단위 테스트에서 `disk I/O error`가 나면 다음 환경변수를 설정하고 재시도한다.

```bash
export PYTHONPYCACHEPREFIX=/tmp/pyc
python -m unittest discover -s tests -p "test_*.py"
```

여전히 실패하면 SQLite fallback이 코드에 적용되어 있는지 확인한다.
적용되어 있으면 환경 자체의 문제로 기록하고 다음 단계로 넘어간다.

### 3단계. Python 버전 호환

`tomllib` 관련 오류가 나면 백포트를 설치한다.

```bash
pip install --break-system-packages tomli
```

---

## 오류 자가 해결 절차

명령 실행 중 오류가 나면 **멈추기 전에** 다음 순서로 시도한다.

```
1차: 오류 메시지를 읽고 원인 파악 → 직접 해결 시도
     (패키지 설치, 환경변수 설정, 경로 수정 등)

2차: 1차 실패 시 다른 방법으로 재시도
     (명령 옵션 변경, 더 짧은 시간으로 재실행 등)

3차: 2차 실패 시 docs/logbook.md에 오류 기록 후 다음 Step으로 우회
     (해당 Step을 건너뛰고 가능한 다음 작업 진행)

3회 모두 실패: 그때 운영자 호출
```

---

## 스프린트 01 실행 순서

### Step 0. STATUS.md 초기화

`docs/STATUS.md`가 없으면 생성한다.

```
# docs/STATUS.md
생성일: [오늘 날짜]
스프린트: 01
```

### Step 1. Synthetic 검증

```bash
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
```

**통과** → Step 2로 진행

**실패** → 환경 자가 해결 절차 적용 후 재시도.
재시도 후에도 실패하면 오류를 `docs/logbook.md`에 기록하고 Step 2로 넘어간다.
(Synthetic 실패가 Step 2~4 실행을 막지 않는다. 환경 문제와 데이터 문제는 별개다.)

### Step 2. Walk-forward 실행

```bash
python -m app --run-walk-forward --horizon-min 15 \
  --walk-forward-min-train-rows 30 \
  --walk-forward-test-rows 10 \
  --walk-forward-step-rows 10 \
  --walk-forward-gap-rows 15 \
  --walk-forward-max-train-rows 40
```

### Step 3. LightGBM 학습 및 challenger 비교

```bash
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
```

### Step 4. 피처 중요도 확인

```
runtime-data/reports/ml/ 에서 가장 최신 feature_importance 파일 읽기
상위 5개 피처 이름과 중요도를 docs/STATUS.md에 기록
```

### Step 5. 결과 기록 및 보고

`docs/STATUS.md` 상단에 추가한다.

```markdown
## [YYYY-MM-DD] 스프린트 01 — 실행 결과

| 지표 | baseline | LightGBM |
|---|---|---|
| 수익률 | | |
| MDD | | |
| 샤프지수 | | |
| 정확도 | | |
| walk-forward 폴드 수 | | |

### 피처 중요도 상위 5개
1.
2.
3.
4.
5.

### 오류 / 경고
[없으면 "없음"]
```

완료 후 아래를 출력한다.

```
🟢 Phase 1 완료 — Claude.ai에 가져갈 내용
- 상황: Step 1~4 완료. 수치 확보됨.
- 가져갈 파일: docs/STATUS.md
- 질문: 수치 확인 후 Phase 2 진행 승인 요청
```

---

## 운영자 호출 기준 (이 두 가지만)

### 1. 자가 해결 3회 모두 실패

```
🔴 운영자 판단 필요 — Claude.ai에 가져갈 내용
- 상황: [무슨 작업에서 3회 실패했는지]
- 시도한 방법: [1차/2차/3차 각각 무엇을 시도했는지]
- 가져갈 파일: docs/logbook.md
- 질문: 추가 조치 방향 결정 필요
```

### 2. 스프린트 완료 조건 충족

```
🟢 스프린트 완료 — Claude.ai에 가져갈 내용
- 상황: LightGBM이 완료 조건 충족
- 가져갈 파일: docs/STATUS.md
- 질문: LightGBM active model 승격 승인 요청
```

---

## 절대 하지 말 것

- `app/risk/` 코드 수정
- `.env` 내용 읽거나 출력
- `runtime-data/` 실제 거래 기록 삭제
- `--mode live` 실행
- Codex 코드를 임의로 되돌리기
