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

$runnerStatePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\runner-state.json"
$progressPath = Join-Path $RuntimeDataDir "reports\codex\automation\state\latest-progress.json"
$contextPath = Join-Path $RuntimeDataDir "reports\codex\automation\state\latest-context.md"

if (-not (Test-Path -LiteralPath $runnerStatePath)) {
    Write-Output "Hourly Repo Audit runner state not found."
    exit 0
}

$runnerState = Get-Content -LiteralPath $runnerStatePath -Raw | ConvertFrom-Json
$pidExists = $false
if ($runnerState.pid) {
    $pidExists = $null -ne (Get-Process -Id $runnerState.pid -ErrorAction SilentlyContinue)
}

$summary = [ordered]@{
    automation_name = $runnerState.automation_name
    status = $runnerState.status
    pid = $runnerState.pid
    process_running = $pidExists
    started_at = $runnerState.started_at
    updated_at = $runnerState.updated_at
    last_run_label = $runnerState.last_run_label
    next_run_at_kst = $runnerState.next_run_at_kst
    last_review_path = $runnerState.last_review_path
    latest_progress_path = $progressPath
    latest_context_path = $contextPath
}

$summary | ConvertTo-Json -Depth 10

