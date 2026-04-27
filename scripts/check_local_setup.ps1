[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$reportDir = Join-Path $RuntimeDataDir "reports\recovery"
$jsonReportPath = Join-Path $reportDir "latest-local-setup-check.json"
$mdReportPath = Join-Path $reportDir "latest-local-setup-check.md"
$envFilePath = Join-Path $WorkspaceRoot ".env"
$envExamplePath = Join-Path $WorkspaceRoot ".env.example"
$secretsReadmePath = Join-Path (Split-Path -Parent $WorkspaceRoot) "secrets\README.local.md"
$nasRecoveryRoot = "\\192.168.0.2\backup\repos\real-time-stock-price-prediction-program\recovery-exports"

New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

function Resolve-PythonExecutable {
    try {
        $candidate = & py -3 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and $candidate) {
            return $candidate.Trim()
        }
    } catch {
    }

    try {
        $candidate = & python -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and $candidate) {
            return $candidate.Trim()
        }
    } catch {
    }

    return ""
}

function Test-PythonModule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExecutable,

        [Parameter(Mandatory = $true)]
        [string]$ModuleName
    )

    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        return $false
    }

    try {
        & $PythonExecutable -c "import $ModuleName" | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-JsonScriptResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        return [ordered]@{
            status = "missing_script"
            ok = $false
            message = "Missing script: $ScriptPath"
        }
    }

    try {
        return (& $ScriptPath -WorkspaceRoot $WorkspaceRoot -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json)
    } catch {
        return [ordered]@{
            status = "error"
            ok = $false
            message = $_.Exception.Message
        }
    }
}

$pythonExecutable = Resolve-PythonExecutable
$dashboardStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1")
$liveRuntimeStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1")
$watchdogStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_runtime_watchdog_status.ps1")
$runtimeStartupLauncherStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_runtime_startup_launcher_status.ps1")

$envFileExists = Test-Path -LiteralPath $envFilePath
$envExampleExists = Test-Path -LiteralPath $envExamplePath
$secretsReadmeExists = Test-Path -LiteralPath $secretsReadmePath
$nasRecoveryRootExists = Test-Path -LiteralPath $nasRecoveryRoot
$websocketsAvailable = Test-PythonModule -PythonExecutable $pythonExecutable -ModuleName "websockets"
$lightgbmAvailable = Test-PythonModule -PythonExecutable $pythonExecutable -ModuleName "lightgbm"

$blockers = @()
$nextActions = @()

if ([string]::IsNullOrWhiteSpace($pythonExecutable)) {
    $blockers += "python_missing"
    $nextActions += "Restore the Python executable path or confirm that py/python commands work."
}

if (-not $envFileExists) {
    $blockers += "missing_root_env"
    $nextActions += "Restore the root .env file from the external secrets recovery path."
}

if (-not $secretsReadmeExists) {
    $blockers += "missing_secrets_readme"
    $nextActions += "Recreate the sibling secrets documentation structure."
}

if (-not $nasRecoveryRootExists) {
    $blockers += "nas_recovery_root_unreachable"
    $nextActions += "Check the NAS share connectivity."
}

if (-not $websocketsAvailable) {
    $blockers += "python_module_websockets_missing"
    $nextActions += "Install the websockets package into the Python environment."
}

if ([string]$dashboardStatus.status -ne "running") {
    $blockers += "dashboard_not_running"
    $nextActions += "Restart the dashboard and confirm the /health response."
}

if ([string]$watchdogStatus.status -ne "running") {
    $blockers += "watchdog_not_running"
    $nextActions += "Restart the runtime watchdog."
}

if (-not [bool]$runtimeStartupLauncherStatus.installed) {
    $blockers += "runtime_startup_launcher_missing"
    $nextActions += "Install the runtime startup launcher for the current repo path."
} elseif (-not [bool]$runtimeStartupLauncherStatus.ok) {
    $blockers += "runtime_startup_launcher_stale"
    $nextActions += "Reinstall the runtime startup launcher so it points to the current repo path."
}

if ([string]$liveRuntimeStatus.status -ne "running") {
    if ([string]$liveRuntimeStatus.blocked_reason -eq "missing_kis_credentials") {
        $blockers += "live_runtime_blocked_missing_kis_credentials"
        if ($envFileExists -and [bool]$liveRuntimeStatus.credentials_ready_for_quotes) {
            $nextActions += "Restart the live runtime so the watchdog can resume collection."
        } elseif ($envFileExists) {
            $nextActions += "Check whether the required KIS values in root .env are empty and fill them."
        } else {
            $nextActions += "Restore root .env and then restart the live runtime."
        }
    } else {
        $blockers += "live_runtime_not_running"
        $nextActions += "Inspect the live runtime stderr/stdout logs and restart it."
    }
}

$nextActions = @($nextActions | Select-Object -Unique)

$payload = [ordered]@{
    ok = ($blockers.Count -eq 0)
    checked_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    env_file_path = $envFilePath
    env_file_exists = $envFileExists
    env_example_exists = $envExampleExists
    secrets_readme_path = $secretsReadmePath
    secrets_readme_exists = $secretsReadmeExists
    nas_recovery_root = $nasRecoveryRoot
    nas_recovery_root_exists = $nasRecoveryRootExists
    python_executable = $pythonExecutable
    websockets_available = $websocketsAvailable
    lightgbm_available = $lightgbmAvailable
    dashboard_status = $dashboardStatus
    live_runtime_status = $liveRuntimeStatus
    watchdog_status = $watchdogStatus
    runtime_startup_launcher_status = $runtimeStartupLauncherStatus
    blockers = $blockers
    next_actions = $nextActions
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $jsonReportPath -Encoding UTF8

$mdLines = @(
    "# Local Setup Check",
    "",
    "- checked at: $($payload.checked_at)",
    "- ok: $($payload.ok)",
    "- env file exists: $envFileExists",
    "- env example exists: $envExampleExists",
    "- secrets readme exists: $secretsReadmeExists",
    "- NAS recovery root exists: $nasRecoveryRootExists",
    "- python executable: $pythonExecutable",
    "- websockets available: $websocketsAvailable",
    "- lightgbm available: $lightgbmAvailable",
    "- dashboard status: $($dashboardStatus.status)",
    "- live runtime status: $($liveRuntimeStatus.status)",
    "- watchdog status: $($watchdogStatus.status)",
    "- runtime startup launcher installed: $($runtimeStartupLauncherStatus.installed)",
    "- runtime startup launcher ok: $($runtimeStartupLauncherStatus.ok)",
    "",
    "## Blockers",
    ""
)

if ($blockers.Count -eq 0) {
    $mdLines += "- none"
} else {
    $mdLines += $blockers | ForEach-Object { "- $_" }
}

$mdLines += @(
    "",
    "## Next Actions",
    ""
)

if ($nextActions.Count -eq 0) {
    $mdLines += "- none"
} else {
    $mdLines += $nextActions | ForEach-Object { "- $_" }
}

$mdLines += @(
    "",
    "## Output Paths",
    "",
    "- json: $jsonReportPath",
    "- markdown: $mdReportPath"
)

$mdLines -join [Environment]::NewLine | Set-Content -LiteralPath $mdReportPath -Encoding UTF8

if ($AsJson) {
    $payload | ConvertTo-Json -Depth 10
} else {
    $payload
}
