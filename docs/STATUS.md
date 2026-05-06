# docs/STATUS.md

생성일: 2026-05-06
스프린트: 03 데이터 품질 점검

## 🟠 [2026-05-06 16:18] 스프린트 04 전 점검 — pykrx 프록시 분봉 품질 확인

- 상황: 스프린트 03에서 적재한 `pykrx-daily-proxy` 15분 프록시 분봉이 실제 KIS WebSocket 기반 분봉과 같은 DB 구조로 들어가지만, 호가 기반 피처의 의미가 실제 호가와 크게 다르다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: 스프린트 04 학습/검증에 프록시 데이터를 그대로 쓸 수는 있으나, `spread_bps`, `bid_ask_imbalance` 같은 호가 기반 피처는 source 별 분포 차이가 커서 별도 처리 필요.

### 확인 1. pykrx 프록시 분봉 구조

구현 위치: `app/collectors/historical.py`

- 거래일당 26개 봉을 만든다. `_market_times()`는 09:00부터 15분 간격으로 시각을 만들기 때문에 마지막 프록시 봉은 15:15다.
- 가격 경로는 일봉 OHLC를 선형 보간한다.
  - 상승일 또는 보합/상승일: index `0=open`, `6=low`, `18=high`, `25=close`
  - 하락일: index `0=open`, `6=high`, `18=low`, `25=close`
  - 각 봉의 open은 직전 프록시 close, close는 보간값이다.
  - high/low는 기본적으로 open/close 사이 값이며, 보간 close가 일봉 high/low anchor와 같을 때만 해당 일봉 high/low를 반영한다.
- 거래량은 전체 일봉 거래량을 U자형 가중치로 26개 봉에 나눈다. 장 초반과 장 후반에 더 큰 weight가 붙고, 마지막 봉에서 반올림 잔여량을 보정한다.
- 프록시 호가는 각 프록시 close 기준으로 `bid=close-tick`, `ask=close+tick`을 만들고, `bid_size=ask_size=max(1, volume//2)`로 채운다.
- 따라서 raw proxy orderbook 기준:
  - `mid_price`는 사실상 프록시 close와 같다.
  - `spread_bps`는 실제 호가 스프레드가 아니라 가격대별 tick size로 만든 기계적 값이다.
  - `bid_ask_imbalance`는 bid/ask size를 같게 넣기 때문에 항상 `0.0`이다.
- 구조 호환성: `MinuteBar`, `OrderbookSnapshot`, `curated_minute_bars`, `raw_orderbook_ticks`, `feature_model_inputs`, `feature_labels`를 그대로 쓰므로 KIS WebSocket 분봉과 스키마는 호환된다. 다만 실제 호가 압력, 체결 강도, 장중 변동 경로를 재현한 데이터는 아니다.

### 확인 2. KIS 실제 호가 vs pykrx 프록시 피처 분포

비교 기준 DB: `runtime-data/dev.db`

| 항목 | `kis-ws` | `pykrx-daily-proxy` |
|---|---:|---:|
| raw orderbook rows | 2,245,513 | 332,228 |
| raw 기간 | 2026-04-28 09:00 ~ 2026-05-06 13:41 | 2021-01-04 09:00 ~ 2026-05-06 15:15 |
| exact feature samples | 12,521 | 332,228 |
| proxy/KIS exact overlap minutes | - | 798 |

주요 feature 분포:

| feature | `kis-ws` median / mean | `pykrx-daily-proxy` median / mean | 판단 |
|---|---:|---:|---|
| `mid_price` | 221,250 / 478,689 | 172,500 / 295,257 | 기간과 종목 가격대 차이 영향이 커 직접 비교 지표로는 제한적 |
| `spread_bps` | 12.83 / 14.74 | 37.92 / 42.31 | 프록시가 실제보다 약 3배 높게 형성되어 분포 차이 큼 |
| `bid_ask_imbalance` | 0.0418 / 0.0337, p05=-0.8056, p95=0.8500 | 0.0 / 0.0, zero_ratio=100% | 프록시는 호가 불균형 정보가 완전히 사라짐 |

### 결론과 스프린트 04 권장 조치

