# Data Sources Strategy

## 1. 수집 원칙

1. `공식 API` 또는 라이선스가 명확한 소스부터 사용합니다.
2. 모든 데이터는 `Asia/Seoul` 기준 시각으로 정규화합니다.
3. 예측 시점 이후에 공개된 정보가 학습 데이터에 들어가지 않도록 `이벤트 타임`을 엄격히 관리합니다.
4. 합법성 검토 전까지는 커뮤니티 직접 크롤링을 MVP 범위에서 제외합니다.

## 2. MVP 우선 데이터 소스

| 구분 | 후보 소스 | 수집 내용 | 주기 | MVP 활용 |
| --- | --- | --- | --- | --- |
| 실시간 시세/호가 | 한국투자 Open API WebSocket | 체결, 호가, 장운영정보, 거래량 | 실시간 | 핵심 입력 |
| 종목/시장 기준정보 | 한국투자 종목정보, KRX OPEN API | 종목코드, 시장구분, 기준 통계 | 일/수시 | 종목 마스터 |
| 공시/재무 | OpenDART | 공시 제목, 접수시각, 주요 재무/원문 | 이벤트/일 | 이벤트 특징 |
| 뉴스 반응 | NAVER 검색 API(뉴스) | 기사 제목, 요약, 발행 시각, 노출량 | 1~5분 폴링 | 뉴스 특징 |
| 공개 반응 프록시 | NAVER 검색 API(카페글/블로그) | 검색 결과량, 제목/요약, 최신성 | 5~10분 폴링 | 투자자 반응 프록시 |
| 관심도 지표 | NAVER DataLab 검색어 트렌드 | 검색량 추이 지수 | 분/시간/일 단위 집계 | 주의집중 프록시 |

## 3. 행동재무학 관점의 특징 설계

### 주의집중 Attention

- 특정 종목명, 테마명, 공시 키워드의 검색량 급증
- 뉴스 수와 카페/블로그 검색 결과량 급증
- 장중 거래량 급증과 반응량 급증의 동시 발생

### 군집 행동 Herding

- 반응량은 커지는데 텍스트 감성 편향이 한 방향으로 급격히 쏠리는지
- 여러 종목이 동일 테마 키워드로 동시에 과열되는지
- 수급 방향과 텍스트 방향이 같은 쪽으로 과도하게 쏠리는지

### 과민 반응 Overreaction

- 공시 또는 뉴스 직후 수익률 절대값이 과거 유사 이벤트 대비 과도한지
- 변동성 확대가 체결 강도나 호가 잔량으로 지지되지 않는지

### 확증 편향/추격 매수

- 오전 급등 이후 반응량은 증가하지만 체결 품질은 약화되는지
- 종가 근처에서 검색량과 감성이 추세를 과도하게 따라가는지

## 4. 커뮤니티/UGC 데이터에 대한 기준

다음 종류의 데이터는 매우 유용할 수 있지만, `약관/라이선스/robots/재배포 가능 범위`를 먼저 검토해야 합니다.

- 종목 토론 게시판
- 포털 댓글
- 커뮤니티 게시글 원문
- 메신저/폐쇄형 채널 데이터

정책이 명확하지 않은 수집은 MVP에서 제외하고, 우선은 `검색 결과 기반 반응 프록시`와 `공개 API`를 사용합니다.

## 5. 저장 계층 권장안

| 계층 | 저장 대상 | 권장 저장소 |
| --- | --- | --- |
| Raw | 원본 이벤트, 원문 메타데이터 | Object Storage 또는 파일 아카이브 |
| Curated | 정규화된 시세/공시/뉴스 | PostgreSQL + 시계열 확장 |
| Feature | 모델 입력용 특징 테이블 | Feature DB 또는 전용 스키마 |
| Serving | 최신 종목 상태, 최근 예측 점수 | Redis 또는 캐시 계층 |

## 6. 운영 시 주의할 점

- 종목코드 변경, 거래정지, 관리종목 전환 같은 메타 변화 반영
- 공시/뉴스의 게시 시각과 실제 시장 반응 시각 분리
- 장전/장중/장후 데이터를 다른 상태값으로 관리
- API 호출 제한, 인증키 만료, 재연결 로직 준비

## 7. 참고 링크

- 한국투자 Open API: <https://apiportal.koreainvestment.com/intro>
- KRX OPEN API: <https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp>
- OpenDART: <https://opendart.fss.or.kr/intro/main.do>
- NAVER 검색 API(뉴스): <https://developers.naver.com/docs/serviceapi/search/news/news.md>
- NAVER 검색 API(카페글): <https://developers.naver.com/docs/serviceapi/search/cafearticle/cafearticle.md>
- NAVER DataLab 검색어 트렌드: <https://developers.naver.com/docs/serviceapi/datalab/search/search.md>
