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

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Description "Watch opted-in Git repositories and auto commit/push when VERSION changes." `
        -Force `
        -ErrorAction Stop | Out-Null
} catch {
    throw "Failed to register scheduled task '$TaskName' for $userId. $($_.Exception.Message) If this machine blocks scheduled task creation, use install_git_autopush_startup_launcher.ps1 instead."
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Scheduled task '$TaskName' still does not exist after registration."
}

Write-Output "Registered scheduled task '$TaskName' for $userId"
