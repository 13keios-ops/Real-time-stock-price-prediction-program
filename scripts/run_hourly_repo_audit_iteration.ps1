param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$TimezoneId = "Korea Standard Time",

    [Parameter(Mandatory = $false)]
    [switch]$ForceKisVerification
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

function Join-Lines {
    param([string[]]$Lines)
    return ($Lines -join [Environment]::NewLine)
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

function Convert-ToRelativePath {
    param([string]$Path)

    $root = [System.IO.Path]::GetFullPath($WorkspaceRoot)
    $full = [System.IO.Path]::GetFullPath($Path)

    if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($root.Length).TrimStart('\\')
    }

    return $full
}

function Write-Log {
    param([string]$Message)

    $logPath = Join-Path $RuntimeDataDir "logs\app\hourly-repo-audit.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Read-TextSnippet {
    param(
        [string]$Path,
        [string]$Label,
        [int]$MaxLines = 80
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return "### $Label`nmissing: $(Convert-ToRelativePath -Path $Path)"
    }

    $lines = Get-Content -LiteralPath $Path -TotalCount $MaxLines -ErrorAction SilentlyContinue
    if (-not $lines) {
        return "### $Label`nempty: $(Convert-ToRelativePath -Path $Path)"
    }

    return (Join-Lines @(
        "### $Label"
        "path: $(Convert-ToRelativePath -Path $Path)"
        ""
        ($lines -join [Environment]::NewLine)
    ))
}

function Get-FileList {
    param(
        [string]$Path,
        [int]$Limit = 40
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return "- missing: $(Convert-ToRelativePath -Path $Path)"
    }

    $items = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object FullName |
        Select-Object -First $Limit

    if (-not $items) {
        return "- no files under $(Convert-ToRelativePath -Path $Path)"
    }

    return ($items | ForEach-Object { "- $(Convert-ToRelativePath -Path $_.FullName)" }) -join [Environment]::NewLine
}

function Read-JsonOrDefault {
    param(
        [string]$Path,
        [object]$DefaultValue
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $DefaultValue
    }

    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
        return $DefaultValue
    }
}

function Convert-ToJsonArray {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }

    if ($Value -is [System.Array]) {
        return @($Value)
    }

    if ($Value -is [pscustomobject]) {
        return @($Value)
    }

    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        return @($Value | ForEach-Object { $_ })
    }

    return @($Value)
}

function Invoke-CodexReport {
    param(
        [string]$Prompt,
        [string]$OutputPath,
        [string]$SchemaPath = ""
    )

    $args = @(
        "--search",
        "-a", "never",
        "exec",
        "-C", $WorkspaceRoot,
        "-s", "read-only",
        "--color", "never",
        "-c", "model_reasoning_effort=low",
        "-o", $OutputPath
    )

    if ($SchemaPath) {
        $args += @("--output-schema", $SchemaPath)
    }

    $args += "-"
    $codexSource = (Get-Command codex).Source
    $codexCommand = Join-Path (Split-Path -Path $codexSource -Parent) "codex.cmd"
    if (-not (Test-Path -LiteralPath $codexCommand)) {
        $codexCommand = $codexSource
    }
    $codexLogPath = Join-Path $RuntimeDataDir "logs\app\hourly-repo-audit-codex.log"
    $promptDir = Join-Path $RuntimeDataDir "tmp\codex-prompts"
    New-Item -ItemType Directory -Force $promptDir | Out-Null
    $promptPath = Join-Path $promptDir ("prompt-{0}.txt" -f ([guid]::NewGuid().ToString("N")))
    Set-Content -LiteralPath $promptPath -Value $Prompt -Encoding UTF8

    $quotedArgs = $args | ForEach-Object {
        if ($_ -match '\s') {
            '"{0}"' -f ($_ -replace '"', '""')
        } else {
            $_
        }
    }

    $commandText = @(
        ('"{0}"' -f $codexCommand),
        ($quotedArgs -join ' '),
        ('< "{0}"' -f $promptPath),
        '1>nul',
        ('2>>"{0}"' -f $codexLogPath)
    ) -join ' '

    try {
        cmd.exe /d /c $commandText | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "codex exec failed with exit code $LASTEXITCODE"
        }
    } finally {
        Remove-Item -LiteralPath $promptPath -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $OutputPath)) {
        throw "codex exec did not create the expected output file: $(Convert-ToRelativePath -Path $OutputPath)"
    }
}

