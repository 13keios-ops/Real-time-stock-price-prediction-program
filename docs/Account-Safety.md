# 계좌 안전 기준

## 역할

이 문서는 계좌 분리, 주문 안전장치, 비밀정보 경계를 정리하는 참고 문서다.
현재 기준은 `AGENTS.md`, `README.md`, `docs/logbook.md`, `docs/Versioning.md`를 우선한다.

## 현재 기준

- 기본 실행 모드는 `paper`다.
- `live` 주문은 기본으로 비활성화한다.
- 실전 API는 조회와 향후 확장 대비용으로만 사용한다.
- 계좌 키와 설정은 `paper/live`를 분리한다.
- 민감 정보는 추적 저장소 밖 `../secrets/`에 둔다.

## 코드 연결

- `app/config/settings.py`
- `app/brokers/kis_auth.py`
- `autopush.json`

## 다음 보강

- 실전 조회 전용 모드와 실전 주문 모드를 더 명확히 분리한다.
- 비밀정보 파일 경로 규약은 로컬 문서로 고정한다.
