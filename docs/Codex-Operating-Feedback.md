# Codex Operating Feedback

이 문서는 사용자가 반복해서 지적한 운영 방식 문제를
작업 전후 체크리스트로 고정하기 위한 기준이다.
규칙 자체는 `AGENTS.md`가 우선이고, 이 문서는 누락 방지용 보조판이다.

## 1. 목적

- 반복 지적을 다음 작업에서 다시 놓치지 않게 만든다.
- 어떤 내용은 `AGENTS.md` 필수 규칙으로 두고,
  어떤 내용은 저장소 전용 skill 후보로 볼지 분리한다.
- 최종 답변이 최근 한 문장에만 끌려가지 않고,
  전체 작업 흐름과 현재 상태를 함께 보고하도록 고정한다.

관련 문서/코드 경로:
`AGENTS.md`, `README.md`, `docs/logbook.md`, `.agents/skills/README.md`

## 2. 반복 지적 체크리스트

### 작업 시작

- 장 진행 상태와 runtime/watchdog 상태를 먼저 확인한다.
- cowork ping-pong 중이면 최신 `review_ver_*`를 먼저 확인한다.
- 사용자가 이미 승인한 같은 작업 범위의 commit/push를 반복해서 묻지 않는다.
- 장중 보호 모드면 root 코드 변경, 전체 테스트, dashboard/runtime 재생성을 피한다.
- D드라이브 기준 저장 경로를 확인하고 새 캐시/다운로드/대용량 산출물을
  C드라이브나 OS 기본 임시 폴더에 두지 않는다.

관련 문서/코드 경로:
`scripts/get_live_runtime_status.sh`,
`scripts/get_runtime_watchdog_status.sh`,
`docs/cowork-reports/`

### 작업 중

- 판단이 필요한 항목은 `권장안`을 먼저 제시하고,
  사용자 판단이 꼭 필요한 이유를 함께 적는다.
- 운영자는 Codex나 Claude가 아니라
  계좌 소유자 또는 실전 운용 승인권자를 뜻한다.
- NAS 백업은 사용자가 해당 작업에서 명시적으로 지시한 경우에만 실행한다.
- side panel에서 열어야 하는 문서는 긴 표와 긴 한 줄을 피하고,
  짧은 section과 bullet 중심으로 작성한다.
- cowork 토큰이 부족한 기간에는 Codex가 가능한 단계까지 진행하고,
  꼭 필요한 질문이나 리뷰 지점에서만 전달용 report를 만든다.

관련 문서/코드 경로:
`docs/Production-Architecture.md`,
`docs/Production-Transition-Progress.md`,
`docs/cowork-reports/README.md`

### 최종 답변

- 최근 steering 질문만 답하지 말고,
  이번 큰 작업 흐름에서 확인한 상태와 조치 결과를 같이 보고한다.
- 최종 답변 전에 종료 전 self-review 를 하고,
  누락한 작업, 잘못 진행한 부분, 결과를 잘못 판단한 부분,
  코드 오류점검, 그 외 필요 리뷰가 있으면
  답변 전에 먼저 조치하거나 `확인 필요`와 다음 조치를 분리해서 적는다.
- 변경 파일, 검증 결과, 남은 위험, 다음 권장안을 짧게 묶어 말한다.
- 작업 마지막에는 현재 작업 모드, 답변 접두어,
  활성 체크리스트 갱신 여부, 기준 문서 반영 여부를 확인한다.
- 푸시나 NAS 백업이 정책/도구에서 막히면 우회하지 않고,
  막힌 이유와 실제 남은 상태를 보고한다.

관련 문서/코드 경로:
`AGENTS.md`, `docs/logbook.md`, `docs/Production-Transition-Progress.md`

## 3. 문서 반영 기준

- 반복 지적이 한 번 더 나오면 먼저 이 문서에 항목이 있는지 확인한다.
- 이미 있는 항목이면 더 구체적인 시행 지점을 추가한다.
- 새 필수 규칙이면 `AGENTS.md`에도 짧게 반영한다.
- 운영 상태나 phase 진행과 연결되면
  `docs/Production-Transition-Progress.md`에도 현재 상태를 갱신한다.
- 당일 실제 조치와 검증 결과는 `docs/logbook.md`에 남긴다.

관련 문서/코드 경로:
`AGENTS.md`, `docs/Production-Transition-Progress.md`, `docs/logbook.md`

## 4. Skill 후보 판정 기준

아래 조건을 많이 만족하면 저장소 전용 skill 후보로 본다.

- 같은 절차가 3회 이상 반복된다.
- 매번 빠지는 순서나 실수가 있다.
- 작업 시작 전 읽어야 할 문서와 실행할 명령이 거의 고정돼 있다.
- 결과 보고 형식이 반복된다.
- 비밀값, 실전 주문, NAS 백업처럼 실수 비용이 큰 안전 규칙이 있다.
- AGENTS 필수 규칙만으로는 실제 작업 단계가 충분히 떠오르지 않는다.

