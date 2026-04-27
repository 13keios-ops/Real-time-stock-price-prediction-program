# AGENTS

> 이 문서는 이 저장소의 단일 운영 기준 문서다.
> 비사소한 작업, 질문 응답, 문서 수정, 폴더 이동, 장시간 실행을 시작하기 전에 항상 가장 먼저 다시 읽는다.

## 1. 이 문서의 역할

- 이 문서는 저장소 운영 규칙, 작업 시작점, 검증 기준, 금지 사항, 문서 역할 분리를 다룬다.
- 이 문서는 현재 상태를 오래 쌓아두는 문서가 아니다.
- 프로젝트 현재 상태와 최근 기록은 `docs/logbook.md`가 맡는다.
- 프로젝트 소개와 전역 구조 설명은 `README.md`가 맡는다.
- 현재 구현 상태와 실행 기준은 `docs/Current-Implementation.md`가 맡는다.
- 버전 관리와 watcher 동작 기준은 `docs/Versioning.md`가 맡는다.
- 비공개 원격, 자격증명, 외부 미러, private artifact 세부는 tracked repo에 쓰지 않고 sibling `../secrets/README.local.md`와 그 하위 로컬 문서에만 둔다.

## 2. 항상 읽는 순서

- 비사소한 작업에서는 아래 순서를 항상 다시 통과한다.
1. `AGENTS.md`
2. `README.md`
3. `docs/logbook.md`
4. 최신 `docs/logbook_archive/logbook_*.md` 1개
5. 관련 주제 문서
6. 필요한 경우에만 세부 설계 문서
- 이 순서는 새 작업 시작, 단계 전환, 문서 구조 변경, 커밋 전, 푸시 전, 후속 실행 전에도 다시 적용한다.
- 코드 수정이나 문서 수정이 없는 질문 응답만 하는 턴도 예외가 아니다.
- 새 기능 추가, 폴더 이동, 레이어 경계 판단이 포함된 작업은 `README.md`의 `새 기능을 어디에 둘까` 섹션을 반드시 다시 확인한다.
- 비공개 원격, 비공개 대용량 자산, 자격증명, 외부 미러, private publish 운영이 포함된 작업은 sibling `../secrets/README.local.md`가 있을 때 함께 다시 읽는다.

## 3. 문서 체계와 단일 역할

- `AGENTS.md`
  - 저장소 운영 규칙의 단일 기준
- `README.md`
  - 프로젝트 소개, 전체 구조, 전역 고정 메모
- `docs/logbook.md`
  - 프로젝트 레벨 현재 상태, 전역 결정, 활성 체크리스트, 최근 로그
- `docs/logbook_archive/logbook_*.md`
  - 이전 단계의 스냅샷 아카이브
- `docs/Current-Implementation.md`
  - 실제 구현된 기능과 실행 방법
- `docs/Versioning.md`
  - 버전 파일, watcher, 자동 commit/push 기준
- `docs/*.md`
  - 주제별 상세 설계와 참고 문서
- `runtime-data/`
  - 실행 로그, 리포트, 캐시, 모델 산출물
- `assets/`
  - root `README.md`가 직접 참조하는 전역 공용 자산 전용
- `templates/codex_starter/`
  - 새 저장소 시작 시 복사해 쓸 운영 팩 자리
- 같은 내용을 여러 상위 문서에 반복하지 않는다.
- 로그성 데이터는 `logbook`에만 쌓고, `README.md`는 current truth만 남긴다.

## 4. 답변과 작업 방식

- 사용자 설명은 쉬운 한국어를 먼저 쓴다.
- 영어 개발 용어와 축약어는 꼭 필요할 때만 쓰고, 먼저 쉬운 한국어 설명을 붙인다.
- 익숙하지 않을 수 있는 용어는 압축해서 반복하지 말고 풀어쓴다.
- 과장된 추임새, 불필요한 장황함, 모호한 낙관 표현은 피한다.
- 현재 무엇이 실제로 돌고 있는지는 대화 맥락이 아니라 로그, 상태 파일, 실행 결과를 먼저 확인한다.
- final 답변 전에는 반드시 `현재 작업 모드`, `답변 prefix`, `active checklist 갱신 여부`, `canonical 문서 반영 여부`를 한 줄 체크포인트로 다시 확인한다.

