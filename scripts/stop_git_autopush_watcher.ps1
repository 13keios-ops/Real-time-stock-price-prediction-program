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
$watcherScriptPath = Join-Path $toolRoot "scripts\watch_git_versions_and_push.ps1"

function Get-WatcherProcesses {
    param([string]$WatcherPath)

    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -in @("powershell.exe", "pwsh.exe")) -and
            -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
            $_.CommandLine -like "*$WatcherPath*"
        }

    return @($processes)
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and "$($task.State)" -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } while ($task -and "$($task.State)" -eq "Running" -and (Get-Date) -lt $deadline)
}

$watcherProcesses = Get-WatcherProcesses -WatcherPath $watcherScriptPath
foreach ($process in $watcherProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

if ($watcherProcesses.Count -gt 0) {
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $watcherProcesses = Get-WatcherProcesses -WatcherPath $watcherScriptPath
    } while ($watcherProcesses.Count -gt 0 -and (Get-Date) -lt $deadline)
}

$status = & $statusScript -TaskName $TaskName -AsJson | ConvertFrom-Json

if ($AsJson) {
    $status | ConvertTo-Json -Depth 6
} else {
    $status
}
