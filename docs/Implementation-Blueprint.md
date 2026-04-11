# Implementation Blueprint

## 1. 목적

이 문서는 현재까지 정리한 기획을 실제 코드 구현 단계로 옮기기 위한 설계 청사진입니다.

## 2. 권장 초기 폴더 구조

```text
app/
  api/
  brokers/
  collectors/
  features/
  labels/
  models/
  observability/
  universe/
  nlp/
  paper_trading/
  portfolio/
  replay/
  reconciliation/
  risk/
  services/
  storage/
  utils/
config/
docs/
scripts/
tests/
```

## 3. 모듈 책임 분리

### `app/brokers/`

- 한국투자 인증
- 한국투자 REST 시세 조회
- 한국투자 WebSocket 시세 수신
- 한국투자 모의주문

### `app/collectors/`

- 시세 이벤트 수집
- 공시/뉴스/검색 데이터 수집
- 원본 저장 연결

### `app/features/`

- 분봉 생성
- 호가 요약
- 특징 계산

### `app/models/`

- 학습 로더
- 추론기
- 모델 버전 로딩

### `app/observability/`

- 활동 로그 기록
- 리포트 산출물 관리
- Codex 검토 대상 파일 인덱싱
- retention/rotation 관리

### `app/universe/`

- 월간 유니버스 산출
- 유니버스 버전 관리
- trading eligibility overlay 계산

### `app/nlp/`

- 뉴스/공시 텍스트 정제
- 종목 엔티티 매핑
- 중복 제거
- 이벤트 분류 및 감성 점수화

### `app/paper_trading/`

- 신호 생성
- 주문 생성
- 포지션 상태
- 손익 집계

### `app/portfolio/`

- 자본 배분
- 종목별 목표 포지션 계산
- 동시 보유 수 제한
- 섹터/테마 과집중 제어

### `app/replay/`

- warm-up 관리
- raw event replay
- decision replay
- recovery gate
- 장후 비교 리포트

### `app/reconciliation/`

- broker state 동기화
- live vs replay 비교
- 포지션/체결 mismatch 점검
- 장후 차이 리포트 생성

### `app/risk/`

- 시간대 필터
- 손실 한도 필터
- 데이터 지연 필터
- 스프레드 필터

## 4. 1차 구현 목표

개발 첫 스프린트에서는 아래까지만 가는 것이 좋습니다.

1. 한국투자 인증
2. 실시간 체결/호가 수집
3. 1분 바 생성
4. 기본 특징 계산
5. 베이스라인 추론 더미 또는 초기 모델 연결
6. 신호 생성
7. 목표 포지션 생성
8. 모의주문 생성
9. 체결/포지션/손익 로그 저장
10. 장후 broker/replay reconciliation 기초 로그

## 5. 구현 순서

### Step 1. 인프라 골격

- 설정 로더
- 로거
- DB 연결
- 스키마 생성
- runtime-data 폴더 초기화

### Step 2. 브로커 연동

- KIS auth client
- KIS quote ws client
- KIS quote rest client
- KIS paper order client

### Step 3. 데이터 계층

- raw 저장
- curated minute bar 생성
- feature snapshot 생성

### Step 3a. 정책 계층

- universe freeze 산출
- market data quality gate
- text event normalization

### Step 4. 추론 계층

- 모델 로더
- 15분/60분 예측
- prediction log 저장

### Step 5. 전략 계층

- signal policy 적용
- portfolio allocator 적용
- risk gate 적용
- paper order 생성

### Step 6. 운영 계층

- 대시보드
- 상태 점검
- 오류/리스크 이벤트 로그
- Codex 검토용 리포트 산출물 생성

### Step 7. 재조정 계층

- 브로커 상태 동기화
- live vs replay 비교
- mismatch 리포트 생성

### Step 8. 복구/리플레이 계층

- warm-up manager
- restart recovery
- 장후 decision replay

## 6. 테스트 우선순위

### 단위 테스트

- 라벨 생성
- 특징 계산
- 진입/청산 규칙
- 리스크 차단 규칙

### 통합 테스트

- 시세 수집 -> 특징 -> 예측 -> 주문 흐름
- 장애 시 재연결
- 모의주문 체결 및 손익 반영

## 7. 현재 개발 직전 체크포인트

아래가 이미 정해져 있어서 바로 구현이 가능합니다.

1. 종목군 기준
2. 예측 수평선
3. 라벨 임계값
4. 모의주문 방향
5. 시간대 규칙
6. 계좌 안전장치
7. 데이터 스키마 초안
8. portfolio/reconciliation 필요성
9. order lifecycle / replay 필요성

## 8. 아직 코드로 구현하며 확정할 부분

1. 실제 KIS TR ID 매핑
2. 시장 캘린더 적재 방식
3. 모델 파일 저장 위치
4. 대시보드 프레임워크 선택
5. broker state 동기화 주기
6. text event pipeline 구현 범위
7. replay 계산 범위를 raw 기준으로 둘지 feature 기준으로 둘지
8. universe overlay 갱신 주기
9. Codex 정기 점검 주기를 app 외부 automation으로 둘지 내부 scheduler로 둘지

## 9. 첫 개발 목표 정의

첫 번째 “동작하는 버전”은 아래를 만족하면 충분합니다.

1. 장중 실시간 체결/호가 수집
2. 종목별 1분 특징 생성
3. 예측 결과 저장
4. 모의주문 신호 저장
5. 목표 포지션 저장
6. paper 주문/체결/포지션 로그 저장
7. 시스템 상태 확인 가능
8. 장후 reconciliation/replay 로그 생성 가능

## 10. 이 문서의 역할

이 문서는 기획 문서와 실제 코드 작업 사이의 연결 문서입니다.

다음 단계에서 사용자는 이 문서를 기준으로 `프로젝트 골격 생성`을 바로 요청할 수 있습니다.
