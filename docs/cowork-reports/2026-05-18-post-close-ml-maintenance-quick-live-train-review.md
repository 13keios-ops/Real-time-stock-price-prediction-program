# Claude cowork 리뷰: post-close ML 유지보수 quick-live-train 전환 + LightGBM/Challenger max_rows 250k 제한 + dashboard 표시

## 검토 대상

- `app/services/research.py` (`LIGHTGBM_DEFAULT_MAX_FEATURE_ROWS=250_000`, `train_lightgbm_from_sqlite`, `run_model_challenger_review_from_sqlite`, `_build_walk_forward_gate`, `_build_walk_forward_setup_review`)
- `app/storage/sqlite_store.py` (`fetch_feature_rows`)
- `scripts/script_dispatch.sh` (`post_close_ml_maintenance`, `post_close_label_refresh`)
- `app/services/dashboard.py` (`_build_walk_forward_setup_status`, 장후 ML 유지보수 카드, 게이트 기준 워크포워드 카드, `setup_status_label`/`gate_status_label` 분리)
- 출력 형식: 위험한 가정 / 보강 필요 테스트 / 문서 보강 필요 / 다른 thread와의 충돌 가능성

## 요약

5개 영역 모두 의도가 명확하고 코드/구현이 그 의도를 충실히 반영합니다. 운영 안정성 측면에서는 **`max_rows=250000` 기본 제한 + quick-live-train + state→dashboard build 순서**가 14GB OOM 위험을 효과적으로 차단합니다. 결론은 **운영 안정성 충분, 보강 후보 4가지 + 다른 thread와 충돌 가능성 2가지**.

핵심 발견 세 가지: (1) `fetch_feature_rows`가 `max_rows`와 함께 호출되면 `ORDER BY event_time DESC LIMIT`로 **최근 row를 가져온 뒤 `_load_labeled_feature_dataset`가 ascending 재정렬** — 의도된 동작. (2) `_build_walk_forward_gate`(research.py 1375행)와 `_build_walk_forward_setup_status`(dashboard.py 2219행)가 **같은 임계치(min_train_rows<1000, test_window_rows<100, max_train_rows<1000, folds>5000, accuracy<0.55, weakest_fold<=0, cumulative_net<=0)를 각자 독립적으로 구현** — 의미적으로 일치하지만 중복으로 인한 drift 위험. (3) `post_close_ml_maintenance`가 **dashboard build를 두 번 한다**(intra-mode 후 + state 파일 쓰기 후) — 의도된 순서이고 정확.

## 위험한 가정

### 1. `max_rows=250000` 기본 제한이 LightGBM/Challenger 모든 호출에 일관 적용되는지 가정

코드 확인 결과 — 부분적으로만 일관됩니다.

- `train_lightgbm_from_sqlite` (research.py 4618행): default `LIGHTGBM_DEFAULT_MAX_FEATURE_ROWS=250_000`. CLI에서 `max_rows`를 명시하지 않으면 제한 적용.
- `run_model_challenger_review_from_sqlite` (5142행): 같은 default.
- 다만 **`_load_labeled_feature_dataset`를 직접 호출하는 다른 경로**(4523, 4798, 4914행)는 `max_rows=None` default → 전체 행 로드. 호출 컨텍스트 따라:
  - 4523행: `train_centroid_baseline_from_sqlite`. centroid 모델은 경량이라 OOM 위험 작음.
  - 4798행: 다른 학습/평가 경로 (정확한 caller는 함수 시그니처로 추가 확인 필요).
  - 4914행: 같은 패턴.
- 즉 **CLI `--train-lightgbm`과 `--run-challengers`만 250k 제한, 다른 내부 호출은 무제한**. quick-live-train 경로는 CLI를 사용하므로 의도대로 보호됨.

위험: 누군가 `_load_labeled_feature_dataset`를 직접 호출하는 새 경로를 만들고 default `max_rows=None`을 두면 silent하게 전체 로드 → OOM 회귀. **이건 default를 `None`에서 `LIGHTGBM_DEFAULT_MAX_FEATURE_ROWS`로 바꾸는 게 fail-safe 측**이지만 centroid/baseline 학습이 영향을 받을 수 있어 일률 변경은 위험. 적어도 docstring 또는 모듈 코멘트로 "`max_rows` 명시 안 하면 무제한 로드 → OOM 위험" 경고 권장.

### 2. `ORDER BY event_time DESC LIMIT 250000` → ascending 재정렬이 split 의미를 깨지 않는다고 가정

확인 결과 — 의도된 동작이 맞고 깨지지 않습니다. 다만 미세 위험.

