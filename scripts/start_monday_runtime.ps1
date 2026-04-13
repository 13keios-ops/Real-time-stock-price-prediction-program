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
    [string]$VerifySymbols = "005930",

    [Parameter(Mandatory = $false)]
    [switch]$SkipMlShadow,

    [Parameter(Mandatory = $false)]
    [switch]$SkipKisVerification,

    [Parameter(Mandatory = $false)]
    [switch]$ForceDashboardRestart
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
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

if (-not $SkipMlShadow) {
    & (Join-Path $WorkspaceRoot "scripts\run_ml_shadow_cycle.ps1")
}

$kisAccount = $null
python -m app --kis-account-balance | Out-Null
$kisAccountPath = Join-Path $RuntimeDataDir "reports\kis-account\latest-account.json"
if (Test-Path -LiteralPath $kisAccountPath) {
    $kisAccount = Get-Content -LiteralPath $kisAccountPath -Raw | ConvertFrom-Json
}

$kisVerification = $null
if (-not $SkipKisVerification) {
    python -m app --verify-kis-ws --symbols $VerifySymbols --max-frames 20 --max-reconnects 1
    $kisVerificationPath = Join-Path $RuntimeDataDir "reports\kis-ws\latest-verification.json"
    if (Test-Path -LiteralPath $kisVerificationPath) {
        $kisVerification = Get-Content -LiteralPath $kisVerificationPath -Raw | ConvertFrom-Json
    }
}

python -m app --build-runtime-report | Out-Null
python -m app --build-dashboard | Out-Null

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
    active_model_version = $registry.active_models.'15'.model_version
    challenger_recommended_action = $challenger.recommended_action
    challenger_walk_forward_gate_status = $challenger.walk_forward_gate_status
    latest_runtime_report_path = $runtimeReportPath
    latest_dashboard_html_path = $dashboardHtmlPath
    latest_kis_account = $kisAccount
    latest_kis_verification = $kisVerification
    runtime_summary = if ($null -ne $runtimeReport) { $runtimeReport.summary } else { $null }
    skipped_ml_shadow = [bool]$SkipMlShadow
    skipped_kis_verification = [bool]$SkipKisVerification
} | ConvertTo-Json -Depth 10
