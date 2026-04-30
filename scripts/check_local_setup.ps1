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
$marketCalendarPath = Join-Path $WorkspaceRoot "config\market_calendar.toml"

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

function Get-EnvFileMap {
    param([string]$LiteralPath)

    $map = @{}
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return $map
    }

    foreach ($line in [System.IO.File]::ReadAllLines($LiteralPath, [System.Text.Encoding]::UTF8)) {
        if ($line -match '^\s*#') {
            continue
        }

        $separatorIndex = $line.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()
        $map[$key] = $value
    }

    return $map
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

function Get-MarketTimeSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Default
    )

    if (-not (Test-Path -LiteralPath $marketCalendarPath)) {
        return $Default
    }

    $pattern = "^\s*$([regex]::Escape($Key))\s*=\s*`"([^`"]+)`""
    $match = [System.IO.File]::ReadAllLines($marketCalendarPath) |
        Where-Object { $_ -match $pattern } |
        Select-Object -First 1
    if ($match -and $match -match $pattern) {
        return $Matches[1]
    }

    return $Default
}

function Get-CurrentMarketSessionStatus {
    $now = Get-Date
    if ($now.DayOfWeek -in @([System.DayOfWeek]::Saturday, [System.DayOfWeek]::Sunday)) {
        return "weekend"
    }

    $sessionOpen = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_open" -Default "09:00"))
    $sessionClose = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_close" -Default "15:30"))
    $currentTime = $now.TimeOfDay

    if ($currentTime -lt $sessionOpen) {
        return "pre-open"
    }
    if ($currentTime -gt $sessionClose) {
        return "post-close"
    }
    return "regular-session"
}

function Test-LiveRuntimeShouldRun {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SessionStatus,

        [Parameter(Mandatory = $false)]
        [int]$PreOpenWarmupMinutes = 60
    )

    if ($SessionStatus -eq "regular-session") {
        return $true
    }
    if ($SessionStatus -ne "pre-open" -or $PreOpenWarmupMinutes -le 0) {
        return $false
    }

    $now = Get-Date
    $sessionOpen = [TimeSpan]::Parse((Get-MarketTimeSetting -Key "session_open" -Default "09:00"))
    $warmupStart = $sessionOpen.Subtract([TimeSpan]::FromMinutes($PreOpenWarmupMinutes))

    return ($now.TimeOfDay -ge $warmupStart) -and ($now.TimeOfDay -lt $sessionOpen)
}

$pythonExecutable = Resolve-PythonExecutable
$dashboardStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1")
$liveRuntimeStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1")
$watchdogStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_runtime_watchdog_status.ps1")
$runtimeStartupLauncherStatus = Get-JsonScriptResult -ScriptPath (Join-Path $WorkspaceRoot "scripts\get_runtime_startup_launcher_status.ps1")

$envFileExists = Test-Path -LiteralPath $envFilePath
$envValues = Get-EnvFileMap -LiteralPath $envFilePath
$tradingMode = if ($envValues.ContainsKey("TRADING_MODE")) { [string]$envValues["TRADING_MODE"] } else { "" }
$brokerPaperMirroringEnabled = (
    $envValues.ContainsKey("ENABLE_BROKER_PAPER_MIRRORING") -and
    [string]$envValues["ENABLE_BROKER_PAPER_MIRRORING"] -eq "true"
)
$paperAccountPresent = (
    $envValues.ContainsKey("KIS_ACCOUNT_NO_PAPER") -and
    -not [string]::IsNullOrWhiteSpace([string]$envValues["KIS_ACCOUNT_NO_PAPER"])
)
$paperAccountShapeValid = (
    $paperAccountPresent -and
    [string]$envValues["KIS_ACCOUNT_NO_PAPER"] -match '^\d{8}(-\d{2})?$'
)
$paperProductCodePresent = (
    $envValues.ContainsKey("KIS_PRODUCT_CODE_PAPER") -and
    -not [string]::IsNullOrWhiteSpace([string]$envValues["KIS_PRODUCT_CODE_PAPER"])
)
$paperProductCodeEffective = ($paperProductCodePresent -or $paperAccountPresent)
$envExampleExists = Test-Path -LiteralPath $envExamplePath
$secretsReadmeExists = Test-Path -LiteralPath $secretsReadmePath
$nasRecoveryRootExists = Test-Path -LiteralPath $nasRecoveryRoot
$websocketsAvailable = Test-PythonModule -PythonExecutable $pythonExecutable -ModuleName "websockets"
$lightgbmAvailable = Test-PythonModule -PythonExecutable $pythonExecutable -ModuleName "lightgbm"
$currentSessionStatus = Get-CurrentMarketSessionStatus
$liveRuntimeShouldRun = Test-LiveRuntimeShouldRun -SessionStatus $currentSessionStatus

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

