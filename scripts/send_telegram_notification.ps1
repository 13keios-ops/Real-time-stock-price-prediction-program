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

$centralHelper = "D:\GitHub\Codex\scripts\send_telegram_notification.ps1"
if (-not (Test-Path -LiteralPath $centralHelper)) {
    throw "Central Codex Telegram helper is missing: $centralHelper"
}

$forward = @{}
foreach ($entry in $PSBoundParameters.GetEnumerator()) {
    $forward[$entry.Key] = $entry.Value
}

if (-not $forward.ContainsKey("RepoRoot")) {
    $forward["RepoRoot"] = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

if (-not $forward.ContainsKey("WatcherSignalDir")) {
    $forward["WatcherSignalDir"] = "D:\GitHub\Codex\runtime-data\autopush\completion-signals\pending"
}

& $centralHelper @forward
