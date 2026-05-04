param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$DashboardHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$DashboardPort = 8765,

    [Parameter(Mandatory = $false)]
    [int]$IntervalSeconds = 60,

    [Parameter(Mandatory = $false)]
    [int]$DashboardRefreshIntervalSeconds = 600,

    [Parameter(Mandatory = $false)]
    [int]$PreOpenWarmupMinutes = 60,

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
$kisVerificationPath = Join-Path $RuntimeDataDir "reports\kis-ws\latest-verification.json"
$marketCalendarPath = Join-Path $WorkspaceRoot "config\market_calendar.toml"
$mlMaintenanceStatePath = Join-Path $RuntimeDataDir "reports\ml-maintenance\state\latest-post-close-ml.json"
$mlMaintenanceLockPath = Join-Path $RuntimeDataDir "reports\ml-maintenance\state\maintenance-in-progress.json"
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
        [string]$MlMaintenanceAction,
        [string[]]$Errors,
        [object]$DashboardStatus,
        [object]$LiveRuntimeStatus,
        [string]$MarketSessionStatus,
        [bool]$LiveRuntimeShouldRun
    )

    $payload = [ordered]@{
        status = $Status
        pid = $PID
        workspace_root = $WorkspaceRoot
        runtime_data_dir = $RuntimeDataDir
        dashboard_host = $DashboardHost
        dashboard_port = $DashboardPort
        interval_seconds = $IntervalSeconds
        dashboard_refresh_interval_seconds = $DashboardRefreshIntervalSeconds
        pre_open_warmup_minutes = $PreOpenWarmupMinutes
        market_session_status = $MarketSessionStatus
        live_runtime_should_run = $LiveRuntimeShouldRun
        started_at = $startedAt
        last_checked_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        dashboard_action = $DashboardAction
        dashboard_snapshot_action = $DashboardSnapshotAction
        live_runtime_action = $LiveRuntimeAction
        ml_maintenance_action = $MlMaintenanceAction
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

function Get-DashboardSnapshotAgeSeconds {
    if (-not (Test-Path -LiteralPath $dashboardSnapshotPath)) {
        return $null
    }

    try {
        return ((Get-Date) - (Get-Item -LiteralPath $dashboardSnapshotPath).LastWriteTime).TotalSeconds
    } catch {
        return $null
    }
}

function Read-KisVerification {
    return Read-JsonFile -Path $kisVerificationPath
}

function Get-MarketTimeSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Default
    )

    if (-not (Test-Path -LiteralPath $marketCalendarPath)) {
        return $Default
    }

    $pattern = "^\s*$([regex]::Escape($Key))\s*=\s*`"([^`"]+)`""
    $match = [System.IO.File]::ReadAllLines($marketCalendarPath) |
        Where-Object { $_ -match $pattern } |
        Select-Object -First 1
    if ($match -and $match -match $pattern) {
        return $Matches[1]
    }

    return $Default
}

function Get-MarketDateListSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $marketCalendarPath)) {
        return @()
    }

    $pattern = "^\s*$([regex]::Escape($Key))\s*=\s*\[(.*)\]"
    $match = [System.IO.File]::ReadAllLines($marketCalendarPath) |
        Where-Object { $_ -match $pattern } |
        Select-Object -First 1
    if (-not $match -or -not ($match -match $pattern)) {
        return @()
    }

    return @($Matches[1] -split "," | ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { $_ })
}

function Test-MarketHoliday {
    param(
        [Parameter(Mandatory = $true)]
        [datetime]$Date
    )

    $dateText = $Date.ToString("yyyy-MM-dd")
    return @(Get-MarketDateListSetting -Key "holidays") -contains $dateText
}

function Get-CurrentMarketSessionStatus {
    $now = Get-Date
    if ($now.DayOfWeek -in @([System.DayOfWeek]::Saturday, [System.DayOfWeek]::Sunday)) {
        return "weekend"
    }
    if (Test-MarketHoliday -Date $now) {
        return "holiday"
    }

    $sessionOpen = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_open" -Default "09:00"))
    $sessionClose = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_close" -Default "15:30"))
    $currentTime = $now.TimeOfDay

    if ($currentTime -lt $sessionOpen) {
        return "pre-open"
    }
    if ($currentTime -gt $sessionClose) {
        return "post-close"
    }
    return "regular-session"
}

