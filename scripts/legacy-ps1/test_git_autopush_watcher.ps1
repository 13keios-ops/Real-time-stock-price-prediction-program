param(
    [Parameter(Mandatory = $false)]
    [string]$TestRoot = ""
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$watcherPath = Join-Path $toolRoot "scripts\watch_git_versions_and_push.ps1"

if (-not $TestRoot) {
    $TestRoot = Join-Path $toolRoot ".tmp-tests\git-autopush"
}

function Resolve-GitExecutable {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCommand -and -not [string]::IsNullOrWhiteSpace($gitCommand.Source)) {
        return $gitCommand.Source
    }

    $desktopRoot = Join-Path $env:LOCALAPPDATA "GitHubDesktop"
    if (Test-Path -LiteralPath $desktopRoot) {
        $desktopGit = Get-ChildItem -LiteralPath $desktopRoot -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "resources\app\git\cmd\git.exe" } |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1

        if ($desktopGit) {
            return $desktopGit
        }
    }

    throw "git executable not found in PATH or GitHub Desktop."
}

function Invoke-Git {
    param(
        [string]$RepoPath,
        [string[]]$Arguments
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $script:GitExecutable -C $RepoPath @Arguments 2>&1
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { "$_" }) -join [Environment]::NewLine

    if ($exitCode -ne 0) {
        throw "$script:GitExecutable -C $RepoPath $($Arguments -join ' ') failed`n$text"
    }

    return $text.Trim()
}

function Assert-Equal {
    param(
        [string]$Actual,
        [string]$Expected,
        [string]$Message
    )

    if ($Actual -ne $Expected) {
        throw "$Message`nExpected: $Expected`nActual:   $Actual"
    }
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Contains {
    param(
        [string]$Text,
        [string]$ExpectedSubstring,
        [string]$Message
    )

    if ($Text -notlike "*$ExpectedSubstring*") {
        throw "$Message`nExpected substring: $ExpectedSubstring`nActual text:`n$Text"
    }
}

function New-BareRemote {
    param([string]$Path)

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:GitExecutable init --bare $Path | Out-Null
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create bare repository at $Path"
    }
}

