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

$statePath = Join-Path $RuntimeDataDir "reports\dashboard\state\server-state.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Dashboard server state not found."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$processRunning = $false
if ($state.pid) {
    $processRunning = $null -ne (Get-Process -Id $state.pid -ErrorAction SilentlyContinue)
}

$effectiveStatus = $state.status
if ((@("starting", "running") -contains [string]$state.status) -and (-not $processRunning)) {
    $effectiveStatus = "stale"
}

$tcpConnection = $null
$portOwnerPid = $null
$dashboardResponding = $false
$dashboardApiResponding = $false
if ($state.port) {
    $tcpConnection = Get-NetTCPConnection -LocalPort $state.port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1
    if ($null -ne $tcpConnection) {
        $portOwnerPid = $tcpConnection.OwningProcess
        try {
            $healthUrl = "{0}/health" -f ([string]$state.url).TrimEnd("/")
            $health = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 3
            $dashboardResponding = ($health.Content -match '"service"\s*:\s*"dashboard"')
        } catch {
            $dashboardResponding = $false
        }
        try {
            $apiUrl = "{0}/api/dashboard.json" -f ([string]$state.url).TrimEnd("/")
            $apiResponse = Invoke-WebRequest -UseBasicParsing $apiUrl -TimeoutSec 5
            $dashboardApiResponding = ($apiResponse.StatusCode -eq 200)
        } catch {
            $dashboardApiResponding = $false
        }
    }
}

if ($processRunning -and $null -ne $tcpConnection -and $dashboardApiResponding) {
    $effectiveStatus = "running"
} elseif ((-not $processRunning) -and $null -ne $tcpConnection -and $dashboardResponding -and $dashboardApiResponding) {
    $effectiveStatus = "running"
    $processRunning = $true
}

$output = [ordered]@{
    status = $effectiveStatus
    pid = if ($processRunning -and $null -ne $portOwnerPid) { $portOwnerPid } else { $state.pid }
    process_running = $processRunning
    port_bound = ($null -ne $tcpConnection)
    host = $state.host
    port = $state.port
    url = $state.url
    started_at = $state.started_at
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
    snapshot_html_path = $state.snapshot_html_path
    snapshot_json_path = $state.snapshot_json_path
    port_owner_pid = $portOwnerPid
    dashboard_responding = $dashboardResponding
    dashboard_api_responding = $dashboardApiResponding
    raw_status = $state.status
}

$stateChanged = ($state.status -ne $effectiveStatus) -or
    ([string]$state.pid -ne [string]$output.pid) -or
    ([bool]$state.process_running -ne [bool]$output.process_running) -or
    ([bool]$state.port_bound -ne [bool]$output.port_bound)

if ($stateChanged) {
    $normalizedState = [ordered]@{
        status = $effectiveStatus
        pid = $output.pid
        process_running = $output.process_running
        port_bound = $output.port_bound
        host = $state.host
        port = $state.port
        url = $state.url
        started_at = $state.started_at
        stdout_log_path = $state.stdout_log_path
        stderr_log_path = $state.stderr_log_path
        snapshot_html_path = $state.snapshot_html_path
        snapshot_json_path = $state.snapshot_json_path
    }
    $normalizedState | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

$output | ConvertTo-Json -Depth 10
