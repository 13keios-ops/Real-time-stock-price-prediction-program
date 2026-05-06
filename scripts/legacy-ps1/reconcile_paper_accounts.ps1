param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

& python -m app --reconcile-paper-accounts
if ($LASTEXITCODE -ne 0) {
    throw "python -m app --reconcile-paper-accounts failed with exit code $LASTEXITCODE"
}
