param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

& python -m app --kis-account-balance
if ($LASTEXITCODE -ne 0) {
    throw "python -m app --kis-account-balance failed with exit code $LASTEXITCODE"
}
