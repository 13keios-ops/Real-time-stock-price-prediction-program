param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$versionPath = Join-Path $repoRoot "VERSION"

if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "Version must not be empty."
}

Set-Content -LiteralPath $versionPath -Value $Version -Encoding UTF8
Write-Output "VERSION updated to $Version"