- sqlite_store.py 1804~1805행: `max_rows` 있으면 `DESC LIMIT` 후 정렬 없이 반환.
- research.py 480행: `dataset.sort(key=lambda item: (str(item["event_time"]), str(item["symbol"])))` ascending 재정렬.
- 결과: **최근 250k row가 시간순 정렬된 상태로 split에 들어감**. 250k row 안에서 head 90% = development, tail 10% = challenger holdout.

위험: 250k 경계가 **거래일 중간에서 끊긴다.** 예: 250k번째 row가 어느 거래일 12:34라면 250,001번째(=12:33) 이전 같은 거래일 데이터가 부분적으로 제외됨. challenger holdout의 첫 거래일에 일부 row만 들어와 회계 일관성이 미세하게 깨질 수 있음. 다만 walk-forward gate 평가는 전체 250k 안에서만 보므로 큰 회귀는 아님.

권장: `fetch_feature_rows`에서 250k 경계를 **거래일 경계로 정렬**(예: 250k에서 가까운 가장 빠른 거래일 시작으로 맞춤). 우선순위 낮음.

### 3. quick-live-train 시간 상한 10분이 14GB DB에서 항상 유지된다고 가정

state 파일에 `time_cap_target_minutes: 10`(550행)이 기록되지만 코드에는 실제 timeout이 없습니다. 250k row 제한 + 8개 task로 일반적으로 10분 안에 끝나지만 실측 보장이 없습니다.

위험: 어느 task가 예상보다 오래 걸리면 quick maintenance가 30분 이상 차지할 수 있고, 그동안 다음 거래일 pre-open warmup 또는 사용자 작업과 충돌. work_ver_5-1의 storage_migration_apply는 service stop check가 있지만 quick-live-train에는 없음. 운영자가 watchdog 자동 트리거로 quick maintenance를 매일 실행한다면 timeout 또는 process kill 정책이 필요.

**권장 보강**: `post_close_ml_maintenance` quick 모드에 wall-clock timeout(예: 20분) 또는 task별 timeout(`timeout 600 run_app --train-lightgbm`). 우선순위 중간.

### 4. dashboard `_build_walk_forward_setup_status`가 `_build_walk_forward_gate`와 영원히 같은 임계치를 유지한다고 가정

코드 확인 — 현재는 일치하지만 두 곳에서 같은 magic number를 따로 정의합니다.

- research.py 1354~1361행: `min_train_rows<1000`, `test_window_rows<100`, `max_train_rows<1000`, `folds>5000`
- dashboard.py 2241~2248행: 같은 4개 임계치를 별도 if문으로 반복.

위험: 한쪽 임계치를 바꾸면 다른 쪽이 따라가지 않아 dashboard 표시와 실제 gate 판단이 어긋남. 운영자가 dashboard "setup OK"를 보고 안심했는데 실제 gate는 review_required 가능. 또는 반대.

**권장 보강**: 두 함수가 공유하는 단일 함수 또는 상수 모듈로 분리. 예: `app/services/walk_forward_gate.py`에 `evaluate_walk_forward_gate(payload) -> {setup_status, gate_status, ...}` 두고 양쪽이 import. 우선순위 높음(silent drift 위험).

### 5. state→dashboard build 순서가 dashboard payload에 정확히 반영된다고 가정

확인 — 의도된 순서이고 정확합니다.

- `post_close_ml_maintenance` quick 분기 (467~487행): intra-mode에서 `build-dashboard` 한 번 (487행).
- state 파일 쓰기 (517~557행).
- 무조건 `build-dashboard` 한 번 더 (558행).

이 두 번째 build가 state 파일을 읽어 카드에 반영. `dashboard.py` 1880행이 `_safe_load_json`으로 `latest-post-close-ml.json`을 읽고 1888/1999/2120행에 payload로 노출. 정확한 순서.

`post_close_label_refresh` (646~647행): `write_label_refresh_state "ok"` 후 `run_label_app_step --build-dashboard`. 같은 순서 — 정확.

위험: 첫 번째 dashboard build와 두 번째 사이에 state 파일 쓰기가 실패하면 두 번째 build가 stale state 또는 missing state를 보여줌. EXIT trap이 `failed` state를 쓰지만 EXIT 전에 두 번째 build가 실행되지 않을 가능성. 다만 `trap '...if [[ $code -ne 0 ]]; then write_label_refresh_state "failed"' EXIT`(639행)가 label refresh에는 있고 ml maintenance에는 없음. ml maintenance는 quick 분기 안에서 task 실패 시 state 파일이 미작성될 수 있음.

**권장 보강**: `post_close_ml_maintenance`에도 EXIT trap으로 실패 시 `failed` state 기록. 우선순위 중간.

## 보강 필요 테스트

