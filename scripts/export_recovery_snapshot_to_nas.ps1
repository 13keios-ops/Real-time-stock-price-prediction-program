[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupShareRoot,
    [switch]$IncludeArtifacts,
    [ValidateRange(1, 1000)]
    [int]$KeepCount = 3,
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

$repoRoot = Split-Path -Parent $scriptRoot
$exportScript = Join-Path $scriptRoot "export_recovery_snapshot.ps1"
$repoFolderName = (Split-Path -Leaf $repoRoot).ToLowerInvariant()

if (-not (Test-Path -LiteralPath $exportScript)) {
    throw "Required script not found: $exportScript"
}

function Normalize-RootPath {
    param(
        [string]$PathValue
    )

    if ($PathValue -match '^[\\/]{2}') {
        return $PathValue.TrimEnd('\', '/')
    }

    return [System.IO.Path]::GetFullPath($PathValue)
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

$backupShareRootNormalized = Normalize-RootPath -PathValue $BackupShareRoot
$repoFolderSlug = Convert-ToSlug -Value $repoFolderName
$destinationRoot = Join-Path $backupShareRootNormalized ("repos\" + $repoFolderSlug + "\recovery-exports")

$arguments = @{
    RepoRoot = $repoRoot
    DestinationRoot = $destinationRoot
    PackagePrefix = $repoFolderSlug + "-recovery"
    KeepCount = $KeepCount
    BackupMode = $BackupMode
}

if ($IncludeArtifacts) {
    $arguments.IncludeArtifacts = $true
}

if ($BackupReason) {
    $arguments.BackupReason = $BackupReason
}

if ($DryRun) {
    Write-Host "Recommended NAS destination root: $destinationRoot"
    Write-Host "Backup mode: $BackupMode"
    Write-Host "Retention keep count: $KeepCount"
    if ($BackupReason) {
        Write-Host "Backup reason: $BackupReason"
    }
    $arguments.DryRun = $true
}

& $exportScript @arguments