아래 조건이면 skill보다 `AGENTS.md` 규칙이나 스크립트가 먼저다.

- 모든 작업에 항상 적용되는 금지 규칙이다.
- 실행 순서가 완전히 결정적이라 스크립트로 잠글 수 있다.
- 아직 절차가 자주 바뀌어 skill로 고정하면 오히려 stale해진다.

관련 문서/코드 경로:
`.agents/skills/README.md`, `AGENTS.md`

## 5. 현재 Skill 후보

### Daily Ops Check

- 후보 상태: skill 승격 완료
- 대상:
  장전/장후 자동화 결과 확인, runtime/watchdog/dashboard 상태,
  계좌 정합성, data quality, logbook 갱신.
- 이유:
  거의 매일 반복되고, 빠지면 장중 수집과 정합성 판단에 직접 영향이 있다.
- 권장안:
  `.agents/skills/daily-ops-check/SKILL.md`를 기준으로 사용한다.
- 2026-06-02 보강:
  broker open order가 남아 있고 order-fill 조회가 rate limit이면
  marker-only alignment를 보류하고 `needs_review`를 유지한다.

관련 문서/코드 경로:
`.agents/skills/daily-ops-check/SKILL.md`,
`scripts/get_live_runtime_status.sh`,
`scripts/get_runtime_watchdog_status.sh`,
`runtime-data/reports/`

### Cowork Ping-Pong

- 후보 상태: 강함
- 대상:
  `work_ver_N`, `review_ver_N`, `work_ver_N-M` 파일명,
  cowork 토큰 제약, 전달용 report 통합본 생성, 리뷰 반영 self-review.
- 이유:
  절차가 반복되고 파일명/버전 실수가 나면 협업 흐름이 끊긴다.
- 권장안:
  `docs/cowork-reports/README.md` 기준이 더 안정되면 skill로 승격한다.

관련 문서/코드 경로:
`docs/cowork-reports/README.md`, `docs/cowork-reports/`

### Market-Safe Work Mode

- 후보 상태: 중간
- 대상:
  장중 보호 모드, 격리 테스트, read-only 점검, D드라이브 산출물 위치.
- 이유:
  모든 작업에 걸치는 필수 안전 규칙이라 AGENTS와 겹친다.
- 권장안:
  skill보다 `AGENTS.md`와 스크립트 check를 우선 유지한다.

관련 문서/코드 경로:
`AGENTS.md`, `scripts/get_live_runtime_status.sh`

### Final Report Shape

- 후보 상태: 중간
- 대상:
  최종 답변에서 전체 흐름, 조치, 검증, 남은 위험,
  권장안, commit/push/NAS 상태를 빠뜨리지 않는 형식.
- 이유:
  사용자가 반복해서 지적한 영역이고, 답변 품질에 직접 영향이 있다.
- 권장안:
  지금은 이 문서와 `AGENTS.md` 체크포인트로 관리하고,
  누락이 반복되면 skill로 승격한다.

관련 문서/코드 경로:
`AGENTS.md`, `docs/logbook.md`

### Recovery And Backup Discipline

- 후보 상태: 약함
- 대상:
  NAS 백업, sanitized recovery export, secret 제외, push/backup 보고.
- 이유:
  이미 `RECOVERY.md`, `AGENTS.md`, 스크립트에 기준이 많다.
- 권장안:
  skill보다 기존 문서와 wrapper 테스트를 유지한다.

관련 문서/코드 경로:
`RECOVERY.md`, `scripts/run_weekly_nas_backup.sh`,
`scripts/run_forced_nas_backup.sh`

## 6. 다음 점검 방식

- 작업 시작 전:
  `AGENTS.md`의 작업 흐름과 이 문서의 2장을 함께 확인한다.
- 작업 종료 전:
  최종 답변 체크포인트와 함께 아래 5가지를 확인한다.
  1. 누락한 작업이 없는지
  2. 잘못 진행한 부분이 없는지
  3. 결과에 대해 잘못 판단한 부분이 없는지
  4. 코드 오류점검이 필요한 작업이면 import, syntax, 호출 경로, 예외 처리, 테스트 필요성을 확인했는지
  5. 작업 범위와 맞닿은 dashboard, 자동화, 데이터 오염, KIS/모의계좌, 보안/비밀값, 저장 경로, cowork 전달물, 사용자 운영 흐름을 리뷰했는지
  문제가 있으면 가능한 범위에서 먼저 조치하고,
  직접 확인하지 못한 내용은 단정하지 않고 `확인 필요`로 남긴다.
- 반복 지적 발생 시:
  이 문서의 해당 항목을 강화하거나 새 항목을 추가한다.
- skill 승격 검토 시:
  4장의 판정 기준으로 후보를 고르고,
  `.agents/skills/` 아래에 최소한의 `SKILL.md`만 둔다.

관련 문서/코드 경로:
`AGENTS.md`, `.agents/skills/README.md`
