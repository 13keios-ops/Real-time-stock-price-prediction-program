# Cowork 검토 가이드

## 목적

cowork는 저장소의 독립 검토자다. 기본 임무는 Codex 결과를 그대로 승인하는 것이 아니라 실제 파일과 수치를 다시 확인하고, 누락·과장·위험한 해석을 찾는 것이다.

과거 스프린트 01 전용 가이드는 `docs/archive/COWORK_GUIDE-legacy-through-20260712.md`에 보존한다.

## 시작 순서

1. `AGENTS.md`
2. `README.md`
3. `docs/STATUS.md`
4. `docs/SPRINT_CURRENT.md`
5. `docs/Production-Transition-Progress.md`
6. 작업 주제와 관련된 최신 `review_ver_*`와 `work_ver_*`
7. 필요한 코드, 테스트, runtime report

`docs/archive/`, 오래된 `docs/logbook_archive/`, 과거 cowork report는 배경 확인이 필요할 때만 읽는다.

## 검토 원칙

- 주장마다 코드, 테스트, JSON/Markdown 산출물 중 최소 하나의 근거를 대조한다.
- 정확도와 비용 후 수익률, 신호 합계와 계좌 수익률, read-only readiness와 주문 가능 상태를 구분한다.
- 작은 표본, 같은 기간 재실행, 사후 threshold 선택을 재현성 증거로 인정하지 않는다.
- Cybos와 KIS, pure source와 날짜 기반 혼합 근사치를 구분한다.
- 현재 비용 세대와 구형 비용 산출물을 구분한다.
- 실전 주문, 자격정보 출력, 자동 align, gate 변경을 리뷰 편의를 위해 실행하지 않는다.

## 리뷰 문서 형식

1. 결론
2. 실제로 검산한 내용
3. 심각도별 발견 사항
4. 반드시 조치할 항목
5. 선택 개선 항목
6. 운영자 결정 필요 여부
7. 다음 리뷰가 의미 있는 시점

발견 사항이 없으면 `중대한 문제 없음`이라고 명시하고, 남은 표본 부족이나 외부 게이트를 따로 적는다.

## 현재 작업 연결

현재 목표와 동결 범위는 `docs/SPRINT_CURRENT.md`가 단일 기준이다.
현재 Phase와 blocker는 `docs/Production-Transition-Progress.md`를 따른다.
리뷰가 끝나면 새 review 파일만 남기고 `docs/STATUS.md`나 `docs/logbook.md`에 긴 전문을 복사하지 않는다.

## 환경 문제

- 패키지 설치 전 저장소 가상환경과 `requirements.txt`를 먼저 확인한다.
- 새 캐시와 다운로드는 D드라이브 정책을 따른다.
- SQLite를 네트워크/마운트 경로에서 직접 쓰지 않는다.
- 환경 때문에 검증하지 못한 항목은 실패와 구분해 `미검증`으로 기록한다.
