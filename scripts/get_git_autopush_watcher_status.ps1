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

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

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
    startup_launcher_path = $startupLauncherPath
    startup_launcher_exists = Test-Path -LiteralPath $startupLauncherPath
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
        foreach ($repoProperty in $repoProperties) {
            $lastResults[$repoProperty.Name] = "$($repoProperty.Value.last_result)"
        }

        $result.last_known_results = $lastResults
    }

    $result.last_state_updated_at = "$($state.updated_at)"
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

if ($result.task_exists -and $result.task_state -eq "Running" -and $result.log_exists -and $result.poll_seconds) {
    $freshnessThresholdSeconds = [Math]::Max(($result.poll_seconds * 3), 120)
    $ageSeconds = ((Get-Date) - [datetime]$result.log_last_write_time).TotalSeconds
    $result.healthy = $ageSeconds -le $freshnessThresholdSeconds
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 6
} else {
    $result
}
