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
    [string]$VerifySymbols = "005930",

    [Parameter(Mandatory = $false)]
    [switch]$SkipMlShadow,

    [Parameter(Mandatory = $false)]
    [switch]$SkipRuntimeCleanup,

    [Parameter(Mandatory = $false)]
    [switch]$SkipLiveRuntime,

    [Parameter(Mandatory = $false)]
    [switch]$SkipKisVerification,

    [Parameter(Mandatory = $false)]
    [switch]$SkipWatchdog,

    [Parameter(Mandatory = $false)]
    [switch]$ForceDashboardRestart,

    [Parameter(Mandatory = $false)]
    [switch]$ForceLiveRuntimeRestart,

    [Parameter(Mandatory = $false)]
    [switch]$ForceWatchdogRestart
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$marketCalendarPath = Join-Path $WorkspaceRoot "config\market_calendar.toml"
$preOpenWarmupMinutes = 60

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
    if ($SessionStatus -ne "pre-open" -or $preOpenWarmupMinutes -le 0) {
        return $false
    }

    $now = Get-Date
    $sessionOpen = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_open" -Default "09:00"))
    $warmupStart = $sessionOpen.Subtract([TimeSpan]::FromMinutes($preOpenWarmupMinutes))

    return ($now.TimeOfDay -ge $warmupStart) -and ($now.TimeOfDay -lt $sessionOpen)
}

function Test-NeedsBrokerPaperAlignment {
    param(
        [Parameter(Mandatory = $false)]
        [object]$PaperReconciliation
    )

    if ($null -eq $PaperReconciliation -or $null -eq $PaperReconciliation.comparison) {
        return $false
    }

    $comparison = $PaperReconciliation.comparison
    return (
        [bool]$comparison.order_mirroring_enabled -and
        [int]$comparison.mirrored_order_count -eq 0 -and
        [int]$comparison.mismatch_count -gt 0
    )
}

if (-not $SkipMlShadow) {
    & (Join-Path $WorkspaceRoot "scripts\run_ml_shadow_cycle.ps1")
}

$dashboardState = $null
$liveRuntimeState = $null
$watchdogState = $null
$runtimeCleanup = $null
$kisAccount = $null
$paperReconciliation = $null
$brokerPaperSync = $null
$paperAlignment = $null
$currentSessionStatus = Get-CurrentMarketSessionStatus
$liveRuntimeShouldRun = Test-LiveRuntimeShouldRun -SessionStatus $currentSessionStatus

if (-not $SkipRuntimeCleanup) {
    Invoke-AppCommand -Arguments @("-m", "app", "--cleanup-runtime-test-data") -DiscardOutput
    $runtimeCleanup = "ok"
}

Invoke-AppCommand -Arguments @("-m", "app", "--kis-account-balance") -DiscardOutput
$kisAccountPath = Join-Path $RuntimeDataDir "reports\kis-account\latest-account-paper.json"
if (-not (Test-Path -LiteralPath $kisAccountPath)) {
    $kisAccountPath = Join-Path $RuntimeDataDir "reports\kis-account\latest-account.json"
}
if (Test-Path -LiteralPath $kisAccountPath) {
    $kisAccount = Get-Content -LiteralPath $kisAccountPath -Raw | ConvertFrom-Json
}
Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
$brokerPaperSyncPath = Join-Path $RuntimeDataDir "reports\broker-paper\latest-sync.json"
if (Test-Path -LiteralPath $brokerPaperSyncPath) {
    $brokerPaperSync = Get-Content -LiteralPath $brokerPaperSyncPath -Raw | ConvertFrom-Json
}
Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput
$paperReconciliationPath = Join-Path $RuntimeDataDir "reports\reconciliation\latest-paper-account-sync.json"
if (Test-Path -LiteralPath $paperReconciliationPath) {
    $paperReconciliation = Get-Content -LiteralPath $paperReconciliationPath -Raw | ConvertFrom-Json
}
if (Test-NeedsBrokerPaperAlignment -PaperReconciliation $paperReconciliation) {
    Invoke-AppCommand -Arguments @("-m", "app", "--align-local-paper-to-broker") -DiscardOutput
    $paperAlignmentPath = Join-Path $RuntimeDataDir "reports\broker-paper\latest-alignment.json"
    if (Test-Path -LiteralPath $paperAlignmentPath) {
        $paperAlignment = Get-Content -LiteralPath $paperAlignmentPath -Raw | ConvertFrom-Json
    }
    Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
    if (Test-Path -LiteralPath $brokerPaperSyncPath) {
        $brokerPaperSync = Get-Content -LiteralPath $brokerPaperSyncPath -Raw | ConvertFrom-Json
    }
    Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput
    if (Test-Path -LiteralPath $paperReconciliationPath) {
        $paperReconciliation = Get-Content -LiteralPath $paperReconciliationPath -Raw | ConvertFrom-Json
    }
}

