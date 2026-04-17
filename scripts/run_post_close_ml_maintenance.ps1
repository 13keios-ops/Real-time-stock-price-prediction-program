param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

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

$startedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
$liveRuntimeWasRunning = $false
$dashboardWasRunning = $false
$errors = @()

([ordered]@{
    status = "running"
    started_at = $startedAt
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    horizon_min = $HorizonMin
    restart_live_runtime = [bool]$RestartLiveRuntime
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
    if ($RestartLiveRuntime -and $liveRuntimeWasRunning) {
        try {
            & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -ForceRestart | Out-Null
        } catch {
            $errors += "live_runtime_restart: $($_.Exception.Message)"
        }
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
    live_runtime_was_running = $liveRuntimeWasRunning
    live_runtime_restarted = [bool]$RestartLiveRuntime -and $liveRuntimeWasRunning
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
