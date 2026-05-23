# Codex Work Ver 11-6

## 범위

`work_ver_11-5` 이후 장중 수집 보호 모드에서 진행한 작은 안전 보강입니다. KIS API 호출, runtime DB write, dashboard 재생성, 실전 주문 경로 연결은 하지 않았습니다.

## 보강 내용

- `app/brokers/kis_response_redaction.py`
  - `find_unredacted_sensitive_paths()`를 추가했습니다.
  - redaction 이후에도 민감 key 값이 `<REDACTED>`가 아니면 JSON path를 반환합니다.
- `scripts/export_kis_paper_fixture_candidates.py`
  - 후보별 `redaction_ok`, `redaction_findings`, `redaction_findings_count`를 출력에 추가했습니다.
  - summary status는 모든 후보가 redaction audit을 통과하면 `ok`, 하나라도 실패하면 `needs_review`가 됩니다.
  - `--fail-on-redaction-findings` 옵션을 추가했습니다. 정상 redaction이면 기존처럼 성공하고, findings가 있으면 non-zero exit로 전달 전 확인에 사용할 수 있습니다.
- `tests/test_kis_response_redaction.py`
  - redaction 완료 payload의 findings가 비어 있는지 검증합니다.
  - 일부러 남긴 `authorization` 값이 findings로 잡히는지 검증합니다.
- `tests/test_kis_paper_fixture_export_script.py`
  - export summary와 후보 payload의 `redaction_ok=true`를 검증합니다.

## 실제 DB 재확인

`python scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings`를 실행했습니다.

- `broker_paper_order_submissions`: 530 rows
- `broker_paper_order_status_snapshots`: 164,508 rows
- summary: `status=ok`
- summary: `redaction_ok=true`
- status snapshot 후보: `redacted_value_count=3`, `redaction_findings_count=0`

출력 파일:

- `runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json`

## cowork에 확인받고 싶은 부분

1. `redaction_ok=true`를 cowork 전달 전 최소 조건으로 두는 것이 충분한지.
2. 주문번호와 종목코드를 mapper 검증 때문에 보존하는 현재 정책을 유지할지.
3. `--fail-on-redaction-findings`를 cowork 전달 전 표준 명령에 포함할지. 현재 기본 실행은 summary만 만들고, 명시 옵션을 줄 때만 non-zero exit로 실패합니다.

## 검증

- `python -m py_compile app/brokers/kis_response_redaction.py scripts/export_kis_paper_fixture_candidates.py`
- `python -m unittest tests.test_kis_response_redaction tests.test_kis_paper_fixture_export_script`
- `python scripts/export_kis_paper_fixture_candidates.py --fail-on-redaction-findings`

## 안전 메모

- KIS live/paper API 신규 호출 없음.
- 실전 계좌 접근 없음.
- 운영 DB schema apply 없음.
- `ALLOW_LIVE_ORDERS`, gate 기준값, `app/risk/`, `VERSION`, `config/` 변경 없음.
- 자동 commit/push 없음.
