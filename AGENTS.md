# 저장소 작업 지침

> 이 파일은 이 저장소에만 필요한 규칙을 둔다. 공통 Codex 작업 방식은 전역 지침을 따르며 여기서 반복하지 않는다.

## 1. 미션

- 국내 주식 실시간 데이터 수집, 특징 생성, 15분/60분 예측, 로컬 가상 모의운용, KIS 모의계좌 검증, 대시보드 리포트를 안정화한다.
- 현재 기본 운영은 실전 자동매매가 아니라 `paper` 연구와 검증이다.
- 실제 상태, 안전한 변경, 재현 가능한 검증, 기준 문서 동기화를 우선한다.

## 2. Read First

비사소한 작업이나 변경 전에는 다음만 먼저 읽는다.

1. `AGENTS.md`
2. `README.md`
3. `docs/STATUS.md`
4. `docs/SPRINT_CURRENT.md`
5. 작업 범위와 직접 관련된 문서

다음 문서는 관련될 때만 읽는다.

- 구현 범위/레이어: `docs/Current-Implementation.md`, `docs/Repository-Structure.md`
- 작업 이력: `docs/logbook.md`와 필요한 최신 archive
- 버전/배포: `docs/Versioning.md`
- cowork: `WORKFLOW.md`, `COWORK_GUIDE.md`, 해당 `docs/cowork-reports/`
- KIS/계좌/연결: `docs/KIS-Connection-Runbook.md`
- 복구/NAS: `RECOVERY.md`
- 자격정보/비공개 원격: 존재할 때 `../secrets/README.local.md`

장전/장후 운영 확인은 `.agents/skills/daily-ops-check/SKILL.md`, 전면 감사는 `.agents/skills/full-check/SKILL.md`를 먼저 따른다.

## 3. 기준 문서 역할

- `README.md`: 프로젝트 개요, 구조, 주요 실행 방법
- `docs/STATUS.md`: 현재 운영 상태와 blocker의 단일 기준
- `docs/SPRINT_CURRENT.md`: 현재 작업 기간, 목표, 체크리스트, 동결 범위
- `docs/logbook.md`: 중요한 변경, 원인, 검증 이력
- `docs/Current-Implementation.md`: 구현 계약과 지원 범위
- `docs/Repository-Structure.md`: 실제 레이어와 문서 지도
- `docs/Production-Transition-Progress.md`: 실전 전환 Phase 상태
- `docs/Execution-Plan.md`: 단계별 실행 순서
- `docs/Model-Research-PreRegistration.md`, `docs/Portfolio-Replay-Evaluator.md`: 연구/평가 고정 기준
- `docs/*Runbook.md`: 주제별 운영 절차
- `docs/cowork-reports/`: 명시적으로 요청되거나 진행 중인 cowork 리뷰 이력
- `docs/archive/`, `docs/logbook_archive/`: 과거 사실 보존

현재 수치는 `docs/STATUS.md` 한 곳만 소유한다. 다른 문서의 날짜가 붙은 수치는 기준선 또는 이력이며, 충돌하면 실제 코드·상태 파일을 확인해 `STATUS`를 갱신한다. 같은 사실을 여러 문서에 길게 복제하지 않는다.

## 4. 작업 흐름

1. 대화 기억이 아니라 파일, 로그, 상태 명령으로 현재 상태를 확인한다.
2. 작업 전 `./scripts/get_live_runtime_status.sh`와 `./scripts/get_runtime_watchdog_status.sh`를 확인한다.
3. 기존 helper, 데이터 계약, 테스트를 재사용하고 변경 범위를 작게 잡는다.
4. 코드 변경은 관련 기준 문서와 같은 작업에서 맞춘다.
5. 실제 검증 결과와 남은 위험을 `docs/logbook.md`에 기록할 가치가 있을 때만 남긴다.
6. 변경이 있으면 `docs/Versioning.md`의 규칙에 따라 같은 작업에서 commit/push까지 마친다.
7. NAS 백업은 사용자가 해당 작업에서 명시적으로 지시한 경우에만 실행한다.

cowork 절차와 `review_ver_*`/`work_ver_*` 산출물은 사용자가 cowork 리뷰를 요청했거나 같은 주제의 리뷰가 실제 진행 중일 때만 사용한다. 일반 작업에 새 리뷰 문서를 만들지 않는다.

## 5. 장중 수집 보호

다음 중 하나면 장중 수집 보호 모드다.

- 상태가 `regular-session` 또는 실제 워밍업 `pre-open`
- `live_runtime_should_run=true`
- live runtime이 실행 중

`overnight`이며 runtime이 정지했고 `live_runtime_should_run=false`이면 보호 모드가 아니다.

보호 모드에서는 사용자 명시 승인 없이 다음을 하지 않는다.

- 루트 코드 변경
- 전체 테스트 또는 `python -m app ...`
- dashboard/runtime 재생성이나 재시작
- `runtime-data/dev.db`에 접근할 수 있는 명령

허용 범위는 읽기 전용 상태 확인, 문서/리포트 정리, `git diff --check`, `bash -n`, `.tmp-tests/`에 완전히 격리된 좁은 테스트다. 구현은 별도 worktree에서 준비하거나 장 종료 뒤 적용한다.

