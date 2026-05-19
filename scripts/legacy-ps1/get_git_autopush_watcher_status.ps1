param(
    [Parameter(Mandatory = $false)]
    [string]$TaskName = "GitAutoPushWatcher",

    [Parameter(Mandatory = $false)]
    [string]$StatePath = "",

    [Parameter(Mandatory = $false)]
    [string]$LogPath = "",

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$defaultRuntimeDir = Join-Path $toolRoot "runtime-data\autopush"
$startupLauncherPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\GitAutoPushWatcher.cmd"
$watcherScriptPath = Join-Path $toolRoot "scripts\watch_git_versions_and_push.ps1"

if (-not $StatePath) {
    $StatePath = Join-Path $defaultRuntimeDir "git-autopush-state.json"
}

if (-not $LogPath) {
    $LogPath = Join-Path $defaultRuntimeDir "git-autopush.log"
}

function Get-TaskArgumentValue {
    param(
        [string]$Arguments,
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Arguments)) {
        return ""
    }

    $quotedPattern = "-$Name\s+`"([^`"]+)`""
    $plainPattern = "-$Name\s+([^\s]+)"

    if ($Arguments -match $quotedPattern) {
        return $Matches[1]
    }

    if ($Arguments -match $plainPattern) {
        return $Matches[1]
    }

    return ""
}

function Get-OptionalTailLine {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $line = Get-Content -LiteralPath $Path -Tail 1 -ErrorAction SilentlyContinue
    return "$line".Trim()
}

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
$watcherProcesses = Get-WatcherProcesses -WatcherPath $watcherScriptPath

$result = [ordered]@{
    task_name             = $TaskName
    task_exists           = $false
    task_state            = "Missing"
    last_run_time         = $null
    next_run_time         = $null
    last_task_result      = $null
    scan_root             = ""
    poll_seconds          = $null
    recurse               = $false
    launch_mode           = "inactive"
    startup_launcher_path = $startupLauncherPath
    startup_launcher_exists = Test-Path -LiteralPath $startupLauncherPath
    watcher_process_count = @($watcherProcesses).Count
    watcher_pids          = @($watcherProcesses | Select-Object -ExpandProperty ProcessId)
    log_path              = $LogPath
    log_exists            = Test-Path -LiteralPath $LogPath
    log_last_write_time   = $null
    log_last_line         = ""
    state_path            = $StatePath
    state_exists          = Test-Path -LiteralPath $StatePath
    state_last_write_time = $null
    managed_repo_count    = 0
    last_state_updated_at = ""
    last_known_results    = @{}
    last_known_notifications = @{}
    telegram_configured   = (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "User"))) -and (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("TELEGRAM_CHAT_ID", "User")))
    healthy               = $false
}

if ($result.log_exists) {
    $logItem = Get-Item -LiteralPath $LogPath
    $result.log_last_write_time = $logItem.LastWriteTime
    $result.log_last_line = Get-OptionalTailLine -Path $LogPath
}

if ($result.state_exists) {
    $stateItem = Get-Item -LiteralPath $StatePath
    $result.state_last_write_time = $stateItem.LastWriteTime

    $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($state.repos) {
        $repoProperties = $state.repos.PSObject.Properties
        $result.managed_repo_count = @($repoProperties).Count

        $lastResults = [ordered]@{}
        $lastNotifications = [ordered]@{}
        foreach ($repoProperty in $repoProperties) {
            $lastResults[$repoProperty.Name] = "$($repoProperty.Value.last_result)"
            $lastNotifications[$repoProperty.Name] = "$($repoProperty.Value.last_notified_at)"
        }

        $result.last_known_results = $lastResults
        $result.last_known_notifications = $lastNotifications
    }

    $result.last_state_updated_at = "$($state.updated_at)"
}

if (-not $task -and $result.startup_launcher_exists) {
    $launcherContent = Get-Content -LiteralPath $startupLauncherPath -Raw -ErrorAction SilentlyContinue
    $pollSecondsValue = Get-TaskArgumentValue -Arguments $launcherContent -Name "PollSeconds"

    $result.scan_root = Get-TaskArgumentValue -Arguments $launcherContent -Name "ScanRoot"
    $result.poll_seconds = if ($pollSecondsValue) { [int]$pollSecondsValue } else { $null }
    $result.recurse = $launcherContent -match "(^|\s)-Recurse(\s|$)"
}

if ($task) {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
    $arguments = "$($task.Actions[0].Arguments)"
    $pollSecondsValue = Get-TaskArgumentValue -Arguments $arguments -Name "PollSeconds"

    $result.task_exists = $true
    $result.task_state = "$($task.State)"
    $result.last_run_time = $taskInfo.LastRunTime
    $result.next_run_time = $taskInfo.NextRunTime
    $result.last_task_result = $taskInfo.LastTaskResult
    $result.scan_root = Get-TaskArgumentValue -Arguments $arguments -Name "ScanRoot"
    $result.poll_seconds = if ($pollSecondsValue) { [int]$pollSecondsValue } else { $null }
    $result.recurse = $arguments -match "(^|\s)-Recurse(\s|$)"
}

if ($result.task_exists -and $result.task_state -eq "Running") {
    $result.launch_mode = "scheduled-task"
} elseif ($result.watcher_process_count -gt 0 -and $result.startup_launcher_exists) {
    $result.launch_mode = "startup-launcher"
} elseif ($result.watcher_process_count -gt 0) {
    $result.launch_mode = "manual"
}

if ($result.log_exists) {
    $basePollSeconds = if ($result.poll_seconds) { $result.poll_seconds } else { 60 }
    $freshnessThresholdSeconds = [Math]::Max(($basePollSeconds * 3), 120)
    $ageSeconds = ((Get-Date) - [datetime]$result.log_last_write_time).TotalSeconds
    $hasRunner = ($result.task_exists -and $result.task_state -eq "Running") -or ($result.watcher_process_count -gt 0)
    $result.healthy = $hasRunner -and ($ageSeconds -le $freshnessThresholdSeconds)
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 6
} else {
    $result
}
