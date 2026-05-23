# Production Architecture / Implementation Blueprint work_ver_11-11

작성: Codex
기준 리뷰: `2026-05-17-production-architecture-implementation-blueprint-review_ver_10.md` 이후 추가 작업
목적: live alert outbox에 비밀값이 남을 위험 축소

## 1. 작업 요약

- `app/services/live_alerting.py`의 outbox JSONL 기록 직전에 `detail_json`을 redaction하도록 보강했습니다.
- 재사용 helper: `app/brokers/kis_response_redaction.py`
- redaction 대상 예:
  - 계좌번호 계열 key
  - token/authorization 계열 key
  - app key/app secret 계열 key
  - email/phone 등 개인 식별 가능성이 있는 key
- 안전 예외 key는 기존 helper 기준을 따릅니다. 예: `pdno`, `ord_no` 등 주문/종목 식별용 안전 key.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 내용 |
| --- | --- |
| 변경 전 | alert outbox record가 `alert.to_record()`의 `detail_json`을 그대로 저장했습니다. |
| 변경 후 | outbox 저장 직전 `detail_json`만 redaction한 record를 저장합니다. render text, 라우팅, dedupe key 계산은 유지합니다. |
| 영향 범위 | `runtime-data/reports/alerts/{local,telegram,email}/alerts-YYYY-MM-DD.jsonl`의 `alert.detail_json` 저장 형태 |
| 회귀 위험 | detail payload를 사람이 디버깅할 때 계좌/토큰/key 계열 값은 보이지 않습니다. 이는 의도된 안전 측 동작입니다. `title`, `message` 같은 자유 텍스트는 아직 redaction하지 않습니다. |

## 3. 검증

- `python -m py_compile app/services/live_alerting.py tests/test_live_alerting.py app/brokers/kis_response_redaction.py`
- `python -m unittest tests.test_live_alerting tests.test_kis_response_redaction`
- 결과: 14개 테스트 통과.

## 4. 안전 확인

- 실제 텔레그램/이메일 발송기 추가 없음.
- KIS live/paper API 신규 호출 없음.
- 운영 DB schema apply 없음.
- runtime DB 쓰기 없음.
- `app/risk/`, `VERSION`, `config/`, gate 기준값, `ALLOW_LIVE_ORDERS` 변경 없음.
- 자동 commit/push 없음.

## 5. cowork 검토 요청

1. alert outbox의 `detail_json`만 redaction하고 `title`/`message`는 후속으로 둔 범위가 충분히 보수적인지 확인 부탁드립니다.
2. `app/services/live_alerting.py`가 `app/brokers/kis_response_redaction.py` helper를 import하는 레이어 의존이 현재 저장소 패턴상 허용 가능한지 봐 주세요.
3. 자유 텍스트 redaction을 다음 단계에서 추가해야 한다면, 단순 키 기반 helper를 유지할지 별도 문자열 sanitizer를 둘지 의견 부탁드립니다.

## 6. Codex 권장안

🟢 다음 단계 권장: 다음 단계에서는 자유 텍스트 전체를 과하게 redaction하기보다, alert 생성 함수 쪽에서 raw broker payload를 `message`에 넣지 않는 규칙과 테스트를 먼저 잠그는 방식을 권장합니다. 그 후 실제 sender 연결 직전에 최종 문자열 sanitizer를 한 번 더 두는 2단계가 좋습니다.

🔴 운영자 판단 필요: 실제 외부 발송기는 아직 붙이지 않는 권장안을 유지합니다. 텔레그램/이메일 token과 수신 주소는 git 추적 파일이 아니라 로컬 secret 경로에서만 읽도록 별도 승인 후 진행하는 편이 안전합니다.
