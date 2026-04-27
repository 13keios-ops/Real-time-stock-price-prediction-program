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
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$logDir = Join-Path $RuntimeDataDir "logs\app"
$stateDir = Join-Path $RuntimeDataDir "reports\runtime-watchdog\state"
$statePath = Join-Path $stateDir "watchdog-state.json"
$stdoutPath = Join-Path $logDir "runtime-watchdog.stdout.log"
$stderrPath = Join-Path $logDir "runtime-watchdog.stderr.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-PowerShellExecutable {
    return (Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe")
}

function Quote-PowerShellLiteral {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

if (Test-Path -LiteralPath $statePath) {
    $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($existingState.pid) {
        $existingProcess = Get-Process -Id $existingState.pid -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess -and -not $ForceRestart) {
            [ordered]@{
                status = "running"
                pid = $existingState.pid
                process_running = $true
                workspace_root = $existingState.workspace_root
                runtime_data_dir = $existingState.runtime_data_dir
                dashboard_host = $existingState.dashboard_host
                dashboard_port = $existingState.dashboard_port
                interval_seconds = $existingState.interval_seconds
                started_at = $existingState.started_at
                last_checked_at = $existingState.last_checked_at
                dashboard_action = $existingState.dashboard_action
                live_runtime_action = $existingState.live_runtime_action
                dashboard_status = $existingState.dashboard_status
                live_runtime_status = $existingState.live_runtime_status
                stdout_log_path = $existingState.stdout_log_path
                stderr_log_path = $existingState.stderr_log_path
                errors = $existingState.errors
                raw_status = $existingState.status
            } | ConvertTo-Json -Depth 10
            exit 0
        }
        if ($null -ne $existingProcess -and $ForceRestart) {
            Stop-Process -Id $existingProcess.Id -Force
            Start-Sleep -Seconds 1
        }
    }
}

$powershellExe = Get-PowerShellExecutable
$scriptPath = Join-Path $WorkspaceRoot "scripts\run_runtime_watchdog_loop.ps1"
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
    $IntervalSeconds
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
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    dashboard_host = $DashboardHost
    dashboard_port = $DashboardPort
    interval_seconds = $IntervalSeconds
    stdout_log_path = $stdoutPath
    stderr_log_path = $stderrPath
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
