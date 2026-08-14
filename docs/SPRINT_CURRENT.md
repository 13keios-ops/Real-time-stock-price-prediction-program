# 현재 스프린트

## 이름

Phase 1 수익성 증거 원장 축적과 사전등록 연구 실행 안정화

## 기간

- 시작: `2026-07-13`
- E1/E5 최초 시도: `2026-07-20` 장후, snapshot I/O timeout
- E1/E5 명시 재시도: `2026-08-09` 장외, snapshot I/O timeout
- 후속 checkpoint: `10/20/30/60거래일`

일주일은 최종 승격 기간이 아니라 첫 조기 진단 구간이다.

## 목표

1. 정규장 예측부터 실제 결과까지 완전한 decision lineage를 축적한다.
2. buy-rescue의 실제 no-trade 모집단을 관찰한다.
3. Phase 0 paper/KIS 정합성 증거 범위를 정확히 분리하고 해소 경로를 결정한다.
4. E1/E5 고정 라운드 실행기가 대용량 DB snapshot 실패를 안전하게 기록·정리하도록 한다.
5. 유효 결과 뒤에만 h15 저빈도 entry, h60 별도 트랙, entry/exit 분리 가설을 동일 포트폴리오 재생으로 비교한다.

## 현재 기준선

- 거래 모드: `paper`
- active h15: `baseline-h15-v1`
- 현재 수익 후보: `0개`
- 자동 승격: 없음
- Phase 0: 유효일 `10/10`, matched 0일, mismatch 10일로 미통과
- Phase 1a: 모의투자 read-only 1차 리허설 통과
- Phase 1b: 실전계좌 bounded read-only 관측과 전용 readiness 1회 통과
- Phase 2/3: 미시작
- 2026-08-14 decision ledger: 3,608행, complete lineage 3,608행, ratio 1.0
- 2026-08-14 WebSocket: reconnect 47, storm 19, closed feature coverage 92.5128%, 전 종목 market 공백 15:01~15:29

## 활성 체크리스트

- [x] 정규장 `serving_decision_ledger` 축적과 완전 lineage 확인
- [x] prediction의 `training_run_id`, `artifact_id`, `artifact_sha256` lineage 확인
- [x] baseline 판단, gate, allocator, 현금·보유·pending, 주문·체결 결과 연결 확인
- [x] 비정상 호가 fail-closed, feature JSONL 정본 재생성, broker status 중복 적재 차단
- [x] buy-rescue 실제 no-trade 모집단 확보와 비용 후 음수 판정
- [x] buy-avoid 19거래일 순방향 lineage 교정과 절대수익 음수 판정
- [x] 장후 data-quality에 거래일별 decision lineage와 WebSocket reconnect/storm 추가
- [x] live runtime 상태에 current/peak RSS 추가
- [x] Phase 0 trace에서 bounded recent lookup과 historical mirrored-order evidence를 분리하고 자동 align을 금지
- [x] Phase 0 full-period read-only probe와 페이지 완결성/외부 활동/원장 차이 fail-closed 판정 구현
- [x] data-quality에 watchlist 공통 raw 누락 구간과 종목별 누락 범위를 추가하고 최근 10일 분 인덱스만 집계하도록 최적화
- [x] 장중 broker paper sync 일반 실패에 지수 백오프, `EGW00201`에 120분 process pause 적용
- [ ] `EGW00201` cooldown 뒤 full-period sanitized account activity 1회 완결; 이력 미제공일 때만 계좌 소유자 승인 clean baseline 선택
- [x] E1/E5 wrapper 명시 1회 실행: `snapshot_failed/research_snapshot_timeout`, 주문·네트워크 0회, 재실행 없음
- [x] 8GiB 이상 DB의 WSL 9P snapshot 기본 경로를 repo-local D드라이브 물리 저장소로 변경하고 partial 정리를 token 단위로 보강
- [ ] E1/E5 유효 결과 확보
- [ ] 유효 결과를 현재 비용 `0.29%`, random control, 비중복 구간으로 판정
- [ ] cowork 리뷰가 필요한 결과면 새 review/work 라운드 생성

## 동결 범위

E1/E5 유효 결과와 Phase 0 해소 경로가 정해지기 전에는 신규 threshold/EV tuning, 종목별·h60 주문 정책, active model/gate 변경, rescue/avoid 주문 반영, 실전 주문/취소를 하지 않는다.

운영 장애, 데이터 lineage 누락, snapshot 원자성, 관측 리포트 오류를 고치는 작업은 동결 대상이 아니다.

## 완료 조건

- 각 거래일 raw→분봉→feature→decision ledger와 complete lineage가 같이 보고된다.
- WebSocket reconnect와 storm이 coverage와 함께 판정된다.
- Phase 0이 전체 기간 계좌 활동 또는 clean baseline 근거로 해소된다.
- E1 후보 3건 재현성과 E5 역선별 부호가 사전 기준으로 판정된다.
- 결과와 무관하게 주문 정책과 active model이 자동 변경되지 않는다.
- 다음 연구를 계속할지 보류할지 숫자 기준으로 문서화된다.

## 다음 분기

- E1/E5 통과: entry 시점 정보만 사용하는 h15 저빈도 비용여유 후보와 h60을 동일 초기 현금·체결·비용·보유 제약의 portfolio replay와 비중복 2구간에서 비교한다.
- E1/E5 실패: threshold 반복 탐색을 멈추고 orderbook×regime, 시간대, 변동성, source, horizon 가설을 새로 사전등록한다.
- 어느 분기든 entry와 exit 모델은 분리 평가하고, 실현 미래 변동폭을 entry 필터로 사용하지 않는다.

## 과거 스프린트

스프린트 01 원문은 `docs/archive/SPRINT_CURRENT-sprint-01-legacy.md`에 보존한다.
