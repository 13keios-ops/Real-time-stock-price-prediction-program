# Codex work_ver_12-3: NAS recovery self-test status

작성: Codex
기준 리뷰: `2026-05-18-production-architecture-implementation-blueprint-review_ver_11.md`
상태: 2026-05-19 장후 `post-close`, 실제 NAS 접근 없음

## 1. 작업 요약

review_ver_11의 P0 권장 항목 중 NAS recovery drill 결과 확인을 진행했다. 실제 NAS 공유에 쓰는 백업은 실행하지 않았다. 저장소 내부 self-test와 기존 runtime report 존재 여부만 확인했다.

## 2. 확인 결과

| 항목 | 결과 |
|---|---|
| recovery export 포함 self-test | `tests.test_wsl_ops` 통과. `runtime-data/reports/alerts/`, `runtime-data/reports/live-risk/`, `runtime-data/reports/live-approvals/`, `runtime-data/ops/`, `runtime-data/ml/registry-backups/` 포함을 검증한다. |
| 비밀값 제외 self-test | `tests.test_wsl_ops` 통과. root `.env`, `runtime-data/cache/kis`, `runtime-data/logs`, `*.pem`, `*.key`, `id_rsa*` 제외를 검증한다. |
| 기존 NAS/recovery runtime report | `runtime-data/reports` 아래에서 기존 `backup`/`recovery`/`nas` report 파일은 확인되지 않았다. |
| 실제 NAS 공유 접근 | 미실행. 대용량 백업/외부 공유 쓰기는 하지 않았다. |
| recovery export dry-run | WSL sandbox approval timeout으로 실행 완료 확인을 하지 못했다. repository 문제로 단정하지 않고 `not_verified`로 남긴다. |

## 3. 검증

실행 완료:

```bash
python -m unittest tests.test_wsl_ops
```

결과:

- 11개 테스트 통과.

실행하지 못한 명령:

```bash
./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run
```

사유:

- WSL sandbox approval review timeout.

## 4. 판단

현재 상태는 `self-test passed / actual drill not verified`다. Phase 1 진입 전에는 최소 1회 실제 dry-run 또는 로컬 export drill이 필요하다. 실제 NAS 공유에 쓰는 강제 백업은 운영자 승인 후 별도 창에서 실행하는 편이 안전하다.

## 5. 다음 단계 권장

🟢 다음 단계 권장:

- 장외 시간에 `./scripts/export_recovery_snapshot.sh --dry-run --destination-root .tmp-tests/recovery-dry-run --package-prefix codex-recovery-dry-run`을 한 번 완료 확인한다.
- 그 다음 실제 NAS 공유가 mount된 상태에서 `./scripts/run_forced_nas_backup.sh --backup-share-root /mnt/backup --backup-reason "before-phase1-readonly"`를 운영자 승인 후 실행한다.
- 생성된 package 목록에서 비밀값 제외와 live 운영 경로 포함을 수동 표본 확인한다.

🔴 운영자 판단 필요:

- 실제 NAS 공유 쓰기 백업 실행 시점과 승인 여부.
