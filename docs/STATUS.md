# 현재 상태

## 기준 시각

- 확인 시각: `2026-07-18 장외 KST`
- 장 상태: `overnight`
- live runtime: 정상 정지
- runtime watchdog: 실행 중, heartbeat fresh
- dashboard: `http://127.0.0.1:8765`, server/API 정상
- Windows startup launcher: 설치 및 정상

## 운용 상태

- 기본 거래 모드: `paper`
- 실전 주문: 비활성
- active h15: `baseline-h15-v1`
- challenger 조치: `keep_active`
- 모델 승격: 없음
- 현재 통과한 수익 후보: `0개`

## 데이터와 학습

- 최신 KIS 거래일: `2026-07-16`
- KIS 누적 거래일: `54일`
- 장후 ML: `status=ok`, `quick-live-train`
- label refresh: `status=ok`
- 전체 데이터 품질: `주의` (2026-07-17 장중 KIS 수집 공백)

학습이 멈춘 것이 아니라 현재 모델이 비용 후 양수 기대값을 입증하지 못한 상태다.

## Rescue/Avoid

- buy-avoid `0.40`: portfolio `-38.1734% -> -36.3645%`, random-control 역선별로 기각
- buy-rescue: Cybos proxy 전 grid 비용 후 음수, KIS live decision ledger는 아직 0행
- hold-rescue `0.40`: 37건 적용, 현금손익 `-26,387원`, 후보 아님

세 항목은 관측/진단용이며 주문 정책에 반영되지 않는다.

## Phase

- Phase 0: 진행 중, 최근 10거래일 기준 `6/10`
- Phase 0 matched/mismatch: `0일/6일`
- mismatch 종목: `035420`, `086520`, `105560`, `247540`
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: live bounded read-only 관측과 전용 readiness 1회 통과
- Phase 2/3: 미시작

Phase 1b 통과는 조회 연결 준비이며 수익성 통과나 주문 승인이 아니다.

## 현재 blocker

1. Phase 0 10개 유효 거래일 정합성
2. 2026-07-17 KIS approval-key SSL/timeout 재발 여부와 수집 공백 해소
3. 비용 후 양수 전략과 비중복 기간 재현성
4. Phase 2/3용 실제 WebSocket recovery 증거
5. 당일 fresh market status
6. 유효기간이 있는 kill switch OFF 상태

## 다음 일정

- 2026-07-20 장전: KIS approval-key 재시도 흐름과 live decision ledger 수집 재개 확인
- 매 거래일 장후: Phase 0 정합성 1회 제한 확인, 2026-07-20에는 label refresh 뒤 E1/E5 1회
- 2026-07-20 장후: 사전등록 E1/E5 한 라운드 (정책 변경 없음)
- 이후: h15 저빈도/h60 portfolio 비교 또는 새 가설 사전등록

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
