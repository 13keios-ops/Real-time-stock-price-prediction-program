# GitHub + NAS 복구

## 목표

드라이브 고장, 운영체제 재설치, 로컬 복구 작업이 필요할 때 GitHub와 NAS를 함께 사용해 저장소를 빠르게 복구한다.

- GitHub: 커밋 이력, 브랜치, 원격 저장소 상태를 보관한다.
- NAS: 특정 시점의 전체 작업 트리 백업과 복구 메타데이터를 보관한다.

## 백업 정책

1. 빠른 복구를 위해 전체 백업을 사용한다.
2. 최신 백업 패키지 3개만 보관한다.
3. 정기 백업은 주 1회 실행한다.
4. 릴리스, 큰 변경, 위험한 장비 작업 전에는 강제 백업을 실행한다.

## 권장 NAS 경로

- 공유 루트: `\\192.168.0.2\backup`
- 저장소 경로: `repos/real-time-stock-price-prediction-program/recovery-exports`
- 전체 경로: `\\192.168.0.2\backup\repos\real-time-stock-price-prediction-program\recovery-exports`

## 백업 패키지 구성

- `repository.bundle`: Git 이력과 참조
- `repo-snapshot/`: 백업 시점의 전체 작업 트리 스냅샷
- `git-status.txt`: 백업 시점의 브랜치와 작업 트리 상태
- `git-remote.txt`: 백업 시점의 원격 저장소 주소
- `git-head.txt`: 백업 시점의 HEAD 커밋
- `metadata.json`: 백업 방식, 보관 정책, 삭제 이력

## 주요 명령

주간 백업:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_weekly_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup"
```

강제 백업:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_forced_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup" -Reason "before-release"
```

로컬 복구 점검:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1
```

## 복구 순서

1. GitHub 또는 `repository.bundle` 에서 저장소를 복구한다.
2. 백업 시점의 작업 트리 상태가 필요하면 `repo-snapshot/` 을 덮어쓴다.
3. 비밀정보, watcher 자산, 로컬 Codex 상태는 별도 복구 경로로 되살린다.
4. 무인 작업을 재개하기 전에 `scripts/check_local_setup.ps1` 를 실행한다.
5. root `.env` 가 없으면 보이는 PowerShell 창에서 `scripts/restore_kis_env_interactive.ps1` 를 실행해 먼저 `paper` KIS app key/secret 을 입력하고 안전하게 저장한다.
6. 계좌 항목도 나중에 필요하면 `scripts/restore_kis_env_interactive.ps1 -IncludeAccountFields` 를 다시 실행한다.

## 로컬 복구 점검

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

## 저장소 메모

- 저장소 이름: `Real-time-stock-price-prediction-program`
- NAS 폴더 이름: `real-time-stock-price-prediction-program`
- 이 파일은 `scripts/` 아래 백업 스크립트와 함께 유지한다.
