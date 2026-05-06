[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupShareRoot,
    [ValidateRange(1, 1000)]
    [int]$KeepCount = 3,
    [string]$Reason = "important-period",
    [switch]$IncludeArtifacts,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# export_recovery_snapshot.ps1 always excludes root .env files, KIS token cache,
# runtime logs, and private key file patterns from the NAS snapshot.
$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
}
else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}

$exportScript = Join-Path $scriptRoot "export_recovery_snapshot_to_nas.ps1"
if (-not (Test-Path -LiteralPath $exportScript)) {
    throw "Required script not found: $exportScript"
}

$arguments = @{
    BackupShareRoot = $BackupShareRoot
    KeepCount = $KeepCount
    BackupMode = "Forced"
    BackupReason = $Reason
}

if ($IncludeArtifacts) {
    $arguments.IncludeArtifacts = $true
}

if ($DryRun) {
    $arguments.DryRun = $true
}

& $exportScript @arguments
