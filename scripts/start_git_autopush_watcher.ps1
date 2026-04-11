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
$startupLauncherPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\GitAutoPushWatcher.cmd"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    if ($EnsureRegistered) {
        $registerArguments = @{
            ScanRoot = $ScanRoot
            PollSeconds = $PollSeconds
            TaskName = $TaskName
        }

        if ($Recurse) {
            $registerArguments.Recurse = $true
        }

        try {
            & $registerScript @registerArguments | Out-Null
        } catch {
            if (-not (Test-Path -LiteralPath $startupLauncherPath)) {
                throw
            }
        }
    }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

if ($task) {
    if ("$($task.State)" -ne "Running") {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
    }
} elseif (Test-Path -LiteralPath $startupLauncherPath) {
    Start-Process -FilePath $startupLauncherPath | Out-Null
    Start-Sleep -Seconds 2
} else {
    throw "Scheduled task '$TaskName' does not exist and no startup launcher was found. Run register_git_autopush_task.ps1 or install_git_autopush_startup_launcher.ps1 first."
}

$status = & $statusScript -TaskName $TaskName -AsJson | ConvertFrom-Json

if ($AsJson) {
    $status | ConvertTo-Json -Depth 6
} else {
    $status
}
