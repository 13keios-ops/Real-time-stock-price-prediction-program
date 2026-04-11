param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [Parameter(Mandatory = $false)]
    [string]$ConfigFileName = "autopush.json",

    [Parameter(Mandatory = $false)]
    [switch]$Enable,

    [Parameter(Mandatory = $false)]
    [switch]$Disable,

    [Parameter(Mandatory = $false)]
    [switch]$AllowDirty,

    [Parameter(Mandatory = $false)]
    [switch]$AllowNonMain,

    [Parameter(Mandatory = $false)]
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

if ($Enable -and $Disable) {
    throw "Choose either -Enable or -Disable, not both."
}

if (-not $Enable -and -not $Disable) {
    throw "Specify either -Enable or -Disable."
}

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
        [string]$WorkingRepo,
        [string[]]$Arguments
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $script:GitExecutable -C $WorkingRepo @Arguments 2>&1
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { "$_" }) -join [Environment]::NewLine

    if ($exitCode -ne 0) {
        throw "$script:GitExecutable -C $WorkingRepo $($Arguments -join ' ') failed`n$text"
    }

    return $text.Trim()
}

$script:GitExecutable = Resolve-GitExecutable
$resolvedRepoPath = [System.IO.Path]::GetFullPath($RepoPath)
$configPath = Join-Path $resolvedRepoPath $ConfigFileName

if (-not (Test-Path -LiteralPath (Join-Path $resolvedRepoPath ".git"))) {
    throw "Repository '$resolvedRepoPath' does not contain a .git directory."
}

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Config '$configPath' does not exist."
}

$branch = Invoke-Git -WorkingRepo $resolvedRepoPath -Arguments @("branch", "--show-current")
$status = Invoke-Git -WorkingRepo $resolvedRepoPath -Arguments @("status", "--porcelain")
$isDirty = -not [string]::IsNullOrWhiteSpace($status)
$isMainBranch = $branch -eq "main"

if ($Enable -and -not $AllowDirty -and $isDirty) {
    throw "Refusing to enable autopush for '$resolvedRepoPath' because the working tree is dirty. Use -AllowDirty only if you intentionally want that."
}

if ($Enable -and -not $AllowNonMain -and -not $isMainBranch) {
    throw "Refusing to enable autopush for '$resolvedRepoPath' because the current branch is '$branch'. Use -AllowNonMain only if you intentionally want that."
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$config.enabled = [bool]$Enable
$config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding UTF8

$result = [pscustomobject]@{
    repo            = $resolvedRepoPath
    branch          = $branch
    dirty           = $isDirty
    enabled         = [bool]$Enable
    config_path     = $configPath
    safety_override = ($AllowDirty -or $AllowNonMain)
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 5
} else {
    $result
}
