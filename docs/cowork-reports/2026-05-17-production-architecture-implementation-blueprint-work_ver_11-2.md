# Codex work_ver_11-2: recovery export self-test + tar exclude fix

## 버전 맥락

- topic: `production-architecture-implementation-blueprint`
- 이 파일: `work_ver_11-2`
- 기준 작업본: `work_ver_11-1`
- 새 cowork review 없이 진행한 Codex 추가 작업이다.

## 작업 이유

실전 audit/alert/live-risk 경로가 NAS recovery export에 포함되는지 확인하는 self-test가 아직 없었다. 실제 NAS 공유에 접근하지 않고 작은 임시 저장소를 tar로 export한 뒤 archive 내용만 검사하는 테스트를 추가했다.

## 발견한 문제

초기 self-test에서 `runtime-data/logs/app/app.log`와 `runtime-data/cache/kis/token.json`이 archive에 포함되는 문제가 드러났다.

원인:

- `scripts/wsl_ops.py`의 `export_recovery()`는 파일별 제외 조건을 두고 있었다.
- 하지만 디렉터리를 `tar.add(path, arcname=rel)`로 추가하면 Python tarfile 기본값이 하위 파일을 재귀적으로 함께 넣는다.
- 그 결과 상위 디렉터리가 먼저 archive에 들어갈 때 제외 대상 하위 파일이 우회 포함될 수 있었다.

## 코드 변경

- 변경: `scripts/wsl_ops.py`
  - recovery export에서 `tar.add(path, arcname=rel, recursive=False)`로 변경.
  - 디렉터리 자체는 archive에 남기되, 하위 파일은 루프의 제외 정책을 각각 통과한 경우에만 추가된다.
- 변경: `tests/test_wsl_ops.py`
  - `runtime-data/reports/alerts/`
  - `runtime-data/reports/live-risk/`
  - `runtime-data/reports/live-approvals/`
  - `runtime-data/ops/`
  - `runtime-data/ml/registry-backups/`
  - 위 경로가 recovery archive에 포함되는지 확인.
  - root `.env`, `runtime-data/cache/kis`, `runtime-data/logs`, key 파일이 제외되는지 확인.

## 문서 변경

- `docs/Production-Architecture.md`
  - recovery export self-test 구현 사실과 `recursive=False` 제외 정책 보강을 반영.
- `docs/Production-Implementation-Blueprint.md`
  - P2-B NAS recovery self-test를 구현 완료 범위로 갱신.
  - 실제 NAS 공유 접근/복구 drill은 후속으로 남김.
- `docs/cowork-reports/README.md`, `docs/logbook.md` 갱신.

## 검증

- `python -m unittest tests.test_wsl_ops` 1차 실패: 기존 export가 runtime logs/KIS token cache를 포함하는 문제 확인.
- `scripts/wsl_ops.py` 수정 후 `python -m unittest tests.test_wsl_ops` 통과, 11개.
- 전체 테스트와 `git diff --check`는 최종 라운드에서 다시 실행 예정.

## 의도적으로 하지 않은 것

- 실제 NAS 공유 접근 없음.
- 실제 backup 실행 없음.
- runtime-data/dev.db 운영 DB 접근 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.

## cowork 리뷰 질문

1. `tar.add(..., recursive=False)`로 디렉터리 재귀 포함을 막고 파일별 제외 정책을 강제하는 방식이 충분한가?
2. recovery export self-test의 포함 경로와 제외 경로가 실전 운용 감사/alert 관점에서 충분한가?
3. 실제 NAS 복구 drill은 Phase 2 전 필수 조건으로 남겨야 하는가, 아니면 Phase 1 read-only 전부터 요구해야 하는가?

## 다음 단계 권장

🟢 다음 단계 권장: 실제 NAS 공유에 쓰는 백업 실행은 별도 승인 후 dry-run/소형 복구 drill로 검증한다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 실제 NAS 복구 drill 주기와 보관 기간.
