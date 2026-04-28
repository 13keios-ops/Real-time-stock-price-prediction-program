[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = "",

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [switch]$SyncInitialCash,

    [Parameter(Mandatory = $false)]
    [switch]$AlignToBroker,

    [Parameter(Mandatory = $false)]
    [switch]$RefreshDashboard,

    [Parameter(Mandatory = $false)]
    [switch]$FailOnMismatch,

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $WorkspaceRoot = Split-Path -Parent $scriptRoot
}
if ([string]::IsNullOrWhiteSpace($RuntimeDataDir)) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

Set-Location $WorkspaceRoot

$envPath = Join-Path $WorkspaceRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing root .env. Restore KIS paper credentials before comparing paper accounts."
}

$reportDir = Join-Path $RuntimeDataDir "reports\reconciliation"
$jsonReportPath = Join-Path $reportDir "latest-paper-dual-account-match.json"
$mdReportPath = Join-Path $reportDir "latest-paper-dual-account-match.md"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

function Invoke-AppCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $false)]
        [switch]$DiscardOutput
    )

    if ($DiscardOutput) {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & python @Arguments 1>$null 2>$null
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    } else {
        & python @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "python $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Read-JsonFile {
    param([string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return $null
    }

    return Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Read-EnvFileMap {
    param([string]$LiteralPath)

    $map = @{}
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return $map
    }

    foreach ($line in [System.IO.File]::ReadAllLines($LiteralPath, [System.Text.Encoding]::UTF8)) {
        if ($line -match '^\s*#') {
            continue
        }

        $separatorIndex = $line.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()
        $map[$key] = $value
    }

    return $map
}

function Set-EnvFileValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,

        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $lines = New-Object 'System.Collections.Generic.List[string]'
    $lines.AddRange([System.IO.File]::ReadAllLines($LiteralPath, [System.Text.Encoding]::UTF8))
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match ('^' + [regex]::Escape($Key) + '=')) {
            $lines[$index] = "$Key=$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) {
        $lines.Add("$Key=$Value") | Out-Null
    }

    [System.IO.File]::WriteAllLines($LiteralPath, $lines.ToArray(), [System.Text.Encoding]::UTF8)
}

function Get-NumberOrNull {
    param([object]$Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace("$Value")) {
        return $null
    }

    try {
        return [double]::Parse("$Value", [System.Globalization.CultureInfo]::InvariantCulture)
    } catch {
        return $null
    }
}

function Format-EnvNumber {
    param([double]$Value)

    if ([Math]::Abs($Value - [Math]::Round($Value)) -lt 0.0001) {
        return ([long][Math]::Round($Value)).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }

    return $Value.ToString("0.########", [System.Globalization.CultureInfo]::InvariantCulture)
}

function Format-Money {
    param([object]$Value)

    $number = Get-NumberOrNull -Value $Value
    if ($null -eq $number) {
        return "-"
    }

    return $number.ToString("#,##0.##", [System.Globalization.CultureInfo]::InvariantCulture)
}

function Test-NearZero {
    param([object]$Value)

    $number = Get-NumberOrNull -Value $Value
    return ($null -ne $number -and [Math]::Abs($number) -lt 1.0)
}

function Test-NearEqual {
    param(
        [object]$Left,
        [object]$Right
    )

    $leftNumber = Get-NumberOrNull -Value $Left
    $rightNumber = Get-NumberOrNull -Value $Right
    return ($null -ne $leftNumber -and $null -ne $rightNumber -and [Math]::Abs($leftNumber - $rightNumber) -lt 1.0)
}

function Get-BrokerTotalAsset {
    param([object]$BrokerAccount)

    if ($null -eq $BrokerAccount) {
        return $null
    }

    $total = Get-NumberOrNull -Value $BrokerAccount.total_asset_amount
    if ($null -ne $total -and $total -ne 0) {
        return $total
    }

    return Get-NumberOrNull -Value $BrokerAccount.total_evaluation_amount
}

$envBefore = Read-EnvFileMap -LiteralPath $envPath
$initialCashBefore = if ($envBefore.ContainsKey("PAPER_INITIAL_CASH")) { $envBefore["PAPER_INITIAL_CASH"] } else { "" }

