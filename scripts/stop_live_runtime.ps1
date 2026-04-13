param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$statePath = Join-Path $RuntimeDataDir "reports\live-runtime\state\listener-state.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Live runtime state not found."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.pid) {
    Write-Output "Live runtime pid is not recorded."
    exit 0
}

$process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
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
    exit 0
}

Stop-Process -Id $process.Id -Force

$payload = [ordered]@{
    status = "stopped"
    pid = $process.Id
    process_running = $false
    stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $state.workspace_root
    runtime_data_dir = $state.runtime_data_dir
    stdout_log_path = $state.stdout_log_path
    stderr_log_path = $state.stderr_log_path
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output "Stopped live runtime pid $($process.Id)."
