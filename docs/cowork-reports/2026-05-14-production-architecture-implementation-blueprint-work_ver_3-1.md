# Production Architecture / Implementation Blueprint - Codex Work Ver 3-1

## 맥락

- 기준 작업본: `work_ver_3`
- 새 cowork 리뷰: 아직 없음
- 계좌 소유자 또는 실전 운용 승인권자 결정: Slice 1 코드 작업 승인, Phase 2 보수 손실 한도와 슬리피지 budget 권장안 채택
- 이번 파일은 `review_ver_3` 전의 하위 작업 기록이다.

## 이번 구현

Slice 1 `live read-only client`를 구현했다.

- 추가: `app/brokers/kis_readonly.py`
- 추가: `tests/test_live_readonly_guard.py`
- 추가: `tests/test_live_client_isolation.py`
- 문서 갱신: `docs/Production-Implementation-Blueprint.md`, `docs/logbook.md`, `docs/cowork-reports/README.md`, `docs/cowork-reports/2026-05-14-production-architecture-implementation-blueprint-operator-decision.md`

`KisReadOnlyClient`는 `KisRestQuoteClient`를 composition으로 감싸고 조회 메서드만 노출한다. `submit_cash_order`, `cancel_order`는 wrapper class에 만들지 않았다. `get_kis_live_readonly_client(settings, mode="live")` factory는 `live`만 허용하고 다른 mode는 거부한다.

## 안전 확인

- 실전 주문 API 호출부는 수정하지 않았다.
- `ALLOW_LIVE_ORDERS` 값은 바꾸지 않았다.
- `app/risk/`는 수정하지 않았다.
- gate 기준값과 `VERSION`은 바꾸지 않았다.
- 테스트는 mock delegate와 factory patch만 사용한다. 실제 KIS 네트워크, token 발급, hashkey 발급은 의도하지 않았다.

## 검증 결과

- `python -m unittest tests.test_live_readonly_guard tests.test_live_client_isolation tests.test_kis_http_clients tests.test_settings`
  - 결과: 통과, 19개
- `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: 통과, 119개

`git diff --check`는 최종 self-review 단계에서 함께 실행한다.

## 다음 작업 권장

🟢 다음 단계 권장: Slice 2a storage schema를 진행한다. 새 테이블 추가 중심이라 live 주문 연결 없이 구현 가능하지만, migration/backup dry-run 절차를 먼저 문서와 테스트로 잠근다.

🟢 다음 단계 권장: Slice 3 market status는 외부 API 연결 전 fixture 기반 순수 로직부터 구현한다. KIS REST 또는 한국거래소 OpenAPI 원천 선택은 별도 결정으로 남긴다.

## 남은 결정

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요: market status 자동 데이터 원천을 KIS REST, 한국거래소 OpenAPI, 수동 snapshot 중 어디까지 Phase 1/2 필수로 둘지 결정해야 한다.

🔴 계좌 소유자 또는 실전 운용 승인권자 판단 필요: audit hash chain anchor 방식, 보관 기간, NAS recovery self-test 미통과 시 Phase 2 금지 여부를 결정해야 한다.
