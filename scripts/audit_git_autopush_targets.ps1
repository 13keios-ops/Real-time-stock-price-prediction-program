param(
    [Parameter(Mandatory = $false)]
    [string]$ScanRoot = "D:\GitHub",

    [Parameter(Mandatory = $false)]
    [string]$ConfigFileName = "autopush.json",

    [Parameter(Mandatory = $false)]
    [string]$VersionFileName = "VERSION",

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

function Get-GitRepositories {
    param([string]$Root)

    Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ".git") } |
        Select-Object -ExpandProperty FullName |
        Sort-Object
}

function Get-RecommendationReason {
    param(
        [bool]$HasRemote,
        [bool]$IsMainBranch,
        [bool]$IsDirty,
        [bool]$HasConfig,
        [bool]$HasVersion,
        [string]$Branch
    )

    if (-not $HasConfig) {
        return "missing autopush.json"
    }

    if (-not $HasVersion) {
        return "missing VERSION"
    }

    if (-not $HasRemote) {
        return "origin remote is missing"
    }

    if (-not $IsMainBranch) {
        return "current branch is '$Branch'"
    }

    if ($IsDirty) {
        return "working tree is not clean"
    }

    return "ready to enable"
}

$script:GitExecutable = Resolve-GitExecutable

if (-not (Test-Path -LiteralPath $ScanRoot)) {
    throw "Scan root '$ScanRoot' does not exist."
}

$results = New-Object System.Collections.Generic.List[object]

foreach ($repoPath in (Get-GitRepositories -Root $ScanRoot)) {
    $branch = (Invoke-Git -RepoPath $RepoPath -Arguments @("branch", "--show-current")).Output
    $remoteResult = Invoke-Git -RepoPath $RepoPath -Arguments @("remote", "get-url", "origin") -IgnoreExitCode
    $status = (Invoke-Git -RepoPath $RepoPath -Arguments @("status", "--porcelain")).Output
    $configPath = Join-Path $repoPath $ConfigFileName
    $versionPath = Join-Path $repoPath $VersionFileName
    $hasConfig = Test-Path -LiteralPath $configPath
    $hasVersion = Test-Path -LiteralPath $versionPath
    $currentEnabled = $null

    if ($hasConfig) {
        $currentEnabled = [bool]((Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).enabled)
    }

    $hasRemote = $remoteResult.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($remoteResult.Output)
    $isMainBranch = $branch -eq "main"
    $isDirty = -not [string]::IsNullOrWhiteSpace($status)
    $recommendedEnabled = $hasConfig -and $hasVersion -and $hasRemote -and $isMainBranch -and -not $isDirty
    $reason = Get-RecommendationReason -HasRemote $hasRemote -IsMainBranch $isMainBranch -IsDirty $isDirty -HasConfig $hasConfig -HasVersion $hasVersion -Branch $branch

    $results.Add([pscustomobject]@{
        repo                  = $repoPath
        branch                = $branch
        remote                = if ($hasRemote) { $remoteResult.Output } else { "" }
        dirty                 = $isDirty
        has_config            = $hasConfig
        has_version           = $hasVersion
        current_enabled       = $currentEnabled
        recommended_enabled   = $recommendedEnabled
        recommendation_reason = $reason
        config_path           = $configPath
        version_path          = $versionPath
    })
}

if ($AsJson) {
    $results | ConvertTo-Json -Depth 5
} else {
    $results
}
