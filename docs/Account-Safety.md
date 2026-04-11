# Account Safety

## 역할

이 문서는 계좌 분리, 주문 안전장치, 비밀정보 경계를 정리하는 reference 문서다.
현재 truth는 `AGENTS.md`, `README.md`, `docs/logbook.md`, `docs/Versioning.md`를 우선한다.

## 현재 기준

- 기본 실행 모드는 `paper`
- `live` 주문은 기본 비활성화
- 실전 API는 조회와 향후 확장 대비용으로만 사용
- 계좌 키와 설정은 `paper/live`를 분리
- 민감 정보는 tracked repo 바깥 `../secrets/`에 둔다

## 코드 연결

- `app/config/settings.py`
- `app/brokers/kis_auth.py`
- `autopush.json`

## 다음 보강

- live 조회 전용 모드와 live 주문 모드를 더 명확히 분리
- secret 파일 경로 규약을 로컬 문서로 고정
