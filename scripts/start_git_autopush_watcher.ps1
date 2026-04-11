param(
    [Parameter(Mandatory = $false)]
    [string]$TaskName = "GitAutoPushWatcher",

    [Parameter(Mandatory = $false)]
    [switch]$EnsureRegistered,

    [Parameter(Mandatory = $false)]
    [string]$ScanRoot = "J:\\GitHub",

    [Parameter(Mandatory = $false)]
    [int]$PollSeconds = 60,

    [Parameter(Mandatory = $false)]
    [switch]$Recurse,

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$registerScript = Join-Path $toolRoot "scripts\register_git_autopush_task.ps1"
$statusScript = Join-Path $toolRoot "scripts\get_git_autopush_watcher_status.ps1"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    if (-not $EnsureRegistered) {
        throw "Scheduled task '$TaskName' does not exist. Run register_git_autopush_task.ps1 first or use -EnsureRegistered."
    }

    $registerArguments = @{
        ScanRoot = $ScanRoot
        PollSeconds = $PollSeconds
        TaskName = $TaskName
    }

    if ($Recurse) {
        $registerArguments.Recurse = $true
    }

    & $registerScript @registerArguments | Out-Null
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ("$($task.State)" -ne "Running") {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
}

$status = & $statusScript -TaskName $TaskName -AsJson | ConvertFrom-Json

if ($AsJson) {
    $status | ConvertTo-Json -Depth 6
} else {
    $status
}
