param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$DashboardHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$DashboardPort = 8765,

    [Parameter(Mandatory = $false)]
    [string]$LauncherName = "RealTimeStockRuntime.cmd",

    [Parameter(Mandatory = $false)]
    [switch]$SkipLiveRuntime,

    [Parameter(Mandatory = $false)]
    [switch]$SkipAccountRefresh,

    [Parameter(Mandatory = $false)]
    [switch]$SkipDashboardBuild,

    [Parameter(Mandatory = $false)]
    [switch]$PrintOnly
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$powershellPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$autobootPath = Join-Path $WorkspaceRoot "scripts\start_runtime_autoboot.ps1"
$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$launcherPath = Join-Path $startupDir $LauncherName

$arguments = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$autobootPath`"",
    "-WorkspaceRoot", "`"$WorkspaceRoot`"",
    "-RuntimeDataDir", "`"$RuntimeDataDir`"",
    "-DashboardHost", "`"$DashboardHost`"",
    "-DashboardPort", $DashboardPort
)

if ($SkipLiveRuntime) {
    $arguments += "-SkipLiveRuntime"
}
if ($SkipAccountRefresh) {
    $arguments += "-SkipAccountRefresh"
}
if ($SkipDashboardBuild) {
    $arguments += "-SkipDashboardBuild"
}

$commandLine = @"
@echo off
start "RealTimeStockRuntime" /min "$powershellPath" $($arguments -join ' ')
"@

if ($PrintOnly) {
    Write-Output $launcherPath
    Write-Output ""
    Write-Output $commandLine.TrimEnd()
    return
}

New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
Set-Content -LiteralPath $launcherPath -Value $commandLine -Encoding ASCII

Write-Output "Installed runtime startup launcher at $launcherPath"
