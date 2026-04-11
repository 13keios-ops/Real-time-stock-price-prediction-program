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

function Write-FallbackMarkdown {
    param(
        [string]$OutputPath,
        [string]$Title,
        [string]$ErrorText
    )

    $content = @"
# $Title

## 핵심 결론

이번 자동 리뷰 실행이 실패했습니다.

## 새로 채택한 최적안

- 자동 리포트 생성 실패 상태를 기록하고 다음 회차에서 재시도합니다.

## 채택 사유

- 실패 로그를 남겨야 다음 회차와 운영 점검에서 원인을 추적할 수 있습니다.

## 기각한 대안

- 실패를 무시하고 아무 파일도 남기지 않는 방식

## 남은 리스크

- Codex CLI 실행 또는 인증 상태를 다시 확인해야 할 수 있습니다.

## 다음 회차 집중 포인트

- Codex CLI 실행 로그와 인증 상태 점검

## 오류

`$ErrorText`
"@

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

$docsSummary = Get-ChildItem -LiteralPath (Join-Path $WorkspaceRoot "docs") -File |
    Sort-Object Name |
    ForEach-Object { "- docs/$($_.Name)" } |
    Out-String

$runtimeSnapshot = if (Test-Path -LiteralPath $RuntimeDataDir) {
    Get-ChildItem -LiteralPath $RuntimeDataDir -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 30 |
        ForEach-Object {
            $relative = Resolve-Path -LiteralPath $_.FullName | ForEach-Object {
                $_.Path.Replace($WorkspaceRoot + "\", "")
            }
            "- $relative"
        } |
        Out-String
} else {
    "- runtime-data missing"
}

$reportSections = if ($ReviewKind -eq "final") {
@"
반드시 아래 섹션을 이 순서대로 포함하세요.

## 현재 프로그램 구조 최종안
## 기존안 대비 개선점
## 새로 확정한 최적안과 사유
## 즉시 개발 착수 가능 항목
## 추가 검증 필요 항목
"@
} else {
@"
반드시 아래 섹션을 이 순서대로 포함하세요.

## 핵심 결론
## 새로 채택한 최적안
## 채택 사유
## 기각한 대안
## 남은 리스크
## 다음 회차 집중 포인트
"@
}

$reviewKindDescription = switch ($ReviewKind) {
    "intraday" { "정시 반복 리뷰" }
    "integration" { "최종 통합 리뷰" }
    "final" { "최종 개선본 리뷰" }
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
- Focus on architecture consistency, data pipeline integrity, ML lifecycle, paper-trading safety, reconciliation/replay/recovery, and observability.
- Output plain Markdown only.

Current docs:
$docsSummary

Current runtime snapshot:
$runtimeSnapshot

$reportSections
"@

Write-Log "Starting $ReviewKind review for label $TimeLabel"

try {
    Invoke-CodexReport -Prompt $prompt -OutputPath $outputPath
    Write-Log "Wrote review output to $outputPath"
} catch {
    Write-Log "Review failed for $TimeLabel: $($_.Exception.Message)"
    Write-FallbackMarkdown -OutputPath $outputPath -Title "$reviewKindDescription 실패 기록" -ErrorText $_.Exception.Message
}

if ($ReviewKind -eq "final") {
    $backlogPath = Join-Path $actionItemsDir "$ReviewDate-priority-backlog.json"
    $backlogPrompt = @"
Analyze the project docs and generated review artifacts for the date $ReviewDate.

Return JSON only that matches the provided schema.

Requirements:
- Prioritize the top actionable improvements for implementation.
- Prefer decision-complete recommendations.
- Keep `source_files` limited to the most relevant doc/report paths.
- Use priorities P0-P3.
- Confidence should be between 0 and 1.
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
