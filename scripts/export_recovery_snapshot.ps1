[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$DestinationRoot,
    [string]$PackagePrefix,
    [switch]$IncludeArtifacts,
    [ValidateRange(0, 1000)]
    [int]$KeepCount = 0,
    [ValidateSet("Manual", "Scheduled", "Forced")]
    [string]$BackupMode = "Manual",
    [string]$BackupReason,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
}
else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}

$defaultRepoRoot = Split-Path -Parent $scriptRoot

if (-not $RepoRoot) {
    $RepoRoot = $defaultRepoRoot
}

if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path $defaultRepoRoot ".codex-artifacts\recovery-exports"
}

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$DestinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)

if ($DestinationRoot.TrimEnd('\') -ieq $RepoRoot.TrimEnd('\')) {
    throw "DestinationRoot cannot be the repository root because that would create a recursive snapshot."
}

function Get-GitDesktopGitPath {
    $desktopRoot = Join-Path $env:LocalAppData "GitHubDesktop"
    if (-not (Test-Path -LiteralPath $desktopRoot)) {
        return $null
    }

    $candidate = Get-ChildItem -LiteralPath $desktopRoot -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "resources\app\git\cmd\git.exe" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1

    if ($candidate) {
        return $candidate
    }

    return $null
}

function Get-GitCommand {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) {
        return $gitCommand.Source
    }

    return Get-GitDesktopGitPath
}

