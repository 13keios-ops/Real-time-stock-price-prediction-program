# External Benchmark Review

## 1. 목적

이 문서는 현재 프로젝트 구조를 외부 유사 사례와 비교해 다시 점검한 결과입니다.

검토 목표:

1. 지금 설계에서 빠진 축이 있는지 확인
2. 유사 시스템들이 공통적으로 분리하는 모듈이 무엇인지 확인
3. 개발 착수 전에 보완해야 할 구조적 리스크를 찾기

검토 일시:

- 2026-04-11

## 2. 검토한 외부 사례

### 공식 문서/공식 오픈소스

- QuantConnect LEAN / Algorithm Framework
- Microsoft Qlib
- AI4Finance FinRL
- Freqtrade
- 한국투자증권 Open API 공식 문서
- 한국투자증권 공식 GitHub 샘플 저장소

### GitHub / 커뮤니티

- `koreainvestment/open-trading-api`
- `Soju06/python-kis`
- QuantConnect 포럼의 backtest/live 차이 논의
- Freqtrade 이슈의 dry-run/live 차이 논의
- 한국투자 Open API WebSocket 연결 문제를 다룬 공개 GitHub Wiki

## 3. 외부 사례에서 반복적으로 보이는 공통 구조

여러 사례를 비교하면, 성공적으로 유지되는 시스템은 거의 항상 아래 구조를 가집니다.

### A. 데이터와 전략과 주문을 분리

QuantConnect는 구조를 `Universe Selection -> Alpha -> Portfolio Construction -> Execution -> Risk Management`로 나눕니다.

이 구조가 중요한 이유:

- 예측이 좋아도 포지션 크기나 주문 정책이 나쁘면 성과가 나빠집니다.
- 반대로 예측은 평범해도 실행과 리스크 관리가 좋으면 결과가 좋아질 수 있습니다.

현재 우리 프로젝트는 `신호`와 `리스크`는 정리되어 있지만, `Portfolio Construction`이 아직 독립 모듈로 명확히 분리되지는 않았습니다.

### B. 오프라인 연구와 온라인 운영을 분리

Qlib는 데이터/모델/평가를 느슨하게 결합하고, 실행 단위별 실험 기록을 남기며, 온라인 운영도 별도 모듈로 둡니다.

FinRL도 기존에는 `train-test-trade` 파이프라인 중심이었고, 최근 구조는 더 강하게 모듈화된 방향으로 이동했습니다.

현재 우리 프로젝트도 연구와 운영을 나누는 방향은 맞지만, `운영 중 재현 가능한 리플레이`와 `live vs replay 비교`가 아직 독립 기능으로는 정리되지 않았습니다.

### C. 실전과 모의와 백테스트를 구분

Freqtrade와 QuantConnect 커뮤니티 사례를 보면, 동일 전략이라도 `backtest`, `paper`, `live` 결과가 쉽게 달라집니다.

원인:

- 슬리피지
- 수수료
- 데이터 지연
- 체결 방식 차이
- 상태 저장/재시작 차이

현재 우리 문서도 이를 인식하고 있지만, `실시간 예측 결과를 같은 기간의 재구성된 백테스트와 매일 비교하는 절차`는 더 명확히 넣을 필요가 있습니다.

### D. WebSocket 복구와 재구독이 핵심

한국투자 공식 공지와 커뮤니티 사례 모두 `WebSocket 재연결`, `ping/pong`, `재구독 복원`이 매우 중요함을 보여줍니다.

이 부분은 단순 부가기능이 아니라 핵심 운영 기능입니다.

### E. 실험 추적과 운영 추적을 모두 남긴다

Qlib는 execution 단위로 실험 아티팩트를 남기고, Freqtrade는 dry-run wallet, protections, config 분리를 제공하며, community에서는 live reconciliation과 state 분리가 반복적으로 강조됩니다.

현재 문서의 실험 추적 방향은 좋지만, `주문/체결/포지션/예측/리스크 이벤트를 하나의 timeline으로 연결하는 관점`이 더 강해지면 좋습니다.

## 4. 현재 구조의 강점

현재 설계는 이미 아래 부분이 잘 잡혀 있습니다.

1. 공식 API 우선 원칙
2. 실시간 수집 + ML 예측 + 자동 모의투자 검증 루프
3. paper/live 분리와 실전 주문 비활성화
4. 데이터 스키마와 운영 로그 초안
5. 15분/60분 라벨과 초기 유니버스 정의
6. 모의주문 규칙, 비용 가정, 시장 시간 규칙

즉, 방향은 꽤 좋고, 지금 필요한 건 새 아이디어보다 `누락된 구조 요소를 보강`하는 일입니다.

## 5. 현재 구조에서 추가로 구체화가 필요한 핵심 부분

아래 항목들은 외부 사례와 비교했을 때, 개발 전에 더 정리하면 좋은 부분입니다.

