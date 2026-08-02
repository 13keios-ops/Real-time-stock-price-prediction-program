# 현재 스프린트

## 이름

Phase 1 수익성 증거 원장 축적과 2026-07-20 사전등록 판정

## 기간

- 시작: `2026-07-13`
- 첫 시도: `2026-07-20` 장후 (snapshot I/O 대기로 유효 결과 없음)
- 후속 checkpoint: `10/20/30/60거래일`

일주일은 최종 승격 기간이 아니라 첫 조기 진단 구간이다.

## 목표

1. 정규장 예측부터 실제 결과까지 완전한 decision lineage를 축적한다.
2. buy-rescue의 실제 no-trade 모집단을 처음으로 관찰한다.
3. Phase 0 paper/KIS 정합성 유효 거래일을 매일 누적한다.
4. 2026-07-20 장후 E1/E5 고정 라운드를 한 번만 실행한다.
5. 결과에 따라 h15 저빈도 entry와 h60 비교를 진행할지 결정한다.

## 현재 기준선

- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 현재 수익 후보: `0개`
- 자동 승격: 없음
- Phase 0: 유효일 `10/10` 관측 완료, matched 0일, mismatch 10일로 완료 조건 미통과
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: 실전계좌 bounded read-only 관측과 전용 readiness 1회 통과
- Phase 2/3: 미시작

## 활성 체크리스트

- [x] 2026-07-13~16 정규장 `serving_decision_ledger` 축적 확인 (2026-07-17 KIS 수집 공백은 별도 P0)
- [x] prediction의 `training_run_id`, `artifact_id`, `artifact_sha256` lineage 확인 (2026-08-02 dashboard guard 통과)
- [x] baseline 판단, gate, allocator, 현금·보유·pending, 주문·체결 결과 연결 확인
- [x] 비정상 호가 fail-closed와 feature JSONL 정본 재생성 보강: raw 감사 보존, 신호/연구 제외, SQLite 행 수 전수 검증
- [x] KIS live buy-rescue no-trade 모집단 관측: decision ledger 52,417행 중 eligible 25,726행(2026-08-02). 현행 비용 기준 모든 실제 rescue 진단이 음수여서 주문 후보 아님
- [ ] Phase 0 mismatch 4종목의 KIS account snapshot 대 order/fill ledger divergence를 자동 align 없이 해소·재확인. 2026-08-02 sanitized trace는 paper snapshot shape와 fetch 시각을 남기며 rejected sell recent count는 모두 0건이다.
- [x] 2026-07-20 장전 KIS approval-key 재시도와 decision ledger 수집 정상화 확인 (3,812행 complete lineage)
- [x] 2026-07-20 장후 label refresh 완료 뒤 E1/E5 wrapper 1회 실행 (D드라이브 research snapshot I/O 대기로 결과 파일 미생성). 자동 재실행은 금지하며 다음 명시 실행은 timeout/atomic snapshot으로 보호
- [ ] E1/E5 유효 결과를 현재 비용 `0.29%`, random control, 비중복 구간 기준으로 판정 (현재는 결과 없음)
- [ ] cowork 리뷰가 필요한 결과면 새 review/work 라운드 생성

## 동결 범위

E1/E5 유효 결과와 Phase 0 snapshot divergence 해소 전에는 신규 threshold/EV tuning, 종목별·h60 주문 정책, active model/gate 변경, rescue/avoid 주문 반영, 실전 주문/취소를 하지 않는다.

운영 장애와 데이터 lineage 누락을 고치는 작업은 동결 대상이 아니다.

## 완료 조건

- 5거래일 원장 수집 결과가 누락 여부와 함께 보고된다.
- E1 후보 3건 재현성과 E5 역선별 부호가 사전 기준으로 판정된다. 현재는 최초 실행의 결과 파일이 없어 재실행 없이 보류한다.
- 결과와 무관하게 주문 정책과 active model이 자동 변경되지 않는다.
- 다음 연구를 계속할지 보류할지 숫자 기준으로 문서화된다.

## 다음 분기

- E1/E5 통과: h15 저빈도와 h60을 동일 portfolio replay, 비중복 2구간으로 비교한다.
- E1/E5 실패: threshold 탐색을 멈추고 orderbook, 시간대, 변동성, source, horizon 가설을 새로 사전등록한다.

## 과거 스프린트

스프린트 01 원문은 `docs/archive/SPRINT_CURRENT-sprint-01-legacy.md`에 보존한다.
