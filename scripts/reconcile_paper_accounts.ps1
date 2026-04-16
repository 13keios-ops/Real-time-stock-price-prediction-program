param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

python -m app --reconcile-paper-accounts
