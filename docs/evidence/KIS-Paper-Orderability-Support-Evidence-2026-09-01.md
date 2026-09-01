# KIS Paper Orderability Support Evidence

## Purpose

이 문서는 KIS 국내주식 모의투자 `order-cash` 문의에 사용할 credential-free 증적이다.
운영 원본은 `runtime-data/reports/broker-paper/kis-support-paper-orderability-evidence.md`에 있으며, 이 파일은 새 clone과 다른 작업환경에서도 확인할 수 있도록 만든 Git-tracked sanitized snapshot이다.

## Environment

- environment: `paper/demo`
- market: Korean domestic stock
- trading mode: `paper`
- live orders: disabled
- paper API credential/account linkage: confirmed by the account owner
- paper account expiration: `2027-04-10`
- account identifier, credential, token, raw header, broker identifier, exact cash and exact orderable quantity: excluded

## Orderability Comparison

계좌 소유자가 승인한 두 one-off read-only 확인 결과다. 정확한 매수가능금액과 수량은 저장하지 않는다.

| Item | `ORD_DVSN=01` | `ORD_DVSN=00` |
| --- | --- | --- |
| Endpoint | `inquire-psbl-order` | `inquire-psbl-order` |
| TR ID | `VTTC8908R` | `VTTC8908R` |
| Symbol | `005930` | `005930` |
| Transport | success | success |
| Business result | success | success |
| `rt_cd` | `0` | `0` |
| Orderability | positive | positive |
| Actual order/cancel | `0/0` | `0/0` |

## Cash-Order Implementation Contract

Repository implementation: `app/brokers/kis_quote_rest.py::KisRestQuoteClient.submit_cash_order()`

- endpoint: `/uapi/domestic-stock/v1/trading/order-cash`
- paper buy TR ID: `VTTC0012U`
- paper sell TR ID: `VTTC0011U`
- body fields: `CANO`, `ACNT_PRDT_CD`, `PDNO`, `ORD_DVSN`, `ORD_QTY`, `ORD_UNPR`, `EXCG_ID_DVSN_CD`, `SLL_TYPE`, `CNDT_PRIC`
- quantity and price: string conversion before submission
- exchange code: `KRX`
- POST hashkey: enabled
- request contract match: `true`

2026-09-01에 한국투자증권 공식 current `order_cash` sample과 endpoint, paper TR ID, body field, string quantity/price, KRX 구성을 다시 비교했고 contract drift를 찾지 못했다.

Official reference:
`https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py`

## Failure Evidence

- taxonomy: `broker_account_not_orderable`
- sanitized message: `모의투자 주문이 불가한 계좌입니다.`
- failure lineage completion: `100%`

| Date | Account rejection | Network calls | Circuit blocks | Successful submissions |
| --- | ---: | ---: | ---: | ---: |
| 2026-08-31 | 871 | 11 | 860 | 0 |
| 2026-09-01 | 811 | 12 | 799 | 0 |

30분 account hard-rejection circuit은 반복 broker network submission만 차단한다. local paper execution, decision/failure lineage, E7 수집은 계속된다.

## Diagnostic Conclusion

`ORDER_TYPE_DIFFERENCE_NOT_CAUSAL`

`KIS paper cash-order endpoint-specific entitlement/policy issue strongly suspected`

Read-only orderability는 같은 paper 계좌에서 `ORD_DVSN=01/00` 모두 성공했지만 실제 `order-cash`만 account-not-orderable로 거절됐다. 현재 repository 계약 오류 근거는 없고 endpoint별 entitlement 또는 account/service policy 문제를 우선 의심한다. 다만 KIS 지원 확인 전에는 `KIS server bug confirmed`로 단정하지 않는다.

## Support Questions

1. 해당 domestic-stock paper account에 `order-cash` API entitlement가 별도로 제한되어 있는가?
2. `inquire-psbl-order`는 성공하지만 `order-cash`만 account-not-orderable이 되는 알려진 paper 조건이 있는가?
3. API 신청, HTS 설정, account type 또는 paper activation에서 추가 설정이 필요한가?
4. KIS에서 해당 계좌의 domestic-stock paper order entitlement/service 상태를 확인할 수 있는가?

계좌번호와 필요한 요청 시각은 KIS가 요구할 때 인증된 지원 채널에서 계좌 소유자가 별도로 제공한다. App key/secret, access token, WebSocket key와 raw authorization header는 제공하지 않는다.

## Probe Stop Policy

KIS 회신 전에는 다음을 수행하지 않는다.

- orderability `--execute` 반복
- 다른 symbol probe
- 다른 order type probe
- 강제 cash order 또는 cancel
- account hard-rejection circuit 완화
- Phase 0 분모를 채우기 위한 강제 submission

기존 정책에서 자연 발생한 broker submission만 관찰한다.

## Phase 0 and Integrity

- current epoch: `0/10`
- matched/mismatch: `0/0`
- successful submissions after baseline: `0`
- reconciliation: `waiting_first_submission`
- readiness: not ready
- KIS network call during tracked snapshot creation: `0`
- order/cancel during tracked snapshot creation: `0/0`
- application code, strategy, E7, Phase 0 baseline, risk, config, VERSION changed: no