Invoke-AppCommand -Arguments @("-m", "app", "--kis-account-balance") -DiscardOutput

$accountReport = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\kis-account\latest-account.json")
if ($null -eq $accountReport -or $null -eq $accountReport.account_snapshot) {
    $accountReport = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\kis-account\latest-account-paper.json")
}
if ($null -eq $accountReport -or $null -eq $accountReport.account_snapshot) {
    throw "KIS paper account report was not created. Check paper account credentials and KIS connectivity."
}

$brokerCashFromAccount = Get-NumberOrNull -Value $accountReport.account_snapshot.cash_balance
if ($SyncInitialCash) {
    if ($null -eq $brokerCashFromAccount -or $brokerCashFromAccount -le 0) {
        throw "Broker paper cash is unavailable, so PAPER_INITIAL_CASH cannot be synchronized."
    }

    Set-EnvFileValue -LiteralPath $envPath -Key "PAPER_INITIAL_CASH" -Value (Format-EnvNumber -Value $brokerCashFromAccount)
}

if ($AlignToBroker) {
    Invoke-AppCommand -Arguments @("-m", "app", "--align-local-paper-to-broker") -DiscardOutput
}

Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput

if ($RefreshDashboard) {
    Invoke-AppCommand -Arguments @("-m", "app", "--build-dashboard") -DiscardOutput
}

$envAfter = Read-EnvFileMap -LiteralPath $envPath
$initialCashAfter = if ($envAfter.ContainsKey("PAPER_INITIAL_CASH")) { $envAfter["PAPER_INITIAL_CASH"] } else { "" }
$reconciliation = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\reconciliation\latest-paper-account-sync.json")
if ($null -eq $reconciliation -or $null -eq $reconciliation.comparison) {
    throw "Paper reconciliation report was not created."
}

