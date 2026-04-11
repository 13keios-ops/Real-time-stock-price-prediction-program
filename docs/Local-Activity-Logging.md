# Local Activity Logging

## 1. 목적

이 문서는 프로그램이 남겨야 하는 로컬 활동 기록의 구조를 정의합니다.

목표:

1. 운영 문제를 나중에 재현 가능하게 만들기
2. 머신러닝 학습/평가 이력을 추적하기
3. Codex가 정기적으로 읽어 개선점을 찾을 수 있게 하기

## 2. 기본 원칙

1. 로그는 `로컬 폴더`에 일관된 구조로 저장
2. 사람이 읽기 쉬운 파일과 기계가 읽기 쉬운 파일을 함께 남김
3. 실전 민감 정보는 저장하지 않음
4. 삭제보다 보관과 회전 정책을 사용

## 3. 권장 루트 폴더

초기 권장 루트:

- `./runtime-data/`

또는

- `./var/`

현재 기준으로는 `./runtime-data/`가 더 직관적입니다.

## 4. 권장 폴더 구조

```text
runtime-data/
  logs/
    app/
    broker/
    data-quality/
    risk/
  ml/
    experiments/
    training-runs/
    evaluation/
    feature-stats/
  trading/
    predictions/
    signals/
    targets/
    orders/
    fills/
    positions/
    reconciliation/
    replay/
  cache/
    market/
    news/
    derived/
  reports/
    codex/
```

## 5. 폴더별 역할

### `logs/app/`

- 앱 시작/종료
- 주요 에러
- 시스템 상태 변화

### `logs/broker/`

- 토큰 발급/갱신
- WebSocket 연결/재연결
- 주문 전송/응답 오류

### `logs/data-quality/`

- stale 데이터 탐지
- 결측률
- 분봉 생성 이상
- NLP 연결 실패율

### `logs/risk/`

- 주문 차단 이유
- 일일 손실 한도 이벤트
- 시간대 차단 이벤트

### `ml/experiments/`

- 실험 메타데이터
- feature set 버전
- 모델 버전

### `ml/training-runs/`

- 학습 로그
- 파라미터
- 성능 요약

### `ml/evaluation/`

- 백테스트 결과
- 워크포워드 결과
- calibration 결과

### `ml/feature-stats/`

- feature drift
- feature 분포
- importance 요약

### `trading/predictions/`

- 실시간 예측 결과

### `trading/signals/`

- 신호 정책 통과/차단 결과

### `trading/targets/`

- 목표 포지션 산출 결과

### `trading/orders/`

- 주문 객체
- 주문 상태 전이

### `trading/fills/`

- 체결 기록

### `trading/positions/`

- 포지션 스냅샷

### `trading/reconciliation/`

- 브로커/내부 상태 차이

### `trading/replay/`

- 장후 replay 결과

### `reports/codex/`

- Codex가 생성한 점검 리포트
- action items
- 개선 제안

## 6. 파일 형식 권장안

초기 권장 조합:

- 이벤트 로그: `jsonl`
- 요약 리포트: `md`
- 구조화 결과: `json`
- 대용량 테이블: `parquet` 또는 `csv`

## 7. 파일 네이밍 규칙

예시:

- `runtime-data/trading/predictions/2026-04-11/predictions-20260411-091500.jsonl`
- `runtime-data/ml/evaluation/2026-04-11/walkforward-summary.json`
- `runtime-data/reports/codex/eod/2026-04-11-review.md`

## 8. Codex가 주로 볼 파일

초기에는 아래만 봐도 충분합니다.

1. 최근 예측 요약
2. 최근 주문/체결 요약
3. risk events
4. reconciliation 결과
5. replay 결과
6. 최근 학습/실험 결과
7. data quality 요약

## 9. Codex 점검 주기 권장안

### 장중 점검

- `30분` 또는 `1시간` 주기

### 장후 점검

- 장 마감 후 `1회`

### 주간 점검

- 주 1회 심층 검토

현재 기준으로는:

- 장중 `1시간` 주기
- 장후 `1회`
- 주간 `1회`

가 가장 무난합니다.

## 10. Codex 점검 결과물

Codex는 아래 내용을 남기게 하는 것이 좋습니다.

1. 오늘 발생한 핵심 이슈
2. 데이터 품질 문제
3. 전략 실패 패턴
4. ML 개선 후보
5. 코드/설정 수정 제안

## 11. 보안 원칙

로그 폴더에는 아래를 저장하지 않는 것이 좋습니다.

1. 실전 API secret 원문
2. 전체 계좌번호 원문
3. 민감한 인증 응답 원문

필요한 경우 마스킹해서 남깁니다.

## 12. 현재 작업 기준안

현재 프로젝트는 아래 방식으로 설계하는 것이 적합합니다.

1. 프로그램은 `runtime-data/` 아래에 활동 기록 저장
2. Codex는 이 폴더를 주기적으로 검토
3. Codex 출력은 `runtime-data/reports/codex/` 아래에 저장
4. 사람 승인 전에는 자동 수정/실전 주문 없음
