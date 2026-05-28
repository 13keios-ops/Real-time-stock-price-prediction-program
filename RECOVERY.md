# GitHub + NAS Recovery

## Goal

Use GitHub and NAS together so the repository can be restored quickly after drive damage, OS reinstall, or other local recovery work.

- GitHub: committed history, branches, and remote state
- NAS: point-in-time working-tree backup plus restore metadata

## Backup Policy

1. NAS 백업은 `재난 복구용 전체 백업`과 `실전 전환 검증용 sanitized recovery export`를 구분한다.
2. 재난 복구용 전체 백업은 이전 저장소 유실 사고 대응을 위한 이중 보관이다. 접근 권한이 제한된 NAS 안에서 전체 작업 트리와 로컬 복구 자산을 보존할 수 있으며, cowork 전달이나 실전 전환 readiness 증거로 직접 쓰지 않는다.
3. 실전 전환 검증용 sanitized recovery export는 root `.env*`, KIS 토큰 캐시, runtime 로그, private key 계열 파일을 제외한다. 이 기준은 `tests/test_wsl_ops.py`와 저장소 export wrapper의 포함/제외 self-test가 잠근다.
4. 정기 백업 명령은 주 1회 기준으로 제공하고, 최신 3개 package를 보관한다.
5. NAS 백업은 용량과 소요 시간이 크므로 Codex가 자율 실행하지 않는다.
6. 주간/강제 NAS 백업은 사용자가 해당 작업에서 명시적으로 지시했을 때만 실행한다.

## Recommended NAS Path

- 공유 루트: `\\192.168.0.2\backup`
- 저장소 경로: `repos/real-time-stock-price-prediction-program/recovery-exports`
- 전체 경로: `\\192.168.0.2\backup\repos\real-time-stock-price-prediction-program\recovery-exports`
- 실전 전환 drill 권장 경로: `repos/real-time-stock-price-prediction-program/recovery-drills/phase1-readonly`

## Package Contents

- `repository.bundle`: Git 이력과 참조
- `repo-snapshot/`: 백업 시점의 작업 트리 스냅샷. sanitized recovery export에서는 비밀값과 머신 로컬 토큰/로그를 제외한다. 재난 복구용 전체 백업은 별도 접근통제 전제로 전체 복구성을 우선한다.
- `git-status.txt`: 백업 시점의 브랜치와 작업 트리 상태
- `git-remote.txt`: 백업 시점의 원격 저장소 주소
- `git-head.txt`: 백업 시점의 HEAD 커밋
- `metadata.json`: 백업 방식, 보관 정책, 삭제 이력

## Main Commands

Weekly backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_weekly_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup"
```

Forced backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_forced_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup" -Reason "before-release"
```

WSL mounted-share backup:

```bash
./scripts/run_weekly_nas_backup.sh --backup-share-root /mnt/backup
./scripts/run_forced_nas_backup.sh --backup-share-root /mnt/backup --backup-reason "before-release"
```

## Restore Order

1. GitHub 또는 `repository.bundle` 에서 저장소를 복구한다.
2. 백업 시점의 작업 트리 상태가 필요하면 `repo-snapshot/` 을 덮어쓴다.
3. sanitized recovery export로 복구한 경우 비밀정보, KIS 토큰 캐시, runtime 로그, watcher 자산, 로컬 Codex 상태는 별도 복구 경로로 되살린다. 재난 복구용 전체 백업을 사용할 때도 복구 직후 권한과 최신성은 다시 확인한다.
4. 무인 작업을 재개하기 전에 `scripts/check_local_setup.sh` 를 실행한다.
5. root `.env` 가 없으면 보이는 bash 창에서 `scripts/restore_kis_env_interactive.sh` 를 실행해 먼저 `paper` KIS app key/secret 을 입력하고 안전하게 저장한다.
6. 계좌 항목도 나중에 필요하면 `scripts/restore_kis_env_interactive.sh -IncludeAccountFields` 를 다시 실행한다.

## Local Recovery Check

이 점검은 아래 파일을 쓴다.

- `runtime-data/reports/recovery/latest-local-setup-check.json`
- `runtime-data/reports/recovery/latest-local-setup-check.md`

확인 항목은 아래와 같다.

- root `.env` 존재 여부
- Python 실행 파일 탐지
- `websockets`, `lightgbm` 모듈 사용 가능 여부
- dashboard / live runtime / watchdog 상태
- 현재 저장소 root 기준 runtime startup launcher 경로 유효성
- NAS 복구 루트 접근 가능 여부

## Repository Note

- 저장소 이름: `Real-time-stock-price-prediction-program`
- NAS 폴더 이름: `real-time-stock-price-prediction-program`
- 이 파일은 `scripts/` 아래 백업 스크립트와 함께 유지한다.