function Test-LiveRuntimeShouldRun {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SessionStatus
    )

    if ($SessionStatus -eq "regular-session") {
        return $true
    }
    if ($SessionStatus -ne "pre-open" -or $PreOpenWarmupMinutes -le 0) {
        return $false
    }

    $now = Get-Date
    $sessionOpen = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_open" -Default "09:00"))
    $warmupStart = $sessionOpen.Subtract([TimeSpan]::FromMinutes($PreOpenWarmupMinutes))

    return ($now.TimeOfDay -ge $warmupStart) -and ($now.TimeOfDay -lt $sessionOpen)
}

function Test-LiveRuntimeRecentlyStarted {
    param(
        [Parameter(Mandatory = $false)]
        [object]$LiveRuntimeStatus,

        [Parameter(Mandatory = $false)]
        [int]$GraceSeconds = 90
    )

    if ($null -eq $LiveRuntimeStatus -or [string]::IsNullOrWhiteSpace([string]$LiveRuntimeStatus.started_at)) {
        return $false
    }

    try {
        $startedAt = [DateTimeOffset]::Parse([string]$LiveRuntimeStatus.started_at)
        return (([DateTimeOffset]::Now - $startedAt).TotalSeconds -lt $GraceSeconds)
    } catch {
        return $false
    }
}

function Invoke-DashboardRefresh {
    $refreshUrl = "http://{0}:{1}/api/refresh" -f $DashboardHost, $DashboardPort
    $response = Invoke-WebRequest -UseBasicParsing $refreshUrl -TimeoutSec 120
    if ($response.StatusCode -ne 200) {
        throw "dashboard refresh returned HTTP $($response.StatusCode)"
    }
}

function Invoke-PowerShellScriptIsolated {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    $powershellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "$ScriptPath failed with exit code $LASTEXITCODE"
    }
}

