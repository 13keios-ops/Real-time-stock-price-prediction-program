param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$DashboardHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$DashboardPort = 8765,

    [Parameter(Mandatory = $false)]
    [int]$IntervalSeconds = 60,

    [Parameter(Mandatory = $false)]
    [switch]$SinglePass
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$stateDir = Join-Path $RuntimeDataDir "reports\runtime-watchdog\state"
$statePath = Join-Path $stateDir "watchdog-state.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

function Write-WatchdogState {
    param(
        [string]$Status,
        [string]$DashboardAction,
        [string]$DashboardSnapshotAction,
        [string]$LiveRuntimeAction,
        [string[]]$Errors,
        [object]$DashboardStatus,
        [object]$LiveRuntimeStatus
    )

    $payload = [ordered]@{
        status = $Status
        pid = $PID
        workspace_root = $WorkspaceRoot
        runtime_data_dir = $RuntimeDataDir
        dashboard_host = $DashboardHost
        dashboard_port = $DashboardPort
        interval_seconds = $IntervalSeconds
        started_at = $startedAt
        last_checked_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        dashboard_action = $DashboardAction
        dashboard_snapshot_action = $DashboardSnapshotAction
        live_runtime_action = $LiveRuntimeAction
        stdout_log_path = (Join-Path $RuntimeDataDir "logs\app\runtime-watchdog.stdout.log")
        stderr_log_path = (Join-Path $RuntimeDataDir "logs\app\runtime-watchdog.stderr.log")
        errors = $Errors
        dashboard_status = $DashboardStatus
        live_runtime_status = $LiveRuntimeStatus
    }

    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

while ($true) {
    $errors = @()
    $dashboardAction = "none"
    $dashboardSnapshotAction = "none"
    $liveRuntimeAction = "none"
    $dashboardStatus = $null
    $liveRuntimeStatus = $null

    try {
        $dashboardStatus = & (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    } catch {
        $errors += "dashboard_status: $($_.Exception.Message)"
    }

    $dashboardHealthy = $false
    if ($null -ne $dashboardStatus) {
        $dashboardHealthy = ([string]$dashboardStatus.status -eq "running") -and [bool]$dashboardStatus.dashboard_responding
    }

    if (-not $dashboardHealthy) {
        try {
            $null = & (Join-Path $WorkspaceRoot "scripts\start_dashboard_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -DashboardHost $DashboardHost `
                -Port $DashboardPort `
                -ForceRestart
            $dashboardAction = "restart"
            $dashboardStatus = & (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
        } catch {
            $dashboardAction = "restart_failed"
            $errors += "dashboard_restart: $($_.Exception.Message)"
        }
    }

    try {
        $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    } catch {
        $errors += "live_runtime_status: $($_.Exception.Message)"
    }

    $liveRuntimeHealthy = $false
    if ($null -ne $liveRuntimeStatus) {
        $liveRuntimeHealthy = ([string]$liveRuntimeStatus.status -eq "running")
    }

    if (-not $liveRuntimeHealthy) {
        try {
            $null = & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -ForceRestart
            $liveRuntimeAction = "restart"
            $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
        } catch {
            $liveRuntimeAction = "restart_failed"
            $errors += "live_runtime_restart: $($_.Exception.Message)"
        }
    }

    $dashboardSnapshotAction = "client_refresh"

    $status = if ($errors.Count -eq 0) { "running" } else { "warning" }
    Write-WatchdogState `
        -Status $status `
        -DashboardAction $dashboardAction `
        -DashboardSnapshotAction $dashboardSnapshotAction `
        -LiveRuntimeAction $liveRuntimeAction `
        -Errors $errors `
        -DashboardStatus $dashboardStatus `
        -LiveRuntimeStatus $liveRuntimeStatus

    if ($SinglePass) {
        break
    }

    Start-Sleep -Seconds $IntervalSeconds
}
