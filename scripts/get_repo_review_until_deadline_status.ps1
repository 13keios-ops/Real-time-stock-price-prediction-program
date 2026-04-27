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

$statePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\until-deadline-runner-state.json"
$runnerScriptPath = Join-Path $WorkspaceRoot "scripts\run_repo_review_until_deadline.ps1"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output "Repo review until deadline state not found."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$processRunning = $false
if ($state.pid) {
    $processRunning = $null -ne (Get-PowerShellScriptProcessRecord -ProcessId ([int]$state.pid) -ScriptPath $runnerScriptPath)
}

$effectiveStatus = $state.status
if ((@("starting", "running", "waiting") -contains [string]$state.status) -and (-not $processRunning)) {
    $effectiveStatus = "stale"
}

[ordered]@{
    automation_name = $state.automation_name
    status = $effectiveStatus
    pid = $state.pid
    process_running = $processRunning
    started_at = $state.started_at
    updated_at = $state.updated_at
    deadline_iso = $state.deadline_iso
    last_run_label = $state.last_run_label
    next_run_at_kst = $state.next_run_at_kst
    last_review_path = $state.last_review_path
    raw_status = $state.status
} | ConvertTo-Json -Depth 10
