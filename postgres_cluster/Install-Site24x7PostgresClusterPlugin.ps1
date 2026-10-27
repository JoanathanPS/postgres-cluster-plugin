<#
.SYNOPSIS
    Site24x7 PostgreSQL Cluster Plugin Windows Installer
.DESCRIPTION
    Installs and configures the postgres_cluster plugin for the Site24x7 Windows Agent.
    Validates Python and psycopg2-binary, verifies connectivity, tests plugin execution,
    ensures the Windows Service (SYSTEM account) has Python in PATH, and deploys the
    plugin files to the Site24x7 agent plugins directory.
.PARAMETER Nodes
    Comma-separated list of cluster nodes (e.g. "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443")
.PARAMETER Username
    PostgreSQL monitoring username (default: "site24x7")
.PARAMETER Password
    PostgreSQL monitoring password
.PARAMETER Db
    Target database name (default: "postgres")
.PARAMETER PatroniPort
    Patroni REST API port or mapping (default: "8008")
.PARAMETER AgentDir
    Site24x7 Windows Agent directory (default: "C:\Program Files (x86)\Site24x7\WinAgent")
.PARAMETER NonInteractive
    Runs without interactive prompts (useful for automated scripts and CI/CD)
.EXAMPLE
    .\Install-Site24x7PostgresClusterPlugin.ps1
.EXAMPLE
    .\Install-Site24x7PostgresClusterPlugin.ps1 -Nodes "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443" -Username "site24x7" -Password "site24x7"
#>

[CmdletBinding()]
param(
    [string]$Nodes = "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443",
    [string]$Username = "site24x7",
    [string]$Password = "",
    [string]$Database = "postgres",
    [string]$PatroniPort = "8008",
    [int]$UseAgentPython = 0,
    [string]$AgentDir = "C:\Program Files (x86)\Site24x7\WinAgent",
    [switch]$NonInteractive,
    [switch]$SkipAdminCheck
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step {
    param([string]$Text)
    Write-Host "`n=== $Text ===" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Text)
    Write-Host " [OK] $Text" -ForegroundColor Green
}

function Write-WarningMsg {
    param([string]$Text)
    Write-Host " [WARN] $Text" -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([string]$Text)
    Write-Host " [ERROR] $Text" -ForegroundColor Red
}

