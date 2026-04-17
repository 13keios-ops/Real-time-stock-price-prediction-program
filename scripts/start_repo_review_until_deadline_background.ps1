param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$TimezoneId = "Korea Standard Time",

    [Parameter(Mandatory = $false)]
    [string]$DeadlineIso = ""
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$startScript = Join-Path $WorkspaceRoot "scripts\run_repo_review_until_deadline.ps1"
$statusScript = Join-Path $WorkspaceRoot "scripts\get_repo_review_until_deadline_status.ps1"
$powershellExe = Join-Path $PSHOME "powershell.exe"

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
)

if ($DeadlineIso) {
    $argumentLine += "-DeadlineIso `"$DeadlineIso`""
}

$process = Start-Process -FilePath $powershellExe `
    -ArgumentList ($argumentLine -join " ") `
    -WorkingDirectory $WorkspaceRoot `
    -PassThru

Start-Sleep -Seconds 4

if ($process.HasExited) {
    throw "Repo review until deadline background launcher exited early with code $($process.ExitCode)."
}

& $powershellExe -NoProfile -ExecutionPolicy Bypass -File $statusScript `
    -WorkspaceRoot $WorkspaceRoot `
    -RuntimeDataDir $RuntimeDataDir
