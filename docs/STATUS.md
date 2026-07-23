# 현재 상태

## 기준 시각

- 확인 시각: `2026-07-23 장후 KST`
- 장 상태: `post-close`
- live runtime: 장후 정상 정지
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

- 최신 KIS 거래일: `2026-07-23`
- KIS 누적 거래일: `58일`
- 2026-07-23 장후 ML: `status=ok`, `quick-live-train`, 16:18 KST 완료
- 2026-07-23 label refresh: `status=ok`, 16:52 KST 완료
- 전체 데이터 품질: 당일 raw tick, orderbook, 분봉, feature, h15/h60 label이 생성됐고 assessment는 `ok`다. 분봉/feature 장마감 기준 coverage는 약 `97.1%`다. 2026-07-17 수집 공백은 과거 P0로 유지한다.
- 수집 안정성: decision ledger는 3,812행을 완전 lineage로 남겼다. 다만 KIS WebSocket `no close frame` 재연결 29회가 있어 연결 안정성은 계속 관찰한다.

학습이 멈춘 것이 아니라 현재 모델이 비용 후 양수 기대값을 입증하지 못한 상태다.

## Rescue/Avoid

- buy-avoid `0.40`: portfolio `-38.1734% -> -36.3645%`, random-control 역선별로 기각
- buy-rescue: Cybos proxy 전 grid 비용 후 음수, KIS live decision ledger는 아직 0행
- hold-rescue: 2026-07-23 paper-only replay가 `diagnostic_only_no_hold_rescue_candidate`로 끝났고 후보 threshold가 없다.

세 항목은 관측/진단용이며 주문 정책에 반영되지 않는다.

## Phase

- Phase 0: 유효 10거래일 관측은 완료됐지만 통과하지 못함
- Phase 0 matched/mismatch: `0일/10일`
- mismatch 종목: `035420`, `086520`, `105560`, `247540`
- 원인 범위: local paper와 KIS order/fill 순수량은 맞지만 KIS account snapshot 수량이 다르다. 자동 align과 `SyncInitialCash`는 계속 보류한다.
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: live bounded read-only 관측과 전용 readiness 1회 통과
- Phase 2/3: 미시작

Phase 1b 통과는 조회 연결 준비이며 수익성 통과나 주문 승인이 아니다.

## 현재 blocker

1. Phase 0의 KIS account snapshot 대 order/fill ledger divergence 해소
2. KIS WebSocket `no close frame` 재연결 빈도와 2026-07-17 approval-key 장애의 재발 여부
3. 비용 후 양수 전략과 비중복 기간 재현성
4. Phase 2/3용 실제 WebSocket recovery 증거
5. 당일 fresh market status
6. 유효기간이 있는 kill switch OFF 상태

## 다음 일정

- 매 거래일 장후: Phase 0 정합성을 중복 KIS 호출 없이 1회 제한 확인하고, snapshot/ledger divergence가 해소되는지 관찰
- E1/E5: 2026-07-20 장후 1회 시도했으나 D드라이브 research snapshot I/O 대기로 결과 파일이 생성되지 않았다. 자동 재실행은 하지 않는다.
- 이후: E1/E5의 유효 결과가 생긴 뒤 h15 저빈도/h60 portfolio 비교 또는 새 가설 사전등록을 결정한다.

## 기준 문서

- 현재 스프린트: `docs/SPRINT_CURRENT.md`
- Phase 진행판: `docs/Production-Transition-Progress.md`
- 구현 범위: `docs/Current-Implementation.md`
- 실행 순서: `docs/Execution-Plan.md`
- 최신 기록: `docs/logbook.md`

2026-07-12 이전 STATUS 원문은 `docs/archive/STATUS-through-20260712.md`에 보존한다.
