# Git Auto Push Manager

## 1. Goal

This document defines a safe way to monitor multiple local Git repositories under one root folder and automatically run `git commit` and `git push` when a repository's version changes.

Recommended target layout:

```text
J:\GitHub\
  Project-A\
    .git\
    VERSION
    autopush.json
  Project-B\
    .git\
    VERSION
    autopush.json
  Project-C\
    .git\
```

One watcher script checks the root folder, finds opt-in repositories, and only acts on repositories that explicitly contain `autopush.json`.

## 2. Important Boundary

GitHub itself cannot watch your local folder directly.

The actual flow is:

1. A PowerShell script runs on your PC.
2. The script scans local repositories.
3. If it detects a valid version change in an opted-in repository, it runs `git commit` and `git push`.
4. GitHub receives the pushed commit normally.

## 3. Recommended Safety Model

Do not auto-push every file change in every repository.

Recommended rule:

- one watcher script for all repositories
- one `autopush.json` per repository
- default opt-in is `off`
- trigger only on `VERSION` file change
- only run on the configured branch

This avoids pushing half-finished work from unrelated projects.

## 4. Files Added In This Repository

- `scripts/watch_git_versions_and_push.ps1`
- `config/autopush.project.schema.json`
- `config/autopush.project.example.json`
- `scripts/bootstrap_git_autopush_targets.ps1`
- `scripts/install_git_autopush_startup_launcher.ps1`
- `scripts/remove_git_autopush_startup_launcher.ps1`
- `scripts/audit_git_autopush_targets.ps1`
- `scripts/set_git_autopush_enabled.ps1`

The watcher keeps its own state and logs under `runtime-data/autopush/`.

To place starter `VERSION` and `autopush.json` files across repositories under one root:

```powershell
.\scripts\bootstrap_git_autopush_targets.ps1 -ScanRoot 'J:\GitHub'
```

Bootstrap defaults:

- `enabled = true` only when the repository is on `main`, has an `origin`, and is currently clean
- dirty or non-`main` repositories get a prepared config with `enabled = false`
- missing `VERSION` files are initialized to `0.1.0`

To audit which repositories are currently safe to enable:

```powershell
.\scripts\audit_git_autopush_targets.ps1 -ScanRoot 'J:\GitHub'
```

To flip one repository after it becomes safe:

```powershell
.\scripts\set_git_autopush_enabled.ps1 -RepoPath 'J:\GitHub\Instargram Card News' -Enable
```

The enable script refuses dirty or non-`main` repositories unless you explicitly opt into overrides.

## 4.1 How Version Detection Works In Practice

For an opted-in repository, the watcher does not guess release timing from arbitrary file changes.

It checks:

- `autopush.json` exists
- `enabled` is `true`
- current branch matches the configured branch
- `VERSION` exists
- current `VERSION` differs from the last pushed version stored in `runtime-data/autopush/git-autopush-state.json`

Only then does it move on to stage, commit, and push logic.

## 5. Per-Repository Config

Each repository that should be auto-managed needs a file named `autopush.json` in the repository root.

Example:

```json
{
  "enabled": true,
  "branch": "main",
  "remote": "origin",
  "trigger": "version-change",
  "version_file": "VERSION",
  "stage_mode": "all",
  "commit_message": "chore(release): v{version}",
  "commit_body_mode": "staged-summary",
  "commit_body_header": "Auto-generated change summary",
  "push_tag": false,
  "tag_name": "v{version}"
}
```

Field meaning:

- `enabled`: repository opt-in switch
- `branch`: only push when the current branch matches this value
- `remote`: usually `origin`
- `trigger`: currently only `version-change`
- `version_file`: usually `VERSION`
- `stage_mode`:
  - `all`: `git add -A`
  - `tracked`: `git add -u`
  - `version-only`: only stage the version file
- `commit_message`: supports `{version}`, `{repo}`, `{branch}`
- `commit_body_mode`:
  - `staged-summary`: auto-generates the commit description from staged file changes and diffstat
  - `none`: commit only the first-line summary
- `commit_body_header`: supports `{version}`, `{repo}`, `{branch}`
- `push_tag`: when `true`, also create and push a tag
- `tag_name`: supports `{version}`, `{repo}`, `{branch}`

## 6. Recommended Workflow

The safest routine is:

1. Finish the code and document changes in the target repository.
2. Change the `VERSION` file last.
3. Let the watcher detect the version change.
4. The watcher commits and pushes automatically.