while ($true) {
    $errors = @()
    $dashboardAction = "none"
    $dashboardSnapshotAction = "none"
    $liveRuntimeAction = "none"
    $mlMaintenanceAction = "none"
    $dashboardStatus = $null
    $liveRuntimeStatus = $null
    $dashboardSnapshot = $null
    $mlMaintenanceLock = Read-JsonFile -Path $mlMaintenanceLockPath
    $maintenanceInProgress = $null -ne $mlMaintenanceLock
    $currentSessionStatus = Get-CurrentMarketSessionStatus
    $liveRuntimeShouldRun = Test-LiveRuntimeShouldRun -SessionStatus $currentSessionStatus

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

    if ((-not $maintenanceInProgress) -and (-not $dashboardHealthy)) {
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

    $dashboardSnapshotAgeSeconds = Get-DashboardSnapshotAgeSeconds
    $dashboardSnapshotNeedsRefresh = (
        $null -eq $dashboardSnapshotAgeSeconds -or
        [double]$dashboardSnapshotAgeSeconds -ge [double]$DashboardRefreshIntervalSeconds
    )

    if ((-not $maintenanceInProgress) -and $dashboardHealthy -and $dashboardSnapshotNeedsRefresh) {
        try {
            Invoke-DashboardRefresh
            $dashboardSnapshotAction = "server_refresh"
        } catch {
            $dashboardSnapshotAction = "server_refresh_failed"
            $errors += "dashboard_refresh: $($_.Exception.Message)"
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
    $liveRuntimeBlockedReason = ""
    $liveRuntimeCredentialsBlocked = $false
    $liveRuntimeBlockedAction = ""
    if ($null -ne $liveRuntimeStatus) {
        $liveRuntimeHealthy = ([string]$liveRuntimeStatus.status -eq "running")
        $liveRuntimeBlockedReason = [string]$liveRuntimeStatus.blocked_reason
        $liveRuntimeCredentialsBlocked = $liveRuntimeBlockedReason -eq "missing_kis_credentials"
        $liveRuntimeBlockedAction = if ($liveRuntimeCredentialsBlocked) {
            if (-not [bool]$liveRuntimeStatus.env_file_exists) {
                "blocked_missing_env"
            } else {
                "blocked_missing_kis_credentials"
            }
        } else {
            ""
        }
    }

    if (
        (-not $maintenanceInProgress) -and
        $liveRuntimeHealthy -and
        (-not $liveRuntimeShouldRun)
    ) {
        try {
            $null = & (Join-Path $WorkspaceRoot "scripts\stop_live_runtime.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir
            $liveRuntimeAction = "off_session_stop_$currentSessionStatus"
            $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
            $liveRuntimeHealthy = $false
        } catch {
            $liveRuntimeAction = "off_session_stop_failed"
            $errors += "live_runtime_off_session_stop: $($_.Exception.Message)"
        }
    }

    if ((-not $maintenanceInProgress) -and (-not $liveRuntimeHealthy)) {
        if ($liveRuntimeCredentialsBlocked) {
            $liveRuntimeAction = $liveRuntimeBlockedAction
        } elseif (-not $liveRuntimeShouldRun) {
            $liveRuntimeAction = "off_session_hold_$currentSessionStatus"
        } else {
            try {
                $null = & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
                    -WorkspaceRoot $WorkspaceRoot `
                    -RuntimeDataDir $RuntimeDataDir `
                    -ForceRestart
                $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
                    -WorkspaceRoot $WorkspaceRoot `
                    -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json

                if ([string]$liveRuntimeStatus.status -eq "running") {
                    $liveRuntimeAction = if ($currentSessionStatus -eq "pre-open") {
                        "pre_open_warmup_start"
                    } else {
                        "restart"
                    }
                } elseif ([string]$liveRuntimeStatus.blocked_reason -eq "missing_kis_credentials") {
                    $liveRuntimeAction = if (-not [bool]$liveRuntimeStatus.env_file_exists) {
                        "blocked_missing_env"
                    } else {
                        "blocked_missing_kis_credentials"
                    }
                } else {
                    $liveRuntimeAction = "restart_failed"
                    $errors += "live_runtime_restart: live runtime did not stay running after restart attempt"
                }
            } catch {
                $liveRuntimeAction = "restart_failed"
                $errors += "live_runtime_restart: $($_.Exception.Message)"
            }
        }
    }

    $needsLiveRuntimeRecovery = $false
    $needsVerificationRefresh = $false
    $latestVerification = Read-KisVerification
    $systemStatus = if ($null -ne $dashboardSnapshot) { $dashboardSnapshot["system_status"] } else { $null }
    $freshness = if ($null -ne $systemStatus) { $systemStatus["freshness"] } else { $null }
    $marketBarFreshness = if ($null -ne $freshness) { $freshness["latest_market_bar"] } else { $null }
    $verificationFreshness = if ($null -ne $freshness) { $freshness["latest_kis_verification"] } else { $null }
    $liveMarketBarFreshness = if ($null -ne $liveRuntimeStatus) { $liveRuntimeStatus.market_bar_freshness } else { $null }
    $liveVerificationFreshness = if ($null -ne $liveRuntimeStatus) { $liveRuntimeStatus.kis_verification_freshness } else { $null }
    $marketBarState = if ($null -ne $liveMarketBarFreshness) {
        [string]$liveMarketBarFreshness.state
    } elseif ($null -ne $marketBarFreshness) {
        [string]$marketBarFreshness["state"]
    } else {
        "missing"
    }
    $verificationState = if ($null -ne $liveVerificationFreshness) {
        [string]$liveVerificationFreshness.state
    } elseif ($null -ne $verificationFreshness) {
        [string]$verificationFreshness["state"]
    } else {
        "missing"
    }
    $liveRuntimeRecentlyStarted = Test-LiveRuntimeRecentlyStarted -LiveRuntimeStatus $liveRuntimeStatus
    $liveRuntimeProvidesFreshMarketData = (
        ($null -ne $liveRuntimeStatus) -and
        ([string]$liveRuntimeStatus.status -eq "running") -and
        ($currentSessionStatus -eq "regular-session") -and
        ($marketBarState -eq "fresh")
    )

    if (
        ($null -ne $liveRuntimeStatus) -and
        ([string]$liveRuntimeStatus.status -eq "running") -and
        ($currentSessionStatus -eq "regular-session") -and
        (-not $liveRuntimeRecentlyStarted) -and
        (@("missing", "stale") -contains $marketBarState)
    ) {
        $needsLiveRuntimeRecovery = $true
    }

    if (
        ($currentSessionStatus -eq "regular-session") -and
        (-not $needsLiveRuntimeRecovery) -and
        (-not $liveRuntimeProvidesFreshMarketData) -and
        (
            ($null -eq $latestVerification) -or
            (@("stale", "missing") -contains $verificationState)
        )
    ) {
        $needsVerificationRefresh = $true
    }

    if ((-not $maintenanceInProgress) -and $needsLiveRuntimeRecovery) {
        try {
            $null = & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -ForceRestart
            $liveRuntimeAction = "restart_stale_runtime_watchlist"
            $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
            try {
                Invoke-DashboardRefresh
                $dashboardSnapshot = Read-DashboardSnapshot
            } catch {
                $errors += "dashboard_refresh_after_live_restart: $($_.Exception.Message)"
            }
        } catch {
            $liveRuntimeAction = "restart_stale_runtime_failed"
            $errors += "live_runtime_stale_restart: $($_.Exception.Message)"
        }
    }

    if ((-not $maintenanceInProgress) -and $needsVerificationRefresh) {
        try {
            & python -m app --verify-kis-ws --symbols $symbolForVerification --max-frames 10 --max-reconnects 1 | Out-Null
            $dashboardSnapshotAction = "refresh_kis_verification"
            Invoke-DashboardRefresh
            $dashboardSnapshot = Read-DashboardSnapshot
        } catch {
            $dashboardSnapshotAction = "refresh_kis_verification_failed"
            $errors += "kis_verification_refresh: $($_.Exception.Message)"
        }
    }

    $todayKey = Get-Date -Format "yyyy-MM-dd"
    $now = Get-Date
    $isWeekday = $now.DayOfWeek -notin @([System.DayOfWeek]::Saturday, [System.DayOfWeek]::Sunday)
    $afterClose = ($now.Hour -gt 16) -or (($now.Hour -eq 16) -and ($now.Minute -ge 5))
    $mlMaintenanceState = Read-JsonFile -Path $mlMaintenanceStatePath
    $mlMaintenanceAlreadyRan = (
        $null -ne $mlMaintenanceState -and
        [string]$mlMaintenanceState["maintenance_date"] -eq $todayKey -and
        [string]$mlMaintenanceState["status"] -eq "ok"
    )

    if ((-not $maintenanceInProgress) -and $isWeekday -and $afterClose -and -not $mlMaintenanceAlreadyRan) {
        try {
            $mlMaintenanceAction = "post_close_ml_rebuild_starting"
            Write-WatchdogState `
                -Status "running" `
                -DashboardAction $dashboardAction `
                -DashboardSnapshotAction $dashboardSnapshotAction `
                -LiveRuntimeAction $liveRuntimeAction `
                -MlMaintenanceAction $mlMaintenanceAction `
                -Errors $errors `
                -DashboardStatus $dashboardStatus `
                -LiveRuntimeStatus $liveRuntimeStatus `
                -MarketSessionStatus $currentSessionStatus `
                -LiveRuntimeShouldRun $liveRuntimeShouldRun

            Invoke-PowerShellScriptIsolated `
                -ScriptPath (Join-Path $WorkspaceRoot "scripts\run_post_close_ml_maintenance.ps1") `
                -Arguments @(
                    "-WorkspaceRoot", $WorkspaceRoot,
                    "-RuntimeDataDir", $RuntimeDataDir
                )
            $mlMaintenanceAction = "post_close_ml_rebuild"
            $dashboardSnapshot = Read-DashboardSnapshot
        } catch {
            $mlMaintenanceAction = "post_close_ml_rebuild_failed"
            $errors += "post_close_ml: $($_.Exception.Message)"
        }
    }

    if ($dashboardSnapshotAction -eq "none") {
        $dashboardSnapshotAction = "client_refresh"
    }
    if ($maintenanceInProgress) {
        if ($dashboardAction -eq "none") {
            $dashboardAction = "maintenance_hold"
        }
        if ($liveRuntimeAction -eq "none") {
            $liveRuntimeAction = "maintenance_hold"
        }
        if ($dashboardSnapshotAction -eq "client_refresh") {
            $dashboardSnapshotAction = "maintenance_hold"
        }
        if ($mlMaintenanceAction -eq "none") {
            $mlMaintenanceAction = "running"
        }
    }

    $status = if ($errors.Count -eq 0) { "running" } else { "warning" }
    Write-WatchdogState `
        -Status $status `
        -DashboardAction $dashboardAction `
        -DashboardSnapshotAction $dashboardSnapshotAction `
        -LiveRuntimeAction $liveRuntimeAction `
        -MlMaintenanceAction $mlMaintenanceAction `
        -Errors $errors `
        -DashboardStatus $dashboardStatus `
        -LiveRuntimeStatus $liveRuntimeStatus `
        -MarketSessionStatus $currentSessionStatus `
        -LiveRuntimeShouldRun $liveRuntimeShouldRun

    if ($SinglePass) {
        break
    }

    Start-Sleep -Seconds $IntervalSeconds
}
