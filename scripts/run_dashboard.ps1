param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8765,
    [int]$RefreshSeconds = 5,
    [int]$RecentLimit = 10
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

python -m app `
    --serve-dashboard `
    --dashboard-host $Host `
    --dashboard-port $Port `
    --dashboard-refresh-seconds $RefreshSeconds `
    --dashboard-recent-limit $RecentLimit
