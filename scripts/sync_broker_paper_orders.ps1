param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

python -m app --sync-broker-paper-orders
if ($LASTEXITCODE -ne 0) {
    throw "python -m app --sync-broker-paper-orders failed with exit code $LASTEXITCODE"
}
