param(
    [string]$DashboardHost = "127.0.0.1",
    [int]$Port = 8765,
    [int]$RefreshSeconds = 300,
    [int]$RecentLimit = 100
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

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

$pythonExe = Resolve-PythonExecutable

& $pythonExe -m app `
    --serve-dashboard `
    --dashboard-host $DashboardHost `
    --dashboard-port $Port `
    --dashboard-refresh-seconds $RefreshSeconds `
    --dashboard-recent-limit $RecentLimit