function Write-FallbackMarkdown {
    param(
        [string]$OutputPath,
        [string]$Title,
        [string]$ErrorText,
        [string]$SessionStatus,
        [string]$KisAction
    )

    if (Test-Path -LiteralPath $OutputPath) {
        $existing = Get-Item -LiteralPath $OutputPath -ErrorAction SilentlyContinue
        if ($null -ne $existing -and $existing.Length -gt 32) {
            return
        }
    }

    $content = Join-Lines @(
        "# $Title",
        "",
        "## 이번 회차 핵심 결론",
        "- Codex CLI 기반 자동 점검이 실패해 fallback 결과를 남깁니다.",
        "",
        "## 새로 확인한 불일치와 누락",
        "- 이번 회차의 상세 진단은 생성하지 못했습니다.",
        "",
        "## 웹서치 기반 적용 제안",
        "- 웹서치 기반 제안도 이번 회차에는 생성하지 못했습니다.",
        "",
        "## 기존 제안 대비 변경점",
        "- 기존 상태를 유지하고 다음 회차에서 재시도합니다.",
        "",
        "## 다음 회차 우선순위",
        "- Codex CLI 호출 경로와 로그인 상태를 먼저 재확인합니다.",
        "- session_status: $SessionStatus",
        "- kis_verification_action: $KisAction",
        "",
        "## 에러 또는 보류 항목",
        "- $ErrorText"
    )

    Set-Content -LiteralPath $OutputPath -Value $content -Encoding UTF8
}

function Write-FallbackProgressJson {
    param(
        [string]$OutputPath,
        [string]$RunLabel,
        [string]$SessionStatus,
        [string]$KisAction,
        [string]$ErrorText,
        [object]$PreviousProgress,
        [string[]]$Artifacts
    )

    $openItems = Convert-ToJsonArray -Value $PreviousProgress.open_items
    $resolvedItems = Convert-ToJsonArray -Value $PreviousProgress.resolved_items
    $sourceLinks = Convert-ToJsonArray -Value $PreviousProgress.latest_source_links

    $payload = [ordered]@{
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        run_label = $RunLabel
        session_status = $SessionStatus
        kis_verification_action = $KisAction
        last_run_summary = "Fallback result written because the Codex CLI execution failed."
        open_items = $openItems
        resolved_items = $resolvedItems
        next_actions = @(
            "Check Codex CLI invocation, login state, and search availability.",
            "Retry the next hourly review with the preserved context files."
        )
        latest_source_links = $sourceLinks
        latest_artifacts = $Artifacts
        error = $ErrorText
    } | ConvertTo-Json -Depth 20

    Set-Content -LiteralPath $OutputPath -Value $payload -Encoding UTF8
}

function Write-FallbackBacklogJson {
    param(
        [string]$OutputPath,
        [string]$DateText,
        [string]$ErrorText,
        [object]$PreviousBacklog
    )

    $items = Convert-ToJsonArray -Value $PreviousBacklog.items
    $payload = [ordered]@{
        date = $DateText
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        items = $items
        error = $ErrorText
    } | ConvertTo-Json -Depth 20

    Set-Content -LiteralPath $OutputPath -Value $payload -Encoding UTF8
}

function Get-MarketSessionInfo {
    param([datetime]$KstNow)

    if ($KstNow.DayOfWeek -in @([System.DayOfWeek]::Saturday, [System.DayOfWeek]::Sunday)) {
        return [ordered]@{
            session_status = "weekend"
            should_run_kis_verify = $false
            note = "Weekend or holiday-like timing. KIS live market-data verification is deferred."
        }
    }

    $hhmm = [int]($KstNow.ToString("HHmm"))

    if ($hhmm -lt 900) {
        return [ordered]@{
            session_status = "pre-open"
            should_run_kis_verify = $false
            note = "Before the regular KRX session open. KIS live market-data verification is deferred."
        }
    }

    if ($hhmm -gt 1530) {
        return [ordered]@{
            session_status = "post-close"
            should_run_kis_verify = $false
            note = "After the regular KRX session close. KIS live market-data verification is deferred."
        }
    }

    return [ordered]@{
        session_status = "regular-session"
        should_run_kis_verify = $true
        note = "Within the regular KRX session window. KIS live market-data verification may be run."
    }
}

