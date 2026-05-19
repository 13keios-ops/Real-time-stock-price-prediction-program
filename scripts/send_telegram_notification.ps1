[CmdletBinding()]
param(
    [string]$Message,
    [string]$TaskSummary,
    [string]$CommitSummary,
    [string]$PushSummary,
    [string]$Extra,
    [string]$RepoRoot,
    [string]$BotToken,
    [string]$ChatId,
    [string]$LinkUrl,
    [string]$WatcherSignalDir,
    [switch]$ShowRecentChats,
    [switch]$Silent,
    [switch]$DryRun,
    [switch]$Direct,
    [switch]$NoWatcherSignal
)

$ErrorActionPreference = "Stop"

$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
}
else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}

$repoRoot = if ($RepoRoot) {
    (Resolve-Path -LiteralPath $RepoRoot).Path
}
else {
    Split-Path -Parent $scriptRoot
}
$repoName = Split-Path -Leaf $repoRoot

function Get-ConfiguredValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$ParameterName,
        [string]$ExplicitValue,
        [switch]$Required
    )

    $value = $ExplicitValue
    if (-not $value) {
        $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    if (-not $value) {
        $value = [Environment]::GetEnvironmentVariable($Name, "User")
    }
    if (-not $value) {
        $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
    }

    if ($value) {
        $value = $value.Trim()
    }

    if ($Required -and [string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required value. Pass -$ParameterName or set environment variable: $Name"
    }

    return $value
}

function Get-ErrorResponseBody {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    $response = $ErrorRecord.Exception.Response
    if (-not $response) {
        return $null
    }

    $stream = $response.GetResponseStream()
    if (-not $stream) {
        return $null
    }

    $reader = New-Object System.IO.StreamReader($stream)
    return $reader.ReadToEnd()
}

function Invoke-TelegramApi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [hashtable]$Body
    )

    $uri = "https://api.telegram.org/bot$botToken/$Method"

    try {
        if ($Body) {
            return Invoke-RestMethod `
                -Method Post `
                -Uri $uri `
                -ContentType "application/x-www-form-urlencoded;charset=utf-8" `
                -Body $Body
        }

        return Invoke-RestMethod -Method Get -Uri $uri
    }
    catch {
        $responseBody = Get-ErrorResponseBody -ErrorRecord $_
        if ($responseBody) {
            throw "Telegram API request failed: $responseBody"
        }

        throw
    }
}

function New-UnicodeText {
    param(
        [Parameter(Mandatory = $true)]
        [int[]]$CodePoints
    )

    return -join ($CodePoints | ForEach-Object { [string][char]$_ })
}

function Get-DefaultWatcherSignalDir {
    param([string]$RepositoryRoot)

    $configuredSignalDir = [Environment]::GetEnvironmentVariable("CODEX_WATCHER_SIGNAL_DIR", "Process")
    if (-not $configuredSignalDir) {
        $configuredSignalDir = [Environment]::GetEnvironmentVariable("CODEX_WATCHER_SIGNAL_DIR", "User")
    }
    if (-not $configuredSignalDir) {
        $configuredSignalDir = [Environment]::GetEnvironmentVariable("CODEX_WATCHER_SIGNAL_DIR", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($configuredSignalDir)) {
        return $configuredSignalDir.Trim()
    }

    $githubRoot = Split-Path -Parent $RepositoryRoot
    $centralRepoRoot = if ((Split-Path -Leaf $RepositoryRoot) -eq "Codex") {
        $RepositoryRoot
    }
    else {
        Join-Path $githubRoot "Codex"
    }

    return (Join-Path $centralRepoRoot "runtime-data\autopush\completion-signals\pending")
}

function New-CompletionSignalId {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $guid = [guid]::NewGuid().ToString("N")
    return "$timestamp-$guid"
}

function Write-WatcherCompletionSignal {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SignalDirectory,
        [Parameter(Mandatory = $true)]
        [string]$NotificationMessage
    )

    New-Item -ItemType Directory -Force -Path $SignalDirectory | Out-Null

    $signalId = New-CompletionSignalId
    $payload = [ordered]@{
        schema_version = 1
        id = $signalId
        type = "codex-work-completed"
        created_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        repo_root = $repoRoot
        repo_name = $repoName
        task_summary = $TaskSummary
        commit_summary = $CommitSummary
        push_summary = $PushSummary
        extra = $Extra
        link_url = $LinkUrl
        silent = [bool]$Silent
        message = $NotificationMessage
        source_script = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
    }

    $json = $payload | ConvertTo-Json -Depth 5
    $tempPath = Join-Path $SignalDirectory "$signalId.tmp"
    $finalPath = Join-Path $SignalDirectory "$signalId.json"

    Set-Content -LiteralPath $tempPath -Value $json -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $finalPath -Force

    return $finalPath
}

$botToken = $null

