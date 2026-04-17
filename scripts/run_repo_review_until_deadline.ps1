param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$TimezoneId = "Korea Standard Time",

    [Parameter(Mandatory = $false)]
    [string]$DeadlineIso = "",

    [Parameter(Mandatory = $false)]
    [switch]$RunImmediately = $true,

    [Parameter(Mandatory = $false)]
    [int]$IterationTimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

function Get-KstNow {
    param([string]$Id)
    try {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById($Id)
    } catch {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Korea Standard Time")
    }
    return [System.TimeZoneInfo]::ConvertTime((Get-Date), $tz)
}

function Get-ResolvedDeadline {
    param(
        [string]$Id,
        [string]$ExplicitIso
    )

    $nowKst = Get-KstNow -Id $Id
    if ($ExplicitIso) {
        $parsed = [datetimeoffset]::Parse($ExplicitIso)
        return $parsed
    }

    $todayDeadline = [datetimeoffset]::Parse(($nowKst.ToString("yyyy-MM-dd") + "T10:00:00+09:00"))
    if ([datetimeoffset]$nowKst -lt $todayDeadline) {
        return $todayDeadline
    }

    return $todayDeadline.AddDays(1)
}

function Write-ReviewLog {
    param([string]$Message)
    $logPath = Join-Path $RuntimeDataDir "logs\app\repo-review-until-deadline.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Update-RunnerState {
    param(
        [string]$Status,
        [string]$DeadlineText,
        [datetimeoffset]$NextRunAt,
        [string]$LastRunLabel = "",
        [string]$LastReviewPath = "",
        [string]$ErrorText = ""
    )

    $statePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\until-deadline-runner-state.json"
    $payload = [ordered]@{
        automation_name = "Repo Review Until Deadline"
        status = $Status
        pid = $PID
        started_at = $script:StartedAt
        updated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        workspace_root = $WorkspaceRoot
        runtime_data_dir = $RuntimeDataDir
        deadline_iso = $DeadlineText
        last_run_label = $LastRunLabel
        last_review_path = $LastReviewPath
        next_run_at_kst = $NextRunAt.ToString("yyyy-MM-dd HH:mm:ss")
        error = $ErrorText
    } | ConvertTo-Json -Depth 10

    Set-Content -LiteralPath $statePath -Value $payload -Encoding UTF8
}

function Get-NextTopOfHour {
    param([datetimeoffset]$NowKst)
    $nextHour = $NowKst.AddHours(1)
    return [datetimeoffset]::Parse(($nextHour.ToString("yyyy-MM-ddTHH:00:00zzz")))
}

