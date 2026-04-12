param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$TimezoneId = "Korea Standard Time",

    [Parameter(Mandatory = $false)]
    [switch]$RunImmediately = $true
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

function Write-Log {
    param([string]$Message)

    $logPath = Join-Path $RuntimeDataDir "logs\app\hourly-repo-audit.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Update-RunnerState {
    param(
        [string]$Status,
        [datetime]$NextRunAt,
        [string]$LastRunLabel = "",
        [string]$LastReviewPath = "",
        [string]$ErrorText = ""
    )

    $statePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\runner-state.json"
    $payload = [ordered]@{
        automation_name = "Hourly Repo Audit"
        status = $Status
        pid = $PID
        started_at = $script:StartedAt
        updated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        workspace_root = $WorkspaceRoot
        runtime_data_dir = $RuntimeDataDir
        last_run_label = $LastRunLabel
        last_review_path = $LastReviewPath
        next_run_at_kst = $NextRunAt.ToString("yyyy-MM-dd HH:mm:ss")
        error = $ErrorText
    } | ConvertTo-Json -Depth 10

    Set-Content -LiteralPath $statePath -Value $payload -Encoding UTF8
}

New-Item -ItemType Directory -Force `
    (Join-Path $RuntimeDataDir "logs\app"), `
    (Join-Path $RuntimeDataDir "reports\codex\automation\state") | Out-Null

$existingStatePath = Join-Path $RuntimeDataDir "reports\codex\automation\state\runner-state.json"
if (Test-Path -LiteralPath $existingStatePath) {
    try {
        $existingState = Get-Content -LiteralPath $existingStatePath -Raw | ConvertFrom-Json
        if ($existingState.pid) {
            $existingProcess = Get-Process -Id $existingState.pid -ErrorAction SilentlyContinue
            if ($null -ne $existingProcess) {
                Write-Output "Hourly Repo Audit runner is already active with pid $($existingState.pid)."
                exit 0
            }
        }
    } catch {
        # ignore stale state parsing problems and continue
    }
}

$script:StartedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
$iterationScript = Join-Path $WorkspaceRoot "scripts\run_hourly_repo_audit_iteration.ps1"

Write-Log "Hourly repo audit runner started with pid $PID"
$initialNowKst = Get-KstNow -Id $TimezoneId
$initialNextHour = $initialNowKst.AddHours(1)
$initialNextRunAt = Get-Date -Year $initialNextHour.Year -Month $initialNextHour.Month -Day $initialNextHour.Day -Hour $initialNextHour.Hour -Minute 0 -Second 0
Update-RunnerState -Status "starting" -NextRunAt $initialNextRunAt

while ($true) {
    $nowKst = Get-KstNow -Id $TimezoneId
    $nextHour = $nowKst.AddHours(1)
    $nextRunAt = Get-Date -Year $nextHour.Year -Month $nextHour.Month -Day $nextHour.Day -Hour $nextHour.Hour -Minute 0 -Second 0
    $currentReviewPath = Join-Path $RuntimeDataDir ("reports\codex\automation\history\{0}\{1}-review.md" -f $nowKst.ToString("yyyy-MM-dd"), $nowKst.ToString("HHmm"))
    $shouldRun = $RunImmediately -or (($nowKst.Minute -eq 0) -and (-not (Test-Path -LiteralPath $currentReviewPath)))

    if ($shouldRun) {
        try {
            Update-RunnerState -Status "running" -NextRunAt $nextRunAt -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm")
            $outputPath = & powershell -NoProfile -ExecutionPolicy Bypass -File $iterationScript `
                -WorkspaceRoot $WorkspaceRoot `
                -RuntimeDataDir $RuntimeDataDir `
                -TimezoneId $TimezoneId
            if ($LASTEXITCODE -ne 0) {
                throw "Iteration runner exited with code $LASTEXITCODE"
            }

            Update-RunnerState -Status "waiting" -NextRunAt $nextRunAt -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm") -LastReviewPath $outputPath
            Write-Log "Hourly repo audit iteration finished for $($nowKst.ToString("yyyy-MM-dd HH:mm"))"
        } catch {
            Update-RunnerState -Status "failed" -NextRunAt $nextRunAt -LastRunLabel $nowKst.ToString("yyyy-MM-dd HH:mm") -ErrorText $_.Exception.Message
            Write-Log "Hourly repo audit iteration failed: $($_.Exception.Message)"
        }
    } else {
        Update-RunnerState -Status "running" -NextRunAt $nextRunAt
        Write-Log "Skipping duplicate run for $($nowKst.ToString("yyyy-MM-dd HH:mm")); next run at $($nextRunAt.ToString("yyyy-MM-dd HH:mm:ss")) KST"
    }

    $RunImmediately = $false
    $sleepSeconds = [Math]::Max(30, [int]($nextRunAt - (Get-Date)).TotalSeconds)
    Start-Sleep -Seconds $sleepSeconds
}

