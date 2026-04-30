# 기준 결정

## 역할

이 문서는 현재 프로젝트의 기준 결정을 짧게 고정하는 참고 문서다.

## 현재 확정 기준

- 시장 범위: `KOSPI + KOSDAQ`
- 운영 유니버스: `최근 60거래일 중앙값 거래대금 상위 30종목`
- 개발용 watchlist: `core 10`
- 예측 수평선: `15분`, `60분`
- KIS 사용 우선순위: `한국투자 Open API`
- 초기 라벨 임계값: `15분 ±0.35%`, `60분 ±0.8%`
- 거래 정책: `paper long-only`, 실전 주문 기본 비활성화
- 시간 정책: 개장 직후 신규 진입 금지, 마감 전 신규 진입 금지
- 버전 관리: `VERSION` 기반 watcher 감지

## canonical 반영 위치

- 현재 기준: `README.md`, `docs/logbook.md`, `docs/Versioning.md`
