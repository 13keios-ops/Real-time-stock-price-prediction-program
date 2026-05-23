# Codex 작업 리포트 work_ver_7-5: readiness 명시 DB 기록 옵션

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-4.md`
- 새 cowork review 없음. 따라서 명명 규칙에 따라 `work_ver_7-5`로 기록한다.
- 작업 시각: 2026-05-16 02시대, `weekend`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| readiness DB 저장 | dry-run JSON만 생성했다. | `--record --database-path <repo 내부 경로>`를 함께 줄 때만 `live_readiness_runs`에 insert한다. | `scripts/script_dispatch.sh`, `tests/test_live_readiness_dry_run_script.py` | 운영 DB 경로를 명시하면 실제 DB insert가 가능하므로 runbook 승인 절차가 필요 |
| 기본 실행 | JSON only | 그대로 JSON only | `scripts/run_live_readiness_dry_run.sh` | 기본 동작 회귀 위험 낮음 |
| 경로 제한 | report/premarket/fixture만 repo 내부 제한 | database path도 repo 내부로 제한 | script wrapper | 외부 DB 기록 불가 |

## 3. 구현 세부

갱신 파일:

- `scripts/script_dispatch.sh`
- `tests/test_live_readiness_dry_run_script.py`
- `AGENTS.md`
- `README.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`
- `docs/logbook.md`

정책:

- `run_live_readiness_dry_run.sh` 기본 실행은 계속 JSON only다.
- `--record`만 주면 실패한다.
- `--record --database-path <repo 내부 경로>`가 같이 있을 때만 SQLite insert를 시도한다.
- 대상 DB 파일은 이미 존재해야 하며, wrapper가 새 SQLite 파일을 조용히 만들지 않는다.
- SQLite store는 `initialize_schema=False`로 열어 schema 자동 생성/적용을 하지 않는다.
- 운영 DB에는 이번 작업 중 실행하지 않았다. 테스트는 `.tmp-tests/` 아래 임시 DB만 사용했다.
- dashboard `실전 전환 readiness dry-run` 카드는 `recorded`와 `database_path`를 함께 표시한다.

## 4. 검증

- `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh`
  - 통과
- `python -m unittest tests.test_live_readiness_dry_run_script tests.test_live_phase_readiness`
  - 통과, 16개
- `python -m unittest tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_dashboard tests.test_codex_ops tests.test_codex_ops_job_script`
  - 통과, 46개
- `python -m app --build-dashboard`
  - 통과
  - 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`
- `python -m unittest discover -s tests -p "test_*.py"`
  - 통과, 187개
- `git diff --check`
  - 통과. 단, `docs/logbook.md`의 CRLF/LF 정규화 경고가 함께 표시됨
- `git diff -- app/risk VERSION config`
  - 출력 없음

## 5. 안전 확인

- 운영 DB insert 실행 없음
- 운영 DB schema apply 없음
- 실제 장애 주입 없음
- Codex CLI 실제 호출 없음
- KIS live 주문 API 호출 없음
- `ALLOW_LIVE_ORDERS` 변경 없음
- gate 기준값 변경 없음
- `app/risk/` 변경 없음
- `VERSION` 변경 없음
- `config/` 변경 없음
- 자동 commit/push 없음

## 6. 다음 권장

🟢 다음 단계 권장: 운영 DB에 Slice 2b schema를 적용한 뒤에도 `--record`는 장전 readiness runbook 안에서만 호출하도록 묶는다. 권장안은 dashboard 또는 premarket report가 `recorded=true/false`를 함께 보여주게 하는 것이다.

🟢 다음 단계 권장: `database` check는 현재 `storage_migration_state`와 가깝다. 다음 구현에서는 SQLite read/write smoke를 별도 fixture 또는 premarket check로 분리해 `database`를 실제 DB 연결성 의미로 좁히는 것이 좋다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 운영 DB에 `--record`를 언제 허용할지 runbook 승인 절차를 정해야 한다. Codex 권장안은 Phase 1 read-only 전환 직전까지는 수동 실행만 허용하는 것이다.

## 7. cowork 확인 질문

1. `--record`가 `--database-path` 없이는 실패하고, 기본은 JSON only인 구조가 충분히 보수적인지.
2. SQLite schema 자동 생성 없이 `initialize_schema=False`로 insert만 시도하는 정책이 운영 DB 적용 전 안전 기준에 맞는지.
3. 다음 단계에서 `database` check를 실제 SQLite read/write smoke로 분리하는 권장안에 이견이 없는지.
