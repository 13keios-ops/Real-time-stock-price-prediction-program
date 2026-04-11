param(
    [Parameter(Mandatory = $false)]
    [string]$ScanRoot = "J:\\GitHub",

    [Parameter(Mandatory = $false)]
    [string]$ConfigFileName = "autopush.json",

    [Parameter(Mandatory = $false)]
    [string]$VersionFileName = "VERSION",

    [Parameter(Mandatory = $false)]
    [string]$InitialVersion = "0.1.0",

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

function Resolve-GitExecutable {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCommand -and -not [string]::IsNullOrWhiteSpace($gitCommand.Source)) {
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

function Invoke-Git {
    param(
        [string]$RepoPath,
        [string[]]$Arguments
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

    if ($exitCode -ne 0) {
        throw "$script:GitExecutable -C $RepoPath $($Arguments -join ' ') failed`n$text"
    }

    return $text.Trim()
}

function Get-GitRepositories {
    param([string]$Root)

    Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ".git") } |
        Select-Object -ExpandProperty FullName |
        Sort-Object
}

function New-AutopushConfigObject {
    param(
        [bool]$Enabled,
        [string]$Branch
    )

    return [ordered]@{
        enabled            = $Enabled
        branch             = $Branch
        remote             = "origin"
        trigger            = "version-change"
        version_file       = $VersionFileName
        stage_mode         = "all"
        commit_message     = "chore(release): v{version}"
        commit_body_mode   = "staged-summary"
        commit_body_header = "Auto-generated change summary"
        push_tag           = $false
        tag_name           = "v{version}"
    }
}

$script:GitExecutable = Resolve-GitExecutable

if (-not (Test-Path -LiteralPath $ScanRoot)) {
    throw "Scan root '$ScanRoot' does not exist."
}

$results = New-Object System.Collections.Generic.List[object]

foreach ($repoPath in (Get-GitRepositories -Root $ScanRoot)) {
    $repoName = Split-Path -Leaf $repoPath
    $branch = Invoke-Git -RepoPath $repoPath -Arguments @("branch", "--show-current")
    $status = Invoke-Git -RepoPath $repoPath -Arguments @("status", "--porcelain")
    $remoteResult = & $script:GitExecutable -C $repoPath remote get-url origin 2>$null
    $remoteExitCode = $LASTEXITCODE
    $remote = if ($remoteExitCode -eq 0) { ($remoteResult | Out-String).Trim() } else { "" }

    $isDirty = -not [string]::IsNullOrWhiteSpace($status)
    $isMainBranch = $branch -eq "main"
    $hasRemote = -not [string]::IsNullOrWhiteSpace($remote)
    $recommendedEnabled = $isMainBranch -and -not $isDirty -and $hasRemote

    $reason = if (-not $hasRemote) {
        "disabled because origin remote is missing"
    } elseif (-not $isMainBranch) {
        "disabled because current branch is '$branch'"
    } elseif ($isDirty) {
        "disabled because working tree is not clean"
    } else {
        "enabled because branch is main, origin exists, and working tree is clean"
    }

    $versionPath = Join-Path $repoPath $VersionFileName
    $configPath = Join-Path $repoPath $ConfigFileName
    $versionCreated = $false
    $configWritten = $false

    if (-not (Test-Path -LiteralPath $versionPath)) {
        Set-Content -LiteralPath $versionPath -Value $InitialVersion -Encoding UTF8
        $versionCreated = $true
    }

    if ($Force -or -not (Test-Path -LiteralPath $configPath)) {
        $config = New-AutopushConfigObject -Enabled $recommendedEnabled -Branch $branch
        $configJson = $config | ConvertTo-Json -Depth 4
        Set-Content -LiteralPath $configPath -Value $configJson -Encoding UTF8
        $configWritten = $true
    }

    $results.Add([pscustomobject]@{
        repo                = $repoPath
        branch              = $branch
        remote              = $remote
        dirty               = $isDirty
        enabled             = $recommendedEnabled
        enabled_reason      = $reason
        version_created     = $versionCreated
        config_written      = $configWritten
        version_path        = $versionPath
        config_path         = $configPath
    })
}

if ($AsJson) {
    $results | ConvertTo-Json -Depth 5
} else {
    $results
}