$null = & (Join-Path $WorkspaceRoot "scripts\start_dashboard_background.ps1") `
    -WorkspaceRoot $WorkspaceRoot `
    -RuntimeDataDir $RuntimeDataDir `
    -DashboardHost $DashboardHost `
    -Port $DashboardPort `
    -ForceRestart:$ForceDashboardRestart

Start-Sleep -Seconds 2
$dashboardState = & (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1") `
    -WorkspaceRoot $WorkspaceRoot `
    -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json

if (-not $SkipLiveRuntime) {
    if ($liveRuntimeShouldRun) {
        $null = & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir `
            -Symbols $VerifySymbols `
            -ForceRestart:$ForceLiveRuntimeRestart
        Start-Sleep -Seconds 2
        $liveRuntimeState = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    } else {
        $null = & (Join-Path $WorkspaceRoot "scripts\stop_live_runtime.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir
        $liveRuntimeState = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    }
}

if (-not $SkipWatchdog) {
    $null = & (Join-Path $WorkspaceRoot "scripts\start_runtime_watchdog_background.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir `
        -DashboardHost $DashboardHost `
        -DashboardPort $DashboardPort `
        -ForceRestart:$ForceWatchdogRestart
    Start-Sleep -Seconds 2
    $watchdogState = & (Join-Path $WorkspaceRoot "scripts\get_runtime_watchdog_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
}

$kisVerification = $null
if (-not $SkipKisVerification) {
    Invoke-AppCommand -Arguments @("-m", "app", "--verify-kis-ws", "--symbols", $VerifySymbols, "--max-frames", "20", "--max-reconnects", "1")
    $kisVerificationPath = Join-Path $RuntimeDataDir "reports\kis-ws\latest-verification.json"
    if (Test-Path -LiteralPath $kisVerificationPath) {
        $kisVerification = Get-Content -LiteralPath $kisVerificationPath -Raw | ConvertFrom-Json
    }
}

Invoke-AppCommand -Arguments @("-m", "app", "--build-runtime-report") -DiscardOutput
Invoke-AppCommand -Arguments @("-m", "app", "--build-dashboard") -DiscardOutput

$registryPath = Join-Path $RuntimeDataDir "ml\registry.json"
$runtimeReportPath = Join-Path $RuntimeDataDir "reports\runtime\latest-runtime-report.json"
$challengerPath = Join-Path $RuntimeDataDir "reports\challengers\latest-challengers-h15.json"
$dashboardHtmlPath = Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.html"

$registry = if (Test-Path -LiteralPath $registryPath) { Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json } else { $null }
$runtimeReport = if (Test-Path -LiteralPath $runtimeReportPath) { Get-Content -LiteralPath $runtimeReportPath -Raw | ConvertFrom-Json } else { $null }
$challenger = if (Test-Path -LiteralPath $challengerPath) { Get-Content -LiteralPath $challengerPath -Raw | ConvertFrom-Json } else { $null }

[ordered]@{
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    dashboard = $dashboardState
    live_runtime = $liveRuntimeState
    watchdog = $watchdogState
    active_model_version = $registry.active_models.'15'.model_version
    challenger_recommended_action = $challenger.recommended_action
    challenger_walk_forward_gate_status = $challenger.walk_forward_gate_status
    latest_runtime_report_path = $runtimeReportPath
    latest_dashboard_html_path = $dashboardHtmlPath
    latest_kis_account = $kisAccount
    latest_broker_paper_sync = $brokerPaperSync
    latest_paper_alignment = $paperAlignment
    latest_paper_reconciliation = $paperReconciliation
    latest_kis_verification = $kisVerification
    runtime_cleanup = $runtimeCleanup
    runtime_summary = if ($null -ne $runtimeReport) { $runtimeReport.summary } else { $null }
    market_session_status = $currentSessionStatus
    live_runtime_should_run = $liveRuntimeShouldRun
    skipped_ml_shadow = [bool]$SkipMlShadow
    skipped_runtime_cleanup = [bool]$SkipRuntimeCleanup
    skipped_live_runtime = [bool]$SkipLiveRuntime
    skipped_watchdog = [bool]$SkipWatchdog
    skipped_kis_verification = [bool]$SkipKisVerification
} | ConvertTo-Json -Depth 10
