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
    [int]$HeartbeatStaleAfterSeconds = 0,

    [Parameter(Mandatory = $false)]
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_process_helpers.ps1")

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$logDir = Join-Path $RuntimeDataDir "logs\app"
$stateDir = Join-Path $RuntimeDataDir "reports\runtime-watchdog\state"
$statePath = Join-Path $stateDir "watchdog-state.json"
$stdoutPath = Join-Path $logDir "runtime-watchdog.stdout.log"
$stderrPath = Join-Path $logDir "runtime-watchdog.stderr.log"
$scriptPath = Join-Path $WorkspaceRoot "scripts\run_runtime_watchdog_loop.ps1"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-PowerShellExecutable {
    return (Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe")
}

function Quote-PowerShellLiteral {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Get-WatchdogHeartbeatInfo {
    param(
        [Parameter(Mandatory = $true)]
        [object]$State,

        [Parameter(Mandatory = $true)]
        [bool]$ProcessRunning
    )

    $intervalSeconds = if ($State.interval_seconds) { [int]$State.interval_seconds } else { 60 }
    $staleAfterSeconds = if ($HeartbeatStaleAfterSeconds -gt 0) {
        $HeartbeatStaleAfterSeconds
    } else {
        [Math]::Max($intervalSeconds * 10, 600)
    }
    $ageSeconds = $null
    $stale = $false
    $timestampText = if ($State.last_checked_at) { [string]$State.last_checked_at } else { [string]$State.started_at }

    if (-not [string]::IsNullOrWhiteSpace($timestampText)) {
        try {
            $checkedAt = [DateTimeOffset]::Parse($timestampText)
            $ageSeconds = [Math]::Round(([DateTimeOffset]::Now - $checkedAt).TotalSeconds, 1)
            $stale = $ProcessRunning -and ($ageSeconds -gt $staleAfterSeconds)
        } catch {
            $stale = $ProcessRunning
        }
    }

    [pscustomobject]@{
        stale = $stale
        age_seconds = $ageSeconds
        stale_after_seconds = $staleAfterSeconds
    }
}

if (Test-Path -LiteralPath $statePath) {
    $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($existingState.pid) {
        $existingProcess = Get-PowerShellScriptProcessRecord -ProcessId ([int]$existingState.pid) -ScriptPath $scriptPath
        $heartbeatInfo = Get-WatchdogHeartbeatInfo -State $existingState -ProcessRunning ($null -ne $existingProcess)
        if ($null -ne $existingProcess -and -not $ForceRestart -and -not [bool]$heartbeatInfo.stale) {
            [ordered]@{
                status = "running"
                pid = $existingState.pid
                process_running = $true
                heartbeat_stale = [bool]$heartbeatInfo.stale
                heartbeat_age_seconds = $heartbeatInfo.age_seconds
                heartbeat_stale_after_seconds = $heartbeatInfo.stale_after_seconds
                workspace_root = $existingState.workspace_root
                runtime_data_dir = $existingState.runtime_data_dir
                dashboard_host = $existingState.dashboard_host
                dashboard_port = $existingState.dashboard_port
                interval_seconds = $existingState.interval_seconds
                dashboard_refresh_interval_seconds = $existingState.dashboard_refresh_interval_seconds
                pre_open_warmup_minutes = $existingState.pre_open_warmup_minutes
                market_session_status = $existingState.market_session_status
                live_runtime_should_run = $existingState.live_runtime_should_run
                started_at = $existingState.started_at
                last_checked_at = $existingState.last_checked_at
                dashboard_action = $existingState.dashboard_action
                dashboard_snapshot_action = $existingState.dashboard_snapshot_action
                live_runtime_action = $existingState.live_runtime_action
                ml_maintenance_action = $existingState.ml_maintenance_action
                dashboard_status = $existingState.dashboard_status
                live_runtime_status = $existingState.live_runtime_status
                stdout_log_path = $existingState.stdout_log_path
                stderr_log_path = $existingState.stderr_log_path
                errors = $existingState.errors
                raw_status = $existingState.status
            } | ConvertTo-Json -Depth 10
            return
        }
        if ($null -ne $existingProcess -and ($ForceRestart -or [bool]$heartbeatInfo.stale)) {
            Stop-Process -Id $existingProcess.ProcessId -Force
            Start-Sleep -Seconds 1
        }
    }
}

$powershellExe = Get-PowerShellExecutable
$commandText = @(
    "&",
    (Quote-PowerShellLiteral $scriptPath),
    "-WorkspaceRoot",
    (Quote-PowerShellLiteral $WorkspaceRoot),
    "-RuntimeDataDir",
    (Quote-PowerShellLiteral $RuntimeDataDir),
    "-DashboardHost",
    (Quote-PowerShellLiteral $DashboardHost),
    "-DashboardPort",
    $DashboardPort,
    "-IntervalSeconds",
    $IntervalSeconds,
    "-DashboardRefreshIntervalSeconds",
    $DashboardRefreshIntervalSeconds,
    "-PreOpenWarmupMinutes",
    $PreOpenWarmupMinutes
) -join " "
$process = Start-Process `
    -FilePath $powershellExe `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-Command", $commandText
    ) `
    -WorkingDirectory $WorkspaceRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Start-Sleep -Seconds 3
$process.Refresh()
$status = if ($process.HasExited) { "failed" } else { "running" }

$payload = [ordered]@{
    status = $status
    pid = $process.Id
    process_running = (-not $process.HasExited)
    heartbeat_stale = $false
    heartbeat_age_seconds = $null
    heartbeat_stale_after_seconds = if ($HeartbeatStaleAfterSeconds -gt 0) { $HeartbeatStaleAfterSeconds } else { [Math]::Max($IntervalSeconds * 10, 600) }
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    dashboard_host = $DashboardHost
    dashboard_port = $DashboardPort
    interval_seconds = $IntervalSeconds
    dashboard_refresh_interval_seconds = $DashboardRefreshIntervalSeconds
    pre_open_warmup_minutes = $PreOpenWarmupMinutes
    stdout_log_path = $stdoutPath
    stderr_log_path = $stderrPath
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