function ConvertTo-PowerShellLiteral {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-IterationWithTimeout {
    param(
        [string]$IterationScript,
        [int]$TimeoutSeconds
    )

    $tmpDir = Join-Path $RuntimeDataDir "tmp\repo-review-until-deadline"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    $stdoutPath = Join-Path $tmpDir ("iteration-{0}.stdout.log" -f ([guid]::NewGuid().ToString("N")))
    $stderrPath = Join-Path $tmpDir ("iteration-{0}.stderr.log" -f ([guid]::NewGuid().ToString("N")))
    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $command = @(
        "&"
        (ConvertTo-PowerShellLiteral -Value $IterationScript)
        "-WorkspaceRoot"
        (ConvertTo-PowerShellLiteral -Value $WorkspaceRoot)
        "-RuntimeDataDir"
        (ConvertTo-PowerShellLiteral -Value $RuntimeDataDir)
        "-TimezoneId"
        (ConvertTo-PowerShellLiteral -Value $TimezoneId)
    ) -join " "

    $argumentLine = "-NoProfile -ExecutionPolicy Bypass -Command $command"

    $process = Start-Process -FilePath $powershellExe `
        -ArgumentList $argumentLine `
        -WorkingDirectory $WorkspaceRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    try {
        if (-not (Wait-Process -Id $process.Id -Timeout $TimeoutSeconds -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $stderrText = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }
            throw "Iteration timed out after $TimeoutSeconds seconds. $stderrText".Trim()
        }

        $process.Refresh()
        $stdoutText = if (Test-Path -LiteralPath $stdoutPath) { (Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }
        $stderrText = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }

        if ($process.ExitCode -ne 0) {
            $detail = if ($stderrText) { $stderrText } else { $stdoutText }
            throw "Iteration runner exited with code $($process.ExitCode). $detail".Trim()
        }

        return ($stdoutText -split "(`r`n|`n)" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    } finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

New-Item -ItemType Directory -Force `
    (Join-Path $RuntimeDataDir "logs\app"), `
    (Join-Path $RuntimeDataDir "reports\codex\automation\state") | Out-Null

$existingStatePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\until-deadline-runner-state.json"
if (Test-Path -LiteralPath $existingStatePath) {
    try {
        $existingState = Get-Content -LiteralPath $existingStatePath -Raw | ConvertFrom-Json
        if ($existingState.pid) {
            $existingProcess = Get-Process -Id $existingState.pid -ErrorAction SilentlyContinue
            if ($null -ne $existingProcess) {
                $activeStatuses = @("starting", "running", "waiting")
                if ($activeStatuses -contains [string]$existingState.status) {
                    Write-Output "Repo review until deadline runner is already active with pid $($existingState.pid)."
                    exit 0
                }

                Stop-Process -Id $existingState.pid -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
    }
}

$deadline = Get-ResolvedDeadline -Id $TimezoneId -ExplicitIso $DeadlineIso
$script:StartedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
$iterationScript = Join-Path $WorkspaceRoot "scripts\run_hourly_repo_audit_iteration.ps1"
$deadlineText = $deadline.ToString("yyyy-MM-ddTHH:mm:sszzz")

$initialNextRun = Get-NextTopOfHour -NowKst (Get-KstNow -Id $TimezoneId)
if ($initialNextRun -gt $deadline) {
    $initialNextRun = $deadline
}

Write-ReviewLog "Repo review until deadline runner started with pid $PID (deadline=$deadlineText)"
Update-RunnerState -Status "starting" -DeadlineText $deadlineText -NextRunAt $initialNextRun

while ($true) {
    $nowKst = [datetimeoffset](Get-KstNow -Id $TimezoneId)
    if ($nowKst -ge $deadline) {
        Update-RunnerState -Status "completed" -DeadlineText $deadlineText -NextRunAt $deadline -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm")
        Write-ReviewLog "Deadline reached; runner completed."
        break
    }

    $nextRunAt = Get-NextTopOfHour -NowKst $nowKst
    if ($nextRunAt -gt $deadline) {
        $nextRunAt = $deadline
    }

    $reviewPath = Join-Path $RuntimeDataDir ("reports\codex\automation\history\{0}\{1}-review.md" -f $nowKst.ToString("yyyy-MM-dd"), $nowKst.ToString("HHmm"))
    $shouldRun = $RunImmediately -or (($nowKst.Minute -eq 0) -and (-not (Test-Path -LiteralPath $reviewPath)))

    if ($shouldRun) {
        try {
            Update-RunnerState -Status "running" -DeadlineText $deadlineText -NextRunAt $nextRunAt -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm")
            $outputPath = Invoke-IterationWithTimeout -IterationScript $iterationScript -TimeoutSeconds $IterationTimeoutSeconds
            Update-RunnerState -Status "waiting" -DeadlineText $deadlineText -NextRunAt $nextRunAt -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm") -LastReviewPath $outputPath
            Write-ReviewLog "Repo review iteration finished for $($nowKst.ToString("yyyy-MM-dd HH:mm"))"
        } catch {
            Update-RunnerState -Status "waiting" -DeadlineText $deadlineText -NextRunAt $nextRunAt -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm") -ErrorText $_.Exception.Message
            Write-ReviewLog "Repo review iteration failed: $($_.Exception.Message)"
        }
    } else {
        Update-RunnerState -Status "waiting" -DeadlineText $deadlineText -NextRunAt $nextRunAt
    }

    $RunImmediately = $false
    $sleepSeconds = [Math]::Max(15, [int]($nextRunAt - [datetimeoffset](Get-KstNow -Id $TimezoneId)).TotalSeconds)
    Start-Sleep -Seconds $sleepSeconds
}
