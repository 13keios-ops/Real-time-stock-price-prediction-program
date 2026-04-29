param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [int]$HorizonMin = 15,

    [Parameter(Mandatory = $false)]
    [switch]$RestartLiveRuntime
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$stateDir = Join-Path $RuntimeDataDir "reports\ml-maintenance\state"
$statePath = Join-Path $stateDir "latest-post-close-ml.json"
$lockPath = Join-Path $stateDir "maintenance-in-progress.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Read-JsonFile {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $LiteralPath -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Invoke-AppCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $false)]
        [switch]$DiscardOutput
    )

    if ($DiscardOutput) {
        & python @Arguments | Out-Null
    } else {
        & python @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "python $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-MarketTimeSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Default
    )

    $marketCalendarPath = Join-Path $WorkspaceRoot "config\market_calendar.toml"
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

function Get-CurrentMarketSessionStatus {
    $now = Get-Date
    if ($now.DayOfWeek -in @([System.DayOfWeek]::Saturday, [System.DayOfWeek]::Sunday)) {
        return "weekend"
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

$startedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
$liveRuntimeWasRunning = $false
$dashboardWasRunning = $false
$marketSessionStatus = Get-CurrentMarketSessionStatus
$liveRuntimeRestarted = $false
$liveRuntimeRestartSkippedReason = ""
$errors = @()

([ordered]@{
    status = "running"
    started_at = $startedAt
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    horizon_min = $HorizonMin
    restart_live_runtime = [bool]$RestartLiveRuntime
    market_session_status = $marketSessionStatus
}) | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $lockPath -Encoding UTF8

try {
    $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    $liveRuntimeWasRunning = ($null -ne $liveRuntimeStatus) -and ([string]$liveRuntimeStatus.status -eq "running")
} catch {
    $errors += "live_runtime_status: $($_.Exception.Message)"
}

try {
    $dashboardStatus = & (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    $dashboardWasRunning = ($null -ne $dashboardStatus) -and ([string]$dashboardStatus.status -eq "running")
} catch {
    $errors += "dashboard_status: $($_.Exception.Message)"
}

try {
    if ($dashboardWasRunning) {
        & (Join-Path $WorkspaceRoot "scripts\stop_dashboard.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | Out-Null
        Start-Sleep -Seconds 2
    }
    if ($liveRuntimeWasRunning) {
        & (Join-Path $WorkspaceRoot "scripts\stop_live_runtime.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | Out-Null
        Start-Sleep -Seconds 2
    }

    Invoke-AppCommand -Arguments @("-m", "app", "--rebuild-actual-ml", "--horizon-min", "$HorizonMin") -DiscardOutput
    Invoke-AppCommand -Arguments @("-m", "app", "--build-runtime-report") -DiscardOutput
    Invoke-AppCommand -Arguments @("-m", "app", "--build-dashboard") -DiscardOutput
} catch {
    $errors += "post_close_ml: $($_.Exception.Message)"
} finally {
    if ($RestartLiveRuntime -and $liveRuntimeWasRunning -and $marketSessionStatus -eq "regular-session") {
        try {
            & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -ForceRestart | Out-Null
            $liveRuntimeRestarted = $true
        } catch {
            $errors += "live_runtime_restart: $($_.Exception.Message)"
        }
    } elseif ($RestartLiveRuntime -and $liveRuntimeWasRunning) {
        $liveRuntimeRestartSkippedReason = "off_session_$marketSessionStatus"
    }
    if ($dashboardWasRunning) {
        try {
            & (Join-Path $WorkspaceRoot "scripts\start_dashboard_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -ForceRestart | Out-Null
        } catch {
            $errors += "dashboard_restart: $($_.Exception.Message)"
        }
    }
}

$runtimeReport = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\runtime\latest-runtime-report.json")
$dashboardReport = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.json")
$rebuildState = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\actual-ml\latest-rebuild.json")

$payload = [ordered]@{
    status = $(if ($errors.Count -eq 0) { "ok" } else { "warning" })
    maintenance_date = (Get-Date -Format "yyyy-MM-dd")
    started_at = $startedAt
    completed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    horizon_min = $HorizonMin
    market_session_status = $marketSessionStatus
    live_runtime_was_running = $liveRuntimeWasRunning
    live_runtime_restarted = $liveRuntimeRestarted
    live_runtime_restart_skipped_reason = $liveRuntimeRestartSkippedReason
    dashboard_was_running = $dashboardWasRunning
    rebuild_state = $rebuildState
    runtime_summary = if ($null -ne $runtimeReport) { $runtimeReport.summary } else { $null }
    dashboard_generated_at = if ($null -ne $dashboardReport) { $dashboardReport.generated_at } else { $null }
    errors = $errors
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
if (Test-Path -LiteralPath $lockPath) {
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
$payload | ConvertTo-Json -Depth 10
