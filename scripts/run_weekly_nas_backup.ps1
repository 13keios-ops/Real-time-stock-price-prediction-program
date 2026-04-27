[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupShareRoot,
    [ValidateRange(1, 1000)]
    [int]$KeepCount = 3,
    [switch]$IncludeArtifacts,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

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
    BackupMode = "Scheduled"
}

if ($IncludeArtifacts) {
    $arguments.IncludeArtifacts = $true
}

if ($DryRun) {
    $arguments.DryRun = $true
}

& $exportScript @arguments
