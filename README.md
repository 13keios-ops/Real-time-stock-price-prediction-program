# Real-time Stock Price Prediction Program

국내 주식시장에서 실시간 가격/호가, 공시/뉴스, 검색/반응 데이터를 결합해 단기 주가 변동을 예측하는 연구·개발 프로젝트입니다.

현재 저장소는 2026-04-10 기준 초기 상태였고, 기존 Markdown 문서는 존재하지 않았습니다. 그래서 먼저 프로젝트의 방향, 데이터 전략, 모델링 전략, 시스템 아키텍처를 문서화하는 방식으로 기반을 잡았습니다.

## 현재 가정

- 초기 버전은 `내부 연구용 의사결정 보조 시스템`을 목표로 합니다.
- 첫 단계에서는 `자동매매`보다 `예측 점수 + 근거 신호 + 경보` 제공에 집중합니다.
- 데이터 수집은 `공식 API 또는 사용 허가가 명확한 소스`를 우선 사용합니다.
- 예측 대상은 전체 시장이 아니라 `유동성이 높은 국내 종목군`부터 시작합니다.

## 문서 맵

- `docs/Review-Notes.md`: 현재 저장소와 문서 상태에 대한 검토 결과
- `docs/PRD.md`: 프로젝트 목표, 범위, 사용자 시나리오, 성공 기준
- `docs/Data-Sources.md`: 데이터 소스 후보, 수집 원칙, 법적/운영 리스크
- `docs/Architecture.md`: 실시간 수집부터 예측 서빙까지의 시스템 구조
- `docs/Modeling-Strategy.md`: 그래프 분석, 심리 요인, 멀티모달 예측 전략
- `docs/Baseline-Decisions.md`: 현재 확정된 1차 기획 기준과 선택 이유
- `docs/Data-Schema.md`: 수집/가공/예측 로그를 위한 데이터 스키마 초안
- `docs/Dashboard-Plan.md`: 연구용 대시보드 화면 구성과 핵심 위젯
- `docs/Experiment-Tracking.md`: 실험, 모델 버전, 예측 로그 관리 기준
- `docs/Machine-Learning-Operations.md`: 머신러닝 모델 계층, 학습 주기, 운영 기준
- `docs/Paper-Trading-Validation.md`: 예측 기반 자동 모의투자 검증 절차와 리스크 통제
- `docs/Signal-Policy.md`: 예측을 주문 신호로 바꾸는 초기 규칙과 리스크 한도
- `docs/Execution-Assumptions.md`: 체결, 슬리피지, 거래비용의 시뮬레이션 가정
- `docs/Account-Safety.md`: 실전/모의 계좌 분리, 비밀정보 관리, 오주문 방지 장치
- `docs/KIS-Integration-Plan.md`: 한국투자 Open API 연동 구조와 인증/시세/주문 흐름
- `docs/Market-Schedule-Rules.md`: 한국 주식시장 시간 규칙과 특수 일정 처리 기준
- `docs/Runtime-Configuration.md`: 환경변수, 실행 모드, 설정 계층 구조
- `docs/Implementation-Blueprint.md`: 개발 시작용 모듈 구조와 단계별 구현 계획
- `docs/External-Benchmark-Review.md`: 외부 유사 구조 조사와 현재 설계의 보완점 정리
- `docs/Portfolio-And-Reconciliation.md`: 자본 배분, 목표 포지션, 브로커/리플레이 재조정 기준
- `docs/Order-Lifecycle.md`: 신호부터 주문/체결/취소/복구까지의 상태 머신
- `docs/Replay-And-Recovery.md`: 재시작 복구, 워밍업, 실시간 리플레이 검증 절차
- `docs/NLP-Event-Pipeline.md`: 뉴스/공시/반응 데이터를 특징으로 만드는 텍스트 파이프라인
- `docs/Market-Data-Policy.md`: raw/adjusted 가격, 분봉 생성, 데이터 품질 게이트 기준
- `docs/Universe-Freeze-Policy.md`: 종목군 산출, 월간 동결, 긴급 거래 제외 규칙
- `docs/Codex-Augmentation-Plan.md`: Codex/CLI/API를 활용한 지속 개선 루프와 역할 분리
- `docs/Local-Activity-Logging.md`: 로컬 활동 로그 폴더 구조와 Codex 검토 대상 산출물 정의
- `docs/Roadmap.md`: 개발 전 기획 단계부터 운영 단계까지의 순차 로드맵
- `docs/Realtime-Operations.md`: 실시간 수집, 지연 관리, 장애 대응, 재학습 운영 전략
- `docs/Validation-Plan.md`: 백테스트, 온라인 모니터링, 정확도 개선 루프

## 현재 확정된 1차 기준

1. 종목군: `최근 60거래일 중앙값 거래대금 상위 30종목`
2. 시장 범위: `KOSPI + KOSDAQ`
3. 제외 대상: `ETF`, `ETN`, `스팩`, `우선주`, `관리종목`, `거래정지 종목`
4. 리밸런싱: `월 1회`
5. 예측 수평선: `15분 방향`, `60분 방향`
6. 실시간 시세 API 1순위: `한국투자 Open API`
7. 계좌 연동 상태: `한국투자증권 실전투자계좌용 API`, `모의투자계좌용 API` 확보
8. 검증 방식: `백테스트 + 실시간 예측 + 자동 모의투자 병행`
9. 보조 데이터: `KRX OPEN API`, `OpenDART`, `NAVER 검색 API`, `NAVER DataLab`
10. 초기 라벨 임계값: `15분 ±0.35%`, `60분 ±0.8%`
11. 초기 자동매매 방향: `모의투자 long-only`, `당일 청산 중심`
12. 실전 주문 정책: `기본값 비활성화`, `개발 초기에는 절대 미사용`
13. 거래비용/슬리피지 기준: `기본형을 기본 시나리오로 사용`, `낙관/보수 시나리오 동시 비교`
14. 모의주문 규칙 기준: `기본형 진입/청산 규칙 사용`
15. 장중 주문 시간대 기준: `개장 직후 10~15분 신규 진입 금지`, `장 마감 전 20~30분 신규 진입 금지`
16. 계좌 안전장치 기준: `paper/live 분리`, `기본값 paper`, `실전 주문 기본 비활성화`

## 권장 MVP 범위

1. 종목 범위: KOSPI/KOSDAQ 유동성 상위 30~50개 종목
2. 예측 수평선: `15분`, `60분`, `당일 종가 방향`
3. 데이터: 실시간 시세/호가, 공시, 뉴스, 검색 반응
4. 출력: 종목별 방향 점수, 신뢰도, 영향 요인, 경보
5. 검증: 워크포워드 백테스트 + 모의 운용 로그

## 바로 다음 작업

1. 실시간 시세용 증권사 Open API 1개를 확정합니다.
2. 초기 종목 유니버스와 예측 수평선을 고정합니다.
3. 수집/평가/운영 로드맵을 기준으로 1차 개발 범위를 동결합니다.
4. 데이터 수집 스키마와 저장소 구조를 코드로 생성합니다.
5. 베이스라인 모델과 평가 파이프라인을 먼저 구현합니다.

## 참고

이 프로젝트는 투자 판단을 보조하는 예측 연구 시스템입니다. 실제 투자에는 거래비용, 슬리피지, 공시 지연, API 장애, 심리적 편향 등 추가 위험이 존재하므로 별도 검증이 필요합니다.
