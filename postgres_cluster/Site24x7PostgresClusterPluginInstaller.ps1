<#
.SYNOPSIS
    Site24x7 PostgreSQL Cluster Plugin Windows Installer
.DESCRIPTION
    Installs and configures the postgres_cluster plugin for the Site24x7 Windows Agent.
    - Locates the active Python 3 runtime and ensures psycopg2-binary is installed for that exact Python.
    - Ensures Python is registered in the Machine PATH so the LocalSystem agent service can invoke it.
    - Deploys postgres_cluster.py and postgres_cluster.cfg with redirect_output=1 under [global_configurations].
    - Verifies plugin output and JSON schema prior to completing installation.
.PARAMETER Nodes
    Comma-separated list of cluster nodes (default: "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443")
.PARAMETER Username
    PostgreSQL monitoring username (default: "site24x7")
.PARAMETER Password
    PostgreSQL monitoring password
.PARAMETER Database
    Target database name (default: "postgres")
.PARAMETER PatroniPort
    Patroni REST API port or mapping (default: "8008")
.PARAMETER AgentDir
    Site24x7 Windows Agent directory (default: "C:\Program Files (x86)\Site24x7\WinAgent")
.PARAMETER PluginFolderName
    Plugin subfolder and script base name (default: "postgres_cluster")
.PARAMETER NonInteractive
    Runs without interactive prompts (for automated deployment)
.PARAMETER SkipAdminCheck
    Skips the Administrator privilege check
.PARAMETER DryRun
    Validates environment and runs plugin without modifying the Agent directory
.EXAMPLE
    .\Site24x7PostgresClusterPluginInstaller.ps1 -NonInteractive
.EXAMPLE
    .\Site24x7PostgresClusterPluginInstaller.ps1 -PluginFolderName "postgres_cluster_dev" -NonInteractive
#>

