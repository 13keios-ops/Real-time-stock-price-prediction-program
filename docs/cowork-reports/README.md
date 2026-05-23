# Codex-Cowork Report History

이 폴더는 Codex와 Claude cowork 사이에 전달한 검토 리포트를 날짜별 Markdown 파일로 보관한다.

규칙:

- 기준 문서의 최신 사실은 `docs/*.md`에 남기고, 이 폴더는 전달 이력과 리뷰 요청 맥락만 보관한다.
- KIS app key, app secret, token, 계좌번호 같은 비밀값은 쓰지 않는다.
- Claude cowork 토큰 제약이 있을 때는 이력 파일을 짧게 유지하고, 필요한 리뷰 질문만 남긴다.

명명 규칙:

- Codex 작업 리포트: `YYYY-MM-DD-{topic}-work_ver_N.md`
- cowork 리뷰 리포트: `YYYY-MM-DD-{topic}-review_ver_N.md`
- 같은 Codex 작업 리포트 `work_ver_N`을 리뷰한 cowork 파일은 같은 숫자의 `review_ver_N`을 쓴다.
- `review_ver_N`을 반영해 Codex가 다시 작업하면 다음 파일은 `work_ver_N+1`이 된다.
- 사용자가 작업을 요청했는데 같은 topic의 새 cowork 리뷰 파일이 없으면, Codex 중간 작업 리포트는 `work_ver_N-1`, `work_ver_N-2`처럼 하위 번호를 쓴다.
- 계좌 소유자/실전 운용 승인권자 결정 기록: `YYYY-MM-DD-{topic}-operator-decision.md`
- 같은 topic의 여러 라운드는 같은 `{topic}` 키를 유지한다.
- 아래 현재 리포트 중 `report`, `cowork-review`, `codex-followup` 이름은 새 규칙 도입 전 레거시 파일이다.

현재 리포트:

- `2026-05-14-production-architecture-implementation-blueprint-report.md`
- `2026-05-14-production-architecture-implementation-blueprint-cowork-review.md`
- `2026-05-14-production-architecture-implementation-blueprint-codex-followup.md`
- `2026-05-14-production-architecture-implementation-blueprint-work_ver_2.md`
- `2026-05-14-production-architecture-implementation-blueprint-review_ver_2.md`
- `2026-05-14-production-architecture-implementation-blueprint-work_ver_3.md`
- `2026-05-14-production-architecture-implementation-blueprint-work_ver_3-1.md`
- `2026-05-14-production-architecture-implementation-blueprint-work_ver_3-2.md`
- `2026-05-14-production-architecture-implementation-blueprint-review_ver_3.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_4.md`
- `2026-05-15-production-architecture-implementation-blueprint-review_ver_4.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_5.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_5-1.md`
- `2026-05-15-production-architecture-implementation-blueprint-review_ver_5.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_6.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_6-1.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_6-2.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_6-3.md`
- `2026-05-15-production-architecture-implementation-blueprint-review_ver_6.md`
- `2026-05-15-production-architecture-implementation-blueprint-work_ver_7.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-1.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-2.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-3.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-4.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_7-5.md`
- `2026-05-16-production-architecture-implementation-blueprint-review_ver_7.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_8.md`
- `2026-05-16-production-architecture-implementation-blueprint-review_ver_8.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_9.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_9-1.md`
- `2026-05-16-production-architecture-implementation-blueprint-work_ver_9-2.md`
- `2026-05-16-production-architecture-implementation-blueprint-review_ver_9.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_10.md`
- `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-1.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-2.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-3.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-4.md`
- `2026-05-17-production-architecture-implementation-blueprint-work_ver_11-5.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-6.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-7.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-8.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-9.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-10.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-11.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-12.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-13.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-14.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-15.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-16.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-17.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-18.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-19.md`
- `2026-05-18-production-architecture-implementation-blueprint-work_ver_11-20.md`
- `2026-05-19-production-architecture-implementation-blueprint-work_ver_12.md`
- `2026-05-19-production-architecture-implementation-blueprint-work_ver_12-1.md`
- `2026-05-19-production-architecture-implementation-blueprint-work_ver_12-2.md`
- `2026-05-19-production-architecture-implementation-blueprint-work_ver_12-3.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13-1.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13-2.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13-3.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13-4.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13-5.md`
- `2026-05-20-production-architecture-implementation-blueprint-work_ver_13-6.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_13-7.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_13-8.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_13.md`
- `2026-05-21-production-architecture-implementation-blueprint-review_ver_13.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-1.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-2.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-3.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-4.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-5.md`
- `2026-05-21-production-architecture-implementation-blueprint-work_ver_14-6.md`
- `2026-05-22-production-architecture-implementation-blueprint-review_ver_14.md`
- `2026-05-22-production-architecture-implementation-blueprint-work_ver_15.md`
- `2026-05-22-production-architecture-implementation-blueprint-review_ver_15.md`
- `2026-05-23-production-architecture-implementation-blueprint-work_ver_16.md`
- `2026-05-14-production-architecture-implementation-blueprint-operator-decision-template.md`
- `2026-05-14-production-architecture-implementation-blueprint-operator-decision.md`
- `2026-05-17-production-architecture-implementation-blueprint-operator-decision.md`
