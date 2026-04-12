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
$escapedScriptPath = $scriptPath.Replace("'", "''")
$dashboardCommand = "& '$escapedScriptPath' -DashboardHost '$DashboardHost' -Port $Port -RefreshSeconds $RefreshSeconds -RecentLimit $RecentLimit"
$process = Start-Process powershell.exe `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $dashboardCommand
    ) `
    -WorkingDirectory $WorkspaceRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Start-Sleep -Seconds 3
$process.Refresh()
$tcpConnection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" } |
    Select-Object -First 1
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
