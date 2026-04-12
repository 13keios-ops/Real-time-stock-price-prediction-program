param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$DashboardHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$Port = 8765,

    [Parameter(Mandatory = $false)]
    [int]$RefreshSeconds = 5,

    [Parameter(Mandatory = $false)]
    [int]$RecentLimit = 10
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$logDir = Join-Path $RuntimeDataDir "logs\app"
$stateDir = Join-Path $RuntimeDataDir "reports\dashboard\state"
$statePath = Join-Path $stateDir "server-state.json"
$stdoutPath = Join-Path $logDir "dashboard-server.stdout.log"
$stderrPath = Join-Path $logDir "dashboard-server.stderr.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-ListeningConnection {
    param([int]$LocalPort)
    return Get-NetTCPConnection -LocalPort $LocalPort -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1
}

function Test-DashboardHealth {
    param([string]$BaseUrl)
    try {
        $healthUrl = "{0}/health" -f $BaseUrl.TrimEnd("/")
        $health = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 3
        return ($health.Content -match '"service"\s*:\s*"dashboard"')
    } catch {
        return $false
    }
}

$existingListener = Get-ListeningConnection -LocalPort $Port
if ($null -ne $existingListener) {
    $existingUrl = "http://{0}:{1}" -f $DashboardHost, $Port
    if (Test-DashboardHealth -BaseUrl $existingUrl) {
        $payload = [ordered]@{
            status = "running"
            pid = $existingListener.OwningProcess
            host = $DashboardHost
            port = $Port
            url = $existingUrl
            refresh_seconds = $RefreshSeconds
            recent_limit = $RecentLimit
            workspace_root = $WorkspaceRoot
            runtime_data_dir = $RuntimeDataDir
            stdout_log_path = $stdoutPath
            stderr_log_path = $stderrPath
            started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
            snapshot_html_path = (Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.html")
            snapshot_json_path = (Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.json")
            process_running = $true
            port_bound = $true
        }
        $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
        $payload | ConvertTo-Json -Depth 10
        exit 0
    }
}

if (Test-Path -LiteralPath $statePath) {
    $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($existingState.pid) {
        $existingProcess = Get-Process -Id $existingState.pid -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess) {
            $existingState.status = "running"
            $existingState.process_running = $true
            $existingState | ConvertTo-Json -Depth 10
            exit 0
        }
    }
}

$scriptPath = Join-Path $WorkspaceRoot "scripts\run_dashboard.ps1"
$process = Start-Process powershell.exe `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $scriptPath,
        "-DashboardHost",
        $DashboardHost,
        "-Port",
        "$Port",
        "-RefreshSeconds",
        "$RefreshSeconds",
        "-RecentLimit",
        "$RecentLimit"
    ) `
    -WorkingDirectory $WorkspaceRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Start-Sleep -Seconds 3
$process.Refresh()
$tcpConnection = Get-ListeningConnection -LocalPort $Port
$status = if ($process.HasExited) { "failed" } elseif ($null -ne $tcpConnection) { "running" } else { "starting" }

$payload = [ordered]@{
    status = $status
    pid = $process.Id
    host = $DashboardHost
    port = $Port
    url = "http://{0}:{1}" -f $DashboardHost, $Port
    refresh_seconds = $RefreshSeconds
    recent_limit = $RecentLimit
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    stdout_log_path = $stdoutPath
    stderr_log_path = $stderrPath
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    snapshot_html_path = (Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.html")
    snapshot_json_path = (Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.json")
    process_running = (-not $process.HasExited)
    port_bound = ($null -ne $tcpConnection)
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
