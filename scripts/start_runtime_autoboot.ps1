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
    [string]$Symbols = "",

    [Parameter(Mandatory = $false)]
    [switch]$SkipDashboard,

    [Parameter(Mandatory = $false)]
    [switch]$SkipLiveRuntime,

    [Parameter(Mandatory = $false)]
    [switch]$SkipAccountRefresh,

    [Parameter(Mandatory = $false)]
    [switch]$SkipDashboardBuild,

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

$stateDir = Join-Path $RuntimeDataDir "reports\runtime-autoboot\state"
$statePath = Join-Path $stateDir "latest-autoboot.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

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

function Read-JsonFile {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return $null
    }
    return Get-Content -LiteralPath $LiteralPath -Raw | ConvertFrom-Json
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

$dashboardState = $null
$liveRuntimeState = $null
$watchdogState = $null
$kisAccount = $null
$brokerPaperSync = $null
$paperReconciliation = $null
$paperAlignment = $null
$runtimeReport = $null
$errors = @()

try {
    if (-not $SkipAccountRefresh) {
        Invoke-AppCommand -Arguments @("-m", "app", "--kis-account-balance") -DiscardOutput
        $kisAccount = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\kis-account\latest-account-paper.json")
        if ($null -eq $kisAccount) {
            $kisAccount = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\kis-account\latest-account.json")
        }
        Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
        $brokerPaperSync = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\broker-paper\latest-sync.json")
        Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput
        $paperReconciliation = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\reconciliation\latest-paper-account-sync.json")
        if (Test-NeedsBrokerPaperAlignment -PaperReconciliation $paperReconciliation) {
            Invoke-AppCommand -Arguments @("-m", "app", "--align-local-paper-to-broker") -DiscardOutput
            $paperAlignment = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\broker-paper\latest-alignment.json")
            Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
            $brokerPaperSync = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\broker-paper\latest-sync.json")
            Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput
            $paperReconciliation = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\reconciliation\latest-paper-account-sync.json")
        }
    }
} catch {
    $errors += "kis_account: $($_.Exception.Message)"
}

try {
    if (-not $SkipDashboard) {
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
    }
} catch {
    $errors += "dashboard: $($_.Exception.Message)"
}

try {
    if (-not $SkipLiveRuntime) {
        $null = & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir `
            -Symbols $Symbols `
            -ForceRestart:$ForceLiveRuntimeRestart

        Start-Sleep -Seconds 2
        $liveRuntimeState = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    }
} catch {
    $errors += "live_runtime: $($_.Exception.Message)"
}

try {
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
} catch {
    $errors += "watchdog: $($_.Exception.Message)"
}

try {
    if (-not $SkipDashboardBuild) {
        Invoke-AppCommand -Arguments @("-m", "app", "--build-runtime-report") -DiscardOutput
        Invoke-AppCommand -Arguments @("-m", "app", "--build-dashboard") -DiscardOutput
        $runtimeReport = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\runtime\latest-runtime-report.json")
    }
} catch {
    $errors += "reporting: $($_.Exception.Message)"
}

try {
    if (-not $SkipDashboard) {
        $dashboardState = & (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    }
} catch {
    $errors += "dashboard_status: $($_.Exception.Message)"
}

try {
    if (-not $SkipLiveRuntime) {
        $liveRuntimeState = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    }
} catch {
    $errors += "live_runtime_status: $($_.Exception.Message)"
}

try {
    if (-not $SkipWatchdog) {
        $watchdogState = & (Join-Path $WorkspaceRoot "scripts\get_runtime_watchdog_status.ps1") `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
    }
} catch {
    $errors += "watchdog_status: $($_.Exception.Message)"
}

$payload = [ordered]@{
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    dashboard = $dashboardState
    live_runtime = $liveRuntimeState
    watchdog = $watchdogState
    kis_account = $kisAccount
    broker_paper_sync = $brokerPaperSync
    paper_alignment = $paperAlignment
    paper_reconciliation = $paperReconciliation
    runtime_summary = if ($null -ne $runtimeReport) { $runtimeReport.summary } else { $null }
    skipped_dashboard = [bool]$SkipDashboard
    skipped_live_runtime = [bool]$SkipLiveRuntime
    skipped_account_refresh = [bool]$SkipAccountRefresh
    skipped_dashboard_build = [bool]$SkipDashboardBuild
    skipped_watchdog = [bool]$SkipWatchdog
    ok = ($errors.Count -eq 0)
    errors = $errors
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
