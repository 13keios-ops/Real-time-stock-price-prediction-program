param(
    [Parameter(Mandatory = $false)]
    [string]$ScanRoot = "D:\GitHub",

    [Parameter(Mandatory = $false)]
    [string]$ConfigFileName = "autopush.json",

    [Parameter(Mandatory = $false)]
    [string]$StatePath = "",

    [Parameter(Mandatory = $false)]
    [string]$LogPath = "",

    [Parameter(Mandatory = $false)]
    [int]$PollSeconds = 60,

    [Parameter(Mandatory = $false)]
    [switch]$Once,

    [Parameter(Mandatory = $false)]
    [switch]$Recurse,

    [Parameter(Mandatory = $false)]
    [switch]$DisableTelegramNotifications
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $PSScriptRoot
$defaultRuntimeDir = Join-Path $toolRoot "runtime-data\autopush"

if (-not $StatePath) {
    $StatePath = Join-Path $defaultRuntimeDir "git-autopush-state.json"
}

if (-not $LogPath) {
    $LogPath = Join-Path $defaultRuntimeDir "git-autopush.log"
}

function Resolve-GitExecutable {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCommand -and
        -not [string]::IsNullOrWhiteSpace($gitCommand.Source) -and
        (Test-Path -LiteralPath $gitCommand.Source)) {
        return $gitCommand.Source
    }

    $desktopRoot = Join-Path $env:LOCALAPPDATA "GitHubDesktop"
    if (Test-Path -LiteralPath $desktopRoot) {
        $desktopGit = Get-ChildItem -LiteralPath $desktopRoot -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "resources\app\git\cmd\git.exe" } |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1

        if ($desktopGit) {
            return $desktopGit
        }
    }

    throw "git executable not found in PATH or GitHub Desktop."
}

function Ensure-ParentDirectory {
    param([string]$Path)

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Write-Log {
    param([string]$Message)

    Ensure-ParentDirectory -Path $LogPath
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Invoke-Git {
    param(
        [string]$RepoPath,
        [string[]]$Arguments,
        [switch]$IgnoreExitCode
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $script:GitExecutable -C $RepoPath @Arguments 2>&1
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { "$_" }) -join [Environment]::NewLine

    if (-not $IgnoreExitCode -and $exitCode -ne 0) {
        throw "$script:GitExecutable -C $RepoPath $($Arguments -join ' ') failed`n$text"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $text.Trim()
    }
}

function Convert-ToRepoRelativePath {
    param(
        [string]$RepoPath,
        [string]$Path
    )

    $repoFull = [System.IO.Path]::GetFullPath($RepoPath)
    $targetFull = [System.IO.Path]::GetFullPath($Path)

    if (-not $targetFull.StartsWith($repoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path $Path is outside repository $RepoPath"
    }

    $relative = $targetFull.Substring($repoFull.Length).TrimStart('\')
    return $relative -replace '\\', '/'
}

function Expand-Template {
    param(
        [string]$Template,
        [string]$Version,
        [string]$RepoName,
        [string]$Branch
    )

    return $Template.Replace("{version}", $Version).Replace("{repo}", $RepoName).Replace("{branch}", $Branch)
}

function Get-GitDirectoryPath {
    param([string]$RepoPath)

    $gitDir = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "--git-dir")).Output
    if ([System.IO.Path]::IsPathRooted($gitDir)) {
        return [System.IO.Path]::GetFullPath($gitDir)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $RepoPath $gitDir))
}

function Assert-RepositoryReadyForCommit {
    param([string]$RepoPath)

    $gitDir = Get-GitDirectoryPath -RepoPath $RepoPath
    $blockedMarkers = @(
        "MERGE_HEAD",
        "REBASE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG"
    )

    foreach ($marker in $blockedMarkers) {
        if (Test-Path -LiteralPath (Join-Path $gitDir $marker)) {
            throw "repository has an active git operation ($marker)"
        }
    }
}

function New-ManagerState {
    return @{
        scan_root  = ""
        updated_at = ""
        repos      = @{}
    }
}

function Import-State {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return (New-ManagerState)
    }

    $raw = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $state = New-ManagerState
    $state.scan_root = "$($raw.scan_root)"
    $state.updated_at = "$($raw.updated_at)"

    if ($raw.repos) {
        foreach ($property in $raw.repos.PSObject.Properties) {
            $repoState = $property.Value
            $state.repos[$property.Name] = @{
                last_observed_version = "$($repoState.last_observed_version)"
                last_pushed_version   = "$($repoState.last_pushed_version)"
                last_commit           = "$($repoState.last_commit)"
                last_result           = "$($repoState.last_result)"
                last_notified_key     = "$($repoState.last_notified_key)"
                last_notified_at      = "$($repoState.last_notified_at)"
                updated_at            = "$($repoState.updated_at)"
            }
        }
    }

    return $state
}

