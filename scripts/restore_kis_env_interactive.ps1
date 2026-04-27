[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [ValidateSet("paper", "live")]
    [string]$TradingMode = "paper",

    [Parameter(Mandatory = $false)]
    [switch]$IncludeAccountFields
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$envPath = Join-Path $WorkspaceRoot ".env"
$envExamplePath = Join-Path $WorkspaceRoot ".env.example"
$basePath = if (Test-Path -LiteralPath $envPath) { $envPath } else { $envExamplePath }

if (-not (Test-Path -LiteralPath $basePath)) {
    throw "Missing base env file: $envExamplePath"
}

function Get-PlainTextFromSecureString {
    param(
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SecureValue
    )

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Get-EnvValue {
    param(
        [AllowEmptyCollection()]
        [AllowEmptyString()]
        [string[]]$Lines,

        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    foreach ($line in $Lines) {
        if ($line -match ('^' + [regex]::Escape($Key) + '=(.*)$')) {
            return $Matches[1]
        }
    }

    return ""
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Lines,

        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    for ($index = 0; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index] -match ('^' + [regex]::Escape($Key) + '=')) {
            $Lines[$index] = "$Key=$Value"
            return
        }
    }

    $Lines.Add("$Key=$Value") | Out-Null
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

function Read-RequiredSecretValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $false)]
        [string]$DefaultValue = ""
    )

    while ($true) {
        $secureValue = Read-Host "$Prompt (input hidden, Enter keeps current if any)" -AsSecureString
        $plainValue = (Get-PlainTextFromSecureString -SecureValue $secureValue).Trim()
        if ([string]::IsNullOrWhiteSpace($plainValue) -and -not [string]::IsNullOrWhiteSpace($DefaultValue)) {
            return $DefaultValue
        }

        if (-not [string]::IsNullOrWhiteSpace($plainValue)) {
            return $plainValue
        }

        Write-Host "Value is required. Please try again." -ForegroundColor Yellow
    }
}

function Read-OptionalValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $false)]
        [string]$DefaultValue = ""
    )

    $value = Read-Host "$Prompt (Enter keeps current/blank)"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $DefaultValue
    }

    return $value.Trim()
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

$sourceLines = [System.IO.File]::ReadAllLines($basePath, [System.Text.Encoding]::UTF8)
$lines = New-Object 'System.Collections.Generic.List[string]'
$lines.AddRange($sourceLines)

$selectedTradingMode = $TradingMode.Trim().ToLowerInvariant()
$prefix = if ($selectedTradingMode -eq "live") { "LIVE" } else { "PAPER" }
$currentTradingMode = (Get-EnvValue -Lines $sourceLines -Key "TRADING_MODE").Trim().ToLowerInvariant()

$currentAppKey = (Get-EnvValue -Lines $sourceLines -Key "KIS_APP_KEY_$prefix").Trim()
$currentAppSecret = (Get-EnvValue -Lines $sourceLines -Key "KIS_APP_SECRET_$prefix").Trim()
$currentAccountNo = (Get-EnvValue -Lines $sourceLines -Key "KIS_ACCOUNT_NO_$prefix").Trim()
$currentProductCode = (Get-EnvValue -Lines $sourceLines -Key "KIS_PRODUCT_CODE_$prefix").Trim()
$currentHtsId = (Get-EnvValue -Lines $sourceLines -Key "KIS_HTS_ID").Trim()

if ([string]::IsNullOrWhiteSpace($currentProductCode) -and $prefix -eq "PAPER") {
    $currentProductCode = "01"
}

Write-Host ""
Write-Host "KIS .env restore" -ForegroundColor Cyan
Write-Host "requested mode: $selectedTradingMode"
Write-Host "current mode in base file: $currentTradingMode"
if ($IncludeAccountFields) {
    Write-Host "This run asks for app key, app secret, account, and product fields."
} else {
    Write-Host "This run asks only for app key and app secret."
    Write-Host "Account fields stay unchanged."
}
Write-Host ""
Write-Host "Target credential set: $prefix" -ForegroundColor Cyan

