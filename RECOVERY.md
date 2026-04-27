# GitHub + NAS Recovery

## Goal

Use GitHub and NAS together so the repository can be restored quickly after drive damage, OS reinstall, or other local recovery work.

- GitHub: committed history, branches, and remote state
- NAS: point-in-time full working-tree backup plus restore metadata

## Backup Policy

1. Use full backups for faster recovery.
2. Keep only the latest 3 backup packages.
3. Run the regular backup once per week.
4. Run a forced backup before releases, large changes, or risky machine work.

## Recommended NAS Path

- Share root: \\192.168.0.2\backup
- Repository path: repos/real-time-stock-price-prediction-program/recovery-exports
- Full path: \\192.168.0.2\backup\repos\real-time-stock-price-prediction-program\recovery-exports

## Package Contents

- repository.bundle: Git history and refs
- repo-snapshot/: full working-tree snapshot at backup time
- git-status.txt: branch and worktree state at backup time
- git-remote.txt: origin URL at backup time
- git-head.txt: HEAD commit at backup time
- metadata.json: backup mode, retention, and prune history

## Main Commands

Weekly backup:

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_weekly_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup"
`

Forced backup:

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_forced_nas_backup.ps1 -BackupShareRoot "\\192.168.0.2\backup" -Reason "before-release"
`

Local recovery check:

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1
`

## Restore Order

1. Restore the repository from GitHub or repository.bundle.
2. Overlay repo-snapshot/ if you need the exported working-tree state.
3. Restore secrets, watcher assets, and local Codex state through their separate recovery path.
4. Run `scripts/check_local_setup.ps1` before resuming unattended work.

## Local Recovery Check

This check writes:

- `runtime-data/reports/recovery/latest-local-setup-check.json`
- `runtime-data/reports/recovery/latest-local-setup-check.md`

It verifies:

- root `.env` presence
- Python executable detection
- `websockets` and `lightgbm` module availability
- dashboard / live runtime / watchdog status
- NAS recovery-root reachability

## Repository Note

- Repository name: Real-time-stock-price-prediction-program
- NAS folder slug: real-time-stock-price-prediction-program
- Keep this file aligned with the backup scripts under scripts/.
