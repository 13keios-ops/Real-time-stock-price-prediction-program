# 작업 기록

## 역할

이 파일은 현재 상태, 활성 체크리스트, 최신 검증만 유지한다.
긴 과거 기록은 `docs/logbook_archive/`와 `docs/archive/`에 보관한다.

## 현재 스냅샷

- 기준 시각: `2026-07-13 01:03 KST`
- 장 상태: `overnight`
- live runtime: 정상 정지
- watchdog/dashboard/startup launcher: 정상
- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 현재 수익 후보: `0개`
- Phase 0: `1/10`, mismatch 4종목
- Phase 1b: bounded read-only 관측 1회 통과

상세 현재값은 `docs/STATUS.md`, Phase 상태는 `docs/Production-Transition-Progress.md`를 기준으로 한다.

## 활성 체크리스트

- [ ] 2026-07-13~17 complete lineage decision ledger 축적
- [ ] 거래일별 Phase 0 정합성 유효 기록 누적
- [ ] 2026-07-20 장후 E1/E5 사전등록 라운드 1회 실행
- [ ] E1/E5 결과에 따라 h15 저빈도/h60 비교 여부 결정
- [ ] 수익 후보가 없으면 threshold tuning 대신 새 가설 사전등록

현재 상세 작업 범위는 `docs/SPRINT_CURRENT.md`를 따른다.

## 최신 검증

- 전체 unittest: `518 tests OK`
- 전체 pytest: `518 passed, 67 subtests passed`
- 저장소 구조/Markdown 감사: `errors=0`, 구조 부채 경고 2건
- dashboard snapshot: `2026-07-12 22:40 KST` 생성
- dashboard server/API: 정상
- 작업 시작 시 git: `main`과 `origin/main` 동기화

## [2026-07-13] 저장소 구조와 현재 문서 정리

- 전체 구조를 실제 파일 기준으로 감사했다: app Python 97개, 테스트 89개, scripts 최상위 139개.
- 감사 전 추적 Markdown 208개의 명시적 local link 누락과 불균형 code fence는 각각 0건이었다.
- `logbook`, `STATUS`, 초기 sprint/workflow/cowork guide, 실전 전환 진행판 원문을 `docs/archive/`에 보존했다.
- archive와 HEAD 원문은 줄바꿈 정규화 기준으로 모두 일치한다.
- 현재판 6개 문서를 합계 약 1만 줄에서 406줄로 축약하고 문서별 소유권을 고정했다.
- `docs/Repository-Structure.md`에 실제 레이어, wrapper 규칙, D드라이브 위치, 구조 부채를 기록했다.
- `scripts/audit_repository_structure.py`와 회귀 테스트 3개를 추가했다.
- 전체 unittest `518 tests OK`, pytest `518 passed, 67 subtests passed`.
- cleanup helper로 87개, `94,171,757 bytes`를 정리하고 root `.pytest_cache`도 제거했다.
- 최종 감사 `errors=0`, 경고는 `research.py`와 `dashboard.py` 대형 모듈 2건뿐이다.
- 대형 모듈은 현재 계약 범위가 넓어 이번 작업에서 분해하지 않고 별도 테스트 리팩터링 대상으로 남겼다.
- 주문 정책, 모델, threshold, gate, Phase 상태, runtime DB, NAS 백업은 변경하지 않았다.

## [2026-07-12] review_ver_33 수익성 증거 정합성

- hold-rescue 기본비용을 구형 `0.13%`에서 현재 `0.29%`로 교정했다.
- E6 `cybos_historical`을 순수 Cybos가 아닌 pre-KIS 혼합 근사치로 명시했다.
- 구형 비용 `0.108%` walk-forward를 현행 수익성 증거에서 제외했다.
- 모든 challenger와 rescue/avoid 후보가 비용 후 수익 또는 재현성 기준을 통과하지 못했다.
- 주문 정책, threshold, active model, gate는 변경하지 않았다.
- 작업 리포트: `docs/cowork-reports/2026-07-12-rescue-avoid-profitability-review-work_ver_34.md`

## 아카이브

- 최신 요약: `docs/logbook_archive/logbook_20260712.md`
- 2026-07-12까지 전체 원문: `docs/archive/logbook-full-through-20260712.md`
- 최초 아카이브: `docs/logbook_archive/logbook_20260411.md`