### 5.1. 포트폴리오 구성 계층

현재는 `예측 -> 신호 -> 주문` 흐름이 중심인데, 중간에 `Portfolio Construction / Capital Allocation` 계층을 더 분명히 두는 것이 좋습니다.

왜 필요한가:

1. 종목당 5% 진입, 최대 3종목 같은 규칙은 사실상 포트폴리오 규칙입니다.
2. 신호는 종목 단위이고, 자본 배분은 계좌 단위입니다.
3. 이후 다중 종목 동시 진입, 동일 테마 분산, 잔여 현금 관리가 필요해집니다.

권장 보강:

- `portfolio/allocator` 모듈 개념 추가
- 신호를 바로 주문으로 보내지 않고 `target position`을 거치게 설계

### 5.2. 브로커 상태 재조정 Reconciliation

QuantConnect는 live 결과와 같은 기간의 OOS backtest를 비교하는 `Reconciliation` 개념을 따로 둡니다.

현재 프로젝트에도 아래 두 종류의 재조정이 필요합니다.

1. `브로커 재조정`
   - 내부 포지션 상태와 한국투자 모의계좌 상태 비교
2. `전략 재조정`
   - 실시간 예측/모의주문 결과와 재구성 replay 결과 비교

권장 보강:

- 앱 시작 시 잔고/미체결/체결 이력 동기화 절차 문서화
- 매일 장후 `live vs replay` 차이 분석 리포트

### 5.3. 주문 상태 머신과 멱등성

현재 스키마에는 주문/체결 테이블이 있지만, 주문 라이프사이클이 아직 충분히 명시적이지는 않습니다.

필요한 상태 예시:

- created
- sent
- acknowledged
- partially_filled
- filled
- cancelled
- rejected
- recovery_pending

왜 중요한가:

1. 재시작 시 중복 주문 방지
2. 체결 지연/응답 누락 대응
3. paper와 live 인터페이스 통일

### 5.4. Raw/Adjusted 데이터 정책과 기업행위 처리

QuantConnect는 corporate actions, raw vs adjusted data를 핵심 개념으로 둡니다.

국내주식에서도 아래 문제는 반드시 생깁니다.

- 액면분할
- 거래정지
- 관리종목
- 종목코드 변경
- 유상증자/권리락 등 이벤트성 가격 불연속

현재 문서에 언급은 있지만, 정책이 더 명확해지면 좋습니다.

권장 보강:

- 실행용 가격 데이터는 `raw`
- 학습용 장기 이력은 필요 시 `조정 데이터 또는 별도 보정 피처`
- 기업행위 이벤트 테이블 별도 관리

### 5.5. Warm-up / Restart Recovery

커뮤니티 사례를 보면, 시스템 재시작 후 충분한 히스토리와 상태를 복원하지 않으면 예측과 주문이 흔들립니다.

현재 구조에서도 아래가 필요합니다.

1. 앱 시작 시 최근 1분 바/호가/특징 워밍업
2. 실시간 구독 복원
3. 직전 포지션/미체결 주문 복원
4. 준비 완료 전 신규 주문 차단

### 5.6. 실시간 재현용 Replay 계층

현재는 백테스트와 모의주문을 따로 생각하고 있지만, 외부 사례를 보면 `같은 실시간 수집 raw 데이터를 다시 재생해 동일 예측을 재구성`하는 기능이 매우 중요합니다.

이 기능이 있으면:

1. live 결과 차이를 정확히 분석 가능
2. 신호 생성 버그 추적 가능
3. 모델/전략 변경 전 회귀 검증 가능

권장 보강:

- raw tick / orderbook 이벤트 기반 replay runner
- 특정 시각대 재생 기능

### 5.7. 뉴스/공시/반응 데이터의 실무형 NLP 파이프라인

현재는 뉴스/공시/검색을 쓰겠다는 방향은 정해졌지만, 텍스트 파이프라인의 실무 세부는 아직 초기 수준입니다.

필요한 세부:

1. 종목 엔티티 매핑
2. 중복 기사 제거
3. 공시/뉴스 이벤트 유형 분류
4. 게시시각과 수집시각 분리
5. 제목만 사용할지, 요약까지 사용할지 기준

이 부분은 사용자의 핵심 목표인 `투자자 반응 + 심리 요인`과 직접 연결되므로 중요도가 높습니다.

### 5.8. 유니버스 Freeze 정책

현재는 `최근 60거래일 중앙값 거래대금 상위 30종목`과 `월 1회 리밸런싱`까지 정해졌습니다.

하지만 아래 세부는 추가로 고정되면 좋습니다.

1. 산출 기준일
2. 적용 시작일
3. 월중 신규 편입 금지 여부
4. 휴장/특수 일정 포함 시 처리 방식

