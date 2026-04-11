param(
    [Parameter(Mandatory = $false)]
    [string]$ScanRoot = "J:\\GitHub",

    [Parameter(Mandatory = $false)]
    [int]$PollSeconds = 60,

    [Parameter(Mandatory = $false)]
    [string]$LauncherName = "GitAutoPushWatcher.cmd",

    [Parameter(Mandatory = $false)]
    [switch]$Recurse,

    [Parameter(Mandatory = $false)]
    [switch]$PrintOnly
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$watcherPath = Join-Path $toolRoot "scripts\watch_git_versions_and_push.ps1"
$powershellPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$launcherPath = Join-Path $startupDir $LauncherName

$arguments = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$watcherPath`"",
    "-ScanRoot", "`"$ScanRoot`"",
    "-PollSeconds", $PollSeconds
)

if ($Recurse) {
    $arguments += "-Recurse"
}

$commandLine = @"
@echo off
start "GitAutoPushWatcher" /min "$powershellPath" $($arguments -join ' ')
"@

if ($PrintOnly) {
    Write-Output $launcherPath
    Write-Output ""
    Write-Output $commandLine.TrimEnd()
    return
}

New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
Set-Content -LiteralPath $launcherPath -Value $commandLine -Encoding ASCII

Write-Output "Installed startup launcher at $launcherPath"
