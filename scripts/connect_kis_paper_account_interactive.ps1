[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = "",

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$DashboardHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$DashboardPort = 8765
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
    throw "Missing .env. Restore KIS app key and secret first."
}

function Get-EnvValue {
    param([string]$Key)

    foreach ($line in $script:EnvLines) {
        if ($line -match ('^' + [regex]::Escape($Key) + '=(.*)$')) {
            return $Matches[1]
        }
    }

    return ""
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key,

        [AllowEmptyString()]
        [string]$Value
    )

    for ($index = 0; $index -lt $script:EnvLines.Count; $index++) {
        if ($script:EnvLines[$index] -match ('^' + [regex]::Escape($Key) + '=')) {
            $script:EnvLines[$index] = "$Key=$Value"
            return
        }
    }

    $script:EnvLines.Add("$Key=$Value") | Out-Null
}

function Read-RequiredValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $false)]
        [string]$DefaultValue = ""
    )

    while ($true) {
        if ([string]::IsNullOrWhiteSpace($DefaultValue)) {
            $value = Read-Host $Prompt
        } else {
            $value = Read-Host "$Prompt (Enter keeps current)"
            if ([string]::IsNullOrWhiteSpace($value)) {
                $value = $DefaultValue
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }

        Write-Host "Value is required. Please try again." -ForegroundColor Yellow
    }
}

function Test-PaperAccountNo {
    param([string]$AccountNo)

    return ("$AccountNo".Trim() -match '^\d{8}(-\d{2})?$')
}

function Read-PaperAccountNo {
    param([string]$DefaultValue = "")

    $defaultForPrompt = if (Test-PaperAccountNo -AccountNo $DefaultValue) { $DefaultValue.Trim() } else { "" }
    while ($true) {
        if ([string]::IsNullOrWhiteSpace($defaultForPrompt)) {
            $value = Read-Host "KIS_ACCOUNT_NO_PAPER (8 digits, or 8 digits-2 digits)"
        } else {
            $value = Read-Host "KIS_ACCOUNT_NO_PAPER (8 digits, or 8 digits-2 digits; Enter keeps current)"
            if ([string]::IsNullOrWhiteSpace($value)) {
                $value = $defaultForPrompt
            }
        }

        if (Test-PaperAccountNo -AccountNo $value) {
            return $value.Trim()
        }

        Write-Host "Use the full paper account number: 8 digits, or 8 digits-2 digits if copied with a suffix." -ForegroundColor Yellow
    }
}

function Get-MaskedAccount {
    param([string]$AccountNo)

    $normalized = "$AccountNo".Trim()
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return ""
    }
    if ($normalized.Length -le 4) {
        return ("*" * $normalized.Length)
    }

    return "$($normalized.Substring(0, 4))$('*' * ($normalized.Length - 4))"
}

function Invoke-AppCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $false)]
        [switch]$DiscardOutput
    )

    if ($DiscardOutput) {
        & python @Arguments | Out-Null
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

    return Get-Content -LiteralPath $LiteralPath -Raw | ConvertFrom-Json
}

function Test-NeedsBrokerPaperAlignment {
    param([object]$PaperReconciliation)

    if ($null -eq $PaperReconciliation -or $null -eq $PaperReconciliation.comparison) {
        return $false
    }

    $comparison = $PaperReconciliation.comparison
    return (
        [bool]$comparison.order_mirroring_enabled -and
        [int]$comparison.mirrored_order_count -eq 0 -and
        [int]$comparison.mismatch_count -gt 0
    )
}

$script:EnvLines = New-Object 'System.Collections.Generic.List[string]'
$script:EnvLines.AddRange([System.IO.File]::ReadAllLines($envPath, [System.Text.Encoding]::UTF8))

$currentAppKey = (Get-EnvValue -Key "KIS_APP_KEY_PAPER").Trim()
$currentAppSecret = (Get-EnvValue -Key "KIS_APP_SECRET_PAPER").Trim()
if ([string]::IsNullOrWhiteSpace($currentAppKey) -or [string]::IsNullOrWhiteSpace($currentAppSecret)) {
    throw "KIS paper app key/secret is missing. Run restore_kis_env_interactive.ps1 first."
}

$currentAccountNo = (Get-EnvValue -Key "KIS_ACCOUNT_NO_PAPER").Trim()
Write-Host ""
Write-Host "KIS paper account connect" -ForegroundColor Cyan
Write-Host "This run keeps the existing paper app key and app secret."
Write-Host "It enables local paper execution plus KIS broker paper mirroring."
Write-Host "Live orders stay disabled."
Write-Host "KIS_PRODUCT_CODE_PAPER is not requested; leave it blank for paper mode."
Write-Host ""

$accountNo = Read-PaperAccountNo -DefaultValue $currentAccountNo

Set-EnvValue -Key "TRADING_MODE" -Value "paper"
Set-EnvValue -Key "ALLOW_LIVE_ORDERS" -Value "false"
Set-EnvValue -Key "ENABLE_PAPER_EXECUTION" -Value "true"
Set-EnvValue -Key "ENABLE_BROKER_PAPER_MIRRORING" -Value "true"
Set-EnvValue -Key "KIS_ACCOUNT_NO_PAPER" -Value $accountNo
Set-EnvValue -Key "KIS_PRODUCT_CODE_PAPER" -Value ""

