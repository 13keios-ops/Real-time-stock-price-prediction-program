# 저장소 심층리뷰 후속 작업 보고서 work_ver_30-2

## 작업 범위

2026-07-10 장후 작업에서 남아 있던 Phase 1 read-only 구조 고정과 Phase 1b 계좌 shape 비교 준비를 진행했다. 모델 실험 동결, 실전 주문 금지, active model/gate 유지 조건은 변경하지 않았다.

## 확인 결과

- 현재 장 상태는 post-close다.
- live runtime은 정상 정지 상태다.
- watchdog과 dashboard는 정상 실행 중이다.
- 로컬 비밀 설정의 상태만 boolean으로 확인했으며 live app key/secret과 live 계좌 항목은 아직 준비되지 않았다.
- `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`다.

## 코드 변경

- 아래 조회 전용 경로를 모두 `get_kis_readonly_client`로 전환했다.
  - `app/collectors/historical.py`
  - `app/services/runtime.py`
  - `app/services/collector.py`
  - `app/services/kis_account.py`
  - `app/__main__.py`의 현재가·호가 CLI
- direct `KisRestQuoteClient` 생성은 `app/brokers/kis_readonly.py`와 KIS 모의계좌 주문 경계인 `app/services/broker_paper.py`만 허용한다.
- `app/services/kis_account_shape_comparison.py`와 `scripts/compare_kis_account_snapshot_checks.sh`를 추가했다.
- 비교 도구는 계좌번호, 잔액, token, raw response를 복사하지 않고 required field, 타입, presence, row count만 비교한다.
- paper와 live의 보유 행 수 차이는 정상일 수 있으므로 equality gate로 쓰지 않고 관측값으로만 남긴다.

## 검증

- 관련 단위 테스트 30개 통과.
- 전체 unittest 470개 통과.
- 전체 pytest 470개와 subtest 67개 통과.
- read-only direct constructor 검색 결과 허용 경계 2곳만 남음.
- Python compileall 통과.
- bash parse와 wrapper help 통과.
- `git diff --check` 통과.

## Codex 의견

이번 변경으로 “플래그가 false라서 안전하다”보다 강한 구조가 됐다. 일반 조회 코드가 주문 메서드를 가진 원본 client를 직접 받지 않기 때문에 실수로 주문 함수를 호출할 표면이 크게 줄었다.

다만 Phase 1b 자체가 통과한 것은 아니다. 실제 live 자격정보와 계좌 응답이 없으므로 live account shape, 예수금/T+2 필드, KIS live HTTP Date는 아직 검증하지 못했다. 이를 구현 완료와 운영 증거 완료로 섞어 쓰면 안 된다.

## 다음 방향

1. live credentials를 저장소 밖 로컬 비밀 저장소에 준비한다.
2. 주문 메서드 없는 client로 live token, account, current price/system clock probe를 1회만 실행한다.
3. paper/live account check를 서로 다른 파일로 저장하고 새 비교 wrapper로 shape 차이를 판정한다.
4. sanitized NAS recovery drill은 사용자 명시 지시가 있을 때만 별도로 실행한다.
5. Phase 0 paper/KIS mismatch 4종목은 다음 거래일 장후 새 단일 호출 정책으로 한 번만 재확인한다.
6. E1/E5 모델 라운드는 예약대로 2026-07-20 장후까지 동결한다.

## 다음 cowork 리뷰 시점

지금은 구조 전환과 로컬 테스트가 명확해 cowork 토큰을 쓸 필요가 낮다. 실제 Phase 1b live read-only 증거와 paper/live shape 비교 결과가 생긴 시점에 안전 경계와 해석을 함께 리뷰하는 것이 권장안이다.