1. **`fetch_feature_rows`의 `max_rows=250000` 동작 회귀 테스트** — `tests/test_sqlite_store.py`에 250k 초과 row 케이스 fixture 어렵지만, 100 row 가짜 DB에서 `max_rows=50`으로 호출하면 최근 50개가 DESC로 반환되는지 검증 + `_load_labeled_feature_dataset`의 ascending 재정렬까지 함께 검증. silent regression 차단.

2. **`train_lightgbm_from_sqlite(max_rows=None)` 호출 시 무제한 로드 차단 가드 또는 경고** — 운영자가 실수로 None을 명시하면 14GB OOM 위험. 테스트로는 max_rows=None일 때 명시적 warning 또는 ConfirmationError 발생을 검증할 수 있음. 코드 변경 동반.

3. **`_build_walk_forward_gate` vs `_build_walk_forward_setup_status` 동등성 테스트** — 같은 fixture payload를 양쪽에 넣고 setup_status/gate_status가 일치하는지 검증. silent drift 차단의 핵심 테스트.

4. **`post_close_ml_maintenance` state 파일 EXIT trap** — quick 모드 중 `--train-lightgbm` 실패 시 state가 `failed`로 기록되는지 검증. `tests/test_post_close_maintenance_script.py`에 fail injection 시나리오 추가.

5. **state→dashboard build 순서 검증** — `post_close_ml_maintenance` 호출 후 `latest-post-close-ml.json`이 존재하고 `latest-dashboard.json`이 그 state 파일의 `completed_at`보다 늦은 시각으로 생성되는지 확인. 시간 순서 invariant 잠금.

6. **`fetch_feature_rows`의 250k 경계 거래일 정합성** (우선순위 낮음) — 250k 경계가 같은 거래일을 부분적으로 자르지 않는지 검증. 현재 코드는 그렇게 잘리는데, 의도된 동작이면 docstring으로 명시. 의도 외라면 거래일 정렬 수정.

## 문서 보강 필요

1. **`docs/Current-Implementation.md`** — quick-live-train 모드의 8개 task와 250k row 제한, 14GB OOM 회피 의도를 명시. legacy quick-live-report와의 차이도 적시.

2. **`docs/Production-Architecture.md` 또는 `docs/Realtime-Operations.md`** — 장후 ML 유지보수의 두 트랙(quick vs heavy-snapshot) 비교 표 갱신. quick은 현재 quick-live-train으로 바뀌었고 8개 task가 어떤 순서로 실행되는지.

3. **`LIGHTGBM_DEFAULT_MAX_FEATURE_ROWS` 모듈 docstring** — 250k 값이 왜 선택됐는지(14GB OOM 사례), 전체 이력 학습은 `--max-rows 0` 또는 `--no-max-rows` 같은 명시 옵션으로만 허용된다는 점, 향후 watchlist 확장 시 재검토 기준.

4. **`_build_walk_forward_setup_status` 또는 `_build_walk_forward_gate` 두 함수의 동기화 의무** — "이 임계치를 바꾸면 다른 함수도 같은 값으로 바꿔야 한다"는 코멘트. 또는 위 보강 테스트 3번이 자동 잠금.

5. **dashboard `장후 ML 유지보수 상태` 카드 note** — 이미 명시되어 있음("quick-live-train은 ... legacy quick-live-report는 학습/평가 row를 만들지 않습니다"). cowork 평가: **충분히 명확**. 운영자가 두 모드의 차이를 오해할 위험 낮음. 다만 운영자가 legacy mode가 무엇이고 언제 발생하는지 잘 모를 수 있어 한 줄 추가 권장 — "오래된 상태 파일(`mode=quick-live-report`)이면 학습/평가 row가 없는 진단만 수행된 결과".

6. **`docs/logbook.md`** — 이번 변경 entry(250k 제한 도입, quick-live-train 전환, dashboard gate 분리 표시).

## 다른 thread와의 충돌 가능성

### 가능성 A: `app/services/dashboard.py` 동시 수정 충돌

실전 운영 준비 thread(production-architecture-implementation-blueprint)도 dashboard.py에 카드를 계속 추가 중:
- review_ver_10/11에서 live_fill_consistency, live_order_attention, live alerting, freshness 카드 추가.
- 이번 thread가 장후 ML 유지보수 카드, gate 분리 표시 추가.

**충돌 위험 정도**: 중간. 다른 탭(ml-current vs status, live-broker, alerts)에 카드가 들어가면 큰 git merge 충돌은 없음. 다만 양 thread가 `collect_dashboard_payload` 함수의 새 key 추가, `_stack_cards` 순서 변경, `status_alerts` 리스트 추가 시 충돌 가능. **권장**: 양 thread가 새 dashboard payload key를 추가할 때 README 또는 dashboard.py 모듈 docstring에 "payload schema에 새 key 추가 시 다른 thread와 조율" 코멘트.

