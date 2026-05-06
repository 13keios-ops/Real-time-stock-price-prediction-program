param(
    [Parameter(Mandatory = $false)]
    [string]$LauncherName = "GitAutoPushWatcher.cmd"
)

$ErrorActionPreference = "Stop"

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$launcherPath = Join-Path $startupDir $LauncherName

if (Test-Path -LiteralPath $launcherPath) {
    Remove-Item -LiteralPath $launcherPath -Force
    Write-Output "Removed startup launcher at $launcherPath"
} else {
    Write-Output "Startup launcher not found at $launcherPath"
}
