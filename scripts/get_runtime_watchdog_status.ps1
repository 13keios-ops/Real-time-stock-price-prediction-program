param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_process_helpers.ps1")

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$statePath = Join-Path $RuntimeDataDir "reports\runtime-watchdog\state\watchdog-state.json"
$watchdogScriptPath = Join-Path $WorkspaceRoot "scripts\run_runtime_watchdog_loop.ps1"

if (-not (Test-Path -LiteralPath $statePath)) {
    [ordered]@{
        status = "stopped"
        process_running = $false
        raw_status = "missing"
        message = "Runtime watchdog state not found."
    } | ConvertTo-Json -Depth 10
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$processRunning = $false
if ($state.pid) {
    $processRunning = $null -ne (Get-PowerShellScriptProcessRecord -ProcessId ([int]$state.pid) -ScriptPath $watchdogScriptPath)
}

$effectiveStatus = [string]$state.status
if ((@("starting", "running", "warning") -contains $effectiveStatus) -and (-not $processRunning)) {
    $effectiveStatus = "stale"
}

[ordered]@{
    status = if ($processRunning -and $effectiveStatus -eq "stale") { "running" } else { $effectiveStatus }
    pid = $state.pid
    process_running = $processRunning
    workspace_root = $state.workspace_root
    runtime_data_dir = $state.runtime_data_dir
    dashboard_host = $state.dashboard_host
    dashboard_port = $state.dashboard_port
    interval_seconds = $state.interval_seconds
    started_at = $state.started_at
    last_checked_at = $state.last_checked_at
    dashboard_action = $state.dashboard_action
    dashboard_snapshot_action = $state.dashboard_snapshot_action
    live_runtime_action = $state.live_runtime_action
    dashboard_status = $state.dashboard_status
    live_runtime_status = $state.live_runtime_status
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
    errors = $state.errors
    raw_status = $state.status
} | ConvertTo-Json -Depth 10
