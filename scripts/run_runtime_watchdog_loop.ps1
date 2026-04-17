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
$dashboardSnapshotPath = Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$symbolForVerification = "005930"

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

function Read-DashboardSnapshot {
    return Read-JsonFile -Path $dashboardSnapshotPath
}

while ($true) {
    $errors = @()
    $dashboardAction = "none"
    $dashboardSnapshotAction = "none"
    $liveRuntimeAction = "none"
    $dashboardStatus = $null
    $liveRuntimeStatus = $null
    $dashboardSnapshot = $null

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

    $dashboardSnapshot = Read-DashboardSnapshot

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

    $needsLiveRuntimeRecovery = $false
    $needsVerificationRefresh = $false
    if ($null -ne $dashboardSnapshot) {
        $latestVerification = $dashboardSnapshot["latest_kis_verification"]
        $systemStatus = $dashboardSnapshot["system_status"]
        $freshness = if ($null -ne $systemStatus) { $systemStatus["freshness"] } else { $null }
        $marketBarFreshness = if ($null -ne $freshness) { $freshness["latest_market_bar"] } else { $null }
        $verificationFreshness = if ($null -ne $freshness) { $freshness["latest_kis_verification"] } else { $null }
        $sessionStatus = [string]$latestVerification["session_status"]

        if (
            ([string]$liveRuntimeStatus.status -eq "running") -and
            ($sessionStatus -eq "regular-session") -and
            ($null -ne $marketBarFreshness) -and
            ([string]$marketBarFreshness["state"] -eq "stale")
        ) {
            $needsLiveRuntimeRecovery = $true
        }

        if (
            ($sessionStatus -eq "regular-session") -and
            (
                ($null -eq $latestVerification) -or
                ($null -eq $verificationFreshness) -or
                (@("stale", "missing") -contains [string]$verificationFreshness["state"])
            )
        ) {
            $needsVerificationRefresh = $true
        }
    }

    if ($needsVerificationRefresh) {
        try {
            & python -m app --verify-kis-ws --symbols $symbolForVerification --max-frames 10 --max-reconnects 1 | Out-Null
            $dashboardSnapshotAction = "refresh_kis_verification"
            $dashboardSnapshot = Read-DashboardSnapshot
        } catch {
            $dashboardSnapshotAction = "refresh_kis_verification_failed"
            $errors += "kis_verification_refresh: $($_.Exception.Message)"
        }
    }

    if ($needsLiveRuntimeRecovery) {
        try {
            $null = & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -ForceRestart
            $liveRuntimeAction = "restart_stale_runtime"
            $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
        } catch {
            $liveRuntimeAction = "restart_stale_runtime_failed"
            $errors += "live_runtime_stale_restart: $($_.Exception.Message)"
        }
    }

    if ($dashboardSnapshotAction -eq "none") {
        $dashboardSnapshotAction = "client_refresh"
    }

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
