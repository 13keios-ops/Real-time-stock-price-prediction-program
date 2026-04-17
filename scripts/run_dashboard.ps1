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
    function Test-RealPythonPath {
        param([string]$Candidate)
        if (-not $Candidate) {
            return $false
        }
        $trimmed = $Candidate.Trim()
        if (-not (Test-Path -LiteralPath $trimmed)) {
            return $false
        }
        if ($trimmed -like "*\\WindowsApps\\python.exe") {
            return $false
        }
        return $true
    }

    try {
        $candidate = & py -3 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and (Test-RealPythonPath $candidate)) {
            return $candidate.Trim()
        }
    } catch {
    }

    try {
        $candidate = & python -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and (Test-RealPythonPath $candidate)) {
            return $candidate.Trim()
        }
    } catch {
    }

    $commonCandidates = @(
        "F:\\Programs\\Python\\Python314\\python.exe",
        "$env:LocalAppData\\Programs\\Python\\Python314\\python.exe",
        "$env:LocalAppData\\Programs\\Python\\Python313\\python.exe",
        "$env:LocalAppData\\Programs\\Python\\Python312\\python.exe"
    )
    foreach ($candidate in $commonCandidates) {
        if (Test-RealPythonPath $candidate) {
            return $candidate
        }
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