function Export-State {
    param(
        [hashtable]$State,
        [string]$Path
    )

    $scanRootFullPath = ""
    $scanRootPrefix = ""
    if (-not [string]::IsNullOrWhiteSpace($State.scan_root)) {
        $scanRootFullPath = [System.IO.Path]::GetFullPath($State.scan_root)
        $scanRootPrefix = $scanRootFullPath.TrimEnd('\') + "\"
    }

    $repos = [ordered]@{}
    foreach ($repoPath in ($State.repos.Keys | Sort-Object)) {
        $repoFullPath = [System.IO.Path]::GetFullPath($repoPath)
        if ($scanRootPrefix) {
            $isScanRoot = $repoFullPath.Equals($scanRootFullPath, [System.StringComparison]::OrdinalIgnoreCase)
            $isUnderScanRoot = $repoFullPath.StartsWith($scanRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
            if (-not $isScanRoot -and -not $isUnderScanRoot) {
                continue
            }
        }

        $repos[$repoPath] = [ordered]@{
            last_observed_version = $State.repos[$repoPath].last_observed_version
            last_pushed_version   = $State.repos[$repoPath].last_pushed_version
            last_commit           = $State.repos[$repoPath].last_commit
            last_result           = $State.repos[$repoPath].last_result
            last_notified_key     = $State.repos[$repoPath].last_notified_key
            last_notified_at      = $State.repos[$repoPath].last_notified_at
            updated_at            = $State.repos[$repoPath].updated_at
        }
    }

    $payload = [ordered]@{
        scan_root  = $State.scan_root
        updated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        repos      = $repos
    } | ConvertTo-Json -Depth 6

    Ensure-ParentDirectory -Path $Path
    Set-Content -LiteralPath $Path -Value $payload -Encoding UTF8
}

function Get-ManagedRepositories {
    param(
        [string]$Root,
        [string]$ConfigName,
        [switch]$SearchRecursively
    )

    $repositories = New-Object System.Collections.Generic.List[string]

    if (Test-Path -LiteralPath (Join-Path $Root ".git")) {
        if (Test-Path -LiteralPath (Join-Path $Root $ConfigName)) {
            $repositories.Add([System.IO.Path]::GetFullPath($Root))
        }
    }

    $candidateDirs = if ($SearchRecursively) {
        Get-ChildItem -LiteralPath $Root -Directory -Recurse -ErrorAction SilentlyContinue
    } else {
        Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue
    }

    foreach ($directory in $candidateDirs) {
        if (Test-Path -LiteralPath (Join-Path $directory.FullName ".git")) {
            if (Test-Path -LiteralPath (Join-Path $directory.FullName $ConfigName)) {
                $repositories.Add([System.IO.Path]::GetFullPath($directory.FullName))
            }
        }
    }

    return $repositories | Sort-Object -Unique
}

function Import-ProjectConfig {
    param(
        [string]$RepoPath,
        [string]$ConfigName
    )

    $configPath = Join-Path $RepoPath $ConfigName
    $raw = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

    return @{
        enabled            = if ($null -eq $raw.enabled) { $false } else { [bool]$raw.enabled }
        branch             = if ([string]::IsNullOrWhiteSpace($raw.branch)) { "main" } else { "$($raw.branch)" }
        remote             = if ([string]::IsNullOrWhiteSpace($raw.remote)) { "origin" } else { "$($raw.remote)" }
        trigger            = if ([string]::IsNullOrWhiteSpace($raw.trigger)) { "version-change" } else { "$($raw.trigger)" }
        version_file       = if ([string]::IsNullOrWhiteSpace($raw.version_file)) { "VERSION" } else { "$($raw.version_file)" }
        stage_mode         = if ([string]::IsNullOrWhiteSpace($raw.stage_mode)) { "all" } else { "$($raw.stage_mode)" }
        commit_message     = if ([string]::IsNullOrWhiteSpace($raw.commit_message)) { "chore(release): v{version}" } else { "$($raw.commit_message)" }
        commit_body_mode   = if ([string]::IsNullOrWhiteSpace($raw.commit_body_mode)) { "staged-summary" } else { "$($raw.commit_body_mode)" }
        commit_body_header = if ([string]::IsNullOrWhiteSpace($raw.commit_body_header)) { "Auto-generated change summary" } else { "$($raw.commit_body_header)" }
        notify_on_success  = if ($null -eq $raw.notify_on_success) { $true } else { [bool]$raw.notify_on_success }
        push_tag           = if ($null -eq $raw.push_tag) { $false } else { [bool]$raw.push_tag }
        tag_name           = if ([string]::IsNullOrWhiteSpace($raw.tag_name)) { "v{version}" } else { "$($raw.tag_name)" }
    }
}

function Get-RemoteStatus {
    param(
        [string]$RepoPath,
        [string]$Remote,
        [string]$Branch
    )

    $remoteRef = "refs/remotes/$Remote/$Branch"
    $exists = Invoke-Git -RepoPath $RepoPath -Arguments @("show-ref", "--verify", "--quiet", $remoteRef) -IgnoreExitCode
    if ($exists.ExitCode -ne 0) {
        return @{
            has_remote_ref = $false
            ahead          = 0
            behind         = 0
        }
    }

    $counts = Invoke-Git -RepoPath $RepoPath -Arguments @("rev-list", "--left-right", "--count", "$Remote/$Branch...HEAD")
    $parts = $counts.Output -split '\s+'

    return @{
        has_remote_ref = $true
        behind         = [int]$parts[0]
        ahead          = [int]$parts[1]
    }
}

function Stage-RepositoryChanges {
    param(
        [string]$RepoPath,
        [string]$StageMode,
        [string]$VersionFileRelativePath
    )

    switch ($StageMode) {
        "all" {
            Invoke-Git -RepoPath $RepoPath -Arguments @("add", "-A") | Out-Null
        }
        "tracked" {
            Invoke-Git -RepoPath $RepoPath -Arguments @("add", "-u") | Out-Null
            Invoke-Git -RepoPath $RepoPath -Arguments @("add", "--", $VersionFileRelativePath) | Out-Null
        }
        "version-only" {
            Invoke-Git -RepoPath $RepoPath -Arguments @("add", "--", $VersionFileRelativePath) | Out-Null
        }
        default {
            throw "Unsupported stage_mode: $StageMode"
        }
    }
}

function Get-HeadVersionValue {
    param(
        [string]$RepoPath,
        [string]$VersionFileRelativePath
    )

    $result = Invoke-Git -RepoPath $RepoPath -Arguments @("show", "HEAD:$VersionFileRelativePath") -IgnoreExitCode
    if ($result.ExitCode -ne 0) {
        return ""
    }

    return $result.Output.Trim()
}

function Get-StagedFileList {
    param([string]$RepoPath)

    return (Invoke-Git -RepoPath $RepoPath -Arguments @("diff", "--cached", "--name-only")).Output
}

function Convert-ChangeCodeToLabel {
    param([string]$Code)

    switch ($Code.Substring(0, 1)) {
        "A" { return "added" }
        "M" { return "modified" }
        "D" { return "deleted" }
        "R" { return "renamed" }
        "C" { return "copied" }
        "T" { return "type-changed" }
        "U" { return "unmerged" }
        default { return "changed" }
    }
}

function Get-StagedChangeSummaryLines {
    param([string]$RepoPath)

    $nameStatusOutput = (Invoke-Git -RepoPath $RepoPath -Arguments @("diff", "--cached", "--name-status", "--find-renames")).Output
    if ([string]::IsNullOrWhiteSpace($nameStatusOutput)) {
        return @()
    }

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($entry in ($nameStatusOutput -split "\r?\n")) {
        if ([string]::IsNullOrWhiteSpace($entry)) {
            continue
        }

        $parts = $entry -split "`t"
        $code = $parts[0]
        $label = Convert-ChangeCodeToLabel -Code $code

        if ($code.StartsWith("R") -and $parts.Count -ge 3) {
            $lines.Add("${label}: $($parts[1]) -> $($parts[2])")
        } elseif ($parts.Count -ge 2) {
            $lines.Add("${label}: $($parts[1])")
        } else {
            $lines.Add("${label}: $entry")
        }
    }

    return $lines.ToArray()
}

function Get-StagedDiffStat {
    param([string]$RepoPath)

    return (Invoke-Git -RepoPath $RepoPath -Arguments @("diff", "--cached", "--stat")).Output
}

function New-CommitBodyText {
    param(
        [string]$RepoPath,
        [hashtable]$Config,
        [string]$Version,
        [string]$RepoName,
        [string]$Branch
    )

    switch ($Config.commit_body_mode) {
        "none" {
            return ""
        }
        "staged-summary" {
            $header = Expand-Template -Template $Config.commit_body_header -Version $Version -RepoName $RepoName -Branch $Branch
            $changeLines = Get-StagedChangeSummaryLines -RepoPath $RepoPath
            $diffStat = Get-StagedDiffStat -RepoPath $RepoPath
            $bodyLines = New-Object System.Collections.Generic.List[string]

            $bodyLines.Add("Version: $Version")
            $bodyLines.Add("")
            $bodyLines.Add("${header}:")

            if ($changeLines.Count -gt 0) {
                foreach ($changeLine in $changeLines) {
                    $bodyLines.Add("- $changeLine")
                }
            } else {
                $bodyLines.Add("- no staged file list available")
            }

            if (-not [string]::IsNullOrWhiteSpace($diffStat)) {
                $bodyLines.Add("")
                $bodyLines.Add("Diffstat:")

                foreach ($statLine in ($diffStat -split "\r?\n")) {
                    $bodyLines.Add($statLine)
                }
            }

            return ($bodyLines -join [Environment]::NewLine).Trim()
        }
        default {
            throw "Unsupported commit_body_mode: $($Config.commit_body_mode)"
        }
    }
}

function Push-Repository {
    param(
        [string]$RepoPath,
        [string]$Remote,
        [string]$Branch,
        [bool]$PushTag,
        [string]$TagName
    )

    $remoteStatus = Get-RemoteStatus -RepoPath $RepoPath -Remote $Remote -Branch $Branch

    if ($remoteStatus.has_remote_ref) {
        Invoke-Git -RepoPath $RepoPath -Arguments @("push", $Remote, $Branch) | Out-Null
    } else {
        Invoke-Git -RepoPath $RepoPath -Arguments @("push", "-u", $Remote, $Branch) | Out-Null
    }

    if ($PushTag) {
        $tagCheck = Invoke-Git -RepoPath $RepoPath -Arguments @("tag", "--list", $TagName)
        if ([string]::IsNullOrWhiteSpace($tagCheck.Output)) {
            Invoke-Git -RepoPath $RepoPath -Arguments @("tag", $TagName) | Out-Null
        }

        Invoke-Git -RepoPath $RepoPath -Arguments @("push", $Remote, $TagName) | Out-Null
    }
}

function Update-RepoState {
    param(
        [hashtable]$State,
        [string]$RepoPath,
        [string]$ObservedVersion,
        [string]$PushedVersion,
        [string]$CommitHash,
        [string]$Result
    )

    if (-not $State.repos.ContainsKey($RepoPath)) {
        $State.repos[$RepoPath] = @{}
    }

    $State.repos[$RepoPath].last_observed_version = $ObservedVersion
    $State.repos[$RepoPath].last_pushed_version = $PushedVersion
    $State.repos[$RepoPath].last_commit = $CommitHash
    $State.repos[$RepoPath].last_result = $Result
    $State.repos[$RepoPath].updated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
}

function Get-ConfiguredSecret {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not $value) {
        $value = [Environment]::GetEnvironmentVariable($Name, "User")
    }
    if (-not $value) {
        $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
    }

    if ($value) {
        return $value.Trim()
    }

    return ""
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

function Send-TelegramMessage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    if ($DisableTelegramNotifications) {
        return "disabled"
    }

    $botToken = Get-ConfiguredSecret -Name "TELEGRAM_BOT_TOKEN"
    $chatId = Get-ConfiguredSecret -Name "TELEGRAM_CHAT_ID"

    if ([string]::IsNullOrWhiteSpace($botToken) -or [string]::IsNullOrWhiteSpace($chatId)) {
        return "missing-env"
    }

    try {
        $sendResult = Invoke-RestMethod `
            -Method Post `
            -Uri "https://api.telegram.org/bot$botToken/sendMessage" `
            -ContentType "application/x-www-form-urlencoded;charset=utf-8" `
            -Body @{
                chat_id = $chatId
                text = $Text
                disable_notification = $false
                disable_web_page_preview = $true
            }

        if ($sendResult.ok) {
            return "sent"
        }

        return "failed"
    }
    catch {
        $responseBody = Get-ErrorResponseBody -ErrorRecord $_
        if ($responseBody) {
            return "failed: $responseBody"
        }

        return "failed: $($_.Exception.Message)"
    }
}

function Send-RepoCompletionNotification {
    param(
        [hashtable]$State,
        [string]$RepoPath,
        [hashtable]$Config,
        [string]$RepoName,
        [string]$Version,
        [string]$CommitHash,
        [string]$Result
    )

    if (-not $Config.notify_on_success) {
        return
    }

    if (-not $State.repos.ContainsKey($RepoPath)) {
        return
    }

    $shortHash = if ($CommitHash.Length -ge 7) { $CommitHash.Substring(0, 7) } else { $CommitHash }
    $notificationKey = "$Result|$Version|$CommitHash"
    $previousNotificationKey = if ($State.repos[$RepoPath].ContainsKey("last_notified_key")) { "$($State.repos[$RepoPath].last_notified_key)" } else { "" }

    if ($previousNotificationKey -eq $notificationKey) {
        return
    }

    $messageLines = @(
        "Codex 저장소 작업 완료",
        "저장소: $RepoName",
        "결과: $Result",
        "버전: $Version",
        "브랜치: $($Config.branch)",
        "커밋: $shortHash"
    )

    $sendStatus = Send-TelegramMessage -Text ($messageLines -join [Environment]::NewLine)

    if ($sendStatus -eq "sent") {
        $State.repos[$RepoPath].last_notified_key = $notificationKey
        $State.repos[$RepoPath].last_notified_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
        Write-Log "[$RepoName] Telegram completion notification sent for version '$Version'"
    } elseif ($sendStatus -eq "missing-env") {
        Write-Log "[$RepoName] Telegram completion notification skipped because TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing"
    } elseif ($sendStatus -ne "disabled") {
        Write-Log "[$RepoName] Telegram completion notification $sendStatus"
    }
}

function Remove-StaleRepoState {
    param(
        [hashtable]$State,
        [string[]]$ActiveRepositories
    )

    $activeRepoMap = @{}
    foreach ($activeRepository in $ActiveRepositories) {
        $activeRepoPath = [System.IO.Path]::GetFullPath($activeRepository)
        $activeRepoMap[$activeRepoPath] = $true
    }

    $staleRepoPaths = @(
        $State.repos.Keys |
            Where-Object { -not $activeRepoMap.ContainsKey([System.IO.Path]::GetFullPath($_)) }
    )

    foreach ($staleRepoPath in $staleRepoPaths) {
        Write-Log "Pruned stale repo state outside current scan root: $staleRepoPath"
    }

    $filteredRepos = @{}
    foreach ($repoPath in ($activeRepoMap.Keys | Sort-Object)) {
        if ($State.repos.ContainsKey($repoPath)) {
            $filteredRepos[$repoPath] = $State.repos[$repoPath]
        }
    }

    $State.repos = $filteredRepos
}

function Process-Repository {
    param(
        [string]$RepoPath,
        [hashtable]$State
    )

    $repoName = Split-Path -Leaf $RepoPath
    $config = Import-ProjectConfig -RepoPath $RepoPath -ConfigName $ConfigFileName

    if (-not $config.enabled) {
        Write-Log "[$repoName] disabled in $ConfigFileName"
        return
    }

    if ($config.trigger -ne "version-change") {
        Write-Log "[$repoName] unsupported trigger '$($config.trigger)'; skipped"
        return
    }

    $currentBranch = Invoke-Git -RepoPath $RepoPath -Arguments @("branch", "--show-current")
    if ($currentBranch.Output -ne $config.branch) {
        Write-Log "[$repoName] current branch '$($currentBranch.Output)' does not match configured branch '$($config.branch)'; skipped"
        return
    }

    $versionPath = Join-Path $RepoPath $config.version_file
    if (-not (Test-Path -LiteralPath $versionPath)) {
        Write-Log "[$repoName] missing version file '$($config.version_file)'; skipped"
        return
    }

    $currentVersion = (Get-Content -LiteralPath $versionPath -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($currentVersion)) {
        Write-Log "[$repoName] version file '$($config.version_file)' is empty; skipped"
        return
    }

    Assert-RepositoryReadyForCommit -RepoPath $RepoPath

    $repoState = if ($State.repos.ContainsKey($RepoPath)) { $State.repos[$RepoPath] } else { @{} }
    $lastPushedVersion = if ($repoState.ContainsKey("last_pushed_version")) { "$($repoState.last_pushed_version)" } else { "" }

    $status = Invoke-Git -RepoPath $RepoPath -Arguments @("status", "--porcelain")
    $hasWorkingTreeChanges = -not [string]::IsNullOrWhiteSpace($status.Output)
    $remoteStatus = Get-RemoteStatus -RepoPath $RepoPath -Remote $config.remote -Branch $config.branch
    $versionChanged = $currentVersion -ne $lastPushedVersion
    $versionFileRelativePath = Convert-ToRepoRelativePath -RepoPath $RepoPath -Path $versionPath
    $headVersion = Get-HeadVersionValue -RepoPath $RepoPath -VersionFileRelativePath $versionFileRelativePath
    $headAlreadyHasVersion = $headVersion -eq $currentVersion

    if ($remoteStatus.has_remote_ref -and $remoteStatus.behind -gt 0) {
        $commitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
        Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $lastPushedVersion -CommitHash $commitHash -Result "branch-behind-remote"
        Write-Log "[$repoName] branch '$($config.branch)' is behind '$($config.remote)/$($config.branch)'; skipped to avoid unsafe auto-commit"
        return
    }

    if (-not $versionChanged) {
        Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $currentVersion -CommitHash (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output -Result "no-version-change"
        Write-Log "[$repoName] version '$currentVersion' unchanged; skipped"
        return
    }

    if ($headAlreadyHasVersion) {
        if (($remoteStatus.has_remote_ref -and $remoteStatus.ahead -gt 0) -or (-not $remoteStatus.has_remote_ref)) {
            $tagName = Expand-Template -Template $config.tag_name -Version $currentVersion -RepoName $repoName -Branch $config.branch
            Push-Repository -RepoPath $RepoPath -Remote $config.remote -Branch $config.branch -PushTag $config.push_tag -TagName $tagName
            $commitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
            Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $currentVersion -CommitHash $commitHash -Result "pushed-existing-version-commit"
            Write-Log "[$repoName] pushed existing HEAD for version '$currentVersion' without creating a new commit"
            Send-RepoCompletionNotification -State $State -RepoPath $RepoPath -Config $config -RepoName $repoName -Version $currentVersion -CommitHash $commitHash -Result "pushed-existing-version-commit"
            return
        }

        $commitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
        Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $currentVersion -CommitHash $commitHash -Result "synced-head-version"
        Write-Log "[$repoName] HEAD already contains version '$currentVersion'; watcher state updated without commit"
        return
    }

    if (-not $hasWorkingTreeChanges) {
        if (($remoteStatus.has_remote_ref -and $remoteStatus.ahead -gt 0) -or (-not $remoteStatus.has_remote_ref)) {
            $tagName = Expand-Template -Template $config.tag_name -Version $currentVersion -RepoName $repoName -Branch $config.branch
            Push-Repository -RepoPath $RepoPath -Remote $config.remote -Branch $config.branch -PushTag $config.push_tag -TagName $tagName
            $commitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
            Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $currentVersion -CommitHash $commitHash -Result "pushed-clean-head"
            Write-Log "[$repoName] pushed existing clean commit for version '$currentVersion'"
            Send-RepoCompletionNotification -State $State -RepoPath $RepoPath -Config $config -RepoName $repoName -Version $currentVersion -CommitHash $commitHash -Result "pushed-clean-head"
            return
        }

        $commitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
        Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $currentVersion -CommitHash $commitHash -Result "synced-clean-state"
        Write-Log "[$repoName] version '$currentVersion' already clean; watcher state updated without commit"
        return
    }

    Stage-RepositoryChanges -RepoPath $RepoPath -StageMode $config.stage_mode -VersionFileRelativePath $versionFileRelativePath

    $stagedFiles = Get-StagedFileList -RepoPath $RepoPath
    if ([string]::IsNullOrWhiteSpace($stagedFiles)) {
        $commitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
        Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $lastPushedVersion -CommitHash $commitHash -Result "no-staged-diff"
        Write-Log "[$repoName] no staged changes found after applying stage_mode '$($config.stage_mode)'; skipped"
        return
    }

    $commitMessage = Expand-Template -Template $config.commit_message -Version $currentVersion -RepoName $repoName -Branch $config.branch
    $commitBody = New-CommitBodyText -RepoPath $RepoPath -Config $config -Version $currentVersion -RepoName $repoName -Branch $config.branch

    if ([string]::IsNullOrWhiteSpace($commitBody)) {
        Invoke-Git -RepoPath $RepoPath -Arguments @("commit", "-m", $commitMessage) | Out-Null
    } else {
        Invoke-Git -RepoPath $RepoPath -Arguments @("commit", "-m", $commitMessage, "-m", $commitBody) | Out-Null
    }

    $tagNameForPush = Expand-Template -Template $config.tag_name -Version $currentVersion -RepoName $repoName -Branch $config.branch
    Push-Repository -RepoPath $RepoPath -Remote $config.remote -Branch $config.branch -PushTag $config.push_tag -TagName $tagNameForPush

    $newCommitHash = (Invoke-Git -RepoPath $RepoPath -Arguments @("rev-parse", "HEAD")).Output
    Update-RepoState -State $State -RepoPath $RepoPath -ObservedVersion $currentVersion -PushedVersion $currentVersion -CommitHash $newCommitHash -Result "committed-and-pushed"
    Write-Log "[$repoName] committed and pushed version '$currentVersion' on branch '$($config.branch)'"
    Send-RepoCompletionNotification -State $State -RepoPath $RepoPath -Config $config -RepoName $repoName -Version $currentVersion -CommitHash $newCommitHash -Result "committed-and-pushed"
}

$script:GitExecutable = Resolve-GitExecutable
$gitName = Split-Path -Leaf $script:GitExecutable
Write-Log "Using git executable: $gitName ($script:GitExecutable)"

$state = Import-State -Path $StatePath
$state.scan_root = $ScanRoot

do {
    try {
        if (-not (Test-Path -LiteralPath $ScanRoot)) {
            throw "Scan root '$ScanRoot' does not exist."
        }

        $repositories = Get-ManagedRepositories -Root $ScanRoot -ConfigName $ConfigFileName -SearchRecursively:$Recurse
        Remove-StaleRepoState -State $state -ActiveRepositories $repositories

        if (-not $repositories) {
            Write-Log "No managed repositories found under $ScanRoot"
        } else {
            foreach ($repository in $repositories) {
                try {
                    Process-Repository -RepoPath $repository -State $state
                } catch {
                    $repoName = Split-Path -Leaf $repository
                    Write-Log "[$repoName] error: $($_.Exception.Message)"
                }
            }
        }

        Export-State -State $state -Path $StatePath
    } catch {
        Write-Log "Watcher cycle failed: $($_.Exception.Message)"
    }

    if (-not $Once) {
        Start-Sleep -Seconds $PollSeconds
    }
} while (-not $Once)
