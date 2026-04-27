param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$runnerStatePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\runner-state.json"

if (-not (Test-Path -LiteralPath $runnerStatePath)) {
    Write-Output "Hourly Repo Audit runner state not found."
    exit 0
}

$runnerState = Get-Content -LiteralPath $runnerStatePath -Raw | ConvertFrom-Json
if (-not $runnerState.pid) {
    Write-Output "Hourly Repo Audit runner pid is not recorded."
    exit 0
}

$process = Get-Process -Id $runnerState.pid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    $payload = [ordered]@{
        automation_name = $runnerState.automation_name
        status = "stale"
        pid = $runnerState.pid
        stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        workspace_root = $WorkspaceRoot
        runtime_data_dir = $RuntimeDataDir
        last_run_label = $runnerState.last_run_label
        last_review_path = $runnerState.last_review_path
        error = "Runner process was already not running when stop was requested."
    }

    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runnerStatePath -Encoding UTF8
    Write-Output "Hourly Repo Audit runner process was already not running. Marked state as stale."
    exit 0
}

Stop-Process -Id $runnerState.pid -Force

$payload = [ordered]@{
    automation_name = $runnerState.automation_name
    status = "stopped"
    pid = $runnerState.pid
    stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    last_run_label = $runnerState.last_run_label
    last_review_path = $runnerState.last_review_path
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runnerStatePath -Encoding UTF8
Write-Output "Stopped Hourly Repo Audit runner pid $($runnerState.pid)."

