# 저장소 점검 자동화

## 목적

매시간 저장소 점검은 이 저장소 전체를 매시간 다시 읽고, 이전 자동화 산출물을 이어받아 아래 작업을 반복한다.

- 구조 점검
- 누락된 구체화 식별
- 코드와 문서 불일치 탐지
- 웹서치 기반 개선 제안
- 다음 회차용 상태 갱신

자동화는 git 추적 파일을 수정하지 않고 `runtime-data/reports/codex/automation/` 아래에만 산출물을 남긴다.

## 스크립트

- `scripts/run_hourly_repo_audit_iteration.sh`
  - 현재 시점 기준 1회 점검 실행
- `scripts/start_hourly_repo_audit.sh`
  - 즉시 1회 실행 후 매시간 반복
- `scripts/start_hourly_repo_audit_background.sh`
  - 백그라운드에서 실행기를 시작하고 바로 상태를 반환
- `scripts/get_hourly_repo_audit_status.sh`
  - 현재 실행기 상태 확인
- `scripts/stop_hourly_repo_audit.sh`
  - 현재 실행기 중지

## 권장 실행 방식

- 1순위는 Codex 자동화다.
- Codex 자동화로 등록하면 앱 UI에서 즉시 중지할 수 있다.
- bash 백그라운드 실행기는 Codex 자동화가 없을 때만 쓰는 예비 경로로 본다.
- 상태 스크립트는 저장된 pid 가 죽어 있으면 `stale` 로 보여준다.

## 출력 경로

- `runtime-data/reports/codex/automation/history/YYYY-MM-DD/HHMM-review.md`
- `runtime-data/reports/codex/automation/research/YYYY-MM-DD/HHMM-web-notes.md`
- `runtime-data/reports/codex/automation/drafts/latest-improvement-draft.md`
- `runtime-data/reports/codex/automation/state/latest-context.md`
- `runtime-data/reports/codex/automation/state/latest-progress.json`
- `runtime-data/reports/codex/automation/state/runner-state.json`
- `runtime-data/reports/codex/automation/backlog/latest-priority-backlog.json`
- `runtime-data/reports/codex/automation/backlog/history/YYYY-MM-DD-HHMM-backlog.json`

## 입력 기준

- 기준 문서를 매 회차 다시 읽는다.
  - `AGENTS.md`
  - `README.md`
  - `docs/logbook.md`
  - 최신 `docs/logbook_archive/logbook_*.md`
  - `docs/Current-Implementation.md`
  - `docs/Versioning.md`
- 최신 실행 리포트와 로그를 함께 읽는다.
- 이전 자동화 상태 파일도 함께 읽는다.

## 웹서치 기준

- 공식 문서와 1차 출처를 먼저 본다.
- GitHub 저장소, 이슈, 커뮤니티 글은 보조 근거로만 쓴다.
- 링크와 검토 시각은 항상 산출물에 남긴다.

## KIS 검증 기준

- 평일 정규장 시간에는 `python -m app --verify-kis-ws --symbols 005930 --max-frames 20 --max-reconnects 1` 실행 후보로 둔다.
- 주말과 장외 시간에는 KIS 시장데이터 미수신을 실패로 보지 않고 보류로 기록한다.
- `connection_ready` 와 `market_data_flow_ok` 는 분리해서 해석한다.

## 상태 이어받기 기준

- `latest-progress.json`
  - 기계가 읽는 현재 상태
- `latest-context.md`
  - 사람이 바로 읽는 인수인계 메모
- `latest-improvement-draft.md`
  - 지금까지 누적한 최적 구조안
- `latest-priority-backlog.json`
  - 현재 우선순위 작업 목록

같은 미해결 항목은 같은 식별자를 유지하고, 다음 회차에서는 `last_seen` 과 근거만 갱신한다.

## 운영 메모

- Codex 호출 일부가 실패해도 예비 산출물은 남긴다.
- 예비 단계에서는 기존 진행 상태와 우선순위 목록을 최대한 보존한다.
- 이 자동화는 git commit, git push, 실전 주문, 민감정보 출력은 하지 않는다.
