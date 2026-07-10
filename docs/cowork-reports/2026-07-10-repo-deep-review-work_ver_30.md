# 2026-07-10 Repository Deep Review Work Ver 30

## 범위
새 LightGBM 연구/아티팩트 무결성/시간 기준 walk-forward 변경을 저장소 전체 실행 경로와 대조하고, 발견된 회귀와 운영상 위험을 보강했다.

## 적용 내용
- LightGBM 학습 실패를 Centroid 모델로 조용히 대체하던 synthetic/KIS orchestration fallback 제거.
- 짧은 synthetic cycle이 temporal purge 이후에도 상승/보합/하락 세 라벨을 유지하도록 연속 regime 생성 패턴 보강.
- shadow LightGBM loader가 최신 파일 하나를 무조건 선택하지 않고 손상, horizon, feature set, 3분류 라벨 불일치 아티팩트를 건너뛰도록 보강.
- model registry history를 최신 100개로 제한.
- registry lock에 소유 PID를 기록하고, 실제 살아 있는 프로세스의 stale lock을 삭제하지 않도록 보강.
- 새 event-time strict horizon purge 기준으로 gate walk-forward 리포트 재생성.
- challenger 재평가와 dashboard snapshot 갱신.

## 결과
- walk-forward: 119 folds, purge mode event_time_strict_after_horizon, 최소 실제 gap 30분, 모든 fold horizon 초과.
- challenger: active baseline-h15-v1 유지, keep_active, promotion_applied=false.
- gate: needs_review, 3분류 정확도 0.4145.
- 1위 fresh_centroid 거래 수 4건으로 표본 부족.
- 전체 unittest: 462개 통과.
- compileall 통과.
- git diff --check 통과.
- 실시간 runtime 정지, watchdog/dashboard 정상.
- 실전 주문, active model 승격, risk/config/VERSION 변경, NAS 백업 없음.

## 판단
현재 변경은 모델 승격이 아니라 검증 누수 방지와 provenance 무결성 보강이다. gate와 active model은 유지한다. 다음 모델 연구는 표본이 충분해질 때까지 신규 threshold tuning보다 live shadow 관측과 데이터 품질 확인을 우선한다.