## 5. 핵심 개발 원칙

- 역할 분리를 먼저 지킨다.
  - 운영 규칙은 `AGENTS.md`
  - 현재 상태와 전역 결정은 `docs/logbook.md`
  - 프로젝트 소개와 구조는 `README.md`
  - 현재 구현과 실행 방법은 `docs/Current-Implementation.md`
  - 버전과 watcher 규칙은 `docs/Versioning.md`
- 각 요소기술은 독립 폴더와 공통 진입점을 유지한다.
- 데모 파일과 실제 모듈 파일은 분리한다.
- 처음부터 과도한 추상화, 미사용 옵션, 추측성 fallback을 넣지 않는다.
- 먼저 주경로를 단순하게 완성하고, 실제 문제가 확인된 뒤 필요한 만큼만 확장한다.
- 새 기능 배치, 레이어 경계, 의존 방향 판단은 `README.md`의 `새 기능을 어디에 둘까`를 단일 기준으로 삼는다.
- `app` 내부 기본 의존 방향은 `brokers/collectors -> features/labels -> models/services -> paper_trading/portfolio/risk -> reporting` 으로 유지한다.
- 민감한 운영 정보는 tracked repo 밖 `../secrets/`에서만 관리한다.

## 6. 산출물과 네이밍 기준

- 로컬 워크스페이스는 `repo / env / secrets` sibling 구조를 기본으로 유지한다.
- 실제 대용량 실행 산출물은 `runtime-data/` 아래에만 둔다.
- root `results/`는 만들지 않는다.
- 새 산출물 루트와 시간이 지나며 누적되는 문서는 가능하면 `YYMMDD_HHMM_설명` prefix를 사용한다.
- smoke, debug, failed run 산출물은 최종 canonical 산출물이 확보되면 삭제 가능한 임시 자산으로 본다.
- git으로 추적할 가치가 있는 소형 자산과 metadata만 repo 안에 둔다.

## 7. 반복 작업은 skill 또는 스크립트로 분리한다

- 이 저장소의 공용 skill 원본 자리는 `repo/.agents/skills/` 아래에 둔다.
- 현재는 canonical skill 본문보다 실행 스크립트가 먼저 존재한다.
- 반복 절차는 가능하면 `scripts/`로 고정하고, 자주 반복되면 나중에 skill로 승격한다.
- 장시간 자동 실행은 watcher 로그와 상태 파일을 남기도록 한다.

## 8. 실무 기본 명령

- 전체 테스트
  - `python -m unittest discover -s tests -p "test_*.py"`
- synthetic 전체 흐름
  - `python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15`
- 단순 백테스트
  - `python -m app --run-backtest --horizon-min 15`
- walk-forward 백테스트
  - `python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10`
- runtime report 생성
  - `python -m app --build-runtime-report`
- 버전 갱신
  - `.\scripts\bump_version.ps1 -Version 0.2.1`

## 9. 완료 기준

- 관련 검증 명령을 실제로 돌려 결과를 확인한다.
- 코드만 끝내지 않고 관련 canonical 문서를 같은 턴에 함께 갱신한다.
- 산출물 경로, 다음 연결점, 삭제된 임시 자산이 있으면 `docs/logbook.md`에 남긴다.
- 변경된 파일이 있으면 가능한 한 같은 턴 안에 commit과 configured remotes push까지 마친다.

## 10. 새 저장소 시작용 복사본

- 이 저장소의 공통 운영 팩 복사본 자리는 `templates/codex_starter/` 아래에 둔다.
- 새 저장소를 시작할 때는 여기의 문서를 복사해 시작한다.
- 복사 후에는 해당 저장소의 구조, 실행 명령, 검증 기준, 민감 정보 경계를 맞게 수정한다.

<!-- NAS_BACKUP_START -->
## NAS Backup Operations

- This repository uses NAS full-backup recovery packages.
- Baseline policy: full backups, latest 3 retained, weekly regular runs, forced backups for important periods.
- Current NAS share-root baseline: \\192.168.0.2\backup
- Keep RECOVERY.md plus scripts/run_weekly_nas_backup.ps1 and scripts/run_forced_nas_backup.ps1 aligned with any policy changes.
- If the backup policy changes, update RECOVERY.md, README.md, AGENTS.md, and the backup scripts together.
<!-- NAS_BACKUP_END -->