function Invoke-Git {
    param(
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $output = & $script:gitCommand -C $RepoRoot @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if (($exitCode -ne 0) -and (-not $AllowFailure)) {
        throw "git $($Arguments -join ' ') failed with exit code $exitCode.`n$($output | Out-String)"
    }

    return @($output)
}

function Test-IsDestinationAncestor {
    param(
        [string]$CandidatePath
    )

    $candidate = $CandidatePath.TrimEnd('\')
    $destination = $script:destinationRootNormalized.TrimEnd('\')
    if ($destination.Length -lt $candidate.Length) {
        return $false
    }

    if ($destination.Equals($candidate, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    return $destination.StartsWith($candidate + "\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Convert-ToSlug {
    param(
        [string]$Value
    )

    if (-not $Value) {
        return "repo"
    }

    $slug = $Value.ToLowerInvariant()
    $slug = [System.Text.RegularExpressions.Regex]::Replace($slug, '[^a-z0-9]+', '-')
    $slug = $slug.Trim('-')

    if (-not $slug) {
        return "repo"
    }

    return $slug
}

function Get-RecoveryPackageDirectories {
    param(
        [string]$Path,
        [string]$PackagePrefix
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    return @(Get-ChildItem -LiteralPath $Path -Directory -Filter ($PackagePrefix + "-*") -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending)
}

function Get-FuturePackagesToPrune {
    param(
        [string]$Path,
        [string]$PackagePrefix,
        [int]$KeepCount
    )

    if ($KeepCount -le 0) {
        return @()
    }

    $existing = @(Get-RecoveryPackageDirectories -Path $Path -PackagePrefix $PackagePrefix)
    $keepExistingCount = [Math]::Max($KeepCount - 1, 0)
    if ($existing.Count -le $keepExistingCount) {
        return @()
    }

    return @($existing | Select-Object -Skip $keepExistingCount)
}

function Copy-RecoveryItem {
    param(
        [System.IO.FileSystemInfo]$Item,
        [string]$SnapshotRoot
    )

    if ($Item.PSIsContainer) {
        $targetPath = Join-Path $SnapshotRoot $Item.Name
        New-Item -ItemType Directory -Force -Path $targetPath | Out-Null

        & robocopy $Item.FullName $targetPath /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) {
            throw "robocopy failed for $($Item.FullName) with exit code $LASTEXITCODE."
        }

        return
    }

    Copy-Item -LiteralPath $Item.FullName -Destination $SnapshotRoot -Force
}

$gitCommand = Get-GitCommand
if (-not $gitCommand) {
    throw "git command was not found in PATH or in the newest GitHub Desktop bundle."
}

$script:gitCommand = $gitCommand
$script:destinationRootNormalized = $DestinationRoot

$repoFolderName = Split-Path -Leaf $RepoRoot
if (-not $PackagePrefix) {
    $PackagePrefix = (Convert-ToSlug -Value $repoFolderName) + "-recovery"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$packageRoot = Join-Path $DestinationRoot ($PackagePrefix + "-" + $timestamp)
$snapshotRoot = Join-Path $packageRoot "repo-snapshot"
$bundlePath = Join-Path $packageRoot "repository.bundle"
$statusPath = Join-Path $packageRoot "git-status.txt"
$remotePath = Join-Path $packageRoot "git-remote.txt"
$headPath = Join-Path $packageRoot "git-head.txt"
$restorePath = Join-Path $packageRoot "RESTORE-FIRST.txt"
$metadataPath = Join-Path $packageRoot "metadata.json"

$branch = ([string](Invoke-Git -Arguments @("rev-parse", "--abbrev-ref", "HEAD") | Select-Object -First 1)).Trim()
$headCommit = ([string](Invoke-Git -Arguments @("rev-parse", "HEAD") | Select-Object -First 1)).Trim()
$remoteOrigin = ([string](Invoke-Git -Arguments @("config", "--get", "remote.origin.url") -AllowFailure | Select-Object -First 1)).Trim()
$statusLines = Invoke-Git -Arguments @("status", "--short", "--branch")

$excludedNames = @(".git")
if (-not $IncludeArtifacts) {
    $excludedNames += ".codex-artifacts"
}

$itemsToCopy = Get-ChildItem -LiteralPath $RepoRoot -Force | Where-Object {
    if ($excludedNames -contains $_.Name) {
        return $false
    }

    return -not (Test-IsDestinationAncestor -CandidatePath $_.FullName)
}

if ($DryRun) {
    Write-Host "Recovery package would be created at: $packageRoot"
    Write-Host "Bundle path: $bundlePath"
    Write-Host "Snapshot root: $snapshotRoot"
    Write-Host "Artifacts included: $([bool]$IncludeArtifacts)"
    Write-Host "Package prefix: $PackagePrefix"
    Write-Host "Backup mode: $BackupMode"
    Write-Host "Retention keep count: $KeepCount"
    if ($BackupReason) {
        Write-Host "Backup reason: $BackupReason"
    }
    Write-Host "Items that would be copied:"
    $itemsToCopy | ForEach-Object { Write-Host "- $($_.Name)" }
    if ($KeepCount -gt 0) {
        $futurePrune = @(Get-FuturePackagesToPrune -Path $DestinationRoot -PackagePrefix $PackagePrefix -KeepCount $KeepCount)
        if ($futurePrune.Count -gt 0) {
            Write-Host "Packages that would be pruned after export:"
            $futurePrune | ForEach-Object { Write-Host "- $($_.FullName)" }
        }
    }
    $global:LASTEXITCODE = 0
    return
}

New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
New-Item -ItemType Directory -Force -Path $snapshotRoot | Out-Null

Invoke-Git -Arguments @("bundle", "create", $bundlePath, "--all") | Out-Null

$statusLines | Set-Content -LiteralPath $statusPath -Encoding UTF8
if ($remoteOrigin) {
    $remoteOrigin | Set-Content -LiteralPath $remotePath -Encoding UTF8
}
else {
    "Unavailable" | Set-Content -LiteralPath $remotePath -Encoding UTF8
}
$headCommit | Set-Content -LiteralPath $headPath -Encoding UTF8

foreach ($item in $itemsToCopy) {
    Copy-RecoveryItem -Item $item -SnapshotRoot $snapshotRoot
}

$restoreNotes = @(
    "Restore order:",
    "1. Clone from GitHub or restore from repository.bundle.",
    "2. Overlay repo-snapshot if you need the exported working-tree state.",
    "3. Restore external secrets, watcher assets, and Codex local state through their separate recovery path.",
    "4. Run scripts/check_local_setup.ps1 before resuming unattended work."
) -join [Environment]::NewLine

$restoreNotes | Set-Content -LiteralPath $restorePath -Encoding UTF8

$prunedPackagePaths = @()
if ($KeepCount -gt 0) {
    $packages = @(Get-RecoveryPackageDirectories -Path $DestinationRoot -PackagePrefix $PackagePrefix)
    $toPrune = @($packages | Select-Object -Skip $KeepCount)
    foreach ($package in $toPrune) {
        Remove-Item -LiteralPath $package.FullName -Recurse -Force
        $prunedPackagePaths += $package.FullName
    }
}

$metadata = [ordered]@{
    created_at = (Get-Date).ToString("s")
    repo_root = $RepoRoot
    destination_root = $DestinationRoot
    package_root = $packageRoot
    snapshot_root = $snapshotRoot
    bundle_path = $bundlePath
    package_prefix = $PackagePrefix
    include_codex_artifacts = [bool]$IncludeArtifacts
    retention_keep_count = $KeepCount
    backup_mode = $BackupMode
    backup_reason = if ($BackupReason) { $BackupReason } else { $null }
    pruned_package_paths = $prunedPackagePaths
    git = [ordered]@{
        branch = $branch
        head = $headCommit
        remote_origin = if ($remoteOrigin) { $remoteOrigin } else { $null }
    }
    notes = @(
        "repository.bundle preserves Git history and refs.",
        "repo-snapshot preserves the exported working tree outside .git.",
        "External secrets and machine-local assets are not included automatically; see RECOVERY.md."
    )
}

$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding UTF8

Write-Host "Recovery package created at $packageRoot"
Write-Host "Bundle: $bundlePath"
Write-Host "Snapshot: $snapshotRoot"
Write-Host "Metadata: $metadataPath"
if ($KeepCount -gt 0) {
    Write-Host "Retention: keep latest $KeepCount package(s)"
}
if ($prunedPackagePaths.Count -gt 0) {
    Write-Host "Pruned older packages:"
    $prunedPackagePaths | ForEach-Object { Write-Host "- $_" }
}

$global:LASTEXITCODE = 0