$nowKst = Get-KstNow -Id $TimezoneId
$reviewDate = $nowKst.ToString("yyyy-MM-dd")
$timeLabel = $nowKst.ToString("HHmm")
$runLabel = $nowKst.ToString("yyyy-MM-dd HH:mm")

$automationRoot = Join-Path $RuntimeDataDir "reports\codex\automation"
$historyDir = Join-Path $automationRoot "history\$reviewDate"
$researchDir = Join-Path $automationRoot "research\$reviewDate"
$draftsDir = Join-Path $automationRoot "drafts"
$stateDir = Join-Path $automationRoot "state"
$backlogDir = Join-Path $automationRoot "backlog"
$backlogHistoryDir = Join-Path $backlogDir "history"

New-Item -ItemType Directory -Force `
    (Join-Path $RuntimeDataDir "logs\app"), `
    $historyDir, `
    $researchDir, `
    $draftsDir, `
    $stateDir, `
    $backlogDir, `
    $backlogHistoryDir | Out-Null

$reviewPath = Join-Path $historyDir "$timeLabel-review.md"
$researchPath = Join-Path $researchDir "$timeLabel-web-notes.md"
$draftPath = Join-Path $draftsDir "latest-improvement-draft.md"
$contextPath = Join-Path $stateDir "latest-context.md"
$progressPath = Join-Path $stateDir "latest-progress.json"
$backlogPath = Join-Path $backlogDir "latest-priority-backlog.json"
$backlogHistoryPath = Join-Path $backlogHistoryDir "$($reviewDate)-$timeLabel-backlog.json"
$runnerStatePath = Join-Path $stateDir "runner-state.json"

$bundleSchemaPath = Join-Path $WorkspaceRoot "config\codex_repo_audit_bundle.schema.json"
$bundlePath = Join-Path $stateDir "latest-bundle.json"

$previousProgress = Read-JsonOrDefault -Path $progressPath -DefaultValue ([ordered]@{
    open_items = @()
    resolved_items = @()
    latest_source_links = @()
})
$previousBacklog = Read-JsonOrDefault -Path $backlogPath -DefaultValue ([ordered]@{ items = @() })

$sessionInfo = Get-MarketSessionInfo -KstNow $nowKst
$kisAction = "skipped-outside-session"

Write-Log "Starting hourly repo audit iteration for $runLabel"

if ($ForceKisVerification -or $sessionInfo.should_run_kis_verify) {
    $envPath = Join-Path $WorkspaceRoot ".env"
    if (Test-Path -LiteralPath $envPath) {
        try {
            Write-Log "Running KIS verification candidate for $runLabel"
            $kisOutput = & python -m app --verify-kis-ws --symbols 005930 --max-frames 20 --max-reconnects 1 2>&1 | Out-String
            $kisAction = "ran-verify-kis-ws"
            Write-Log "KIS verification completed for $runLabel"
            if ($kisOutput.Trim()) {
                Write-Log $kisOutput.Trim()
            }
        } catch {
            $kisAction = "verify-kis-ws-failed"
            Write-Log "KIS verification failed: $($_.Exception.Message)"
        }
    } else {
        $kisAction = "skipped-no-dotenv"
        Write-Log "Skipped KIS verification because .env is missing"
    }
} else {
    Write-Log "Skipped KIS verification because session status is $($sessionInfo.session_status)"
}

$gitStatus = git status --short | Out-String
if (-not $gitStatus.Trim()) {
    $gitStatus = "clean"
}

$repoSnapshot = Join-Lines @(
    "Top-level items:",
    (Get-ChildItem -LiteralPath $WorkspaceRoot | Sort-Object Name | ForEach-Object { "- $($_.Name)" }),
    "",
    "Scripts:",
    (Get-FileList -Path (Join-Path $WorkspaceRoot "scripts") -Limit 80),
    "",
    "Tests:",
    (Get-FileList -Path (Join-Path $WorkspaceRoot "tests") -Limit 80),
    "",
    "Git status:",
    $gitStatus.Trim()
)

$hintContext = Join-Lines @(
    (Read-TextSnippet -Path (Join-Path $RuntimeDataDir "reports\kis-ws\latest-verification.md") -Label "latest KIS verification"),
    "",
    (Read-TextSnippet -Path (Join-Path $RuntimeDataDir "reports\runtime\latest-runtime-report.md") -Label "latest runtime report"),
    "",
    (Read-TextSnippet -Path (Join-Path $RuntimeDataDir "reports\challengers\latest-challengers-h15.md") -Label "latest challenger report"),
    "",
    (Read-TextSnippet -Path $progressPath -Label "previous progress state"),
    "",
    (Read-TextSnippet -Path $contextPath -Label "previous handoff context")
)

$pathInstructions = Join-Lines @(
    "Canonical files to reread in order:",
    "- AGENTS.md",
    "- README.md",
    "- docs/logbook.md",
    "- docs/logbook_archive/logbook_20260411.md",
    "- docs/Current-Implementation.md",
    "- docs/Versioning.md",
    "",
    "Latest report files to inspect:",
    "- runtime-data/reports/kis-ws/latest-verification.md",
    "- runtime-data/reports/runtime/latest-runtime-report.md",
    "- runtime-data/reports/backtests/latest-backtest-h15.md",
    "- runtime-data/reports/backtests/latest-walk-forward-h15.md",
    "- runtime-data/reports/challengers/latest-challengers-h15.md",
    "",
    "Previous automation files to inspect if present:",
    "- runtime-data/reports/codex/automation/state/latest-progress.json",
    "- runtime-data/reports/codex/automation/state/latest-context.md",
    "- runtime-data/reports/codex/automation/drafts/latest-improvement-draft.md",
    "- runtime-data/reports/codex/automation/backlog/latest-priority-backlog.json"
)

$commonHeader = Join-Lines @(
    "You are running the Hourly Repo Audit for a Korean stock prediction and paper-trading repository.",
    "",
    "Run label: $runLabel",
    "Session status: $($sessionInfo.session_status)",
    "KIS verification action this run: $kisAction",
    "Session note: $($sessionInfo.note)",
    "",
    "Rules:",
    "- Do not modify repo-tracked files.",
    "- Use shell only for read-only inspection inside the repository.",
    "- Use web search for up to 3 unresolved high-impact questions.",
    "- Prefer official docs and primary sources first; use GitHub and community only as secondary support.",
    "- Keep stable ids for the same unresolved issues when you update progress and backlog.",
    "- Treat weekend or market-off hours as deferred KIS market-data verification, not a failure.",
    "- Write concise Korean outputs.",
    "",
    $pathInstructions,
    "",
    $repoSnapshot,
    "",
    "Current hints:",
    $hintContext
)

$bundlePrompt = Join-Lines @(
    $commonHeader,
    "",
    "Return JSON only that matches the provided schema.",
    "Inspect the repository, use web search for up to 3 unresolved high-impact questions, and build the full hourly audit package in Korean.",
    "",
    "review_markdown must use exactly these sections in order:",
    "## 이번 회차 핵심 결론",
    "## 새로 확인한 불일치와 누락",
    "## 웹서치 기반 적용 제안",
    "## 기존 제안 대비 변경점",
    "## 다음 회차 우선순위",
    "## 에러 또는 보류 항목",
    "",
    "research_markdown must use exactly these sections in order:",
    "## 이번 회차 연구 질문",
    "## 공식 출처",
    "## GitHub 및 커뮤니티 참고",
    "## 적용 가능한 개선 포인트",
    "## 이번 회차 반영 우선순위",
    "",
    "draft_markdown must use exactly these sections in order:",
    "## 현재 최적 구조안",
    "## 새로 채택한 안과 사유",
    "## 아직 미확정인 부분",
    "## 구현 직전 체크포인트",
    "",
    "context_markdown must use exactly these sections in order:",
    "## 핵심 결론",
    "## 미해결 위험",
    "## 다음 실행 우선순위",
    "## 대기 조건과 시장시간 메모",
    "",
    "Use stable ids for the same unresolved issues.",
    "Treat weekend or market-off hours as deferred KIS market-data verification, not a failure.",
    "Prefer official docs and primary sources first, then GitHub and community support.",
    "latest_source_links must include reviewed_at and published_at null when unknown.",
    "backlog_items must reflect the current implementation priority order."
)

$generatedArtifacts = @(
    (Convert-ToRelativePath -Path $reviewPath),
    (Convert-ToRelativePath -Path $researchPath),
    (Convert-ToRelativePath -Path $draftPath),
    (Convert-ToRelativePath -Path $contextPath),
    (Convert-ToRelativePath -Path $progressPath),
    (Convert-ToRelativePath -Path $backlogPath),
    (Convert-ToRelativePath -Path $backlogHistoryPath)
)

try {
    Invoke-CodexReport -Prompt $bundlePrompt -OutputPath $bundlePath -SchemaPath $bundleSchemaPath

    $bundle = Get-Content -LiteralPath $bundlePath -Encoding UTF8 -Raw | ConvertFrom-Json

    Set-Content -LiteralPath $reviewPath -Value $bundle.review_markdown -Encoding UTF8
    Set-Content -LiteralPath $researchPath -Value $bundle.research_markdown -Encoding UTF8
    Set-Content -LiteralPath $draftPath -Value $bundle.draft_markdown -Encoding UTF8
    Set-Content -LiteralPath $contextPath -Value $bundle.context_markdown -Encoding UTF8

    $progressPayload = [ordered]@{
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        run_label = $runLabel
        session_status = $sessionInfo.session_status
        kis_verification_action = $kisAction
        last_run_summary = $bundle.last_run_summary
        open_items = Convert-ToJsonArray -Value $bundle.open_items
        resolved_items = Convert-ToJsonArray -Value $bundle.resolved_items
        next_actions = Convert-ToJsonArray -Value $bundle.next_actions
        latest_source_links = Convert-ToJsonArray -Value $bundle.latest_source_links
        latest_artifacts = $generatedArtifacts
        error = $null
    } | ConvertTo-Json -Depth 20
    Set-Content -LiteralPath $progressPath -Value $progressPayload -Encoding UTF8

    $backlogPayload = [ordered]@{
        date = $reviewDate
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        items = Convert-ToJsonArray -Value $bundle.backlog_items
        error = $null
    } | ConvertTo-Json -Depth 20
    Set-Content -LiteralPath $backlogPath -Value $backlogPayload -Encoding UTF8
    Copy-Item -LiteralPath $backlogPath -Destination $backlogHistoryPath -Force

    $runnerState = [ordered]@{
        automation_name = "Hourly Repo Audit"
        status = "completed"
        last_run_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        last_run_label = $runLabel
        session_status = $sessionInfo.session_status
        kis_verification_action = $kisAction
        last_review_path = $reviewPath
        last_research_path = $researchPath
        last_bundle_path = $bundlePath
        last_progress_path = $progressPath
        last_backlog_path = $backlogPath
    } | ConvertTo-Json -Depth 10
    Set-Content -LiteralPath $runnerStatePath -Value $runnerState -Encoding UTF8

    Write-Log "Hourly repo audit iteration completed for $runLabel"
} catch {
    $errorText = $_.Exception.Message
    Write-Log "Hourly repo audit iteration failed for ${runLabel}: $errorText"

    Write-FallbackMarkdown -OutputPath $reviewPath -Title "Hourly Repo Audit fallback" -ErrorText $errorText -SessionStatus $sessionInfo.session_status -KisAction $kisAction
    Write-FallbackMarkdown -OutputPath $researchPath -Title "Hourly Repo Audit research fallback" -ErrorText $errorText -SessionStatus $sessionInfo.session_status -KisAction $kisAction
    Write-FallbackMarkdown -OutputPath $draftPath -Title "Hourly Repo Audit draft fallback" -ErrorText $errorText -SessionStatus $sessionInfo.session_status -KisAction $kisAction
    Write-FallbackMarkdown -OutputPath $contextPath -Title "Hourly Repo Audit context fallback" -ErrorText $errorText -SessionStatus $sessionInfo.session_status -KisAction $kisAction
    Write-FallbackProgressJson -OutputPath $progressPath -RunLabel $runLabel -SessionStatus $sessionInfo.session_status -KisAction $kisAction -ErrorText $errorText -PreviousProgress $previousProgress -Artifacts $generatedArtifacts
    Write-FallbackBacklogJson -OutputPath $backlogPath -DateText $reviewDate -ErrorText $errorText -PreviousBacklog $previousBacklog
    Copy-Item -LiteralPath $backlogPath -Destination $backlogHistoryPath -Force

    $runnerState = [ordered]@{
        automation_name = "Hourly Repo Audit"
        status = "failed"
        last_run_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        last_run_label = $runLabel
        session_status = $sessionInfo.session_status
        kis_verification_action = $kisAction
        error = $errorText
        last_review_path = $reviewPath
        last_progress_path = $progressPath
        last_backlog_path = $backlogPath
    } | ConvertTo-Json -Depth 10
    Set-Content -LiteralPath $runnerStatePath -Value $runnerState -Encoding UTF8
}

Write-Output $reviewPath
