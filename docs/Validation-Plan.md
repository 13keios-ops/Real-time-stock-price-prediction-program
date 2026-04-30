# 검증과 정확도 개선 계획

## 역할

정확도 향상과 검증 루프를 어떤 순서로 강화할지 정리하는 참고 문서다.

## 핵심 원칙

- 정확도 향상은 모델 교체보다 데이터 품질과 검증 구조 개선에서 먼저 나온다.
- 단일 split보다 walk-forward 검증을 우선한다.
- accuracy만으로 개선을 선언하지 않는다.

## 현재 추천 순서

1. raw 저장과 bar 생성 안정화
2. label 품질 확인
3. baseline backtest / walk-forward 고정
4. challenger 모델 추가
5. paper trading runtime 비교
6. drift와 feature 품질 점검

## 비교 기준

- 정확도
- 거래 수
- 누적 수익률
- fold 간 편차
- 신호 발생 범위
- 비용 민감도

## 다음 확장

- 도전자 모델 순위표
- feature 통계 리포트
- 일자별 regime 비교
- model registry 자동 승격 규칙