if ($ShowRecentChats) {
    $botToken = Get-ConfiguredValue -Name "TELEGRAM_BOT_TOKEN" -ParameterName "BotToken" -ExplicitValue $BotToken -Required
    $updates = Invoke-TelegramApi -Method "getUpdates"
    $rows = @()

    foreach ($update in @($updates.result)) {
        $messageObject = $update.message
        if (-not $messageObject) {
            $messageObject = $update.edited_message
        }
        if (-not $messageObject) {
            $messageObject = $update.channel_post
        }
        if (-not $messageObject) {
            continue
        }

        $chat = $messageObject.chat
        $labelParts = @()
        if ($chat.title) { $labelParts += $chat.title }
        if ($chat.username) { $labelParts += "@$($chat.username)" }
        if ($chat.first_name) { $labelParts += $chat.first_name }
        if ($chat.last_name) { $labelParts += $chat.last_name }

        $rows += [pscustomobject]@{
            update_id = $update.update_id
            chat_id = $chat.id
            chat_type = $chat.type
            chat_label = ($labelParts -join " ").Trim()
            text = $messageObject.text
        }
    }

    if ($rows.Count -eq 0) {
        Write-Host "No recent Telegram chat updates found. Send any message to your bot first, then run this again."
        return
    }

    $rows | Sort-Object update_id -Descending | Format-Table -AutoSize
    return
}

$labelRepository = New-UnicodeText @(0xC800, 0xC7A5, 0xC18C)
$labelTask = New-UnicodeText @(0xC791, 0xC5C5)
$labelTime = New-UnicodeText @(0xC2DC, 0xAC01)
$labelCommit = New-UnicodeText @(0xCEE4, 0xBC0B)
$labelPush = New-UnicodeText @(0xD478, 0xC2DC)
$labelDone = New-UnicodeText @(0xC644, 0xB8CC)
$defaultCompletionTitle = "Codex $labelRepository $labelTask $labelDone"

$completionTitle = if ($env:CODEX_COMPLETION_TITLE) {
    $env:CODEX_COMPLETION_TITLE
}
else {
    $defaultCompletionTitle
}

if (-not $TaskSummary) {
    $TaskSummary = $labelDone
}

if (-not $Message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $messageLines = New-Object System.Collections.Generic.List[string]
    $messageLines.Add($completionTitle)
    $messageLines.Add("${labelRepository}: $repoName")
    $messageLines.Add("${labelTask}: $TaskSummary")
    $messageLines.Add("${labelTime}: $timestamp")

    if ($CommitSummary) {
        $messageLines.Add("${labelCommit}: $CommitSummary")
    }
    if ($PushSummary) {
        $messageLines.Add("${labelPush}: $PushSummary")
    }
    if ($Extra) {
        $messageLines.Add($Extra)
    }

    $Message = $messageLines -join [Environment]::NewLine
}

if ($LinkUrl) {
    $Message = "$Message`n$LinkUrl"
}

if ($Message.Length -gt 4096) {
    throw "Telegram sendMessage text must be 4096 characters or fewer. Current length: $($Message.Length)"
}

$signalDirectory = if ($WatcherSignalDir) {
    $WatcherSignalDir
}
else {
    Get-DefaultWatcherSignalDir -RepositoryRoot $repoRoot
}

$sendDirectly = [bool]$Direct -or [bool]$NoWatcherSignal
$shouldSignalWatcher = -not [bool]$NoWatcherSignal
$chatIdForDisplay = Get-ConfiguredValue -Name "TELEGRAM_CHAT_ID" -ParameterName "ChatId" -ExplicitValue $ChatId
$botTokenForDisplay = Get-ConfiguredValue -Name "TELEGRAM_BOT_TOKEN" -ParameterName "BotToken" -ExplicitValue $BotToken

if ($DryRun) {
    [pscustomobject]@{
        would_signal_watcher = $shouldSignalWatcher
        signal_directory = if ($shouldSignalWatcher) { $signalDirectory } else { "" }
        would_send_direct = $sendDirectly
        message = $Message
        chat_id = $chatIdForDisplay
        silent = [bool]$Silent
        has_bot_token = -not [string]::IsNullOrWhiteSpace($botTokenForDisplay)
    }
    return
}

$signalPath = ""
if ($shouldSignalWatcher) {
    $signalPath = Write-WatcherCompletionSignal -SignalDirectory $signalDirectory -NotificationMessage $Message
}

$directMessageId = $null
$directChatId = $null
if ($sendDirectly) {
    $botToken = Get-ConfiguredValue -Name "TELEGRAM_BOT_TOKEN" -ParameterName "BotToken" -ExplicitValue $BotToken -Required
    $chatId = Get-ConfiguredValue -Name "TELEGRAM_CHAT_ID" -ParameterName "ChatId" -ExplicitValue $ChatId -Required

    $sendBody = @{
        chat_id = $chatId
        text = $Message
        disable_notification = [bool]$Silent
        disable_web_page_preview = $true
    }

    $sendResult = Invoke-TelegramApi -Method "sendMessage" -Body $sendBody
    $directMessageId = $sendResult.result.message_id
    $directChatId = $sendResult.result.chat.id
}

[pscustomobject]@{
    ok = $true
    mode = if ($shouldSignalWatcher) { "watcher-signal" } else { "direct" }
    signal_path = $signalPath
    direct_sent = $sendDirectly
    direct_message_id = $directMessageId
    chat_id = $directChatId
    message = if ($shouldSignalWatcher) { "Watcher notification signal queued." } else { "Telegram notification sent." }
}
