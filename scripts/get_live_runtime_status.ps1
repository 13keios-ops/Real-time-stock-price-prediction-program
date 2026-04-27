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

$statePath = Join-Path $RuntimeDataDir "reports\live-runtime\state\listener-state.json"
$dashboardPath = Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.json"

Add-Type -AssemblyName System.Web.Extensions

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $serializer.MaxJsonLength = 67108864
        $jsonText = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        return $serializer.DeserializeObject($jsonText)
    } catch {
        return $null
    }
}

if (-not (Test-Path -LiteralPath $statePath)) {
    [ordered]@{
        status = "stopped"
        process_running = $false
        raw_status = "missing"
        message = "실시간 수집기 상태 파일이 없습니다."
    } | ConvertTo-Json -Depth 10
    return
}

$state = Read-JsonFile -Path $statePath
if ($null -eq $state) {
    [ordered]@{
        status = "warning"
        process_running = $false
        raw_status = "invalid"
        message = "실시간 수집기 상태 파일을 읽지 못했습니다."
    } | ConvertTo-Json -Depth 10
    return
}
$processRunning = $false
if ($state["pid"]) {
    $processRunning = $null -ne (Get-Process -Id $state["pid"] -ErrorAction SilentlyContinue)
}

$dashboardPayload = Read-JsonFile -Path $dashboardPath

$systemStatus = if ($null -ne $dashboardPayload) { $dashboardPayload["system_status"] } else { $null }
$freshness = if ($null -ne $systemStatus) { $systemStatus["freshness"] } else { $null }

$effectiveStatus = if ($processRunning) { "running" } elseif ([string]$state["status"] -eq "failed") { "failed" } else { "stopped" }
[ordered]@{
    status = $effectiveStatus
    pid = $state["pid"]
    process_running = $processRunning
    workspace_root = $state["workspace_root"]
    runtime_data_dir = $state["runtime_data_dir"]
    symbols = $state["symbols"]
    watchlist_file = $state["watchlist_file"]
    max_frames = $state["max_frames"]
    max_reconnects = $state["max_reconnects"]
    prediction_horizons = $state["prediction_horizons"]
    trading_signal_horizon = $state["trading_signal_horizon"]
    stdout_log_path = $state["stdout_log_path"]
    stderr_log_path = $state["stderr_log_path"]
    started_at = $state["started_at"]
    latest_market_bar_time = if ($null -ne $systemStatus) { $systemStatus["latest_market_bar_time"] } else { $null }
    latest_prediction_time = if ($null -ne $systemStatus) { $systemStatus["latest_prediction_time"] } else { $null }
    latest_signal_time = if ($null -ne $systemStatus) { $systemStatus["latest_signal_time"] } else { $null }
    market_bar_freshness = if ($null -ne $freshness) { $freshness["latest_market_bar"] } else { $null }
    prediction_freshness = if ($null -ne $freshness) { $freshness["latest_prediction"] } else { $null }
    signal_freshness = if ($null -ne $freshness) { $freshness["latest_signal"] } else { $null }
    kis_verification_freshness = if ($null -ne $freshness) { $freshness["latest_kis_verification"] } else { $null }
    session_status = if ($null -ne $dashboardPayload -and $null -ne $dashboardPayload["latest_kis_verification"]) { $dashboardPayload["latest_kis_verification"]["session_status"] } else { $null }
    raw_status = $state["status"]
} | ConvertTo-Json -Depth 10