$appKey = Read-RequiredSecretValue -Prompt "KIS_APP_KEY_$prefix" -DefaultValue $currentAppKey
$appSecret = Read-RequiredSecretValue -Prompt "KIS_APP_SECRET_$prefix" -DefaultValue $currentAppSecret
$accountNo = $currentAccountNo
$productCode = $currentProductCode
$htsId = $currentHtsId

if ($IncludeAccountFields) {
    $accountNo = Read-RequiredValue -Prompt "KIS_ACCOUNT_NO_$prefix" -DefaultValue $currentAccountNo
    $productCode = Read-RequiredValue -Prompt "KIS_PRODUCT_CODE_$prefix" -DefaultValue $productCode
    $htsId = Read-OptionalValue -Prompt "KIS_HTS_ID" -DefaultValue $currentHtsId
}

Set-EnvValue -Lines $lines -Key "TRADING_MODE" -Value $selectedTradingMode
Set-EnvValue -Lines $lines -Key "KIS_APP_KEY_$prefix" -Value $appKey
Set-EnvValue -Lines $lines -Key "KIS_APP_SECRET_$prefix" -Value $appSecret
Set-EnvValue -Lines $lines -Key "KIS_ACCOUNT_NO_$prefix" -Value $accountNo
Set-EnvValue -Lines $lines -Key "KIS_PRODUCT_CODE_$prefix" -Value $productCode
Set-EnvValue -Lines $lines -Key "KIS_HTS_ID" -Value $htsId

[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.Encoding]::UTF8)

Write-Host ""
Write-Host ".env saved" -ForegroundColor Green
Write-Host "path: $envPath"
Write-Host "trading mode: $selectedTradingMode"
Write-Host "credential set updated: $prefix"
Write-Host "account fields updated: $($IncludeAccountFields.IsPresent)"
Write-Host "account: $(Get-MaskedAccount -AccountNo $accountNo)"
Write-Host "product code: $productCode"
Write-Host ""

$liveRuntimeStatus = $null
$watchdogStatus = $null
$setupCheck = $null
$verificationOutput = $null

try {
    Write-Host "Starting live runtime..." -ForegroundColor Cyan
    & (Join-Path $WorkspaceRoot "scripts\start_live_runtime_background.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir `
        -ForceRestart | Out-Null
    Start-Sleep -Seconds 2
    $liveRuntimeStatus = & (Join-Path $WorkspaceRoot "scripts\get_live_runtime_status.ps1") `
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
        -ForceRestart | Out-Null
    Start-Sleep -Seconds 2
    $watchdogStatus = & (Join-Path $WorkspaceRoot "scripts\get_runtime_watchdog_status.ps1") `
        -WorkspaceRoot $WorkspaceRoot `
        -RuntimeDataDir $RuntimeDataDir | ConvertFrom-Json
} catch {
    Write-Host "Runtime watchdog start failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    Write-Host "Running KIS verification..." -ForegroundColor Cyan
    $verificationOutput = & python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
    if ($LASTEXITCODE -ne 0) {
        throw "python -m app --verify-kis-ws failed with exit code $LASTEXITCODE"
    }
} catch {
    Write-Host "KIS verification failed: $($_.Exception.Message)" -ForegroundColor Yellow
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
if ($null -ne $liveRuntimeStatus) {
    Write-Host "live runtime status: $($liveRuntimeStatus.status)"
    if ($liveRuntimeStatus.blocked_reason) {
        Write-Host "live runtime blocked reason: $($liveRuntimeStatus.blocked_reason)"
    }
}
if ($null -ne $watchdogStatus) {
    Write-Host "watchdog status: $($watchdogStatus.status)"
    Write-Host "watchdog action: $($watchdogStatus.live_runtime_action)"
}
if ($null -ne $setupCheck) {
    Write-Host "setup check ok: $($setupCheck.ok)"
    if ($setupCheck.blockers) {
        Write-Host "blockers: $([string]::Join(', ', $setupCheck.blockers))"
    }
}
if ($verificationOutput) {
    Write-Host ""
    Write-Host "KIS verify output:"
    $verificationOutput | ForEach-Object { Write-Host $_ }
}

Write-Host ""
Read-Host "Press Enter to close"
