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

$statePath = Join-Path $RuntimeDataDir "reports\live-runtime\state\listener-state.json"

function Get-LiveRuntimeProcessRecord {
    param([int]$ProcessId)

    if (-not $ProcessId) {
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace($process.CommandLine)) {
        return $null
    }

    $commandLine = "$($process.CommandLine)"
    if (
        ($commandLine -match '(?i)(^|\s)-m\s+app(\s|$)') -and
        ($commandLine -match '(?i)(^|\s)--kis-ws-listen(\s|$)')
    ) {
        return $process
    }

    return $null
}

function Get-LiveRuntimeProcessRecords {
    return Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $commandLine = "$($_.CommandLine)"
            -not [string]::IsNullOrWhiteSpace($commandLine) -and
            $commandLine -match '(?i)(^|\s)-m\s+app(\s|$)' -and
            $commandLine -match '(?i)(^|\s)--kis-ws-listen(\s|$)'
        }
}

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Live runtime state not found."
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.pid) {
    Write-Output "Live runtime pid is not recorded."
    return
}

$process = Get-LiveRuntimeProcessRecord -ProcessId ([int]$state.pid)
if ($null -eq $process) {
    $payload = [ordered]@{
        status = "stopped"
        pid = $state.pid
        process_running = $false
        stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        workspace_root = $state.workspace_root
        runtime_data_dir = $state.runtime_data_dir
        stdout_log_path = $state.stdout_log_path
        stderr_log_path = $state.stderr_log_path
        error = "Live runtime process was already not running when stop was requested."
    }
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Output "Live runtime process was already not running."
    return
}

$processesToStop = @(Get-LiveRuntimeProcessRecords)
if ($processesToStop.Count -eq 0) {
    $processesToStop = @($process)
}

foreach ($processToStop in $processesToStop) {
    Stop-Process -Id $processToStop.ProcessId -Force -ErrorAction SilentlyContinue
}

$payload = [ordered]@{
    status = "stopped"
    pid = $process.ProcessId
    stopped_pids = @($processesToStop | ForEach-Object { $_.ProcessId })
    process_running = $false
    stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $state.workspace_root
    runtime_data_dir = $state.runtime_data_dir
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$stoppedPidText = (($processesToStop | ForEach-Object { "$($_.ProcessId)" }) -join ", ")
Write-Output "Stopped live runtime pid(s) $stoppedPidText."
