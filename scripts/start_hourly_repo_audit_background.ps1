param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$TimezoneId = "Korea Standard Time"
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$startScript = Join-Path $WorkspaceRoot "scripts\start_hourly_repo_audit.ps1"
$statusScript = Join-Path $WorkspaceRoot "scripts\get_hourly_repo_audit_status.ps1"

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "Missing start script: $startScript"
}

if (-not (Test-Path -LiteralPath $statusScript)) {
    throw "Missing status script: $statusScript"
}

$argumentLine = @(
    "-NoProfile"
    "-ExecutionPolicy Bypass"
    "-File `"$startScript`""
    "-WorkspaceRoot `"$WorkspaceRoot`""
    "-RuntimeDataDir `"$RuntimeDataDir`""
    "-TimezoneId `"$TimezoneId`""
) -join " "

$process = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $argumentLine `
    -WorkingDirectory $WorkspaceRoot `
    -PassThru

Start-Sleep -Seconds 4

if ($process.HasExited) {
    throw "Hourly Repo Audit background launcher exited early with code $($process.ExitCode)."
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $statusScript `
    -WorkspaceRoot $WorkspaceRoot `
    -RuntimeDataDir $RuntimeDataDir
