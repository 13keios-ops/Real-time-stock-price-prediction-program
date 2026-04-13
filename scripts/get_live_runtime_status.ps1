param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$statePath = Join-Path $RuntimeDataDir "reports\live-runtime\state\listener-state.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    [ordered]@{
        status = "stopped"
        process_running = $false
        raw_status = "missing"
        message = "실시간 수집기 상태 파일이 없습니다."
    } | ConvertTo-Json -Depth 10
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$processRunning = $false
if ($state.pid) {
    $processRunning = $null -ne (Get-Process -Id $state.pid -ErrorAction SilentlyContinue)
}

$effectiveStatus = if ($processRunning) { "running" } elseif ([string]$state.status -eq "failed") { "failed" } else { "stopped" }
[ordered]@{
    status = $effectiveStatus
    pid = $state.pid
    process_running = $processRunning
    workspace_root = $state.workspace_root
    runtime_data_dir = $state.runtime_data_dir
    symbols = $state.symbols
    watchlist_file = $state.watchlist_file
    max_frames = $state.max_frames
    max_reconnects = $state.max_reconnects
    prediction_horizons = $state.prediction_horizons
    trading_signal_horizon = $state.trading_signal_horizon
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
    started_at = $state.started_at
    raw_status = $state.status
} | ConvertTo-Json -Depth 10
