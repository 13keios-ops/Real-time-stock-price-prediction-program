param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_process_helpers.ps1")

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$statePath = Join-Path $RuntimeDataDir "reports\dashboard\state\server-state.json"

function Get-DashboardProcessRecord {
    param([int]$ProcessId)

    return Get-PythonAppProcessRecord `
        -ProcessId $ProcessId `
        -RequiredCommandPatterns @('(?i)(^|\s)--serve-dashboard(\s|$)')
}

function Get-DashboardProcessRecords {
    return Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $commandLine = "$($_.CommandLine)"
            -not [string]::IsNullOrWhiteSpace($commandLine) -and
            $commandLine -match '(?i)(^|\s)-m\s+app(\s|$)' -and
            $commandLine -match '(?i)(^|\s)--serve-dashboard(\s|$)'
        }
}

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Dashboard server state not found."
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.pid -and -not $state.port) {
    Write-Output "Dashboard server pid is not recorded."
    return
}

$process = $null
$effectivePid = $null
if ($state.pid) {
    $process = Get-DashboardProcessRecord -ProcessId ([int]$state.pid)
    if ($null -ne $process) {
        $effectivePid = $process.ProcessId
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
                $process = Get-DashboardProcessRecord -ProcessId ([int]$tcpConnection.OwningProcess)
                $state.pid = $tcpConnection.OwningProcess
                if ($null -ne $process) {
                    $effectivePid = $process.ProcessId
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
    return
}

$processesToStop = @(Get-DashboardProcessRecords)
if ($processesToStop.Count -eq 0 -and $effectivePid) {
    $processesToStop = @($process)
}

foreach ($processToStop in $processesToStop) {
    Stop-Process -Id $processToStop.ProcessId -Force -ErrorAction SilentlyContinue
}

$payload = [ordered]@{
    status = "stopped"
    pid = $effectivePid
    stopped_pids = @($processesToStop | ForEach-Object { $_.ProcessId })
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
Write-Output "Stopped dashboard server pid $effectivePid."