[CmdletBinding()]
param(
    [string]$Nodes = "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443",
    [string]$Username = "site24x7",
    [string]$Password = "",
    [string]$Database = "postgres",
    [string]$PatroniPort = "8008",
    [string]$AgentDir = "C:\Program Files (x86)\Site24x7\WinAgent",
    [string]$PluginFolderName = "postgres_cluster",
    [switch]$NonInteractive,
    [switch]$SkipAdminCheck,
    [switch]$DryRun
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
# 1. Administrator Check
# ==============================================================================
Write-Step "1/5 Checking Permissions"
if ($DryRun -or $SkipAdminCheck) {
    Write-WarningMsg "Skipping Administrator check (DryRun/SkipAdminCheck enabled)."
} else {
    $isAdmin = Check-Admin
    if (-not $isAdmin) {
        Write-WarningMsg "Administrator privileges are required to deploy files into '$AgentDir'."
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
                if ($PluginFolderName) { $argList += " -PluginFolderName `"$PluginFolderName`"" }
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
# 2. Locate Python and Verify psycopg2-binary
# ==============================================================================
Write-Step "2/5 Locating Python 3 and psycopg2-binary"

$PythonExe = $null

$candidatePythons = @(
    "C:\Users\Joanathan\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Joanathan\AppData\Local\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)
foreach ($p in $candidatePythons) {
    if ($p -and (Test-Path $p)) {
        $PythonExe = $p
        break
    }
}

if (-not $PythonExe) {
    try {
        $pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pyCmd -and $pyCmd.Source -notmatch "WindowsApps") {
            $PythonExe = $pyCmd.Source
        }
    } catch {}
}

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

if (-not $PythonExe) {
    Write-ErrorMsg "Python 3 could not be located. Please install Python 3 and add it to PATH."
    exit 1
}

$pyVersion = (& $PythonExe --version 2>&1).ToString().Trim()
Write-Success "Found Python runtime: $PythonExe ($pyVersion)"

# Ensure psycopg2-binary is installed for this exact Python runtime
Write-Host "Verifying psycopg2 module..."
$psycopgCheck = & $PythonExe -c "import psycopg2; print(psycopg2.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-WarningMsg "psycopg2 is not installed in $PythonExe. Installing psycopg2-binary..."
    & $PythonExe -m pip install --quiet psycopg2-binary
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorMsg "Failed to install psycopg2-binary into $PythonExe."
        exit 1
    }
    Write-Success "psycopg2-binary installed successfully."
} else {
    Write-Success "psycopg2 is available (version $psycopgCheck)."
}

# Ensure Python directory is in Machine PATH for LocalSystem agent service
$pyFolder = Split-Path -Parent $PythonExe
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
if ($machinePath -and $machinePath -notmatch [regex]::Escape($pyFolder)) {
    try {
        [Environment]::SetEnvironmentVariable("Path", "$pyFolder;$machinePath", "Machine")
        Write-Success "Added Python folder '$pyFolder' to Machine PATH."
    } catch {
        Write-WarningMsg "Could not update Machine PATH (non-critical if already in PATH): $_"
    }
}

# ==============================================================================
# 3. Solicit / Verify Configuration Parameters
# ==============================================================================
Write-Step "3/5 Configuration Parameters"

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
Write-Host "  Nodes:              $Nodes"
Write-Host "  User:               $Username"
Write-Host "  Database:           $Database"
Write-Host "  Patroni Port:       $PatroniPort"
Write-Host "  Target Plugin Name: $PluginFolderName"

# ==============================================================================
# 4. Deploy Plugin to Site24x7 Agent Directory
# ==============================================================================
Write-Step "4/5 Deploying Plugin Files"

$targetPluginsDir = Join-Path $AgentDir "monitoring\Plugins\$PluginFolderName"

if ($DryRun) {
    Write-Success "[DRY RUN] Would deploy to: $targetPluginsDir"
} else {
    if (-not (Test-Path $AgentDir)) {
        Write-WarningMsg "Site24x7 Agent directory not found at '$AgentDir'."
        Write-WarningMsg "Staging plugin files in: $ScriptDir"
    } else {
        try {
            if (-not (Test-Path $targetPluginsDir)) {
                New-Item -ItemType Directory -Path $targetPluginsDir -Force | Out-Null
            }

            $sourcePy = Join-Path $ScriptDir "postgres_cluster.py"
            $destPy = Join-Path $targetPluginsDir "$PluginFolderName.py"

            # Copy Python collector
            Copy-Item -Path $sourcePy -Destination $destPy -Force
            Write-Success "Deployed collector to $destPy"

            # Deploy configuration file with redirect_output=1 under [global_configurations]
            $cfgContent = @"
[global_configurations]
use_agent_python=0
redirect_output=1

[$PluginFolderName]
nodes="$Nodes"
username="$Username"
password="$Password"
db="$Database"
patroni_port="$PatroniPort"
"@

            $targetCfg = Join-Path $targetPluginsDir "$PluginFolderName.cfg"
            Set-Content -Path $targetCfg -Value $cfgContent -Encoding Ascii
            (Get-Item $targetCfg).LastWriteTime = Get-Date
            Write-Success "Deployed configuration to $targetCfg (unencrypted, agent will encrypt)"
        } catch {
            Write-ErrorMsg "Failed to deploy files to ${targetPluginsDir}: $_"
            exit 1
        }
    }
}

# ==============================================================================
# 5. Validate Plugin Execution
# ==============================================================================
Write-Step "5/5 Validating Plugin Execution"

$scriptToRun = if ($DryRun) { Join-Path $ScriptDir "postgres_cluster.py" } else { Join-Path $targetPluginsDir "$PluginFolderName.py" }
$testArgs = @(
    $scriptToRun,
    "--nodes", $Nodes,
    "--username", $Username,
    "--password", $Password,
    "--db", $Database
)
if ($PatroniPort -and $PatroniPort -ne "none") {
    $testArgs += @("--patroni_port", $PatroniPort)
}

Write-Host "Running collector verification via $PythonExe..."
$t0 = [System.Diagnostics.Stopwatch]::StartNew()
$output = & $PythonExe @testArgs 2>&1
$t0.Stop()
$exitCode = $LASTEXITCODE
$elapsedMs = $t0.ElapsedMilliseconds

if ($exitCode -ne 0) {
    Write-ErrorMsg "Plugin validation failed with exit code $exitCode (elapsed: ${elapsedMs}ms)."
    Write-Host $output -ForegroundColor Yellow
    exit 1
}

try {
    $json = $output | ConvertFrom-Json
    if ($json.status -eq 0) {
        Write-ErrorMsg "Plugin returned status 0 (error condition): $($json.msg)"
        exit 1
    }
    Write-Success "Plugin validation succeeded in ${elapsedMs}ms!"
    Write-Host "  Plugin Version:      $($json.plugin_version)" -ForegroundColor Gray
    Write-Host "  Nodes Total:         $($json.'Nodes Total')" -ForegroundColor Gray
    Write-Host "  Nodes Up:            $($json.'Nodes Up')" -ForegroundColor Gray
    Write-Host "  Primary Count:       $($json.'Primary Count')" -ForegroundColor Gray
    Write-Host "  Primary Timeline:    $($json.'Primary Timeline')" -ForegroundColor Gray
    Write-Host "  Max Replay Backlog:  $($json.'Max Replay Backlog') bytes" -ForegroundColor Gray
    Write-Host "  Replication Slots:   $($json.'Replication Slots Total') total ($($json.'Physical Slots') physical, $($json.'Logical Slots') logical)" -ForegroundColor Gray
    Write-Host "  Cluster Nodes:       $($json.Cluster_Nodes.Count) rows" -ForegroundColor Gray
    Write-Host "  Standbys Detected:   $($json.Replication_Standbys.Count) rows" -ForegroundColor Gray
} catch {
    Write-ErrorMsg "Failed to parse plugin output as JSON: $_"
    Write-Host $output
    exit 1
}

Write-Host @"

==================================================================
 Site24x7 PostgreSQL Cluster Plugin Setup Verified Successfully!
==================================================================
Plugin Target: $targetPluginsDir
Python:        $PythonExe

Agent Lifecycle:
1. Registration: The agent registers the plugin within ~50 seconds.
   Check: Get-Content -Path "$AgentDir\monitoring\logs\Details\PluginRegisterLog.log" -Tail 25
2. Data Collection: Runs every 5 minutes.
   Check: Get-Content -Path "$AgentDir\monitoring\logs\Details\PluginLog.log" -Tail 25
3. In Site24x7 Web Console:
   - Navigate to: Plugins -> Plugin Integrations
   - Open monitor: $PluginFolderName
   - Verify: 6 Dashboard tabs, Cluster_Nodes table, Replication_Standbys table.
==================================================================
"@ -ForegroundColor Green
