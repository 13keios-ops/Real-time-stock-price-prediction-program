# docs/STATUS.md

생성일: 2026-05-06
스프린트: 01

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
