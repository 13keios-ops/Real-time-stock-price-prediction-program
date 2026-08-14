---
name: full-check
description: Use for this repository when the user asks for a FULL CHECK, end-to-end project audit, project-goal alignment review, collection and decision-evidence review, profitability or monetization-readiness review, or autonomous safe remediation across code, data, reports, tests, and canonical docs.
---

# FULL CHECK

프로젝트가 현재 목표를 향해 제대로 개발되는지 전면 검수한다.
수집량이나 모델 정확도 하나만 보지 말고 원천 데이터부터 실제 비용 후 포트폴리오 손익까지 증거 사슬을 확인한다.
안전하고 범위가 분명한 결함은 분석에서 멈추지 말고 수정, 검증, 문서화, commit/push까지 끝낸다.

## 1. 시작 조건을 고정한다

먼저 `AGENTS.md`의 작업 시작 문서 순서를 따른다. 최소한 아래 문서를 다시 읽는다.

- `README.md`
- `docs/STATUS.md`
- `docs/SPRINT_CURRENT.md`
- `docs/logbook.md`와 최신 `docs/logbook_archive/logbook_*.md`
- `docs/Current-Implementation.md`
- `docs/Versioning.md`
- `docs/Production-Transition-Progress.md`
- `docs/Execution-Plan.md`
- `docs/Model-Research-PreRegistration.md`
- `docs/Codex-Operating-Feedback.md`
- 작업 범위와 직접 관련된 `docs/*.md`

