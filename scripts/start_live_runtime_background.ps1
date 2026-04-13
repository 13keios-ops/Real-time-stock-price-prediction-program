param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

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

if (Test-Path -LiteralPath $statePath) {
    $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($existingState.pid) {
        $existingProcess = Get-Process -Id $existingState.pid -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess -and -not $ForceRestart) {
            $existingState.status = "running"
            $existingState.process_running = $true
            $existingState | ConvertTo-Json -Depth 10
            exit 0
        }
        if ($null -ne $existingProcess -and $ForceRestart) {
            Stop-Process -Id $existingProcess.Id -Force
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
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
