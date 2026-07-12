# Codex + Cowork 협업 운영 기준

## 역할

이 문서는 Codex와 외부 cowork가 같은 저장소를 검토할 때의 현재 협업 절차를 정의한다.
저장소 내부 작업 규칙은 `AGENTS.md`가 최우선이며, 현재 사실은 기준 문서와 실제 리포트를 따른다.

- Codex: 구현, 검증, 문서 동기화, 커밋과 푸시를 끝까지 수행한다.
- cowork: 독립 검산과 비판적 리뷰를 기본 역할로 한다.
- 운영자: 계좌 소유자 또는 실전 운용 승인권자다. AI 도구를 운영자라고 부르지 않는다.
- 사용자가 승인한 ML 실험 범위에서는 `AGENTS.md`의 자율 범위를 따른다.

과거의 `Codex는 코드만`, `Cowork는 실행만` 같은 고정 역할 분리는 더 이상 현재 규칙이 아니다.
원문은 `docs/archive/WORKFLOW-legacy-through-20260712.md`에 보존한다.

## 기준 우선순위

1. `AGENTS.md`
2. 실제 코드, 테스트, runtime 상태 파일
3. `README.md`, `docs/Current-Implementation.md`
4. `docs/Production-Transition-Progress.md`, `docs/Execution-Plan.md`
5. `docs/Model-Research-PreRegistration.md`
6. 최신 `docs/cowork-reports/*review_ver_*`와 대응 `work_ver_*`
7. 아카이브와 과거 참고 문서

과거 문서와 현재 구현이 충돌하면 현재 코드와 기준 문서를 우선하고, 충돌 자체를 작업 리포트에 기록한다.

## 기본 반복 절차

1. 장 상태와 live runtime/watchdog를 실제 명령으로 확인한다.
2. 최신 review와 work가 같은 주제를 이미 닫았는지 확인한다.
3. 리뷰 지적을 코드, 테스트, JSON/Markdown 산출물에 각각 대조한다.
4. 타당한 지적만 최소 범위로 반영한다.
5. 관련 테스트와 전체 검증을 실행한다.
6. `docs/logbook.md`와 기준 문서를 갱신한다.
7. `work_ver_*`에 결과뿐 아니라 Codex 의견, 다음 방향, 보류 기준을 남긴다.
8. 변경이 있으면 같은 작업에서 commit과 push까지 마친다.

## 파일 규칙

- 리뷰: `docs/cowork-reports/YYYY-MM-DD-주제-review_ver_N.md`
- 작업 결과: `docs/cowork-reports/YYYY-MM-DD-주제-work_ver_N.md`
- 토론이나 계획: 주제를 드러내는 별도 Markdown 파일
- 현재 상태: `docs/STATUS.md`
- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- 최근 작업 기록: `docs/logbook.md`
- 오래된 원문: `docs/archive/`와 `docs/logbook_archive/`

`docs/STATUS.md`와 `docs/logbook.md`에 긴 실험 전문을 반복하지 않는다.

## 안전 경계

- 기본 거래 모드는 `paper`다.
- 실전 주문/취소, live flag, gate, `app/risk/`, `config/`, `VERSION`은 명시 범위 없이 바꾸지 않는다.
- 자격정보와 계좌 식별자는 문서, 로그, 리뷰에 기록하지 않는다.
- 장중 수집 보호 모드에서는 `AGENTS.md`가 허용한 읽기 전용 작업만 수행한다.
- NAS 백업은 사용자가 그 작업에서 명시적으로 지시한 경우에만 실행한다.
- commit/push는 사용자의 영구 승인에 따라 반복 질문 없이 수행한다. 도구 정책이 막으면 우회하지 않는다.

## 완료 보고

완료 보고에는 실제 상태, 변경 파일, 검증 결과, 모델/Phase 의미, 남은 blocker, 운영자 결정 필요 여부를 포함한다.
