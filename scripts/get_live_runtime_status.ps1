param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$statePath = Join-Path $RuntimeDataDir "reports\live-runtime\state\listener-state.json"
$dashboardPath = Join-Path $RuntimeDataDir "reports\dashboard\latest-dashboard.json"
$kisVerificationPath = Join-Path $RuntimeDataDir "reports\kis-ws\latest-verification.json"
$envFilePath = Join-Path $WorkspaceRoot ".env"

Add-Type -AssemblyName System.Web.Extensions

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $serializer.MaxJsonLength = 67108864
        $jsonText = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        return $serializer.DeserializeObject($jsonText)
    } catch {
        return $null
    }
}

function Read-DotEnvMap {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $envMap = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $envMap
    }

    foreach ($rawLine in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        $line = "$rawLine".Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }

        $pair = $line.Split("=", 2)
        $key = $pair[0].Trim()
        $value = $pair[1].Trim().Trim("'`"")
        if (-not [string]::IsNullOrWhiteSpace($key)) {
            $envMap[$key] = $value
        }
    }

    return $envMap
}

function Get-NormalizedEnvValue {
    param([string]$Value)

    $normalized = "$Value".Trim()
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return ""
    }

    $lowered = $normalized.ToLowerInvariant()
    if (
        $normalized.StartsWith("?ш린??") -or
        $normalized.StartsWith("諛쒓툒諛쏆?_") -or
        $normalized.StartsWith("<") -or
        $normalized.StartsWith("[") -or
        (@("placeholder", "changeme", "example", "sample") -contains $lowered)
    ) {
        return ""
    }

    return $normalized
}

function Get-EnvSettingValue {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$DotEnvMap,

        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $false)]
        [string]$Default = ""
    )

    $processValue = [Environment]::GetEnvironmentVariable($Key)
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return "$processValue"
    }

    if ($DotEnvMap.ContainsKey($Key)) {
        return "$($DotEnvMap[$Key])"
    }

    return $Default
}

function Get-KisCredentialStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EnvFilePath
    )

    $dotEnvMap = Read-DotEnvMap -Path $EnvFilePath
    $tradingModeRaw = (Get-EnvSettingValue -DotEnvMap $dotEnvMap -Key "TRADING_MODE" -Default "paper").Trim().ToLowerInvariant()
    $tradingMode = if ($tradingModeRaw -eq "live") { "live" } else { "paper" }
    $prefix = if ($tradingMode -eq "live") { "LIVE" } else { "PAPER" }
    $appKey = Get-NormalizedEnvValue -Value (Get-EnvSettingValue -DotEnvMap $dotEnvMap -Key "KIS_APP_KEY_$prefix")
    $appSecret = Get-NormalizedEnvValue -Value (Get-EnvSettingValue -DotEnvMap $dotEnvMap -Key "KIS_APP_SECRET_$prefix")

    return [ordered]@{
        trading_mode = $tradingMode
        ready_for_quotes = (-not [string]::IsNullOrWhiteSpace($appKey)) -and (-not [string]::IsNullOrWhiteSpace($appSecret))
    }
}

if (-not (Test-Path -LiteralPath $statePath)) {
    [ordered]@{
        status = "stopped"
        process_running = $false
        raw_status = "missing"
        message = "실시간 수집기 상태 파일이 없습니다."
    } | ConvertTo-Json -Depth 10
    return
}

function Get-LogTailSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $false)]
        [int]$Tail = 20
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $lines = Get-Content -LiteralPath $Path -Tail $Tail -ErrorAction SilentlyContinue |
        ForEach-Object { "$_".TrimEnd() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    if (-not $lines) {
        return ""
    }

    return ($lines -join [Environment]::NewLine).Trim()
}

function Get-BlockedReasonFromText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    if ($Text -match "KIS credentials are not configured") {
        return "missing_kis_credentials"
    }

    return ""
}

function Get-LastNonEmptyLine {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    $lines = $Text -split "\r?\n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if (-not $lines) {
        return ""
    }

    return "$($lines[-1])".Trim()
}

function Get-TimestampFreshness {
    param(
        [Parameter(Mandatory = $false)]
        [string]$Timestamp,

        [Parameter(Mandatory = $false)]
        [double]$FreshMinutes = 60,

        [Parameter(Mandatory = $false)]
        [double]$StaleMinutes = 240
    )

    if ([string]::IsNullOrWhiteSpace($Timestamp)) {
        return [ordered]@{
            available = $false
            timestamp = $null
            age_minutes = $null
            state = "missing"
            label = "missing"
            note = "timestamp missing"
        }
    }

    try {
        $parsed = [DateTimeOffset]::Parse($Timestamp)
        $ageMinutes = [Math]::Round(([DateTimeOffset]::Now - $parsed).TotalMinutes, 2)
        $state = if ($ageMinutes -le $FreshMinutes) {
            "fresh"
        } elseif ($ageMinutes -le $StaleMinutes) {
            "stale"
        } else {
            "old"
        }
        return [ordered]@{
            available = $true
            timestamp = $Timestamp
            age_minutes = $ageMinutes
            state = $state
            label = $state
            note = "$ageMinutes minutes old"
        }
    } catch {
        return [ordered]@{
            available = $false
            timestamp = $Timestamp
            age_minutes = $null
            state = "invalid"
            label = "invalid"
            note = "timestamp parse failed"
        }
    }
}

