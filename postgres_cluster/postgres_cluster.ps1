<#
.SYNOPSIS
    Site24x7 PostgreSQL Cluster Plugin PowerShell Runner
.DESCRIPTION
    Executes the PostgreSQL cluster monitor via Python and returns JSON metrics
    to the Site24x7 Windows Agent. Uses Write-Output and works seamlessly with
    Site24x7 agent's redirect_output=1 configuration to avoid anonymous pipe limits.
#>

param(
    [string]$cluster_host = "",
    [string]$postgres_port = "",
    [string]$nodes = "",
    [string]$username = "",
    [string]$password = "",
    [string]$db = "postgres",
    [string]$patroni_port = ""
)

$ErrorActionPreference = "Continue"

# 1. Locate Python executable
$PythonExe = $null

$pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pyCmd -and $pyCmd.Source -notmatch "WindowsApps") {
    $PythonExe = $pyCmd.Source
}

if (-not $PythonExe) {
    $errObj = @{
        plugin_version     = 5
        heartbeat_required = $true
        status             = 0
        msg                = "Python 3 executable not found on host. Please ensure Python is installed with psycopg2-binary."
    }
    Write-Output ($errObj | ConvertTo-Json -Compress)
    exit 0
}

# 2. Locate the Python cluster script
# In deployed agent folder, the file is named postgres_cluster_impl.py
# (so only postgres_cluster.ps1 is registered as the plugin)
$implScript = Join-Path $PSScriptRoot "postgres_cluster_impl.py"
if (-not (Test-Path $implScript)) {
    # Fallback to postgres_cluster.py if running from project repo
    $implScript = Join-Path $PSScriptRoot "postgres_cluster.py"
}

if (-not (Test-Path $implScript)) {
    $errObj = @{
        plugin_version     = 5
        heartbeat_required = $true
        status             = 0
        msg                = "PostgreSQL cluster script not found in: $PSScriptRoot"
    }
    Write-Output ($errObj | ConvertTo-Json -Compress)
    exit 0
}

# 3. Build argument list
$pyArgs = @($implScript)
if ($cluster_host) {
    $pyArgs += @("--cluster_host", $cluster_host)
    if ($postgres_port) { $pyArgs += @("--postgres_port", $postgres_port) }
} elseif ($nodes) {
    $pyArgs += @("--nodes", $nodes)
    if ($postgres_port) { $pyArgs += @("--postgres_port", $postgres_port) }
}
if ($username) {
    $pyArgs += @("--username", $username)
}
if ($db) {
    $pyArgs += @("--db", $db)
} else {
    $pyArgs += @("--db", "postgres")
}
if ($patroni_port) {
    $pyArgs += @("--patroni_port", $patroni_port)
}

# 4. Execute Python and capture output
try {
    $previousPgpw = $env:PGPASSWORD
    if ($password) { $env:PGPASSWORD = $password }
    try {
        $output = & $PythonExe @pyArgs 2>&1
    } finally {
        $env:PGPASSWORD = $previousPgpw
    }
    $exitCode = $LASTEXITCODE

    $outStr = ($output -join "`n").Trim()

    if ($outStr -match '^\s*\{.*"plugin_version".*\}\s*$') {
        Write-Output $outStr
    } elseif ($outStr -match '^\s*\{.*\}\s*$') {
        Write-Output $outStr
    } else {
        $msg = if ($outStr) { $outStr } else { "Process exited with code $exitCode and empty output" }
        $errObj = @{
            plugin_version     = 5
            heartbeat_required = $true
            status             = 0
            msg                = $msg
        }
        Write-Output ($errObj | ConvertTo-Json -Compress)
    }
} catch {
    $errObj = @{
        plugin_version     = 5
        heartbeat_required = $true
        status             = 0
        msg                = "Exception executing Python script: $($_.Exception.Message)"
    }
    Write-Output ($errObj | ConvertTo-Json -Compress)
}
