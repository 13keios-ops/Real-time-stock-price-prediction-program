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

$statePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\until-deadline-runner-state.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Repo review until deadline state not found."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.pid) {
    Write-Output "Repo review until deadline pid is not recorded."
    exit 0
}

$process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    [ordered]@{
        automation_name = $state.automation_name
        status = "stale"
        pid = $state.pid
        stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        deadline_iso = $state.deadline_iso
        error = "Runner process was already not running when stop was requested."
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Output "Repo review until deadline runner was already not running. Marked state as stale."
    exit 0
}

Stop-Process -Id $state.pid -Force

[ordered]@{
    automation_name = $state.automation_name
    status = "stopped"
    pid = $state.pid
    stopped_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    deadline_iso = $state.deadline_iso
    last_run_label = $state.last_run_label
    last_review_path = $state.last_review_path
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8

Write-Output "Stopped repo review until deadline runner pid $($state.pid)."