- `pykrx-daily-proxy`는 5년치 가격/라벨 볼륨을 확보하는 목적에는 유효하다.
- 단, 실제 KIS WebSocket 기반 학습/추론과 같은 의미로 호가 피처를 쓰면 분포 이동이 크다.
- 스프린트 04에서는 아래 중 하나를 먼저 정해야 한다.
  1. proxy source 학습에서는 `spread_bps`, `bid_ask_imbalance`를 제외하거나 neutral 처리한다.
  2. feature에 `data_source` 또는 `is_proxy` 계열 구분값을 추가해 모델이 source 차이를 학습하게 한다.
  3. 실제 KIS 데이터만으로 짧은 기간 검증을 할 때와 proxy 장기 데이터 검증을 분리해 평가 리포트를 따로 낸다.
- 현재 상태에서 LightGBM 중요도 상위에 `mid_price`, `spread_bps`, `bid_ask_imbalance`가 들어간 것은 proxy/actual 분포 차이 또는 가격수준 의존 가능성을 함께 의심해야 한다.

## 🔴 [2026-05-06 05:22] 운영자 판단 필요 — Phase 1 Windows 직접 실행 완료

- 상황: Windows 로컬 환경에서 작업 1 단위 테스트 통과 후 Phase 1 명령 3개를 순서대로 직접 실행 완료. LightGBM은 validation 정확도와 누적 손실 폭에서는 baseline보다 좋아 보이나, 실제 매수 신호가 3건뿐이라 challenger 판단은 `keep_active`이며 walk-forward gate도 `needs_review`.
- 가져갈 파일: `docs/STATUS.md`
- 질문: 아래 Phase 1 수치를 기준으로 Codex가 Phase 2 원인 분석(거래 수 부족, walk-forward 정확도 미달, LightGBM 신호 희소성)을 진행해도 되는지 확인 필요.

### 실행 명령과 결과

| 단계 | 명령 | 결과 |
|---|---|---|
| 작업 1 검증 | `python -m unittest discover -s tests -p "test_*.py"` | `Ran 85 tests in 25.449s`, `OK` |
| baseline/참조 walk-forward | `python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40` | `exit 0` |
| LightGBM 학습 | `python -m app --train-lightgbm --horizon-min 15` | `exit 0` |
| Challenger 비교 | `python -m app --run-challengers --horizon-min 15` | `exit 0` |

### Phase 1 핵심 수치

> MDD와 샤프지수는 현재 리포트 원 필드가 아니라, 거래별 또는 fold별 `net_return_pct` 단순누적 시퀀스로 계산한 참고값이다.

| 지표 | baseline / active | LightGBM latest | baseline 대비 |
|---|---:|---:|---|
| validation rows | 2303 | 2303 | 동일 |
| trades_taken | 1013 | 3 | LightGBM 신호가 과소 |
| 누적 순수익률 | -51.599478% | -0.113131% | LightGBM 손실 폭 우위 |
| MDD | -58.734863% | -0.177832% | LightGBM 손실 폭 우위 |
| 샤프지수 | -0.163627 | -0.203249 | baseline 우위 |
| 정확도 | 0.108120 | 0.816761 | LightGBM 우위 |
| win_rate | 0.358342 | 0.333333 | baseline 우위 |
| baseline 대비 판정 | 기준 | 정확도/순수익률은 우위이나 거래 수 3건으로 승격 불가 | `recommended_action=keep_active` |

### Walk-forward 참조 수치

| 항목 | 값 |
|---|---:|
| model_version | `walk-forward-centroid-h15-v1` |
| folds | 1147 |
| rows_evaluated | 11470 |
| trades_taken | 3126 |
| overall_accuracy | 0.438710 |
| trade_hit_rate | 0.197377 |
| win_rate | 0.442738 |
| 누적 순수익률 | -14.115270% |
| MDD(폴드 순수익 단순누적 기준) | -160.630188% |
| 샤프지수(폴드 순수익 기준) | -0.010281 |
| gate | `needs_review` — `Walk-forward overall accuracy is too low (0.4387).` |