대화의 과거 상태를 현재 사실로 사용하지 않는다. 파일, 로그, DB, 상태 명령의 최신 증거로 다시 확인한다.

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
./scripts/get_live_runtime_status.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/get_dashboard_status.sh
./scripts/get_runtime_startup_launcher_status.sh
git status --short --branch
```

- `regular-session`, 실제 장전 워밍업인 `pre-open`, `live_runtime_should_run=true`, live runtime 실행 중이면 장중 수집 보호 모드로 전환한다.
- 장중 보호 모드에서는 read-only 확인, 문서 정리, `git diff --check`, `bash -n`, `.tmp-tests/` 격리 테스트만 수행한다.
- 장중 보호 모드에서 root 코드, 운영 DB, dashboard/runtime, 전체 테스트를 건드리지 않는다.
- 장전/장후 운영 상태가 범위에 포함되면 `.agents/skills/daily-ops-check/SKILL.md`도 읽고 적용한다.
- dirty worktree에서는 변경 출처를 구분하고 사용자 변경을 되돌리지 않는다.

## 2. 현재 목표와 감사 범위를 선언한다

현재 프로젝트 목표, phase, 스프린트 완료 조건, 동결 범위, blocker를 먼저 정리한다.
기본 목표는 다음 증거 사슬을 안정화하는 것이다.

```text
실시간/역사 원천 -> 정규화 -> 분봉/호가 -> feature/label
-> prediction/artifact -> signal/gate/allocator -> order/fill
-> paper/KIS reconciliation -> 비용 후 portfolio 결과 -> 승격/보류 판단
```

아래 축을 각각 `정상`, `주의`, `실패`, `확인 불가`로 판정하고 근거 경로와 생성 시각을 붙인다.

1. 운영과 수집 안정성
2. 데이터 품질과 source provenance
3. 판단 계보와 재현성
4. paper/KIS 계좌 및 체결 정합성
5. 모델과 전략의 비용 후 수익성
6. 리스크, 운영 실패 비용, 실전 전환 준비도
7. 코드, 테스트, 문서, 자동화의 정합성

## 3. 증거 인벤토리를 만든다

보고서 이름의 `latest`만 믿지 말고 내부 시각, 거래일 범위, artifact, source, 비용 버전을 확인한다.

- runtime/watchdog/dashboard/startup launcher 상태와 로그
- `runtime-data/reports/data-quality/`의 KIS live 품질, source drift, feature 진단
- `runtime-data/reports/ml-maintenance/state/`의 학습과 label refresh
- `runtime-data/reports/challengers/`, `backtests/`, `ml/`의 active/challenger와 replay
- `runtime-data/reports/reconciliation/`과 `broker-paper/`의 Phase 0 증거
- `runtime-data/reports/live-readiness/`의 readiness와 freshness
- `runtime-data/reports/dashboard/latest-dashboard.json`
- SQLite row count, 시간 범위, 중복, 결측, lineage를 증명하는 read-only query 또는 기존 진단
- 관련 소스 코드, 테스트, 설정 예시, 현재 문서

계좌번호, token, raw broker response, secret은 출력하거나 새 산출물에 기록하지 않는다.
새 캐시, snapshot, 대용량 산출물은 D드라이브 기준 경로만 사용한다.

## 4. 수집과 데이터 품질을 검수한다

원천별, 종목별, 거래일별로 아래를 확인한다.

- raw market/orderbook symbol-minute coverage, 장중 공백, 중복, malformed row
- 분봉 close, feature, label의 시간 범위와 coverage
- orderbook freshness, 비정상 bid/ask, crossed quote의 fail-closed 처리
- KIS live, Cybos historical/proxy, 혼합 근사치의 source 구분
- timezone, 거래일 캘린더, 장전/정규장/장후 경계
- 미래 정보 누수와 같은 bar 체결 가정
- `serving_decision_ledger` 증가, active/shadow 계보, complete lineage ratio
- WebSocket reconnect count, storm count, reason, listener 공백
- DB 크기, WAL/journal, disk 여유, snapshot timeout, 중복 JSONL 보관

장후이고 live runtime이 정지한 경우에만 필요하면 아래 진단을 1회 갱신한다.

```bash
python3 scripts/summarize_kis_live_data_quality.py --recent-days 10
```

- row 수만 증가했다고 수집 정상으로 판정하지 않는다.
- coverage 기준 미달, 불완전 lineage, reconnect storm을 정상으로 덮지 않는다.
- storm이 없고 coverage와 lineage가 기준을 충족하면 수집 성공과 연결 주의를 분리한다.
- historical/proxy 결과를 KIS live 성능으로 부르지 않는다.

## 5. 판단과 근거 계보를 검수한다

실제 코드와 원장에서 한 decision episode를 끝까지 추적한다.

```text
source -> feature -> model run/artifact -> prediction
-> signal -> safety gate -> allocator -> order intent
-> local/broker order -> fill -> position -> realized/unrealized PnL
```

- `training_run_id`, `artifact_id`, hash, prediction 시각, source window가 보존되는지 확인한다.
- active/shadow, 관측/주문 반영, baseline/challenger를 분리한다.
- safety gate, cash, position, pending 차단을 rescue가 뒤집지 않는지 확인한다.
- no-trade 모집단을 실제 decision stage로 정의했는지 확인한다.
- 같은 decision의 중복 prediction/artifact가 fail-closed 되는지 확인한다.
- dashboard, JSON, Markdown의 판정과 단위가 같은지 확인한다.
- proxy, 진단, 후보, 승격 가능 상태를 서로 다른 용어로 표시한다.

계보가 불완전하면 정확도와 손익이 좋아 보여도 수익성 증거로 승격하지 않는다.

## 6. Phase 0과 운용 정합성을 검수한다

`latest-paper-account-history.json`의 최근 유효 거래일, matched/mismatch 일수와 종목을 먼저 확인한다.
세부 절차는 `daily-ops-check`의 paper/KIS 정합성 절을 따른다.

- local paper, mirrored submission, KIS order/fill lookup, account snapshot의 범위를 분리한다.
- `historical_mirrored_orders_only`를 전체 KIS 계좌 활동 원장으로 부르지 않는다.
- bounded lookup이 비교 기간을 덮지 않으면 원인을 확정하지 않는다.
- `EGW00201`과 cooldown에서는 같은 endpoint를 반복 호출하지 않는다.
- mismatch를 자동 align, `SyncInitialCash`, clean baseline으로 덮지 않는다.
- Phase 0이 불일치면 로컬 누적 paper PnL을 실전 수익 증거로 사용하지 않는다.

실제 주문/취소, 자동 정렬, clean baseline은 이 skill의 자율 조치 범위가 아니다.

## 7. 수익성과 수익화 가능성을 검수한다

첫 결론에 `현재 통과한 수익 후보 수`를 명시한다.
정확도, 적중률, 손실 감소만으로 수익 후보라고 부르지 않는다.

### 비용과 단위를 맞춘다

- canonical 비용 모델을 코드/리포트에서 읽고 `cost_model_version`을 확인한다. 이 skill에 비용률을 복제하지 않는다.
- 수수료, 세금, spread, slippage, 지연, 부분 체결, 강제청산을 구분한다.
- historical 가정과 canary 실측 비용을 분리한다.
- 겹치는 신호 수익률 합, 퍼센트포인트 합, 계좌 수익률, 원화 PnL을 혼용하지 않는다.
- 모집단, horizon, 행동, threshold, 비용이 다른 지표를 직접 비교하지 않는다.

### 승격 가능한 수익 증거를 확인한다

후보는 최소한 다음을 모두 통과해야 한다.

- 절대 비용 후 portfolio net return과 평균 거래 기대값이 양수다.
- 현금, 포지션, 중복 보유, pending order, 체결 가능 가격을 반영한 decision-episode replay다.
- same-count random control과 사전등록 baseline을 이긴다.
- 독립된 비중복 기간과 거래일별 일관성을 보인다.
- 최소 거래/episode/클래스 표본과 완전 lineage를 충족한다.
- 미래 정보, 같은 bar 비현실 체결, 사후 최선 threshold 선택이 없다.
- 최대 낙폭, 손실 연속, turnover, 종목 집중, regime 민감도가 허용 가능하다.
- 비용 2배, slippage 악화, 지연 체결 민감도에서도 결론이 쉽게 뒤집히지 않는다.

### 수익화 관점을 별도로 판단한다

- 자본 규모가 커질 때 유동성, 호가 충격, 체결률이 유지되는지 본다.
- 낮은 빈도가 비용만 줄이는지 거래당 기대값도 개선하는지 분리한다.
- 특정 종목, 시간대, 하루, regime에 수익이 몰리는지 본다.
- reconnect, stale evidence, 계좌 mismatch의 운영 손실이 예상 이익보다 큰지 본다.
- h15, h60, entry, hold/exit를 각각 독립 검증한다.
- paper 성과가 Phase 2 canary로 갈 만큼 재현 가능하고 감사 가능한지 본다.

판정은 아래 중 하나로 보수적으로 분류한다.

- `no_profitable_candidate`: 비용 후 양수 후보 없음
- `research_candidate_only`: 진단은 유망하지만 독립 검증 또는 실행 제약 미통과
- `paper_candidate`: 사전등록, replay, 표본, 비용, lineage 통과 후 paper 검증 가능
- `canary_review_ready`: Phase 0/1, 리스크, kill switch, 실측 계획까지 갖춰 운영자 심사 가능

`buy-avoid`, `buy-rescue`, `hold-rescue`, meta-policy는 관측용인지 후보인지 분리한다.
baseline 손실을 줄였어도 절대 수익이 음수면 `no_profitable_candidate`다.

## 8. 구현과 저장소 품질을 검수한다

- README와 실제 레이어, 명령, 산출물 경로가 일치하는지 확인한다.
- collector, feature, model, portfolio, risk, reporting의 의존 방향을 확인한다.
- 대형 모듈, 중복 wrapper, stale report, 암묵적 fallback이 판단을 왜곡하는지 본다.
- 예외가 성공으로 삼켜지거나 stale `latest`가 유지되는지 본다.
- 네트워크 호출, retry, timeout, cooldown이 bounded/fail-closed인지 본다.
- dashboard가 진단값을 수익 또는 승격처럼 과장하지 않는지 본다.
- 핵심 결함과 회귀 위험에 대응하는 좁은 테스트가 있는지 본다.

문서 주장과 구현이 다르면 구현을 읽어 현재 사실을 확정한 뒤 둘을 함께 고친다.

## 9. 발견 사항을 우선순위화하고 조치한다

1. `P0`: 데이터 손실, 미래 누수, 주문 위험, 잘못된 수익 주장, 계좌/체결 감사 불가
2. `P1`: 수집 공백, lineage 불완전, stale 판정, 비용/단위 오류, 재현성 부족
3. `P2`: 구조 부채, 성능, 중복, 문서/대시보드 표현, 운영 편의

안전하고 원인이 확정된 결함은 같은 작업에서 직접 수정한다.

- 기존 ownership 경계를 따른다.
- 새 threshold 탐색보다 평가 오류, provenance, replay, stale evidence를 먼저 고친다.
- 수정마다 변경 전/후, 영향 범위, 회귀 위험을 확인한다.
- 관련 canonical 문서와 `docs/logbook.md`를 함께 갱신한다.
- 독립적인 큰 작업은 단계별 검증 뒤 다음 단계로 간다.

명시 승인 또는 별도 phase gate 없이는 다음을 바꾸지 않는다.

- 실전 주문/취소와 `ALLOW_LIVE_ORDERS`
- `app/risk/`, kill switch 해제, 리스크 한도
- active model, promotion, gate, threshold, 종목별 주문 정책
- `config/`, `VERSION`, 자격정보, 계좌 baseline/자동 align
- 새 외부 데이터 소스와 NAS 백업

ML 실험은 `AGENTS.md`의 자율 범위와 현재 사전등록/동결 범위를 모두 만족할 때만 실행한다.
3회 연속 개선이 없으면 더 탐색하지 말고 운영자 판단 항목으로 올린다.

## 10. 검증하고 종료한다

변경 범위에 맞춰 좁은 테스트부터 실행하고, 장외이며 안전할 때 전체 테스트를 수행한다.

```bash
python -m unittest discover -s tests -p "test_*.py"
python scripts/audit_repository_structure.py
git diff --check
```

- Python 변경은 import/syntax/호출 경로와 관련 unittest를 확인한다.
- bash 변경은 최소 `bash -n`을 실행한다.
- dashboard 변경은 `tests.test_dashboard`와 실제 build를 고려한다.
- broker/reconciliation 변경은 관련 전용 테스트를 실행한다.
- 테스트를 못 했으면 이유와 잔여 위험을 숨기지 않는다.
- 금지 범위, 의도하지 않은 파일, 불필요한 백그라운드 프로세스를 다시 확인한다.
- 정책과 권한이 허용하면 변경을 commit/push하고 실제 결과를 보고한다.

## 11. 최종 보고 형식을 지킨다

한국어로 아래 순서를 사용한다.

1. `FULL CHECK: 정상/주의/실패`와 현재 목표 정합성
2. 통과한 수익 후보 수와 수익화 판정
3. P0/P1/P2 발견 사항과 근거 경로/시각/범위
4. 직접 조치한 내용과 변경 파일
5. 실행한 검증과 실제 결과
6. Phase 0, coverage/lineage/reconnect, active/challenger 상태
7. 남은 blocker와 다음 권장 순서
8. 건드리지 않은 보호 범위와 commit/push 상태

좋아 보이는 숫자보다 표본 부족, 비용 후 음수, lineage 결함, 비현실 체결 가정을 먼저 해석한다.
확인하지 못한 사실은 단정하지 말고 `확인 필요`로 남긴다.
최종 답변 전 `현재 작업 모드`, `답변 접두어`, `활성 체크리스트 갱신 여부`, `기준 문서 반영 여부`를 한 줄로 self-review한다.