## 6. 코드와 저장 위치

주요 책임 경계는 다음과 같다.

- `app/brokers/`: KIS 인증, REST, WebSocket
- `app/collectors/`: 외부 응답을 내부 이벤트로 변환
- `app/features/`, `app/labels/`: 분봉, 특징, 라벨
- `app/models/`, `app/services/research.py`: 모델과 연구
- `app/services/streaming.py`: 실시간 처리
- `app/paper_trading/`, `app/portfolio/`, `app/reconciliation/`: paper 주문·포트폴리오·정합
- `app/risk/`: 주문 전 위험 통제
- `app/storage/`: SQLite/JSONL 계약
- `scripts/`: 반복 실행 wrapper
- `tests/`: 회귀 검증

기본 의존 방향은 `brokers/collectors -> features/labels -> models/services -> paper_trading/portfolio/risk -> reporting`이다.

새 산출물은 D드라이브만 사용한다.

- 누적 runtime 산출물: `runtime-data/`
- 임시 테스트: `.tmp-tests/`
- 모델: `runtime-data/ml/`
- 리포트: `runtime-data/reports/`
- 대용량 외부 데이터/연구 snapshot: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/`

root `results/`와 C드라이브 기본 임시 경로는 사용하지 않는다.

## 7. 운영 안전

- 기본 거래 모드는 `paper`, 실전 주문은 기본 비활성이다.
- 실전 주문/취소, 주문 flag, `app/risk/`, `config/`, Phase 기준, 계좌 정렬, clean baseline은 사용자 명시 범위 없이 바꾸거나 실행하지 않는다.
- `ENABLE_BROKER_PAPER_MIRRORING=true`이면 로컬 paper 주문이 KIS 모의계좌에 제출될 수 있음을 항상 고려한다.
- KIS key/secret/token/계좌 식별자는 git 추적 파일, 로그, 리뷰에 기록하지 않는다.
- 루트 `.env`는 추적하지 않고 권한 `0600`을 유지한다.
- 장외·휴장일에는 live runtime을 임의로 시작하지 않는다. 휴장일은 `config/market_calendar.toml`을 따른다.
- 실제 브로커 체결 시각의 포트폴리오 snapshot과 과거 epoch 증거는 삭제·재작성하지 않는다.
- KIS REST 페이징, rate limit, WebSocket 복구, 계좌 정합 절차는 `docs/KIS-Connection-Runbook.md`를 따른다.

ML 실험은 사전등록과 스프린트 동결 범위 안에서만 자율 수행한다. 데이터 소스, 스프린트 목표, `app/risk/`, 운영 스크립트 구조, 승격 결정이 바뀌면 운영자 판단을 받는다.

## 8. 주요 검증 명령

상태:

```bash
./scripts/get_live_runtime_status.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/get_dashboard_status.sh
./scripts/get_runtime_startup_launcher_status.sh
```

전체 테스트:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

구조/CLI:

```bash
python scripts/audit_repository_structure.py
python -m app --help
```

이 저장소에는 별도 lint 명령이 없다. 실행하지 않은 lint를 통과했다고 보고하지 않는다.

검증 범위:

- 문서만 변경: `git diff --check`
- 구조/문서 역할 변경: repository structure audit
- Python 또는 동작 변경: 관련 테스트와 전체 `unittest`
- dashboard 변경: `tests.test_dashboard`와 필요 시 build
- broker paper sync 변경: `tests.test_broker_paper_sync tests.test_paper_reconciliation`
- KIS WebSocket 변경: `tests.test_kis_ws_parser tests.test_kis_ws_verification`
- bash 변경: `bash -n`

## 9. 버전과 자동화

- `VERSION`은 배포 준비 신호이며 작업 마지막에만 변경한다.
- `autopush.json`의 기준 브랜치는 `main`, 원격은 `origin`이다.
- 자동화 산출물은 `runtime-data/reports/codex/` 아래에만 둔다.
- 운영 자동화는 root 코드, DB schema, runtime, 실전 flag를 자동 변경하지 않는다.
- 자동화의 KIS 네트워크 실행과 Phase 전환 조건은 daily ops skill과 관련 runbook을 따른다.

## 10. 완료 확인

- 사용자 요구, 스프린트 동결 범위, 장중 보호 상태를 다시 대조한다.
- 테스트 출력과 runtime/KIS 판단을 실제 증거와 대조한다.
- 의도하지 않은 변경, 비밀값, 백그라운드 프로세스를 확인한다.
- 현재 사실은 `STATUS`, 구현 변경은 관련 기준 문서, 중요한 이력은 `logbook`에 필요한 만큼만 반영한다.
- 새 문서·추상화·복제 규칙은 기존 문서로 해결되지 않을 때만 추가한다.

<!-- NAS_BACKUP_START -->
## NAS 백업

상세 정책과 명령은 `RECOVERY.md`가 소유한다. 주간/강제 NAS 백업 모두 사용자가 해당 작업에서 명시적으로 지시한 경우에만 실행하며, 자격정보와 token cache는 sanitized export에 포함하지 않는다.
<!-- NAS_BACKUP_END -->
