param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [int]$HeartbeatStaleAfterSeconds = 0
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

$intervalSeconds = if ($state.interval_seconds) { [int]$state.interval_seconds } else { 60 }
$effectiveHeartbeatStaleAfterSeconds = if ($HeartbeatStaleAfterSeconds -gt 0) {
    $HeartbeatStaleAfterSeconds
} else {
    [Math]::Max($intervalSeconds * 10, 600)
}

$heartbeatAgeSeconds = $null
$heartbeatStale = $false
$heartbeatCheckedAt = $null
if ($state.last_checked_at) {
    try {
        $heartbeatCheckedAt = [DateTimeOffset]::Parse([string]$state.last_checked_at)
        $heartbeatAgeSeconds = [Math]::Round(([DateTimeOffset]::Now - $heartbeatCheckedAt).TotalSeconds, 1)
        $heartbeatStale = $processRunning -and ($heartbeatAgeSeconds -gt $effectiveHeartbeatStaleAfterSeconds)
    } catch {
        $heartbeatStale = $processRunning
    }
} elseif ($state.started_at) {
    try {
        $heartbeatCheckedAt = [DateTimeOffset]::Parse([string]$state.started_at)
        $heartbeatAgeSeconds = [Math]::Round(([DateTimeOffset]::Now - $heartbeatCheckedAt).TotalSeconds, 1)
        $heartbeatStale = $processRunning -and ($heartbeatAgeSeconds -gt $effectiveHeartbeatStaleAfterSeconds)
    } catch {
        $heartbeatStale = $processRunning
    }
}

$effectiveStatus = [string]$state.status
if ((@("starting", "running", "warning") -contains $effectiveStatus) -and (-not $processRunning)) {
    $effectiveStatus = "stale"
}
if ((@("starting", "running", "warning") -contains $effectiveStatus) -and $heartbeatStale) {
    $effectiveStatus = "stale"
}

[ordered]@{
    status = $effectiveStatus
    pid = $state.pid
    process_running = $processRunning
    heartbeat_stale = $heartbeatStale
    heartbeat_age_seconds = $heartbeatAgeSeconds
    heartbeat_stale_after_seconds = $effectiveHeartbeatStaleAfterSeconds
    workspace_root = $state.workspace_root
    runtime_data_dir = $state.runtime_data_dir
    dashboard_host = $state.dashboard_host
    dashboard_port = $state.dashboard_port
    interval_seconds = $state.interval_seconds
    dashboard_refresh_interval_seconds = $state.dashboard_refresh_interval_seconds
    pre_open_warmup_minutes = $state.pre_open_warmup_minutes
    market_session_status = $state.market_session_status
    live_runtime_should_run = $state.live_runtime_should_run
    started_at = $state.started_at
    last_checked_at = $state.last_checked_at
    dashboard_action = $state.dashboard_action
    dashboard_snapshot_action = $state.dashboard_snapshot_action
    live_runtime_action = $state.live_runtime_action
    ml_maintenance_action = $state.ml_maintenance_action
    dashboard_status = $state.dashboard_status
    live_runtime_status = $state.live_runtime_status
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
    errors = $state.errors
    raw_status = $state.status
} | ConvertTo-Json -Depth 10
