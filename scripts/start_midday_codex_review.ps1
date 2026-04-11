param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$ReviewDate = "2026-04-11"
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

function Write-Log {
    param([string]$Message)

    $logPath = Join-Path $RuntimeDataDir "logs\app\midday-codex-review.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Parse-ScheduledTime {
    param([string]$DateText, [string]$TimeText)

    return [datetime]::ParseExact(
        "$DateText $TimeText",
        "yyyy-MM-dd HH:mm",
        [System.Globalization.CultureInfo]::InvariantCulture
    )
}

$schemaPath = Join-Path $WorkspaceRoot "config\codex_review_action_items.schema.json"
$runnerPath = Join-Path $WorkspaceRoot "scripts\run_codex_review_iteration_v4.ps1"

New-Item -ItemType Directory -Force `
    $RuntimeDataDir, `
    (Join-Path $RuntimeDataDir "logs\app"), `
    (Join-Path $RuntimeDataDir "reports\codex\intraday\$ReviewDate"), `
    (Join-Path $RuntimeDataDir "reports\codex\eod\$ReviewDate"), `
    (Join-Path $RuntimeDataDir "reports\codex\action-items") | Out-Null

$runStatePath = Join-Path $RuntimeDataDir "reports\codex\run-state.json"
$schedule = @(
    @{ kind = "intraday"; time = "10:00"; label = "1000"; marker = Join-Path $RuntimeDataDir "reports\codex\intraday\$ReviewDate\iteration-1000.md" },
    @{ kind = "intraday"; time = "11:00"; label = "1100"; marker = Join-Path $RuntimeDataDir "reports\codex\intraday\$ReviewDate\iteration-1100.md" },
    @{ kind = "intraday"; time = "12:00"; label = "1200"; marker = Join-Path $RuntimeDataDir "reports\codex\intraday\$ReviewDate\iteration-1200.md" },
    @{ kind = "integration"; time = "12:20"; label = "1220"; marker = Join-Path $RuntimeDataDir "reports\codex\eod\$ReviewDate\integration-1220.md" },
    @{ kind = "final"; time = "12:40"; label = "1240"; marker = Join-Path $RuntimeDataDir "reports\codex\eod\$ReviewDate\final-improvement-plan.md" }
)

$runState = [ordered]@{
    review_date = $ReviewDate
    started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    workspace_root = $WorkspaceRoot
    runtime_data_dir = $RuntimeDataDir
    schedule = $schedule | ForEach-Object {
        [ordered]@{
            kind = $_.kind
            time = $_.time
            label = $_.label
            marker = $_.marker
        }
    }
}

$runState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runStatePath -Encoding UTF8
Write-Log "Midday Codex review runner started"

foreach ($job in $schedule) {
    $scheduledAt = Parse-ScheduledTime -DateText $ReviewDate -TimeText $job.time
    $now = Get-Date

    if ($now -lt $scheduledAt) {
        $sleepSeconds = [Math]::Max(0, [int]($scheduledAt - $now).TotalSeconds)
        Write-Log "Sleeping $sleepSeconds seconds until $($job.time) for $($job.kind)"
        Start-Sleep -Seconds $sleepSeconds
    } elseif (Test-Path -LiteralPath $job.marker) {
        Write-Log "Skipping $($job.kind) $($job.label) because output already exists"
        continue
    } else {
        Write-Log "Scheduled time $($job.time) has passed; running $($job.kind) $($job.label) immediately"
    }

    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $runnerPath `
            -ReviewKind $job.kind `
            -WorkspaceRoot $WorkspaceRoot `
            -RuntimeDataDir $RuntimeDataDir `
            -ReviewDate $ReviewDate `
            -TimeLabel $job.label `
            -BacklogSchemaPath $schemaPath | Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Iteration runner exited with code $LASTEXITCODE"
        }
    } catch {
        Write-Log "Iteration $($job.kind)/$($job.label) failed: $($_.Exception.Message)"
    }
}

Write-Log "Midday Codex review runner completed"
