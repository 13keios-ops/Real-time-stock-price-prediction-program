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

$statePath = Join-Path $RuntimeDataDir "reports\runtime-watchdog\state\watchdog-state.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Runtime watchdog state not found."
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.pid) {
    Write-Output "Runtime watchdog pid is not recorded."
    return
}

$process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    $payload = [ordered]@{
        status = "stale"
        pid = $state.pid
        process_running = $false
        stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        workspace_root = $state.workspace_root
        runtime_data_dir = $state.runtime_data_dir
        dashboard_host = $state.dashboard_host
        dashboard_port = $state.dashboard_port
        interval_seconds = $state.interval_seconds
        stdout_log_path = $state.stdout_log_path
        stderr_log_path = $state.stderr_log_path
        error = "Runtime watchdog process was already not running when stop was requested."
    }
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Output "Runtime watchdog process was already not running. Marked state as stale."
    return
}

Stop-Process -Id $process.Id -Force

$payload = [ordered]@{
    status = "stopped"
    pid = $process.Id
    process_running = $false
    stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $state.workspace_root
    runtime_data_dir = $state.runtime_data_dir
    dashboard_host = $state.dashboard_host
    dashboard_port = $state.dashboard_port
    interval_seconds = $state.interval_seconds
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output "Stopped runtime watchdog pid $($process.Id)."
