param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$statePath = Join-Path $RuntimeDataDir "reports\dashboard\state\server-state.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Dashboard server state not found."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.pid -and -not $state.port) {
    Write-Output "Dashboard server pid is not recorded."
    exit 0
}

$process = $null
$effectivePid = $null
if ($state.pid) {
    $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        $effectivePid = $process.Id
    }
}

if ($state.port) {
    $tcpConnection = Get-NetTCPConnection -LocalPort $state.port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1
    if ($null -ne $tcpConnection) {
        try {
            $healthUrl = "{0}/health" -f ([string]$state.url).TrimEnd("/")
            $health = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 3
            if ($health.Content -match '"service"\s*:\s*"dashboard"') {
                $process = Get-Process -Id $tcpConnection.OwningProcess -ErrorAction SilentlyContinue
                $state.pid = $tcpConnection.OwningProcess
                if ($null -ne $process) {
                    $effectivePid = $process.Id
                }
            }
        } catch {
        }
    }
}

if ($null -eq $process) {
    $payload = [ordered]@{
        status = "stale"
        pid = $state.pid
        stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        host = $state.host
        port = $state.port
        url = $state.url
        workspace_root = $WorkspaceRoot
        runtime_data_dir = $RuntimeDataDir
        stdout_log_path = $state.stdout_log_path
        stderr_log_path = $state.stderr_log_path
        snapshot_html_path = $state.snapshot_html_path
        snapshot_json_path = $state.snapshot_json_path
        error = "Dashboard process was already not running when stop was requested."
    }
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Output "Dashboard server process was already not running. Marked state as stale."
    exit 0
}

Stop-Process -Id $effectivePid -Force

$payload = [ordered]@{
    status = "stopped"
    pid = $effectivePid
    stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    host = $state.host
    port = $state.port
    url = $state.url
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
    snapshot_html_path = $state.snapshot_html_path
    snapshot_json_path = $state.snapshot_json_path
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output "Stopped dashboard server pid $($process.Id)."