function Check-Admin {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ==============================================================================
# 1. Administrator Elevation Check
# ==============================================================================
Write-Step "1/6 Checking Permissions"
if ($SkipAdminCheck) {
    Write-WarningMsg "Skipping Administrator check (-SkipAdminCheck passed)."
} else {
    $isAdmin = Check-Admin
    if (-not $isAdmin) {
        Write-WarningMsg "Administrator privileges are required to install plugins into the Site24x7 Agent directory."
        if (-not $NonInteractive) {
            $elevate = Read-Host "Would you like to relaunch this installer as Administrator? (Y/n)"
            if ($elevate -eq "" -or $elevate -match "^[Yy]") {
                $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
                if ($Nodes) { $argList += " -Nodes `"$Nodes`"" }
                if ($Username) { $argList += " -Username `"$Username`"" }
                if ($Password) { $argList += " -Password `"$Password`"" }
                if ($Database) { $argList += " -Database `"$Database`"" }
                if ($PatroniPort) { $argList += " -PatroniPort `"$PatroniPort`"" }
                if ($AgentDir) { $argList += " -AgentDir `"$AgentDir`"" }
                Start-Process powershell -Verb RunAs -ArgumentList $argList
                exit 0
            }
        }
        Write-ErrorMsg "Installation aborted: Administrator rights required."
        exit 1
    }
    Write-Success "Running with Administrator privileges."
}

# ==============================================================================
# 2. Python Environment Detection & Dependency Check
# ==============================================================================
Write-Step "2/6 Locating Python and psycopg2-binary"

$PythonExe = $null

# Priority 1: Check standard PATH
try {
    $pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pyCmd -and $pyCmd.Source -notmatch "WindowsApps") {
        $PythonExe = $pyCmd.Source
    }
} catch {}

# Priority 2: Check py launcher
if (-not $PythonExe) {
    try {
        $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            $lines = & py -0p 2>&1
            foreach ($line in $lines) {
                if ($line -match '([A-Z]:\\[^\s]+\\python\.exe)') {
                    $candidate = $matches[1]
                    if (Test-Path $candidate) {
                        $PythonExe = $candidate
                        break
                    }
                }
            }
        }
    } catch {}
}

# Priority 3: Search common user/system install locations
if (-not $PythonExe) {
    $searchPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Python313\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($path in $searchPaths) {
        if (Test-Path $path) {
            $PythonExe = $path
            break
        }
    }
}

if (-not $PythonExe) {
    Write-ErrorMsg "Python 3 could not be located. Please install Python 3 (https://www.python.org) and rerun this installer."
    exit 1
}

$pyVersion = (& $PythonExe --version 2>&1).ToString().Trim()
Write-Success "Found Python: $PythonExe ($pyVersion)"

# Ensure psycopg2-binary is installed
Write-Host "Verifying psycopg2 module..."
$psycopgCheck = & $PythonExe -c "import psycopg2; print(psycopg2.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-WarningMsg "psycopg2 is not installed. Installing psycopg2-binary..."
    & $PythonExe -m pip install --quiet psycopg2-binary
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorMsg "Failed to install psycopg2-binary. Please run: & `"$PythonExe`" -m pip install psycopg2-binary"
        exit 1
    }
    Write-Success "psycopg2-binary successfully installed."
} else {
    Write-Success "psycopg2 is available (v$psycopgCheck)."
}

# ==============================================================================
# 3. Configure Python for the Site24x7 Windows Service (SYSTEM Account)
# ==============================================================================
Write-Step "3/6 Ensuring Python Availability for Site24x7 Windows Service"

# The Site24x7 Windows Service runs as NT AUTHORITY\SYSTEM and only reads Machine Environment PATH.
$pyFolder = Split-Path -Parent $PythonExe
$pyScripts = Join-Path $pyFolder "Scripts"
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")

$needsPathUpdate = $false
if ($machinePath -notmatch [regex]::Escape($pyFolder)) {
    $machinePath = "$pyFolder;$machinePath"
    $needsPathUpdate = $true
}
if ($machinePath -notmatch [regex]::Escape($pyScripts)) {
    $machinePath = "$pyScripts;$machinePath"
    $needsPathUpdate = $true
}

if ($needsPathUpdate) {
    Write-Host "Adding Python directory to Machine PATH for SYSTEM service..."
    try {
        [Environment]::SetEnvironmentVariable("Path", $machinePath, "Machine")
        Write-Success "Machine PATH updated with Python paths."
    } catch {
        Write-WarningMsg "Could not update Machine PATH (requires admin elevation): $_"
    }
} else {
    Write-Success "Python is already present in Machine PATH."
}

# ==============================================================================
# 4. Solicit / Verify Configuration Parameters
# ==============================================================================
Write-Step "4/6 Configuration Parameters"

if (-not $NonInteractive) {
    $inputNodes = Read-Host "PostgreSQL Cluster Nodes [$Nodes]"
    if ($inputNodes -ne "") { $Nodes = $inputNodes }

    $inputUser = Read-Host "Monitoring Username [$Username]"
    if ($inputUser -ne "") { $Username = $inputUser }

    if ($Password -eq "") {
        $secPass = Read-Host -Prompt "Monitoring Password [site24x7]" -AsSecureString
        $plainPass = [System.Net.NetworkCredential]::new("", $secPass).Password
        if ($plainPass -ne "") { $Password = $plainPass } else { $Password = "site24x7" }
    }

    $inputDb = Read-Host "Database Name [$Database]"
    if ($inputDb -ne "") { $Database = $inputDb }

    $inputPatroni = Read-Host "Patroni REST Port [$PatroniPort]"
    if ($inputPatroni -ne "") { $PatroniPort = $inputPatroni }
} else {
    if ($Password -eq "") { $Password = "site24x7" }
}

Write-Host "Config summary:"
Write-Host "  Nodes:        $Nodes"
Write-Host "  User:         $Username"
Write-Host "  Database:     $Database"
Write-Host "  Patroni Port: $PatroniPort"

# ==============================================================================
# 5. Validate Plugin Execution
# ==============================================================================
Write-Step "5/6 Testing Plugin Execution Against Cluster"

$pluginScript = Join-Path $ScriptDir "postgres_cluster.py"
if (-not (Test-Path $pluginScript)) {
    Write-ErrorMsg "Could not find postgres_cluster.py in $ScriptDir"
    exit 1
}

$testArgs = @(
    $pluginScript,
    "--nodes", $Nodes,
    "--username", $Username,
    "--password", $Password,
    "--db", $Database
)
if ($PatroniPort -and $PatroniPort -ne "none") {
    $testArgs += @("--patroni_port", $PatroniPort)
}

$output = & $PythonExe @testArgs 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-ErrorMsg "Plugin test execution failed with exit code $exitCode."
    Write-Host $output -ForegroundColor Yellow
    exit 1
}

# Validate JSON output
try {
    $json = $output | ConvertFrom-Json
    if ($json.status -eq 0) {
        Write-ErrorMsg "Plugin returned status 0 (error condition): $($json.msg)"
        exit 1
    }
    Write-Success "Plugin test run succeeded!"
    Write-Host "  Nodes Total:         $($json.'Nodes Total')" -ForegroundColor Gray
    Write-Host "  Nodes Up:            $($json.'Nodes Up')" -ForegroundColor Gray
    Write-Host "  Primary Count:       $($json.'Primary Count')" -ForegroundColor Gray
    Write-Host "  Primary Timeline:    $($json.'Primary Timeline')" -ForegroundColor Gray
    Write-Host "  Max Replay Backlog:  $($json.'Max Replay Backlog') bytes" -ForegroundColor Gray
    Write-Host "  Child Nodes:         $($json.Cluster_Nodes.Count) rows" -ForegroundColor Gray
    Write-Host "  Standby Rows:        $($json.Replication_Standbys.Count) rows" -ForegroundColor Gray
} catch {
    Write-ErrorMsg "Failed to parse plugin output as JSON: $_"
    Write-Host $output
    exit 1
}

# ==============================================================================
# 6. Deploy to Site24x7 Agent Directory
# ==============================================================================
Write-Step "6/6 Deploying to Site24x7 Windows Agent"

$targetPluginsDir = Join-Path $AgentDir "monitoring\Plugins\postgres_cluster"

if (-not (Test-Path $AgentDir)) {
    Write-WarningMsg "Site24x7 Agent directory not found at '$AgentDir'."
    Write-WarningMsg "Please ensure Site24x7 Windows Agent is installed."
    Write-WarningMsg "Plugin files are validated and ready in: $ScriptDir"
    exit 0
}

    try {
        if (-not (Test-Path $targetPluginsDir)) {
            New-Item -ItemType Directory -Path $targetPluginsDir -Force | Out-Null
        }

        # Copy python script
        Copy-Item -Path $pluginScript -Destination (Join-Path $targetPluginsDir "postgres_cluster.py") -Force
        Write-Success "Copied postgres_cluster.py to $targetPluginsDir"

        # Generate configuration file
        $cfgContent = @"
[global_configurations]
use_agent_python=$UseAgentPython

[postgres_cluster]
nodes="$Nodes"
username="$Username"
password="$Password"
db="$Database"
patroni_port="$PatroniPort"
"@

        $targetCfg = Join-Path $targetPluginsDir "postgres_cluster.cfg"
        Set-Content -Path $targetCfg -Value $cfgContent -Encoding UTF8
        Write-Success "Generated configuration: $targetCfg"
    } catch {
        Write-ErrorMsg "Failed to write to $targetPluginsDir. Please run this script with elevated Administrator privileges: $_"
        exit 1
    }

Write-Host @"

==================================================================
 Site24x7 PostgreSQL Cluster Plugin Installed Successfully!
==================================================================
Target: $targetPluginsDir

Next steps:
1. The Site24x7 Agent checks for new plugins every ~50 seconds.
2. Monitor discovery in the Agent register log:
   Get-Content -Path "$AgentDir\monitoring\logs\Details\PluginRegisterLog.log" -Tail 30 -Wait
3. Monitor periodic data collection logs (collected every 5 mins):
   Get-Content -Path "$AgentDir\monitoring\logs\Details\PluginLog.log" -Tail 30 -Wait
4. In the Site24x7 Web Console:
   - Navigate to: Plugins -> Plugin Integrations
   - Open monitor: postgres_cluster
   - Check the custom 'Cluster' tab, 'Cluster_Nodes' table, and 'Replication_Standbys' table.

==================================================================
"@ -ForegroundColor Green
