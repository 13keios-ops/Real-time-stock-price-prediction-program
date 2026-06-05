---
name: daily-ops-check
description: Use for this repository when checking or acting on 장전/장후 자동화, daily runtime status, paper/KIS reconciliation, data quality, or dashboard freshness.
---

# Daily Ops Check

이 skill은 이 저장소의 장전/장후 자동화 결과를 확인하고
필요한 조치를 끝까지 진행할 때 쓴다.

## 1. 시작 안전 확인

먼저 아래를 실행한다.

```bash
./scripts/get_live_runtime_status.sh
./scripts/get_runtime_watchdog_status.sh
git status --short --branch
```

- `regular-session`, `pre-open`, `live_runtime_should_run=true`,
  live runtime 실행 중이면 장중 보호 모드다.
- 장중 보호 모드에서는 사용자 명시 승인 없이 root 코드 변경,
  전체 테스트, dashboard/runtime 재생성, 운영 DB 쓰기 가능 명령을 피한다.
- `post-close`, `overnight`, 휴장일이고 live runtime 이 꺼져 있으면
  장후/장외 조치를 진행할 수 있다.

## 2. 오늘 자동화 산출물 확인

오늘 날짜 기준으로 아래 파일을 우선 확인한다.

```bash
find runtime-data/reports -type f -newermt "YYYY-MM-DD 00:00:00" \
  \( -name "*.json" -o -name "*.md" \) | sort
```

핵심 파일:

- `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
- `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`
- `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`
- `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
- `runtime-data/reports/data-quality/latest-feature-source-drift.json`
- `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.json`
- `runtime-data/reports/broker-paper/latest-sync.json`
- `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
- `runtime-data/reports/recovery/latest-local-setup-check.json`
- `runtime-data/reports/dashboard/latest-dashboard.json`

## 3. 판정 기준

정상으로 볼 수 있는 상태:

- premarket readiness: `status=ok`, blockers/warnings 없음.
- post-close ML: `status=ok`.
- post-close label refresh: `status=ok`.
- KIS live data quality: `assessment.status=ok`.
- local setup: `ok=true`, blockers/warnings 없음.
- live runtime: 장후에는 정지 상태가 정상.
- watchdog: `status=running`, `errors=[]`.

주의로 남길 수 있는 상태:

- source drift: `source_drift_detected`.
  현재는 KIS live와 Cybos historical 차이를 알려주는 진단이다.
- feature diagnostics: `no_clear_single_feature_signal`.
  모델 승격 근거가 아니라 데이터 누적 필요 신호다.
- broker sync `pending_symbols` 존재.
  `status=ok`이고 주문이 아직 open 상태이면 바로 실패로 보지 않는다.

조치가 필요한 상태:

- reconciliation 또는 dual match 가 `needs_review`.
- KIS `EGW00201` rate limit.
- dashboard snapshot 이 조치 전 시각에 머물러 있음.
- post-close status 파일이 `running` 또는 stale 로 남아 있음.
- local setup blockers/warnings 존재.

## 4. 조치 원칙

### KIS rate limit

- 같은 endpoint를 계속 반복 호출하지 않는다.
- cooldown 뒤 1회 재시도한다.
- 계속 `EGW00201`이면 추가 호출을 멈추고 logbook에 남긴다.

### paper/KIS 정합성

먼저 broker sync와 reconciliation을 재실행한다.

```bash
python -m app --sync-broker-paper-orders
python -m app --reconcile-paper-accounts
```

다음 조건이면 marker-only alignment를 권장한다.

- 보유 수량 mismatch 가 0이다.
- broker account 조회가 정상이다.
- local snapshot 이 오래되어 현재가/평가금액만 어긋난다.
- broker sync 의 `open_order_count`가 0이거나,
  남은 open order가 다음 거래일 기준선에 영향을 주지 않는다고 확인됐다.
- `-SyncInitialCash`가 필요한 상황이 아니다.

적용 명령:

```bash
./scripts/verify_paper_dual_account_match.sh -AlignToBroker -AsJson
```

주의:

- 보유 포지션이 있으면 `-SyncInitialCash`를 임의로 붙이지 않는다.
- 수량 mismatch 가 있으면 align으로 덮지 말고 원인을 먼저 확인한다.
- `open_order_count > 0`이고 order-fill 조회가 rate limit이면
  align을 보류하고 `needs_review`를 유지한다.
- 단, 최신 KIS 모의계좌 status snapshot 이 이미 있고 주문일이 현재 점검일보다
  이전이며, 체결수량 0 / 잔량 전체 유지인 prior-day stale open 주문은
  다음 거래일 기준선에 체결로 반영될 수 없는 만료 후보로 본다.
  이때 보유 수량 mismatch 0, broker account 조회 정상, 현금/총자산 gap 이
  평가 기준선 차이로 설명되면 marker-only alignment 를 적용할 수 있다.
- snapshot 이 없는 제출 주문, 당일 open 주문, 부분 체결 후 잔량이 남은 주문은
  stale 로 단정하지 않고 조회 복구 또는 사람 확인 전까지 align 을 보류한다.
- 장후이고 같은 order-fill endpoint 가 cooldown 뒤 1회 재시도에서도
  `EGW00201`로 막혔으며, broker account snapshot 이 정상/최신이고
  다음 거래일 기준선 보호가 필요한 paper mirroring 수량 mismatch 라면
  `-SyncInitialCash` 없이 broker account 기준 marker-only alignment 를 적용할 수 있다.
  이 경우 order-level fill 감사가 복구되지 않았다는 한계를 logbook 에 반드시 남긴다.
- 실전 계좌 주문/취소는 하지 않는다.

### 리포트와 dashboard

정합성 조치 뒤에는 아래를 갱신한다.

```bash
python -m app --build-runtime-report
python -m app --build-dashboard
./scripts/get_dashboard_status.sh
```

`--build-dashboard`는 오래 걸릴 수 있으므로 장후에는 넉넉한 timeout을 둔다.
timeout이면 최신 `latest-dashboard.json`의 `generated_at`과 남은 프로세스를 확인한다.

## 5. 문서화

작업 종료 전 아래 문서를 갱신한다.

- `docs/logbook.md`: 당일 확인, 조치, 검증, 남은 위험.
- `docs/Production-Transition-Progress.md`: phase 진행이나 P0 보드에 영향이 있을 때.
- `docs/Codex-Operating-Feedback.md`: 반복 누락 또는 skill 기준 변경이 있을 때.

NAS 백업은 사용자가 명시적으로 지시한 경우에만 실행한다.

## 6. 최종 보고 형식

최종 답변에는 아래를 포함한다.

- 장전 readiness 결과.
- 장후 ML/label/data quality 결과.
- paper/KIS 정합성 조치 전후.
- dashboard/runtime 갱신 여부.
- 변경 파일과 검증 명령.
- 남은 위험과 다음 권장안.
- commit/push/NAS 백업 상태.
- 현재 작업 모드, 답변 접두어, 체크리스트 갱신,
  기준 문서 반영 여부.
