param(
    [Parameter(Mandatory = $false)]
    [string]$TaskName = "GitAutoPushWatcher",

    [Parameter(Mandatory = $false)]
    [int]$WaitSeconds = 10,

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$statusScript = Join-Path $toolRoot "scripts\get_git_autopush_watcher_status.ps1"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and "$($task.State)" -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } while ($task -and "$($task.State)" -eq "Running" -and (Get-Date) -lt $deadline)
}

$status = & $statusScript -TaskName $TaskName -AsJson | ConvertFrom-Json

if ($AsJson) {
    $status | ConvertTo-Json -Depth 6
} else {
    $status
}
