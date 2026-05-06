param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-Location $WorkspaceRoot

python -m app --align-local-paper-to-broker
if ($LASTEXITCODE -ne 0) {
    throw "python -m app --align-local-paper-to-broker failed with exit code $LASTEXITCODE"
}
