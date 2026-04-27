param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter(Mandatory = $false)]
    [string]$RuntimeDataDir = "",

    [Parameter(Mandatory = $false)]
    [string]$LauncherName = "RealTimeStockRuntime.cmd"
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeDataDir) {
    $RuntimeDataDir = Join-Path $WorkspaceRoot "runtime-data"
}

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$launcherPath = Join-Path $startupDir $LauncherName
$exists = Test-Path -LiteralPath $launcherPath
$launcherContent = if ($exists) {
    [System.IO.File]::ReadAllText($launcherPath, [System.Text.Encoding]::ASCII)
} else {
    ""
}

function Get-NormalizedPathValue {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }

    try {
        if (Test-Path -LiteralPath $PathValue) {
            return (Get-Item -LiteralPath $PathValue).FullName
        }
    } catch {
    }

    return "$PathValue".Trim()
}

$launcherWorkspaceRoot = ""
$launcherRuntimeDataDir = ""
$autobootScriptPath = ""
if ($launcherContent) {
    $workspaceMatch = [regex]::Match($launcherContent, '-WorkspaceRoot\s+"([^"]+)"')
    if ($workspaceMatch.Success) {
        $launcherWorkspaceRoot = $workspaceMatch.Groups[1].Value
    }

    $runtimeDataMatch = [regex]::Match($launcherContent, '-RuntimeDataDir\s+"([^"]+)"')
    if ($runtimeDataMatch.Success) {
        $launcherRuntimeDataDir = $runtimeDataMatch.Groups[1].Value
    }

    $autobootMatch = [regex]::Match($launcherContent, '-File\s+"([^"]+)"')
    if ($autobootMatch.Success) {
        $autobootScriptPath = $autobootMatch.Groups[1].Value
    }
}

$expectedWorkspaceRoot = Get-NormalizedPathValue -PathValue $WorkspaceRoot
$expectedRuntimeDataDir = Get-NormalizedPathValue -PathValue $RuntimeDataDir
$normalizedLauncherWorkspaceRoot = Get-NormalizedPathValue -PathValue $launcherWorkspaceRoot
$normalizedLauncherRuntimeDataDir = Get-NormalizedPathValue -PathValue $launcherRuntimeDataDir
$normalizedAutobootScriptPath = Get-NormalizedPathValue -PathValue $autobootScriptPath
$workspaceRootMatches = $exists -and
    (-not [string]::IsNullOrWhiteSpace($normalizedLauncherWorkspaceRoot)) -and
    [string]::Equals($normalizedLauncherWorkspaceRoot, $expectedWorkspaceRoot, [System.StringComparison]::OrdinalIgnoreCase)
$runtimeDataDirMatches = $exists -and
    (-not [string]::IsNullOrWhiteSpace($normalizedLauncherRuntimeDataDir)) -and
    [string]::Equals($normalizedLauncherRuntimeDataDir, $expectedRuntimeDataDir, [System.StringComparison]::OrdinalIgnoreCase)
$autobootScriptExists = $false
if ($normalizedAutobootScriptPath) {
    $autobootScriptExists = Test-Path -LiteralPath $normalizedAutobootScriptPath
}

$staleReasons = @()
if ($exists) {
    if (-not $workspaceRootMatches) {
        $staleReasons += "workspace_root_mismatch"
    }
    if (-not $runtimeDataDirMatches) {
        $staleReasons += "runtime_data_dir_mismatch"
    }
    if (-not $autobootScriptExists) {
        $staleReasons += "autoboot_script_missing"
    }
}

[ordered]@{
    installed = $exists
    ok = $exists -and ($staleReasons.Count -eq 0)
    launcher_path = $launcherPath
    startup_dir = $startupDir
    launcher_workspace_root = $launcherWorkspaceRoot
    launcher_runtime_data_dir = $launcherRuntimeDataDir
    autoboot_script_path = $autobootScriptPath
    autoboot_script_exists = $autobootScriptExists
    workspace_root_matches = $workspaceRootMatches
    runtime_data_dir_matches = $runtimeDataDirMatches
    stale_reasons = $staleReasons
    last_write_time = if ($exists) { (Get-Item -LiteralPath $launcherPath).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz") } else { $null }
} | ConvertTo-Json -Depth 10
