param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$DashboardHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$Port = 8765,

    [Parameter(Mandatory = $false)]
    [int]$RefreshSeconds = 300,

    [Parameter(Mandatory = $false)]
    [int]$RecentLimit = 100

    ,

    [Parameter(Mandatory = $false)]
    [switch]$ForceRestart
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

function Resolve-PythonExecutable {
    function Test-RealPythonPath {
        param([string]$Candidate)
        if (-not $Candidate) {
            return $false
        }
        $trimmed = $Candidate.Trim()
        if (-not (Test-Path -LiteralPath $trimmed)) {
            return $false
        }
        if ($trimmed -like "*\\WindowsApps\\python.exe") {
            return $false
        }
        return $true
    }

    try {
        $candidate = & py -3 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and (Test-RealPythonPath $candidate)) {
            return $candidate.Trim()
        }
    } catch {
    }

    try {
        $candidate = & python -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and (Test-RealPythonPath $candidate)) {
            return $candidate.Trim()
        }
    } catch {
    }

    $commonCandidates = @(
        "F:\\Programs\\Python\\Python314\\python.exe",
        "$env:LocalAppData\\Programs\\Python\\Python314\\python.exe",
        "$env:LocalAppData\\Programs\\Python\\Python313\\python.exe",
        "$env:LocalAppData\\Programs\\Python\\Python312\\python.exe"
    )
    foreach ($candidate in $commonCandidates) {
        if (Test-RealPythonPath $candidate) {
            return $candidate
        }
    }

    throw "Python executable could not be resolved."
}

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
        if (-not ($health.Content -match '"service"\s*:\s*"dashboard"')) {
            return $false
        }
        $apiUrl = "{0}/api/dashboard.json" -f $BaseUrl.TrimEnd("/")
        $api = Invoke-WebRequest -UseBasicParsing $apiUrl -TimeoutSec 5
        return ($api.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Stop-PortOwnerIfPresent {
    param([int]$LocalPort)
    $listener = Get-ListeningConnection -LocalPort $LocalPort
    if ($null -eq $listener) {
        return $false
    }
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        return $true
    }
    return $false
}

$existingListener = Get-ListeningConnection -LocalPort $Port
if ($null -ne $existingListener) {
    $existingUrl = "http://{0}:{1}" -f $DashboardHost, $Port
    if ($ForceRestart) {
        Stop-PortOwnerIfPresent -LocalPort $Port | Out-Null
        $existingListener = $null
    } elseif (Test-DashboardHealth -BaseUrl $existingUrl) {
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
        if ($null -ne $existingProcess -and -not $ForceRestart) {
            $existingState.status = "running"
            $existingState.process_running = $true
            $existingState | ConvertTo-Json -Depth 10
            exit 0
        }
    }
}

$pythonExe = Resolve-PythonExecutable
$startProcessArgs = @{
    FilePath = $pythonExe
    ArgumentList = @(
        "-m",
        "app",
        "--serve-dashboard",
        "--dashboard-host",
        $DashboardHost,
        "--dashboard-port",
        "$Port",
        "--dashboard-refresh-seconds",
        "$RefreshSeconds",
        "--dashboard-recent-limit",
        "$RecentLimit"
    )
    WorkingDirectory = $WorkspaceRoot
    WindowStyle = "Hidden"
    RedirectStandardOutput = $stdoutPath
    RedirectStandardError = $stderrPath
    PassThru = $true
}

$process = Start-Process @startProcessArgs

Start-Sleep -Seconds 3
$process.Refresh()
$tcpConnection = $null
$dashboardResponding = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    $tcpConnection = Get-ListeningConnection -LocalPort $Port
    if ($null -ne $tcpConnection) {
        $dashboardResponding = Test-DashboardHealth -BaseUrl ("http://{0}:{1}" -f $DashboardHost, $Port)
        if ($dashboardResponding) {
            break
        }
    }
    Start-Sleep -Seconds 1
    $process.Refresh()
}
$effectivePid = if ($null -ne $tcpConnection) { $tcpConnection.OwningProcess } else { $process.Id }
$status = if ($null -ne $tcpConnection -and $dashboardResponding) {
    "running"
} elseif ($process.HasExited) {
    "failed"
} else {
    "starting"
}

$payload = [ordered]@{
    status = $status
    pid = $effectivePid
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
    process_running = ($status -eq "running" -or -not $process.HasExited)
    port_bound = ($null -ne $tcpConnection)
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