function Get-LiveRuntimeMessage {
    param(
        [string]$BlockedReason,
        [bool]$EnvFileExists,
        [string]$FailureReason
    )

    if ($BlockedReason -eq "missing_kis_credentials") {
        if (-not $EnvFileExists) {
            return "KIS credentials are blocked because root .env is missing."
        }

        return "KIS credentials are blocked because required .env values are not configured."
    }

    if (-not [string]::IsNullOrWhiteSpace($FailureReason)) {
        return $FailureReason
    }

    return ""
}

function Get-LiveRuntimeProcessRecord {
    param([int]$ProcessId)

    if (-not $ProcessId) {
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace($process.CommandLine)) {
        return $null
    }

    $commandLine = "$($process.CommandLine)"
    if (
        ($commandLine -match '(?i)(^|\s)-m\s+app(\s|$)') -and
        ($commandLine -match '(?i)(^|\s)--kis-ws-listen(\s|$)')
    ) {
        return $process
    }

    return $null
}

$state = Read-JsonFile -Path $statePath
if ($null -eq $state) {
    [ordered]@{
        status = "warning"
        process_running = $false
        raw_status = "invalid"
        message = "실시간 수집기 상태 파일을 읽지 못했습니다."
    } | ConvertTo-Json -Depth 10
    return
}
$processRunning = $false
if ($state["pid"]) {
    $processRunning = $null -ne (Get-LiveRuntimeProcessRecord -ProcessId ([int]$state["pid"]))
}

$stdoutLogPath = "$($state["stdout_log_path"])"
$stderrLogPath = "$($state["stderr_log_path"])"
$stdoutTail = if ([string]$state["stdout_tail"]) { [string]$state["stdout_tail"] } else { Get-LogTailSummary -Path $stdoutLogPath }
$stderrTail = if ([string]$state["stderr_tail"]) { [string]$state["stderr_tail"] } else { Get-LogTailSummary -Path $stderrLogPath }
$storedFailureReason = if ([string]$state["failure_reason"]) {
    Get-LastNonEmptyLine -Text ([string]$state["failure_reason"])
} else {
    ""
}
$failureReason = if ($storedFailureReason -and $storedFailureReason -ne ".") {
    $storedFailureReason
} elseif ($stderrTail) {
    Get-LastNonEmptyLine -Text $stderrTail
} elseif ($stdoutTail) {
    Get-LastNonEmptyLine -Text $stdoutTail
} else {
    ""
}
if ($failureReason -eq "0" -or $failureReason -eq ".") {
    $failureReason = ""
}
if ($processRunning) {
    $failureReason = ""
}
$envFileExists = Test-Path -LiteralPath $envFilePath
$credentialStatus = Get-KisCredentialStatus -EnvFilePath $envFilePath
$credentialsReadyForQuotes = [bool]$credentialStatus["ready_for_quotes"]
$tradingMode = [string]$credentialStatus["trading_mode"]
$parsedBlockedReason = Get-BlockedReasonFromText -Text ($failureReason + [Environment]::NewLine + $stdoutTail)
$storedBlockedReason = if ([string]$state["blocked_reason"]) {
    [string]$state["blocked_reason"]
} else {
    ""
}
$blockedReason = if ($storedBlockedReason) { $storedBlockedReason } else { $parsedBlockedReason }
$knownCredentialsFailureReason = "python.exe -m app: error: KIS credentials are not configured. Fill .env values before using KIS commands."
$staleCredentialsFailureCleared = $false
if (($blockedReason -eq "missing_kis_credentials") -and $credentialsReadyForQuotes) {
    $blockedReason = ""
    if ($failureReason -eq $knownCredentialsFailureReason) {
        $failureReason = ""
    }
    $staleCredentialsFailureCleared = $true
}
if (($blockedReason -eq "missing_kis_credentials") -and (($failureReason -eq ".") -or [string]::IsNullOrWhiteSpace($failureReason))) {
    $failureReason = $knownCredentialsFailureReason
}
$message = Get-LiveRuntimeMessage -BlockedReason $blockedReason -EnvFileExists $envFileExists -FailureReason $failureReason

$dashboardPayload = Read-JsonFile -Path $dashboardPath
$latestKisVerification = Read-JsonFile -Path $kisVerificationPath

$systemStatus = if ($null -ne $dashboardPayload) { $dashboardPayload["system_status"] } else { $null }
$freshness = if ($null -ne $systemStatus) { $systemStatus["freshness"] } else { $null }
$dashboardKisVerification = if ($null -ne $dashboardPayload -and $null -ne $dashboardPayload["latest_kis_verification"]) {
    $dashboardPayload["latest_kis_verification"]
} else {
    $null
}
$effectiveKisVerification = if ($null -ne $latestKisVerification) { $latestKisVerification } else { $dashboardKisVerification }
$effectiveKisVerificationFreshness = if ($null -ne $latestKisVerification) {
    Get-TimestampFreshness -Timestamp ([string]$latestKisVerification["verified_at"])
} elseif ($null -ne $freshness) {
    $freshness["latest_kis_verification"]
} else {
    $null
}