$comparison = $reconciliation.comparison
$localAccount = $reconciliation.local_account
$brokerAccount = $reconciliation.broker_account
$brokerCash = Get-NumberOrNull -Value $brokerAccount.cash_balance
if ($null -eq $brokerCash) {
    $brokerCash = $brokerCashFromAccount
}
$brokerTotal = Get-BrokerTotalAsset -BrokerAccount $brokerAccount
$localCash = Get-NumberOrNull -Value $localAccount.cash_balance
$localTotal = Get-NumberOrNull -Value $localAccount.net_liquidation_value
$cashGap = Get-NumberOrNull -Value $comparison.cash_gap
$totalAssetGap = Get-NumberOrNull -Value $comparison.total_asset_gap
$mismatchCount = [int]($comparison.mismatch_count | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
$mirroredOrderCount = [int]($comparison.mirrored_order_count | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
$localPositionCount = if ($null -eq $localAccount.positions) { 0 } else { @($localAccount.positions).Count }
$initialCashMatchesBroker = Test-NearEqual -Left $initialCashAfter -Right $brokerCash
$balanceMatch = if ($null -ne $comparison.balance_match) { [bool]$comparison.balance_match } else { Test-NearZero -Value $cashGap }
$totalAssetMatch = if ($null -ne $comparison.total_asset_match) { [bool]$comparison.total_asset_match } else { Test-NearZero -Value $totalAssetGap }
$accountsMatch = (
    [bool]$reconciliation.ok -and
    $mismatchCount -eq 0 -and
    $balanceMatch -and
    $totalAssetMatch
)
$mirroringEnabled = [bool]$comparison.order_mirroring_enabled
$ok = (
    [bool]$accountReport.ok -and
    [bool]$reconciliation.ok -and
    $mirroringEnabled -and
    $initialCashMatchesBroker -and
    $accountsMatch
)

if ($ok -and $mirroredOrderCount -eq 0) {
    $status = "matched_waiting_first_submission"
} elseif ($ok) {
    $status = "matched"
} elseif (-not $initialCashMatchesBroker) {
    $status = "initial_cash_mismatch"
} else {
    $status = "needs_review"
}

$payload = [ordered]@{
    ok = $ok
    checked_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    status = $status
    actions = [ordered]@{
        sync_initial_cash = [bool]$SyncInitialCash
        align_to_broker = [bool]$AlignToBroker
        refresh_dashboard = [bool]$RefreshDashboard
    }
    env = [ordered]@{
        paper_initial_cash_before = $initialCashBefore
        paper_initial_cash_after = $initialCashAfter
        initial_cash_matches_broker_cash = $initialCashMatchesBroker
        trading_mode = if ($envAfter.ContainsKey("TRADING_MODE")) { $envAfter["TRADING_MODE"] } else { "" }
        broker_paper_mirroring_enabled = $mirroringEnabled
    }
    broker_account = [ordered]@{
        ok = [bool]$accountReport.ok
        fetched_at = $accountReport.fetched_at
        account_no_masked = $accountReport.account_snapshot.account_no_masked
        cash_balance = $brokerCash
        total_asset_amount = $brokerTotal
        position_count = [int]($accountReport.account_snapshot.position_row_count | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
    }
    local_account = [ordered]@{
        cash_balance = $localCash
        net_liquidation_value = $localTotal
        position_count = $localPositionCount
        orders_total = $localAccount.orders_total
        fills_total = $localAccount.fills_total
        broker_order_submissions = $localAccount.broker_order_submissions
    }
    comparison = [ordered]@{
        reconciliation_ok = [bool]$reconciliation.ok
        reconciliation_status = $comparison.status
        mismatch_count = $mismatchCount
        cash_gap = $cashGap
        raw_cash_gap = Get-NumberOrNull -Value $comparison.raw_cash_gap
        total_asset_gap = $totalAssetGap
        balance_match = $balanceMatch
        total_asset_match = $totalAssetMatch
        broker_effective_cash_balance = Get-NumberOrNull -Value $comparison.broker_effective_cash_balance
        mirrored_order_count = $mirroredOrderCount
        note = $comparison.note
    }
    report_json_path = $jsonReportPath
    report_markdown_path = $mdReportPath
}

$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $jsonReportPath -Encoding UTF8

$mdLines = @(
    "# Paper Dual Account Match",
    "",
    "- checked at: $($payload.checked_at)",
    "- ok: $($payload.ok)",
    "- status: $($payload.status)",
    "- local initial cash before: $($payload.env.paper_initial_cash_before)",
    "- local initial cash after: $($payload.env.paper_initial_cash_after)",
    "- broker cash: $(Format-Money -Value $payload.broker_account.cash_balance)",
    "- local cash: $(Format-Money -Value $payload.local_account.cash_balance)",
    "- cash gap: $(Format-Money -Value $payload.comparison.cash_gap)",
    "- total asset gap: $(Format-Money -Value $payload.comparison.total_asset_gap)",
    "- mismatch count: $($payload.comparison.mismatch_count)",
    "- mirrored order count: $($payload.comparison.mirrored_order_count)",
    "- reconciliation status: $($payload.comparison.reconciliation_status)",
    "- note: $($payload.comparison.note)",
    "",
    "## Output Paths",
    "",
    "- json: $jsonReportPath",
    "- markdown: $mdReportPath"
)
$mdLines -join [Environment]::NewLine | Set-Content -LiteralPath $mdReportPath -Encoding UTF8

if ($AsJson) {
    $payload | ConvertTo-Json -Depth 10
} else {
    Write-Host "Paper dual account match: $($payload.status)"
    Write-Host "broker cash: $(Format-Money -Value $payload.broker_account.cash_balance)"
    Write-Host "local cash: $(Format-Money -Value $payload.local_account.cash_balance)"
    Write-Host "cash gap: $(Format-Money -Value $payload.comparison.cash_gap)"
    Write-Host "total asset gap: $(Format-Money -Value $payload.comparison.total_asset_gap)"
    Write-Host "mismatch count: $($payload.comparison.mismatch_count)"
    Write-Host "report: $jsonReportPath"
}

if ($FailOnMismatch -and -not $ok) {
    throw "Local virtual paper account and broker paper account are not matched. status=$status"
}
