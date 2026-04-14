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
    [switch]$ForceDashboardRestart,

    [Parameter(Mandatory = $false)]
    [switch]$ForceLiveRuntimeRestart
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$stateDir = Join-Path $RuntimeDataDir "reports\runtime-autoboot\state"
$statePath = Join-Path $stateDir "latest-autoboot.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Read-JsonFile {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return $null
    }
    return Get-Content -LiteralPath $LiteralPath -Raw | ConvertFrom-Json
}

$dashboardState = $null
$liveRuntimeState = $null
$kisAccount = $null
$runtimeReport = $null
$errors = @()

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
    if (-not $SkipAccountRefresh) {
        python -m app --kis-account-balance | Out-Null
        $kisAccount = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\kis-account\latest-account-paper.json")
        if ($null -eq $kisAccount) {
            $kisAccount = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\kis-account\latest-account.json")
        }
    }
} catch {
    $errors += "kis_account: $($_.Exception.Message)"
}

try {
    if (-not $SkipDashboardBuild) {
        python -m app --build-runtime-report | Out-Null
        python -m app --build-dashboard | Out-Null
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

$payload = [ordered]@{
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    dashboard = $dashboardState
    live_runtime = $liveRuntimeState
    kis_account = $kisAccount
    runtime_summary = if ($null -ne $runtimeReport) { $runtimeReport.summary } else { $null }
    skipped_dashboard = [bool]$SkipDashboard
    skipped_live_runtime = [bool]$SkipLiveRuntime
    skipped_account_refresh = [bool]$SkipAccountRefresh
    skipped_dashboard_build = [bool]$SkipDashboardBuild
    ok = ($errors.Count -eq 0)
    errors = $errors
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
