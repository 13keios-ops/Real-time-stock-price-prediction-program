function Get-CommandLineProcessRecord {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,

        [Parameter(Mandatory = $false)]
        [string[]]$AllowedProcessNames = @(),

        [Parameter(Mandatory = $false)]
        [string[]]$RequiredCommandPatterns = @()
    )

    if (-not $ProcessId) {
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace($process.CommandLine)) {
        return $null
    }

    if ($AllowedProcessNames.Count -gt 0) {
        $matchedName = $false
        foreach ($allowedName in $AllowedProcessNames) {
            if ([string]::Equals("$($process.Name)", "$allowedName", [System.StringComparison]::OrdinalIgnoreCase)) {
                $matchedName = $true
                break
            }
        }

        if (-not $matchedName) {
            return $null
        }
    }

    $commandLine = "$($process.CommandLine)"
    foreach ($pattern in $RequiredCommandPatterns) {
        if ($commandLine -notmatch $pattern) {
            return $null
        }
    }

    return $process
}

function Get-PowerShellScriptProcessRecord {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,

        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
        return $null
    }

    return Get-CommandLineProcessRecord `
        -ProcessId $ProcessId `
        -AllowedProcessNames @("powershell.exe", "pwsh.exe") `
        -RequiredCommandPatterns @([regex]::Escape($ScriptPath))
}

function Get-PythonAppProcessRecord {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,

        [Parameter(Mandatory = $false)]
        [string[]]$RequiredCommandPatterns = @()
    )

    $patterns = @('(?i)(^|\s)-m\s+app(\s|$)')
    if ($RequiredCommandPatterns) {
        $patterns += $RequiredCommandPatterns
    }

    return Get-CommandLineProcessRecord `
        -ProcessId $ProcessId `
        -RequiredCommandPatterns $patterns
}
