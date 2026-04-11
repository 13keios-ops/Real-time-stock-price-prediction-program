param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("intraday", "integration", "final")]
    [string]$ReviewKind,

    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeDataDir,

    [Parameter(Mandatory = $true)]
    [string]$ReviewDate,

    [Parameter(Mandatory = $true)]
    [string]$TimeLabel,

    [Parameter(Mandatory = $false)]
    [string]$BacklogSchemaPath = ""
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)

    $logPath = Join-Path $RuntimeDataDir "logs\app\midday-codex-review.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Invoke-CodexReport {
    param(
        [string]$Prompt,
        [string]$OutputPath,
        [string]$SchemaPath = ""
    )

    $args = @(
        "exec",
        "-C", $WorkspaceRoot,
        "-s", "read-only",
        "--color", "never",
        "-o", $OutputPath
    )

    if ($SchemaPath) {
        $args += @("--output-schema", $SchemaPath)
    }

    $args += $Prompt

    & codex @args
    if ($LASTEXITCODE -ne 0) {
        throw "codex exec failed with exit code $LASTEXITCODE"
    }
}

function Convert-ToRelativePath {
    param([string]$Path)

    $normalizedRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)
    $normalizedPath = [System.IO.Path]::GetFullPath($Path)

    if ($normalizedPath.StartsWith($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $normalizedPath.Substring($normalizedRoot.Length).TrimStart('\')
    }

    return $normalizedPath
}

function Get-FileList {
    param(
        [string]$Path,
        [int]$Limit = 30
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

function Write-FallbackMarkdown {
    param(
        [string]$OutputPath,
        [string]$ReviewTitle,
        [string]$ErrorText,
        [bool]$IsFinal
    )

    $content = if ($IsFinal) {
        @(
            "# $ReviewTitle",
            "",
            "## 현재 프로그램 구조 최종안",
            "- 자동 리뷰 실행은 준비되었지만, 이번 회차는 Codex CLI 호출 오류로 인해 fallback 결과를 남겼습니다.",
            "",
            "## 기존안 대비 개선점",
            "- 실패 자체를 runtime-data 로그와 산출물에 남겨 다음 회차와 수동 점검에 활용할 수 있게 했습니다.",
            "",
            "## 새로 확정한 최적안과 사유",
            "- 최적안: 오류 시 canonical docs를 건드리지 않고 fallback 보고서와 빈 backlog를 남깁니다.",
            "- 사유: 자동화 실패가 발생해도 검토 흐름이 끊기지 않고 원인 추적이 가능해집니다.",
            "",
            "## 즉시 개발 착수 가능 항목",
            "- Codex CLI 실행 권한, 로그인 상태, 프롬프트 및 스키마 입력을 다시 점검합니다.",
            "",
            "## 추가 검증 필요 항목",
            "- 실제 Codex CLI 실행 성공 여부",
            "- 최종 backlog JSON 스키마 적합성",
            "",
            "## 오류",
            "`$ErrorText`"
        ) -join [Environment]::NewLine
    } else {
        @(
            "# $ReviewTitle",
            "",
            "## 핵심 결론",
            "- 이번 자동 리뷰는 Codex CLI 호출 오류로 fallback 보고서를 남겼습니다.",
            "",
            "## 새로 채택한 최적안",
            "- 최적안: 실패 상태를 숨기지 않고 그대로 기록한 뒤 다음 회차에서 재검토합니다.",
            "",
            "## 채택 사유",
            "- 오류 기록이 남아야 반복 리뷰에서 원인을 축적하고 수정할 수 있습니다.",
            "",
            "## 기각한 대안",
            "- 오류를 무시하고 빈 결과만 남기는 방식",
            "",
            "## 남은 리스크",
            "- Codex CLI 실행 경로, 입력 길이, 로그인 상태 중 하나가 여전히 문제일 수 있습니다.",
            "",
            "## 다음 회차 집중 포인트",
            "- Codex CLI 호출 로그와 출력 파일 생성 여부를 재확인합니다.",
            "",
            "## 오류",
            "`$ErrorText`"
        ) -join [Environment]::NewLine
    }

    Set-Content -LiteralPath $OutputPath -Value $content -Encoding UTF8
}

function Write-FallbackJson {
    param(
        [string]$OutputPath,
        [string]$ErrorText
    )

    $payload = [ordered]@{
        date         = $ReviewDate
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        items        = @()
        error        = $ErrorText
    } | ConvertTo-Json -Depth 5

    Set-Content -LiteralPath $OutputPath -Value $payload -Encoding UTF8
}

$intradayDir = Join-Path $RuntimeDataDir "reports\codex\intraday\$ReviewDate"
$eodDir = Join-Path $RuntimeDataDir "reports\codex\eod\$ReviewDate"
$actionItemsDir = Join-Path $RuntimeDataDir "reports\codex\action-items"

New-Item -ItemType Directory -Force $intradayDir, $eodDir, $actionItemsDir | Out-Null

$outputPath = switch ($ReviewKind) {
    "intraday" { Join-Path $intradayDir "iteration-$TimeLabel.md" }
    "integration" { Join-Path $eodDir "integration-$TimeLabel.md" }
    "final" { Join-Path $eodDir "final-improvement-plan.md" }
}

$docsDir = Join-Path $WorkspaceRoot "docs"
$reportsDir = Join-Path $RuntimeDataDir "reports\codex"
$runtimeLogsDir = Join-Path $RuntimeDataDir "logs"
$runtimeMlDir = Join-Path $RuntimeDataDir "ml"
$runtimeTradingDir = Join-Path $RuntimeDataDir "trading"
$runtimeCacheDir = Join-Path $RuntimeDataDir "cache"

$docsSummary = Get-FileList -Path $docsDir -Limit 200
$existingReportSummary = Get-FileList -Path $reportsDir -Limit 40
$runtimeSnapshot = @(
    "logs:"
    (Get-FileList -Path $runtimeLogsDir -Limit 20)
    ""
    "ml:"
    (Get-FileList -Path $runtimeMlDir -Limit 20)
    ""
    "trading:"
    (Get-FileList -Path $runtimeTradingDir -Limit 20)
    ""
    "cache:"
    (Get-FileList -Path $runtimeCacheDir -Limit 20)
) -join [Environment]::NewLine

$reportSections = if ($ReviewKind -eq "final") {
    @(
        "Use exactly these Markdown sections in this order:",
        "",
        "## 현재 프로그램 구조 최종안",
        "## 기존안 대비 개선점",
        "## 새로 확정한 최적안과 사유",
        "## 즉시 개발 착수 가능 항목",
        "## 추가 검증 필요 항목"
    ) -join [Environment]::NewLine
} else {
    @(
        "Use exactly these Markdown sections in this order:",
        "",
        "## 핵심 결론",
        "## 새로 채택한 최적안",
        "## 채택 사유",
        "## 기각한 대안",
        "## 남은 리스크",
        "## 다음 회차 집중 포인트"
    ) -join [Environment]::NewLine
}

$reviewKindDescription = switch ($ReviewKind) {
    "intraday" { "Hourly architecture review" }
    "integration" { "Integrated pre-final review" }
    "final" { "Final improvement review" }
}

$prompt = @"
You are reviewing a Korean stock prediction and paper-trading architecture project.

Review kind: $reviewKindDescription
Review date: $ReviewDate
Time label: $TimeLabel

Rules:
- Do not modify repo-tracked files.
- Review the current docs and any runtime-data artifacts if present.
- If runtime-data is sparse or missing, explicitly list the missing runtime artifacts and continue with docs-only structural review.
- Choose a single best option when multiple design choices conflict.
- Always explain why the chosen option is best and why other options were rejected.
- Focus on architecture consistency, data pipeline integrity, ML lifecycle, paper-trading safety, reconciliation, replay, recovery, and observability.
- Optimize for practical implementation readiness.
- Output plain Markdown only.

Current docs:
$docsSummary

Existing codex reports:
$existingReportSummary

Current runtime snapshot:
$runtimeSnapshot

$reportSections
"@

Write-Log "Starting $ReviewKind review for label $TimeLabel"

try {
    Invoke-CodexReport -Prompt $prompt -OutputPath $outputPath
    Write-Log "Wrote review output to $outputPath"
} catch {
    Write-Log "Review failed for ${TimeLabel}: $($_.Exception.Message)"
    Write-FallbackMarkdown -OutputPath $outputPath -ReviewTitle "$reviewKindDescription fallback" -ErrorText $_.Exception.Message -IsFinal ($ReviewKind -eq "final")
}

if ($ReviewKind -eq "final") {
    $backlogPath = Join-Path $actionItemsDir "$ReviewDate-priority-backlog.json"
    $backlogPrompt = @"
Analyze the project docs and generated review artifacts for the date $ReviewDate.

Return JSON only that matches the provided schema.

Requirements:
- Prioritize the top actionable improvements for implementation.
- Prefer decision-complete recommendations.
- Keep source_files limited to the most relevant doc or report paths.
- Use priorities P0-P3.
- Confidence should be between 0 and 1.
- Include only items that are still useful after the final review.
"@

    try {
        Invoke-CodexReport -Prompt $backlogPrompt -OutputPath $backlogPath -SchemaPath $BacklogSchemaPath
        Write-Log "Wrote backlog output to $backlogPath"
    } catch {
        Write-Log "Backlog generation failed: $($_.Exception.Message)"
        Write-FallbackJson -OutputPath $backlogPath -ErrorText $_.Exception.Message
    }
}

Write-Output $outputPath
