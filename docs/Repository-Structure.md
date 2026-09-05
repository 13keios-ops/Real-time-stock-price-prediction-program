# Repository Structure

## 목적

이 문서는 실제 저장소의 책임 경계, 기준 문서, 산출물 위치, 알려진 구조 부채를 빠르게 확인하는 지도다.

## 애플리케이션 계층

```text
app/brokers/          KIS 인증, REST, WebSocket, read-only/order adapter
app/collectors/       외부 데이터를 내부 이벤트로 변환
app/features/         분봉과 feature 생성
app/labels/           horizon label 생성
app/models/           모델, artifact lineage, registry와 loader
app/services/         orchestration, research, streaming, dashboard, readiness
app/paper_trading/    paper 주문, 체결, 비용 모델
app/portfolio/        비중과 보유 한도
app/reconciliation/   paper/KIS 정합성
app/risk/             주문 전 risk gate
app/storage/          SQLite/JSONL 계약과 저장
app/replay/           재생 서비스
app/nlp/              이벤트 텍스트 정규화
app/universe/         종목 메타데이터와 watchlist
```

기본 의존 방향은 `brokers/collectors -> features/labels -> models/services -> paper_trading/portfolio/risk -> reporting`이다.

## 운영 디렉터리

```text
config/               TOML 설정과 watchlist
migrations/           DB schema migration
scripts/              반복 CLI와 Python 구현 wrapper
tests/                unittest/pytest 회귀 검증
runtime-data/         DB, 로그, 리포트, 모델, 캐시
.tmp-tests/           격리 테스트와 Codex 작업 초안
.agents/skills/       저장소 전용 skill
docs/cowork-reports/  ping-pong review/work 이력
docs/archive/         퇴역한 운영 문서 원문
docs/logbook_archive/ 최근 작업 요약 아카이브
```

`scripts/`에서 같은 stem의 `.py`와 `.sh`가 함께 있는 것은 중복 구현이 아니라 Python 본체와 shell wrapper 조합이다.

## 저장 위치

- 저장소 내부 runtime/임시 산출물은 WSL 배포판이 있는 D드라이브에 물리적으로 저장한다.
- 대용량 외부 데이터와 연구 snapshot은 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/`에 둔다.
- root `results/`와 C드라이브 기본 temp/download 경로는 사용하지 않는다.
- NAS 백업은 사용자 명시 지시가 있을 때만 실행한다.

## 문서 역할

### 현재 기준

- `AGENTS.md`: Codex 작업 규칙
- `README.md`: 프로젝트 개요와 주요 명령
- `docs/STATUS.md`: 현재 운영 상태와 blocker의 단일 기준
- `docs/SPRINT_CURRENT.md`: 현재 작업 기간과 동결 범위
- `docs/logbook.md`: 중요한 변경, 원인, 검증 이력
- `docs/Current-Implementation.md`: 실제 구현 범위
- `docs/Production-Transition-Progress.md`: Phase와 blocker
- `docs/Execution-Plan.md`: 전체 단계별 방법과 이유
- `docs/Model-Research-PreRegistration.md`: 모델 연구 사전등록
- `docs/Repository-Structure.md`: 저장소와 문서 지도

### 참고와 이력

- `docs/cowork-reports/`: 리뷰와 후속 작업 전문
- `docs/archive/`: 퇴역한 현재판의 원문
- `docs/logbook_archive/`: 최근 기간 요약
- 그 외 `docs/*.md`: 주제별 설계와 runbook

같은 현재 수치를 여러 문서에 길게 반복하지 않는다. 현재값은 `STATUS`, Phase는 `Production-Transition-Progress`, 작업은 `SPRINT_CURRENT`, 세부 구현은 `Current-Implementation`이 소유한다. 다른 문서의 날짜가 붙은 수치는 기준선 또는 이력으로 해석한다.

## 2026-07-13 구조 감사

- Python app 파일: `97`
- 테스트 파일: `89`
- scripts 최상위 파일: `139`
- 감사 전 Markdown: `208`개
- 명시적 Markdown local link 누락: `0`
- 불균형 code fence: `0`
- 추적 중인 `.orig`/`.rej`: `0`

## 알려진 구조 부채

- `app/services/research.py`: 약 8,583줄
- `app/services/dashboard.py`: 약 6,117줄
- `app/storage/sqlite_store.py`: 약 2,125줄

이 세 파일은 크지만 장중 운영과 연구 계약에 넓게 연결돼 있다. 이번 문서 감사에서는 분해하지 않는다.

향후 기능 변경이 해당 파일을 다시 크게 늘릴 때 아래 순서로 추출한다.

1. 순수 계산 helper와 I/O 경계를 먼저 테스트로 고정한다.
2. report renderer, query adapter, gate evaluator처럼 단방향 책임부터 별도 모듈로 옮긴다.
3. public 함수 signature와 runtime artifact schema를 유지한다.
4. 한 작업에서 대형 모듈 여러 개를 동시에 분해하지 않는다.

## 결정론적 감사

```bash
python scripts/audit_repository_structure.py
```

감사 항목은 필수 경로, 현재 Markdown local link와 code fence, `.orig`/`.rej`, 상태 문서 과대화, 5,000줄 이상 Python 모듈이다.
경고는 구조 부채를 보여주되 실행을 실패시키지 않는다. 필수 경로 누락, 깨진 현재 문서 링크, patch 잔여물은 오류다.