if ($envFileExists -and $tradingMode -eq "paper" -and $brokerPaperMirroringEnabled -and -not $paperAccountPresent) {
    $blockers += "kis_paper_account_missing"
    $nextActions += "Fill KIS_ACCOUNT_NO_PAPER in root .env, then refresh the broker paper-account reports."
}

if ($envFileExists -and $tradingMode -eq "paper" -and $brokerPaperMirroringEnabled -and $paperAccountPresent -and -not $paperAccountShapeValid) {
    $blockers += "kis_paper_account_invalid_format"
    $nextActions += "Fill KIS_ACCOUNT_NO_PAPER with the full 8-digit paper account number, or 8 digits-2 digits if copied with a suffix."
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

$watchdogStatusValue = [string]$watchdogStatus.status
$watchdogProcessRunning = [bool]$watchdogStatus.process_running
if ($watchdogStatusValue -ne "running" -and -not ($watchdogStatusValue -eq "warning" -and $watchdogProcessRunning)) {
    $blockers += "watchdog_not_running"
    $nextActions += "Restart the runtime watchdog."
} elseif ($watchdogStatusValue -eq "warning") {
    $nextActions += "Inspect runtime watchdog warning details if the warning persists across the next cycle."
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
    } elseif ($liveRuntimeShouldRun) {
        $blockers += "live_runtime_not_running"
        $nextActions += "Inspect the live runtime stderr/stdout logs and restart it."
    } else {
        $nextActions += "Live runtime is stopped because the current market session is $currentSessionStatus."
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
    trading_mode = $tradingMode
    broker_paper_mirroring_enabled = $brokerPaperMirroringEnabled
    kis_paper_account_present = $paperAccountPresent
    kis_paper_account_shape_valid = $paperAccountShapeValid
    kis_paper_product_code_explicit_present = $paperProductCodePresent
    kis_paper_product_code_effective = $paperProductCodeEffective
    env_example_exists = $envExampleExists
    secrets_readme_path = $secretsReadmePath
    secrets_readme_exists = $secretsReadmeExists
    nas_recovery_root = $nasRecoveryRoot
    nas_recovery_root_exists = $nasRecoveryRootExists
    python_executable = $pythonExecutable
    websockets_available = $websocketsAvailable
    lightgbm_available = $lightgbmAvailable
    current_session_status = $currentSessionStatus
    live_runtime_should_run = $liveRuntimeShouldRun
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
    "- trading mode: $tradingMode",
    "- broker paper mirroring enabled: $brokerPaperMirroringEnabled",
    "- KIS paper account present: $paperAccountPresent",
    "- KIS paper account shape valid: $paperAccountShapeValid",
    "- KIS paper product code explicit present: $paperProductCodePresent",
    "- KIS paper product code effective: $paperProductCodeEffective",
    "- env example exists: $envExampleExists",
    "- secrets readme exists: $secretsReadmeExists",
    "- NAS recovery root exists: $nasRecoveryRootExists",
    "- python executable: $pythonExecutable",
    "- websockets available: $websocketsAvailable",
    "- lightgbm available: $lightgbmAvailable",
    "- current session status: $currentSessionStatus",
    "- live runtime should run: $liveRuntimeShouldRun",
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