With `stage_mode = all`, the version bump is the "release-ready" signal.
With `commit_body_mode = staged-summary`, the commit summary line stays version-focused and the description body is filled automatically from the staged diff.

## 7. Watcher Behavior

For each opted-in repository, the watcher:

1. checks `.git` and `autopush.json`
2. validates the current branch
3. reads the configured version file
4. compares the version with the last successfully pushed version
5. if the version changed:
   - stages changes
   - commits with the configured message
   - pushes to the configured remote/branch
   - optionally creates and pushes a tag

If the version did not change, the repository is skipped.

Safety refinements in the current script:

- if the configured branch is behind the remote branch, the repository is skipped to avoid creating an auto-commit on top of stale history
- if `HEAD` already contains the target `VERSION`, the watcher pushes the existing commit instead of sweeping unrelated dirty files into a new commit
- if Git is in the middle of merge/rebase/cherry-pick style operations, the repository is skipped
- the watcher resolves `git.exe` from PATH first and then falls back to GitHub Desktop's bundled Git
- when enabled, the auto-created commit description is built from staged change status lines plus `git diff --cached --stat`

## 8. Run Once Or Continuous Mode

Run one scan:

```powershell
.\scripts\watch_git_versions_and_push.ps1 -ScanRoot 'J:\GitHub' -Once
```

Run continuously:

```powershell
.\scripts\watch_git_versions_and_push.ps1 -ScanRoot 'J:\GitHub' -PollSeconds 60
```

Optional recursive scan:

```powershell
.\scripts\watch_git_versions_and_push.ps1 -ScanRoot 'J:\GitHub' -PollSeconds 60 -Recurse
```

## 9. Start At Windows Logon

If you want the watcher to start automatically when Windows logs in:

```powershell
.\scripts\register_git_autopush_task.ps1 -ScanRoot 'J:\GitHub' -PollSeconds 60
```

Recursive scan example:

```powershell
.\scripts\register_git_autopush_task.ps1 -ScanRoot 'J:\GitHub' -PollSeconds 60 -Recurse
```

This creates a Windows Scheduled Task named `GitAutoPushWatcher`.

Manual task control scripts:

```powershell
.\scripts\get_git_autopush_watcher_status.ps1
.\scripts\start_git_autopush_watcher.ps1 -EnsureRegistered
.\scripts\stop_git_autopush_watcher.ps1
```

These scripts are useful for direct operations and for Codex automations that should check health or restart the watcher.

If `Register-ScheduledTask` returns `Access is denied`, use the Startup-folder launcher instead:

```powershell
.\scripts\install_git_autopush_startup_launcher.ps1 -ScanRoot 'J:\GitHub' -PollSeconds 60
```

Remove it later with:

```powershell
.\scripts\remove_git_autopush_startup_launcher.ps1
```

This avoids Task Scheduler permission issues and still starts the watcher at Windows logon for the current user.

## 10. State And Logs

Default files:

- `runtime-data/autopush/git-autopush.log`
- `runtime-data/autopush/git-autopush-state.json`

The state file prevents the same version from being pushed repeatedly.

## 10.1 Smoke Test

The repository also includes an integration-style test script:

```powershell
.\scripts\test_git_autopush_watcher.ps1
```

The test creates temporary repositories under `.tmp-tests/`, validates:

- one watcher scanning one root with multiple repositories
- `autopush.json` opt-in behavior
- automatic commit/push on `VERSION` change
- automatic commit description generation from staged changes
- safe push of an already committed release without auto-committing unrelated untracked files

## 11. Recommended Usage Policy

Recommended:

- use this only for repositories that deliberately opt in
- bump `VERSION` only when the repository is really ready
- keep `branch` fixed to `main` or another release branch

Not recommended:

- enabling every repository under `J:\GitHub`
- using `stage_mode = all` if you frequently change `VERSION` early
- auto-pushing repositories with secrets, generated files, or unstable working trees

## 12. Best Default

For most projects, the best starting point is:

```json
{
  "enabled": true,
  "branch": "main",
  "remote": "origin",
  "trigger": "version-change",
  "version_file": "VERSION",
  "stage_mode": "all",
  "commit_message": "chore(release): v{version}",
  "commit_body_mode": "staged-summary",
  "commit_body_header": "Auto-generated change summary",
  "push_tag": false,
  "tag_name": "v{version}"
}
```

That gives:

- one watcher for all projects
- repository-by-repository opt-in
- explicit version-based release signal
- automatic commit and push without manual repetition
