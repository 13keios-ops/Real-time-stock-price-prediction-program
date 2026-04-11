# Versioning

## Current Rule

This repository now uses `VERSION` in the repo root as the release-ready trigger.

- current version: `0.2.0`
- branch: `main`
- watcher config: `autopush.json`
- trigger: `version-change`

## Recommended Workflow

1. Finish code and docs changes.
2. Run tests.
3. Update `VERSION` last.
4. Commit locally if you want an explicit checkpoint.
5. Let the git watcher detect the new version and push the existing release commit.

## Commands

Update the version:

```powershell
.\scripts\bump_version.ps1 -Version 0.2.1
```

Manual commit example:

```powershell
git add -A
git commit -m "chore(release): v0.2.1"
```

## Notes

- `autopush.json` is now enabled for this repository.
- The watcher monitors `VERSION`.
- If `HEAD` already contains the target version, the watcher can push that existing commit without creating another auto-commit.
