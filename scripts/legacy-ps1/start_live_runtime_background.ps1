param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$Symbols = "",

    [Parameter(Mandatory = $false)]
    [string]$WatchlistFile = "config/watchlist.txt",

    [Parameter(Mandatory = $false)]
    [int]$MaxFrames = 0,

    [Parameter(Mandatory = $false)]
    [int]$MaxReconnects = 999999,

    [Parameter(Mandatory = $false)]
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$logDir = Join-Path $RuntimeDataDir "logs\app"
$stateDir = Join-Path $RuntimeDataDir "reports\live-runtime\state"
$statePath = Join-Path $stateDir "listener-state.json"
$stdoutPath = Join-Path $logDir "live-runtime.stdout.log"
$stderrPath = Join-Path $logDir "live-runtime.stderr.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-LogTailSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $false)]
        [int]$Tail = 20
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $lines = Get-Content -LiteralPath $Path -Tail $Tail -ErrorAction SilentlyContinue |
        ForEach-Object { "$_".TrimEnd() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    if (-not $lines) {
        return ""
    }

    return ($lines -join [Environment]::NewLine).Trim()
}

function Get-BlockedReasonFromText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    if ($Text -match "KIS credentials are not configured") {
        return "missing_kis_credentials"
    }

    return ""
}

function Get-LastNonEmptyLine {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    $lines = $Text -split "\r?\n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if (-not $lines) {
        return ""
    }

    return "$($lines[-1])".Trim()
}

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

    throw "Python executable could not be resolved."
}

if ($ForceRestart) {
    $runningLiveProcesses = @(Get-LiveRuntimeProcessRecords)
    foreach ($liveProcess in $runningLiveProcesses) {
        Stop-Process -Id $liveProcess.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($runningLiveProcesses.Count -gt 0) {
        Start-Sleep -Seconds 1
    }
}

if (Test-Path -LiteralPath $statePath) {
    $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($existingState.pid) {
        $existingProcess = Get-LiveRuntimeProcessRecord -ProcessId ([int]$existingState.pid)
        if ($null -ne $existingProcess -and -not $ForceRestart) {
            $existingState.status = "running"
            $existingState.process_running = $true
            $existingState | ConvertTo-Json -Depth 10
            return
        }
        if ($null -ne $existingProcess -and $ForceRestart) {
            Stop-Process -Id $existingProcess.ProcessId -Force
            Start-Sleep -Seconds 1
        }
    }
}

$pythonExe = Resolve-PythonExecutable
$argumentList = @(
    "-m",
    "app",
    "--kis-ws-listen",
    "--max-frames",
    "$MaxFrames",
    "--max-reconnects",
    "$MaxReconnects",
    "--watchlist-file",
    "$WatchlistFile"
)

if ($Symbols) {
    $argumentList += @("--symbols", "$Symbols")
}

$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $argumentList `
    -WorkingDirectory $WorkspaceRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Start-Sleep -Seconds 3
$process.Refresh()
$status = if ($process.HasExited) { "failed" } else { "running" }
$envFilePath = Join-Path $WorkspaceRoot ".env"
$stdoutTail = ""
$stderrTail = ""
$failureReason = ""
$blockedReason = ""
$exitCode = $null
$stoppedAt = $null

if ($process.HasExited) {
    $exitCode = $process.ExitCode
    $stdoutTail = Get-LogTailSummary -Path $stdoutPath
    $stderrTail = Get-LogTailSummary -Path $stderrPath
    $failureReason = if ($stderrTail) {
        Get-LastNonEmptyLine -Text $stderrTail
    } elseif ($stdoutTail) {
        Get-LastNonEmptyLine -Text $stdoutTail
    } else {
        "Live runtime exited immediately after launch."
    }
    $blockedReason = Get-BlockedReasonFromText -Text ($failureReason + [Environment]::NewLine + $stdoutTail)
    $stoppedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
}

$payload = [ordered]@{
    status = $status
    pid = $process.Id
    process_running = (-not $process.HasExited)
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    symbols = $Symbols
    watchlist_file = $WatchlistFile
    max_frames = $MaxFrames
    max_reconnects = $MaxReconnects
    prediction_horizons = @("15", "60")
    trading_signal_horizon = "15"
    stdout_log_path = $stdoutPath
    stderr_log_path = $stderrPath
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    env_file_path = $envFilePath
    env_file_exists = (Test-Path -LiteralPath $envFilePath)
}

if ($null -ne $exitCode) {
    $payload.exit_code = $exitCode
}

if ($stoppedAt) {
    $payload.stopped_at = $stoppedAt
}

if ($failureReason) {
    $payload.failure_reason = $failureReason
}

if ($blockedReason) {
    $payload.blocked_reason = $blockedReason
}

if ($stdoutTail) {
    $payload.stdout_tail = $stdoutTail
}

if ($stderrTail) {
    $payload.stderr_tail = $stderrTail
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