[System.IO.File]::WriteAllLines($envPath, $script:EnvLines.ToArray(), [System.Text.Encoding]::UTF8)

Write-Host ""
Write-Host ".env saved" -ForegroundColor Green
Write-Host "account: $(Get-MaskedAccount -AccountNo $accountNo)"
Write-Host "product code: not entered; paper default is applied internally when needed"
Write-Host "broker paper mirroring: enabled"
Write-Host "live orders: disabled"

$brokerPaperSync = $null
$paperReconciliation = $null
$paperAlignment = $null
$dashboardState = $null
$liveRuntimeState = $null
$watchdogState = $null
$setupCheck = $null

try {
    Write-Host ""
    Write-Host "Refreshing broker paper account..." -ForegroundColor Cyan
    Invoke-AppCommand -Arguments @("-m", "app", "--kis-account-balance") -DiscardOutput
    Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
    $brokerPaperSync = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\broker-paper\latest-sync.json")
    Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput
    $paperReconciliation = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\reconciliation\latest-paper-account-sync.json")

    if (Test-NeedsBrokerPaperAlignment -PaperReconciliation $paperReconciliation) {
        Write-Host "Aligning local paper baseline to broker paper account..." -ForegroundColor Cyan
        Invoke-AppCommand -Arguments @("-m", "app", "--align-local-paper-to-broker") -DiscardOutput
        $paperAlignment = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\broker-paper\latest-alignment.json")
        Invoke-AppCommand -Arguments @("-m", "app", "--sync-broker-paper-orders") -DiscardOutput
        $brokerPaperSync = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\broker-paper\latest-sync.json")
        Invoke-AppCommand -Arguments @("-m", "app", "--reconcile-paper-accounts") -DiscardOutput
        $paperReconciliation = Read-JsonFile -LiteralPath (Join-Path $RuntimeDataDir "reports\reconciliation\latest-paper-account-sync.json")
    }
} catch {
    Write-Host "Broker paper preparation failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    Write-Host "Starting dashboard..." -ForegroundColor Cyan
    & (Join-Path $WorkspaceRoot "scripts\start_dashboard_background.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir `
        -DashboardHost $DashboardHost `
        -Port $DashboardPort `
        -ForceRestart | Out-Null
    Start-Sleep -Seconds 2
    $dashboardState = & (Join-Path $WorkspaceRoot "scripts\get_dashboard_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
} catch {
    Write-Host "Dashboard start failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    Write-Host "Starting live runtime..." -ForegroundColor Cyan
    & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir `
        -ForceRestart | Out-Null
    Start-Sleep -Seconds 2
    $liveRuntimeState = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
} catch {
    Write-Host "Live runtime start failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    Write-Host "Starting runtime watchdog..." -ForegroundColor Cyan
    & (Join-Path $WorkspaceRoot "scripts\start_runtime_watchdog_background.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir `
        -DashboardHost $DashboardHost `
        -DashboardPort $DashboardPort `
        -ForceRestart | Out-Null
    Start-Sleep -Seconds 2
    $watchdogState = & (Join-Path $WorkspaceRoot "scripts\get_runtime_watchdog_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
} catch {
    Write-Host "Runtime watchdog start failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    $setupCheck = & (Join-Path $WorkspaceRoot "scripts\check_local_setup.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir `
        -AsJson | ConvertFrom-Json
} catch {
    Write-Host "check_local_setup failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Summary" -ForegroundColor Cyan
if ($null -ne $paperReconciliation) {
    Write-Host "reconciliation status: $($paperReconciliation.comparison.status)"
    Write-Host "mismatch count: $($paperReconciliation.comparison.mismatch_count)"
    Write-Host "mirroring enabled: $($paperReconciliation.comparison.order_mirroring_enabled)"
}
if ($null -ne $brokerPaperSync) {
    Write-Host "broker sync status: $($brokerPaperSync.status)"
}
if ($null -ne $paperAlignment) {
    Write-Host "alignment status: $($paperAlignment.status)"
}
if ($null -ne $dashboardState) {
    Write-Host "dashboard status: $($dashboardState.status)"
    Write-Host "dashboard url: $($dashboardState.url)"
}
if ($null -ne $liveRuntimeState) {
    Write-Host "live runtime status: $($liveRuntimeState.status)"
    if ($liveRuntimeState.blocked_reason) {
        Write-Host "live runtime blocked reason: $($liveRuntimeState.blocked_reason)"
    }
}
if ($null -ne $watchdogState) {
    Write-Host "watchdog status: $($watchdogState.status)"
}
if ($null -ne $setupCheck) {
    Write-Host "setup check ok: $($setupCheck.ok)"
    if ($setupCheck.blockers) {
        Write-Host "blockers: $([string]::Join(', ', $setupCheck.blockers))"
    }
}

Write-Host ""
Read-Host "Press Enter to close"
