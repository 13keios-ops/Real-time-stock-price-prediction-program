param(
    [Parameter(Mandatory = $false)]
    [string]$ScanRoot = "J:\\GitHub",

    [Parameter(Mandatory = $false)]
    [int]$PollSeconds = 60,

    [Parameter(Mandatory = $false)]
    [string]$TaskName = "GitAutoPushWatcher",

    [Parameter(Mandatory = $false)]
    [switch]$Recurse
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$watcherPath = Join-Path $toolRoot "scripts\watch_git_versions_and_push.ps1"
$powershellPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$userId = "$env:USERDOMAIN\$env:USERNAME"

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

$action = New-ScheduledTaskAction -Execute $powershellPath -Argument ($arguments -join " ")
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Description "Watch opted-in Git repositories and auto commit/push when VERSION changes." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$TaskName' for $userId"
