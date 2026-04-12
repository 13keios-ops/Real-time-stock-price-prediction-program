param(
    [string]$WorkspaceRoot = "."
)

$ErrorActionPreference = "Stop"
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
Set-Location -LiteralPath $resolvedWorkspaceRoot

python -m app --cleanup-runtime-test-data --project-root $resolvedWorkspaceRoot
python -m app --build-dashboard --project-root $resolvedWorkspaceRoot