이걸 정하지 않으면 live/backtest 종목군이 미묘하게 어긋날 수 있습니다.

## 6. 외부 사례별 핵심 시사점

### QuantConnect LEAN

핵심 시사점:

- `Universe / Alpha / Portfolio / Execution / Risk` 분리는 매우 유효합니다.
- live와 backtest 차이를 일상적으로 측정하는 `reconciliation` 개념이 중요합니다.

우리 구조에 반영할 점:

- `portfolio`와 `reconciliation`을 독립 개념으로 문서/코드 구조에 추가하는 것이 좋습니다.

### Qlib

핵심 시사점:

- 데이터, 모델, 평가를 느슨하게 결합
- execution 단위 실험 기록
- online serving 루틴과 online manager 개념

우리 구조에 반영할 점:

- 실험 추적 시스템을 더 강하게 유지
- online routine과 model promotion 절차를 명시

### FinRL

핵심 시사점:

- `train-test-trade`는 좋은 출발점
- 최신 방향은 coupled monolith보다 decoupled modular layers

우리 구조에 반영할 점:

- 초기에 train/test/trade 구조로 시작하되, 장기적으로는 모듈 분리를 더 강화해야 함

### Freqtrade

핵심 시사점:

- dry-run wallet
- protections
- configuration 분리
- production 전환 경고/절차

우리 구조에 반영할 점:

- 모의자금 시작값, 보호장치, 설정 분리를 더 체계적으로 유지

### 한국투자 공식 샘플 저장소

핵심 시사점:

- `strategy_builder -> backtester -> KIS Open API` 흐름을 공식 샘플도 채택
- 공식 샘플 자체가 이미 `백테스트와 주문 실행을 연결된 파이프라인`으로 봄

우리 구조에 반영할 점:

- 현재 방향이 공식 생태계와도 잘 맞음
- 다만 샘플은 참고용이므로 운영 안정성은 별도 설계가 필요

### python-kis 커뮤니티 라이브러리

핵심 시사점:

- 복구 가능한 WebSocket
- live/paper 시크릿 분리
- 토큰 관리와 thread-safe 처리
- 휴장일 조회와 환경 분리

우리 구조에 반영할 점:

- 브로커 클라이언트를 완전 자작하더라도 이 패턴은 적극 참고할 가치가 높음

## 7. 결론

### 전체 판단

현재 프로젝트의 큰 방향은 타당합니다.

외부 사례와 비교해 봐도:

- `실시간 수집`
- `ML 예측`
- `자동 모의투자 검증`
- `paper/live 분리`

라는 큰 틀은 잘 잡혀 있습니다.

### 하지만 개발 전 보강하면 좋은 핵심 5개

1. `Portfolio Construction` 계층 명시
2. `Reconciliation` 계층 명시
3. `주문 상태 머신 + 멱등성` 명시
4. `기업행위 / raw-adjusted 데이터 정책` 명시
5. `Warm-up / Restart / Replay` 절차 명시

## 8. 다음 문서 작업 우선순위 제안

만약 개발 전에 한 번 더 구조를 다듬는다면, 아래 순서가 가장 효율적입니다.

1. `Portfolio-And-Reconciliation.md`
2. `Order-Lifecycle.md`
3. `Market-Data-Policy.md`
4. `Replay-And-Recovery.md`
5. `NLP-Event-Pipeline.md`

이 다섯 문서가 추가되면, 설계 빈틈은 상당히 줄어듭니다.

## 9. 참고 링크

- QuantConnect Algorithm Framework Overview: <https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview>
- QuantConnect Reconciliation: <https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/reconciliation>
- Qlib Workflow: <https://qlib.readthedocs.io/en/stable/component/workflow.html>
- Qlib Online Serving: <https://qlib.readthedocs.io/en/v0.9.2/component/online.html>
- FinRL GitHub: <https://github.com/AI4Finance-Foundation/FinRL>
- Freqtrade Configuration: <https://docs.freqtrade.io/en/latest/configuration/>
- Freqtrade Protections: <https://www.freqtrade.io/en/2024.1/includes/protections/>
- 한국투자 Open API 개발자센터: <https://apiportal.koreainvestment.com/>
- 한국투자 공식 샘플 저장소: <https://github.com/koreainvestment/open-trading-api>
- python-kis: <https://github.com/Soju06/python-kis>
- 한국투자 WebSocket 연결 이슈 사례: <https://github-wiki-see.page/m/boostcampwm-2024/web16-JuGa/wiki/%ED%95%9C%EA%B5%AD%ED%88%AC%EC%9E%90-Open-API-%EC%9B%B9%EC%86%8C%EC%BC%93-%EC%97%B0%EA%B2%B0%EC%9D%B4-%EC%A4%91%EB%8B%A8%EB%90%98%EB%8A%94-%EB%AC%B8%EC%A0%9C>