function Set-TextFile {
    param(
        [string]$Path,
        [string]$Content
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
}

function Initialize-Repository {
    param(
        [string]$RepoPath,
        [string]$RemotePath,
        [bool]$EnableAutopush
    )

    New-Item -ItemType Directory -Force -Path $RepoPath | Out-Null
    Invoke-Git -RepoPath $RepoPath -Arguments @("init", "-b", "main") | Out-Null
    Invoke-Git -RepoPath $RepoPath -Arguments @("config", "user.name", "Codex Test") | Out-Null
    Invoke-Git -RepoPath $RepoPath -Arguments @("config", "user.email", "codex-test@example.com") | Out-Null

    Set-TextFile -Path (Join-Path $RepoPath "README.md") -Content "# Test Repo"
    Set-TextFile -Path (Join-Path $RepoPath "VERSION") -Content "1.0.0"

    if ($EnableAutopush) {
        Set-TextFile -Path (Join-Path $RepoPath "autopush.json") -Content @'
{
  "enabled": true,
  "branch": "main",
  "remote": "origin",
  "trigger": "version-change",
  "version_file": "VERSION",
  "stage_mode": "all",
  "commit_message": "chore(release): v{version}",
  "push_tag": false,
  "tag_name": "v{version}"
}
'@
    }

    Invoke-Git -RepoPath $RepoPath -Arguments @("add", "-A") | Out-Null
    Invoke-Git -RepoPath $RepoPath -Arguments @("commit", "-m", "chore: initial state") | Out-Null
    Invoke-Git -RepoPath $RepoPath -Arguments @("remote", "add", "origin", $RemotePath) | Out-Null
    Invoke-Git -RepoPath $RepoPath -Arguments @("push", "-u", "origin", "main") | Out-Null
}

$script:GitExecutable = Resolve-GitExecutable

if (Test-Path -LiteralPath $TestRoot) {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force
}

$scanRoot = Join-Path $TestRoot "scan-root"
$remotesRoot = Join-Path $TestRoot "remotes"
$statePath = Join-Path $TestRoot "state\git-autopush-state.json"
$logPath = Join-Path $TestRoot "state\git-autopush.log"

$repoManaged = Join-Path $scanRoot "RepoManaged"
$repoOptOut = Join-Path $scanRoot "RepoOptOut"
$repoExistingHead = Join-Path $scanRoot "RepoExistingHead"

$remoteManaged = Join-Path $remotesRoot "RepoManaged.git"
$remoteOptOut = Join-Path $remotesRoot "RepoOptOut.git"
$remoteExistingHead = Join-Path $remotesRoot "RepoExistingHead.git"

New-BareRemote -Path $remoteManaged
New-BareRemote -Path $remoteOptOut
New-BareRemote -Path $remoteExistingHead

Initialize-Repository -RepoPath $repoManaged -RemotePath $remoteManaged -EnableAutopush:$true
Initialize-Repository -RepoPath $repoOptOut -RemotePath $remoteOptOut -EnableAutopush:$false
Initialize-Repository -RepoPath $repoExistingHead -RemotePath $remoteExistingHead -EnableAutopush:$true

Set-TextFile -Path (Join-Path $repoManaged "VERSION") -Content "1.0.1"
Set-TextFile -Path (Join-Path $repoManaged "release-notes.txt") -Content "Managed repo release payload"

Set-TextFile -Path (Join-Path $repoOptOut "VERSION") -Content "1.0.1"
Set-TextFile -Path (Join-Path $repoOptOut "release-notes.txt") -Content "This repo should stay untouched"

Set-TextFile -Path (Join-Path $repoExistingHead "VERSION") -Content "1.0.1"
Set-TextFile -Path (Join-Path $repoExistingHead "tracked-change.txt") -Content "Already committed before watcher"
Invoke-Git -RepoPath $repoExistingHead -Arguments @("add", "-A") | Out-Null
Invoke-Git -RepoPath $repoExistingHead -Arguments @("commit", "-m", "chore: prepare release 1.0.1") | Out-Null
Set-TextFile -Path (Join-Path $repoExistingHead "scratch.txt") -Content "Leave this untracked"

& $watcherPath -ScanRoot $scanRoot -Once -StatePath $statePath -LogPath $logPath -DisableTelegramNotifications

$managedVersionRemote = (& $script:GitExecutable --git-dir $remoteManaged show main:VERSION).Trim()
$optOutVersionRemote = (& $script:GitExecutable --git-dir $remoteOptOut show main:VERSION).Trim()
$existingHeadVersionRemote = (& $script:GitExecutable --git-dir $remoteExistingHead show main:VERSION).Trim()

Assert-Equal -Actual $managedVersionRemote -Expected "1.0.1" -Message "Managed repo VERSION should be pushed."
Assert-Equal -Actual $optOutVersionRemote -Expected "1.0.0" -Message "Opt-out repo should remain unchanged on remote."
Assert-Equal -Actual $existingHeadVersionRemote -Expected "1.0.1" -Message "Existing HEAD repo should push the already committed VERSION."

$managedCommitMessage = Invoke-Git -RepoPath $repoManaged -Arguments @("log", "-1", "--pretty=%s")
$managedCommitBody = Invoke-Git -RepoPath $repoManaged -Arguments @("log", "-1", "--pretty=%b")
$existingHeadCommitMessage = Invoke-Git -RepoPath $repoExistingHead -Arguments @("log", "-1", "--pretty=%s")
$existingHeadCommitCount = Invoke-Git -RepoPath $repoExistingHead -Arguments @("rev-list", "--count", "HEAD")

Assert-Equal -Actual $managedCommitMessage -Expected "chore(release): v1.0.1" -Message "Managed repo should get an auto-generated release commit."
Assert-Contains -Text $managedCommitBody -ExpectedSubstring "Version: 1.0.1" -Message "Managed repo commit body should include the version."
Assert-Contains -Text $managedCommitBody -ExpectedSubstring "- modified: VERSION" -Message "Managed repo commit body should mention the VERSION file."
Assert-Contains -Text $managedCommitBody -ExpectedSubstring "- added: release-notes.txt" -Message "Managed repo commit body should mention added files."
Assert-Contains -Text $managedCommitBody -ExpectedSubstring "Diffstat:" -Message "Managed repo commit body should include a diffstat section."
Assert-Equal -Actual $existingHeadCommitMessage -Expected "chore: prepare release 1.0.1" -Message "Existing HEAD repo should not get an extra auto-commit."
Assert-Equal -Actual $existingHeadCommitCount -Expected "2" -Message "Existing HEAD repo should keep exactly one release commit plus the initial commit."
Assert-True -Condition (Test-Path -LiteralPath (Join-Path $repoExistingHead "scratch.txt")) -Message "Existing HEAD repo should keep unrelated untracked files."

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$managedState = $state.repos.PSObject.Properties | Where-Object { $_.Name -eq $repoManaged } | Select-Object -First 1
$existingHeadState = $state.repos.PSObject.Properties | Where-Object { $_.Name -eq $repoExistingHead } | Select-Object -First 1

Assert-True -Condition ($null -ne $managedState) -Message "Managed repo must be present in the watcher state."
Assert-True -Condition ($null -ne $existingHeadState) -Message "Existing HEAD repo must be present in the watcher state."
Assert-Equal -Actual "$($managedState.Value.last_pushed_version)" -Expected "1.0.1" -Message "Managed repo state should store the pushed version."
Assert-Equal -Actual "$($existingHeadState.Value.last_result)" -Expected "pushed-existing-version-commit" -Message "Existing HEAD repo should record the safe push-only path."

Write-Output "Watcher integration test passed."
Write-Output "State file: $statePath"
Write-Output "Log file:   $logPath"