[string]$rawStatus = "$($state["status"])"
$effectiveStatus = if ($processRunning) {
    "running"
} elseif ($blockedReason -eq "missing_kis_credentials") {
    "failed"
} elseif (($rawStatus -eq "failed") -and -not $staleCredentialsFailureCleared) {
    "failed"
} else {
    "stopped"
}

$normalizedStateStatus = if ($effectiveStatus -eq "running") { "running" } else { $effectiveStatus }
$normalizedStoppedAt = if ([string]$state["stopped_at"]) {
    [string]$state["stopped_at"]
} elseif (-not $processRunning) {
    Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
} else {
    ""
}

if (
    ($rawStatus -ne $normalizedStateStatus) -or
    ([bool]$state["process_running"] -ne $processRunning) -or
    ([string]$state["blocked_reason"] -ne $blockedReason) -or
    ([string]$state["failure_reason"] -ne $failureReason) -or
    ([string]$state["stdout_tail"] -ne $stdoutTail) -or
    ([string]$state["stderr_tail"] -ne $stderrTail) -or
    ([string]$state["message"] -ne $message) -or
    ([bool]$state["env_file_exists"] -ne $envFileExists) -or
    ([bool]$state["credentials_ready_for_quotes"] -ne $credentialsReadyForQuotes) -or
    ([string]$state["trading_mode"] -ne $tradingMode)
) {
    $normalizedState = [ordered]@{
        status = $normalizedStateStatus
        pid = $state["pid"]
        process_running = $processRunning
        workspace_root = $state["workspace_root"]
        runtime_data_dir = $state["runtime_data_dir"]
        symbols = $state["symbols"]
        watchlist_file = $state["watchlist_file"]
        max_frames = $state["max_frames"]
        max_reconnects = $state["max_reconnects"]
        prediction_horizons = $state["prediction_horizons"]
        trading_signal_horizon = $state["trading_signal_horizon"]
        stdout_log_path = $stdoutLogPath
        stderr_log_path = $stderrLogPath
        started_at = $state["started_at"]
        env_file_path = $envFilePath
        env_file_exists = $envFileExists
        trading_mode = $tradingMode
        credentials_ready_for_quotes = $credentialsReadyForQuotes
        message = $message
    }

    if ($normalizedStoppedAt) {
        $normalizedState.stopped_at = $normalizedStoppedAt
    }

    if ($null -ne $state["exit_code"]) {
        $normalizedState.exit_code = $state["exit_code"]
    }

    if ($failureReason) {
        $normalizedState.failure_reason = $failureReason
    }

    if ($blockedReason) {
        $normalizedState.blocked_reason = $blockedReason
    }

    if ($stdoutTail) {
        $normalizedState.stdout_tail = $stdoutTail
    }

    if ($stderrTail) {
        $normalizedState.stderr_tail = $stderrTail
    }

    $normalizedState | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $state = $normalizedState
}

[ordered]@{
    status = $effectiveStatus
    pid = $state["pid"]
    process_running = $processRunning
    workspace_root = $state["workspace_root"]
    runtime_data_dir = $state["runtime_data_dir"]
    symbols = $state["symbols"]
    watchlist_file = $state["watchlist_file"]
    max_frames = $state["max_frames"]
    max_reconnects = $state["max_reconnects"]
    prediction_horizons = $state["prediction_horizons"]
    trading_signal_horizon = $state["trading_signal_horizon"]
    stdout_log_path = $stdoutLogPath
    stderr_log_path = $stderrLogPath
    started_at = $state["started_at"]
    stopped_at = $state["stopped_at"]
    env_file_path = $envFilePath
    env_file_exists = $envFileExists
    trading_mode = $tradingMode
    credentials_ready_for_quotes = $credentialsReadyForQuotes
    exit_code = $state["exit_code"]
    blocked_reason = $blockedReason
    failure_reason = $failureReason
    message = $message
    latest_market_bar_time = if ($null -ne $systemStatus) { $systemStatus["latest_market_bar_time"] } else { $null }
    latest_prediction_time = if ($null -ne $systemStatus) { $systemStatus["latest_prediction_time"] } else { $null }
    latest_signal_time = if ($null -ne $systemStatus) { $systemStatus["latest_signal_time"] } else { $null }
    market_bar_freshness = if ($null -ne $freshness) { $freshness["latest_market_bar"] } else { $null }
    prediction_freshness = if ($null -ne $freshness) { $freshness["latest_prediction"] } else { $null }
    signal_freshness = if ($null -ne $freshness) { $freshness["latest_signal"] } else { $null }
    kis_verification_freshness = $effectiveKisVerificationFreshness
    session_status = if ($null -ne $effectiveKisVerification) { $effectiveKisVerification["session_status"] } else { $null }
    raw_status = $rawStatus
} | ConvertTo-Json -Depth 10
