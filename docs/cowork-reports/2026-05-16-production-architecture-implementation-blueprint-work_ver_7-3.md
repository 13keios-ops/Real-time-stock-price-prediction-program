# Codex 작업 리포트 work_ver_7-3: dashboard readiness dry-run 카드

## 1. 작업 맥락

- 기준 리뷰: `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- 직전 작업본: `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-2.md`
- 새 cowork review 없음. 따라서 명명 규칙에 따라 `work_ver_7-3`으로 기록한다.
- 작업 시각: 2026-05-16 02시대, `weekend`

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| readiness 표시 | JSON report를 파일로만 확인해야 했다. | dashboard `상태 및 설정 > 현재 프로그램 상태`에 `실전 전환 readiness dry-run` 카드를 추가했다. | `app/services/dashboard.py`, `tests/test_dashboard.py` | report schema가 바뀌면 표시 값이 `-` 또는 `미검증/차단`으로 보일 수 있음 |
| 운영 DB 연결 | readiness report가 DB record와 분리되어 있었다. | 이번에도 DB insert 없이 JSON read-only만 유지했다. | dashboard payload | DB 기록 누적은 아직 되지 않음 |

## 3. 구현 세부

신규/갱신 파일:

- `app/services/dashboard.py`
- `tests/test_dashboard.py`
- `docs/logbook.md`
- `docs/Production-Architecture.md`
- `docs/Production-Implementation-Blueprint.md`

표시 데이터:

- `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
- `runtime-data/reports/live-readiness/latest-readiness.json`

카드 표시 항목:

- Codex premarket 상태
- Live readiness 상태
- phase
- trading day
- 생성 시각
- dry-run 여부
- 통과 여부
- blockers
- token refresh / WebSocket recovery / account snapshot / market status / kill switch / database check

## 4. 검증

- `python -m unittest tests.test_dashboard tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script`
  - 통과, 26개
- `python -m unittest tests.test_dashboard tests.test_live_phase_readiness tests.test_live_readiness_dry_run_script tests.test_codex_ops tests.test_codex_ops_job_script`
  - 통과, 42개
- `bash -n scripts/script_dispatch.sh scripts/run_live_readiness_dry_run.sh scripts/run_codex_ops_job.sh`
  - 통과
- `python -m app --build-dashboard`
  - 통과
  - 생성: `runtime-data/reports/dashboard/latest-dashboard.html`, `runtime-data/reports/dashboard/latest-dashboard.json`

## 5. 안전 확인

- dashboard는 JSON report를 read-only로 읽는다.
- 운영 DB insert 없음
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

🟢 다음 단계 권장: readiness DB insert는 기본 동작으로 넣지 말고 별도 명시 옵션으로 설계한다. Codex 권장안은 `run_live_readiness_dry_run.sh`는 계속 JSON only로 두고, 후속 `--record` 또는 별도 script에서 `live_readiness_runs`에 저장하는 것이다.

🟢 다음 단계 권장: dashboard 카드가 보이면 다음에는 storage migration apply 전 운영자 확인 절차와 NAS backup self-test 상태를 같은 영역에 붙인다.

🔴 계좌 소유자/실전 운용 승인권자 판단 필요: 없음. 이번 작업은 read-only dashboard 표시와 테스트만 추가했다.

## 7. cowork 확인 질문

1. readiness report를 dashboard에 read-only로 표시하는 현재 위치가 적절한지.
2. DB insert를 기본 동작에서 제외하고 별도 명시 옵션으로 분리하는 권장안에 이견이 없는지.
3. 다음 카드를 storage migration apply readiness / NAS backup self-test로 확장해도 되는지.
