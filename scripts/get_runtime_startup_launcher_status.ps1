param(
    [Parameter(Mandatory = $false)]
    [string]$LauncherName = "RealTimeStockRuntime.cmd"
)

$ErrorActionPreference = "Stop"

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$launcherPath = Join-Path $startupDir $LauncherName
$exists = Test-Path -LiteralPath $launcherPath

[ordered]@{
    installed = $exists
    launcher_path = $launcherPath
    startup_dir = $startupDir
    last_write_time = if ($exists) { (Get-Item -LiteralPath $launcherPath).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz") } else { $null }
} | ConvertTo-Json -Depth 10