### 가능성 B: `reporting.py` build_runtime_report 출력 schema 동시 수정

`build_runtime_report`는 양 thread가 모두 출력 항목을 추가하는 영역:
- 실전 thread: `live_fill_mismatches`, `live_order_attention`, `live_open_orders` 항목 추가 (review_ver_10).
- 이번 thread: `quick-live-train` 결과 (build-runtime-report가 task 안에 들어 있어 자동으로 영향).

**충돌 위험 정도**: 낮음. 양 thread가 같은 dict의 다른 key를 추가하면 merge 가능. 다만 같은 key를 다른 의미로 쓰면 silent conflict.

### 가능성 C: state 파일 경로/형식 패턴 충돌

양 thread가 모두 `runtime-data/reports/.../state/latest-*.json` 패턴 사용:
- 이번 thread: `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`, `latest-post-close-label-refresh.json`
- 실전 thread: `runtime-data/reports/recovery/latest-local-setup-check.json`, `runtime-data/reports/live-risk/kill-switch.json`, `runtime-data/reports/live-readiness/latest-readiness.json`

**충돌 위험 정도**: 매우 낮음. 디렉토리가 분리되어 있고 NAS 백업 포함 정책도 양 thread 모두 동의(state는 백업 포함). 다만 dashboard가 state 파일 갱신 시점을 어떻게 표시할지(`generated_at` vs `completed_at` 명명)가 thread별로 다르면 운영자가 헷갈릴 수 있음. **권장**: state 파일의 timestamp 필드 명명 통일 — 두 thread 합의가 필요한 작은 결정.

### 가능성 D: `--build-dashboard` 호출 빈도 충돌

이번 thread가 quick-live-train에서 `--build-dashboard`를 **두 번** 호출(487행 + 558행). 실전 thread도 alert outbox, kill switch state 변경 후 dashboard 갱신을 요구할 수 있음. 양 thread가 모두 자주 호출하면:
- 단일 거래일에 dashboard build가 10회 이상 발생 가능.
- 6.5GB DB에서 build가 30초~몇 분 걸리므로 누적 부담.

**충돌 위험 정도**: 중간. **권장**: dashboard build에 throttle(예: 마지막 build로부터 60초 이내면 skip + 캐시 반환) 정책. 또는 state 변경 시 dashboard build 요청만 큐에 넣고 별도 background worker가 실행. 우선순위 중간.

## 종합

| 영역 | 평가 | 핵심 보강 |
|---|---|---|
| LightGBM/Challenger max_rows=250k 기본 제한 | 운영 안정성 충분 | `_load_labeled_feature_dataset` 다른 caller 가드 + 250k 경계 거래일 정합성 |
| quick-live-train 전환 | 범위 적절 | wall-clock timeout + EXIT trap state 기록 |
| state→dashboard build 순서 | 정확 | 시간 순서 invariant 테스트 |
| 장후 ML 유지보수 카드 표시 | 충분히 명확 | legacy quick-live-report 의미 한 줄 추가 |
| walk-forward setup/gate 분리 표시 | 의미상 일치 | **research.py와 dashboard.py 임계치 단일 함수로 분리(silent drift 위험)** |
| 다른 thread와 충돌 가능성 | A/D 중간, B/C 낮음 | dashboard payload schema 조율 + build 빈도 throttle |

## 다음 단계 권장 (운영 안정성 관점)

1. **최우선**: `_build_walk_forward_gate`와 `_build_walk_forward_setup_status`의 임계치를 단일 함수로 통합 + 동등성 테스트 추가. silent drift가 가장 위험.
2. **중요**: `_load_labeled_feature_dataset` default `max_rows=None`인 다른 caller에 docstring 경고 또는 fail-safe default.
3. **권장**: quick-live-train 모드에 EXIT trap으로 failed state 기록 + wall-clock timeout.
4. **권장**: dashboard build throttle 정책(60초 cooldown).
5. **문서**: 250k 임계치의 선택 근거(14GB OOM 사례)와 전체 이력 학습 명시 옵션 사용법을 `docs/Current-Implementation.md`에 추가.
6. **thread 조율**: dashboard.py payload schema 추가 시 양 thread가 조율하는 한 줄 컨벤션(주석 또는 README).

## 운영자 결정 필요 없음

이번 검토에서 운영자(계좌 소유자/실전 운용 승인권자) 판단이 필요한 새 항목은 없습니다. 모든 보강 항목이 코드/문서/테스트 작업이고 운영 정책 변경 없음. 실전 운영 준비 thread의 잔여 결정(Phase 2 한도, system clock, NAS drill)은 별도로 진행.
