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

function Join-Lines {
    param([string[]]$Lines)
    return ($Lines -join [Environment]::NewLine)
}

function Invoke-CodexReport {
    param(
        [string]$Prompt,
        [string]$OutputPath,
        [string]$SchemaPath = ""
    )

    $args = @(
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

    $codexSource = (Get-Command codex -ErrorAction Stop).Source
    $codexCommand = Join-Path (Split-Path -Path $codexSource -Parent) "codex.cmd"
    if (-not (Test-Path -LiteralPath $codexCommand)) {
        $codexCommand = $codexSource
    }

    $codexLogPath = Join-Path $RuntimeDataDir "logs\app\midday-codex-review-codex.log"
    $promptDir = Join-Path $RuntimeDataDir "tmp\codex-prompts"
    New-Item -ItemType Directory -Force $promptDir | Out-Null
    $promptPath = Join-Path $promptDir ("prompt-{0}.txt" -f ([guid]::NewGuid().ToString("N")))
    Set-Content -LiteralPath $promptPath -Value $Prompt -Encoding UTF8

    $args += "-"
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
}

function Convert-ToRelativePath {
    param([string]$Path)

    $root = [System.IO.Path]::GetFullPath($WorkspaceRoot)
    $full = [System.IO.Path]::GetFullPath($Path)

    if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($root.Length).TrimStart('\')
    }

    return $full
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

function Get-ReportSectionTemplate {
    param([string]$Kind)

    if ($Kind -eq "final") {
        return Join-Lines @(
            "Use exactly these Markdown sections in this order:",
            "",
            "## Final Program Structure",
            "## Improvements Versus Prior Plan",
            "## Finalized Best Option And Reason",
            "## Ready For Immediate Work",
            "## Additional Validation Needed"
        )
    }

    return Join-Lines @(
        "Use exactly these Markdown sections in this order:",
        "",
        "## Key Conclusion",
        "## Newly Adopted Best Option",
        "## Reason For Adoption",
        "## Rejected Alternative",
        "## Remaining Risks",
        "## Next Iteration Focus"
    )
}

function Write-FallbackMarkdown {
    param(
        [string]$OutputPath,
        [string]$ReviewTitle,
        [string]$ErrorText,
        [bool]$IsFinal
    )

    $content = if ($IsFinal) {
        Join-Lines @(
            "# $ReviewTitle",
            "",
            "## Final Program Structure",
            "- The automated review runner is prepared, but this iteration stored a fallback result because the Codex CLI call failed.",
            "",
            "## Improvements Versus Prior Plan",
            "- The failure itself is preserved in runtime-data logs and artifacts so the next iteration and manual review can trace it.",
            "",
            "## Finalized Best Option And Reason",
            "- Best option: on errors, leave canonical docs untouched and write a fallback report plus an empty backlog file.",
            "- Reason: the review loop stays observable and recoverable even when automation fails.",
            "",
            "## Ready For Immediate Work",
            "- Recheck Codex CLI permissions, login state, prompt handling, and schema input.",
            "",
            "## Additional Validation Needed",
            "- Whether the real Codex CLI call succeeds end to end",
            "- Whether the final backlog JSON conforms to schema",
            "",
            "## Error",
            ('`' + $ErrorText + '`')
        )
    } else {
        Join-Lines @(
            "# $ReviewTitle",
            "",
            "## Key Conclusion",
            "- This automated review wrote a fallback report because the Codex CLI call failed.",
            "",
            "## Newly Adopted Best Option",
            "- Best option: do not hide the failure; record it as-is and revisit it in the next iteration.",
            "",
            "## Reason For Adoption",
            "- Persisting the error makes the repeated review loop traceable and fixable.",
            "",
            "## Rejected Alternative",
            "- Ignoring the error and leaving only an empty result",
            "",
            "## Remaining Risks",
            "- The root cause may still be the Codex CLI execution path, prompt length, or login state.",
            "",
            "## Next Iteration Focus",
            "- Recheck the Codex CLI invocation logs and whether an output file is created.",
            "",
            "## Error",
            ('`' + $ErrorText + '`')
        )
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
$runtimeSnapshot = Join-Lines @(
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
)

$reportSections = Get-ReportSectionTemplate -Kind $ReviewKind

$reviewKindDescription = switch ($ReviewKind) {
    "intraday" { "Hourly architecture review" }
    "integration" { "Integrated pre-final review" }
    "final" { "Final improvement review" }
}

$prompt = Join-Lines @(
    "You are reviewing a Korean stock prediction and paper-trading architecture project.",
    "",
    "Review kind: $reviewKindDescription",
    "Review date: $ReviewDate",
    "Time label: $TimeLabel",
    "",
    "Rules:",
    "- Do not modify repo-tracked files.",
    "- Review the current docs and any runtime-data artifacts if present.",
    "- If runtime-data is sparse or missing, explicitly list the missing runtime artifacts and continue with docs-only structural review.",
    "- Choose a single best option when multiple design choices conflict.",
    "- Always explain why the chosen option is best and why other options were rejected.",
    "- Focus on architecture consistency, data pipeline integrity, ML lifecycle, paper-trading safety, reconciliation, replay, recovery, and observability.",
    "- Optimize for practical implementation readiness.",
    "- Output plain Markdown only.",
    "",
    "Current docs:",
    $docsSummary,
    "",
    "Existing codex reports:",
    $existingReportSummary,
    "",
    "Current runtime snapshot:",
    $runtimeSnapshot,
    "",
    $reportSections
)

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
    $backlogPrompt = Join-Lines @(
        "Analyze the project docs and generated review artifacts for the date $ReviewDate.",
        "",
        "Return JSON only that matches the provided schema.",
        "",
        "Requirements:",
        "- Prioritize the top actionable improvements for implementation.",
        "- Prefer decision-complete recommendations.",
        "- Keep source_files limited to the most relevant doc or report paths.",
        "- Use priorities P0-P3.",
        "- Confidence should be between 0 and 1.",
        "- Include only items that are still useful after the final review."
    )

    try {
        Invoke-CodexReport -Prompt $backlogPrompt -OutputPath $backlogPath -SchemaPath $BacklogSchemaPath
        Write-Log "Wrote backlog output to $backlogPath"
    } catch {
        Write-Log "Backlog generation failed: $($_.Exception.Message)"
        Write-FallbackJson -OutputPath $backlogPath -ErrorText $_.Exception.Message
    }
}

Write-Output $outputPath