### LightGBM 학습 수치

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506052213057306` |
| train_rows | 9212 |
| validation_rows | 2303 |
| validation_accuracy | 0.816761 |
| activation_applied | `false` |

### 피처 중요도 상위 5개

| 순위 | 피처 | importance |
|---:|---|---:|
| 1 | `mid_price` | 1450 |
| 2 | `spread_bps` | 1110 |
| 3 | `bid_ask_imbalance` | 1077 |
| 4 | `avg_trade_size` | 986 |
| 5 | `hl_range_pct` | 853 |

### 다음 요청

- Codex Phase 2 원인 분석 후보:
  - LightGBM validation 정확도는 높지만 `up` 신호가 3건뿐이라 거래 커버리지가 부족한 이유 확인.
  - walk-forward 정확도 0.438710으로 gate 0.55 기준 미달 원인 확인.
  - `mid_price`, `spread_bps`, `bid_ask_imbalance` 중심 중요도 편중이 데이터 누수/가격수준 의존인지 점검.
- 운영자 판단 필요: 예 — Phase 2 원인 분석 착수 승인 필요.

## 🔴 [2026-05-06 두 번째 호출] 운영자 판단 필요 — Codex 패치 후에도 Synthetic 미통과

- 상황: Codex 커밋 `eb3949f`(WAL→DELETE journal fallback) 적용 후 재실행했으나, virtiofs FUSE 환경에서는 `journal_mode=DELETE` 단독으로도 SQLite 가 `disk I/O error` 로 실패. 단위 테스트 85 발견(개수 일치) 중 40건이 동일 오류로 실패. Synthetic 도 같은 원인으로 진입 직후 실패.
- 가져갈 파일: `docs/logbook.md` (상단 "Cowork 후속 검증" 섹션에 pragma 조합별 실험표 포함)
- 질문: Codex 에 다음 중 어떤 추가 조치를 지시할지 결정 필요
  1. **`DELETE` 선택 시 `PRAGMA locking_mode=EXCLUSIVE` 함께 설정** — 실험에서 동작 확인. 단일 프로세스 운영(Cowork synthetic, 단위 테스트)에는 영향 없으나 동시 접속이 필요한 대시보드/감시기 동시 운영 시 영향 검토 필요.
  2. **DELETE 실패 시 `journal_mode=MEMORY` 로 한 단계 더 fallback** — 가장 단순. 정전·크래시 시 DB 무결성 약간 저하 가능. Cowork 샌드박스 한정 적용 권장.
  3. **Phase 1 진단을 운영자가 Windows 로컬에서 직접 실행** — Cowork 환경 자체를 우회. 가장 빠르지만 자동화 흐름 깨짐.

### 사전 정리(이번 세션 적용 사항 — 다음 세션에 영향 없음)
- 작업트리 `app/storage/sqlite_store.py` 가 FUSE 동기화 중 1074→964줄로 절단된 채 도착해 `SyntaxError`. `git show HEAD:` 로 정본 1074줄 복원함(코드 변경 아님, 정본 복원).
- Cowork 샌드박스 Python 3.10.12 ↔ 프로젝트 요구 ≥3.12 갭은 `tomli` 백포트를 `tomllib` shim 으로 메움.
- 누락 패키지(`lightgbm`, `scikit-learn`, `websockets`, `joblib`, `tomli`, `scipy`, `threadpoolctl`) 설치 완료.

### 핵심 실험표 (logbook.md 상세)

| pragma 조합 | 결과 |
|---|---|
| `journal_mode=DELETE` | FAIL: disk I/O error |
| `journal_mode=DELETE` + `synchronous=NORMAL` (현재 코드) | FAIL: disk I/O error |
| `journal_mode=DELETE` + `synchronous=OFF` | FAIL: disk I/O error |
| `journal_mode=DELETE` + `locking_mode=EXCLUSIVE` | OK |
| `journal_mode=MEMORY` | OK |
| `journal_mode=OFF` | OK |

### Phase 1 결과
- Step 1 Synthetic 흐름 검증: **여전히 실패** (Codex 1차 패치로는 미해결)
- Step 2~5: 미실행 (가이드의 "Synthetic 통과 전 Step 2 보류" 규칙)

### 다음 단계
운영자 결정 후 Codex 재작업 또는 Windows 직접 실행 결정. 결정 전까지 추가 실행 없이 대기.
