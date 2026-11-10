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
    REQUIRED. Address of one cluster node, or several comma separated: host:port[:patroni_port]
    (the plugin finds the other nodes itself). There is no default.
.PARAMETER Username
    REQUIRED. PostgreSQL monitoring username. There is no default.
.PARAMETER Password
    PostgreSQL monitoring password. Prefer the secure interactive prompt or the S247_POSTGRES_CLUSTER_INSTALL_PASSWORD / MONITOR_PASSWORD environment variable over a command-line argument.
.PARAMETER Database
    REQUIRED. Database the plugin connects to. There is no default.
.PARAMETER PatroniPort
    Patroni REST API port. Leave empty if the cluster is not Patroni.
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
    .\Site24x7PostgresClusterPluginInstaller.ps1 -Nodes "10.0.0.5:5432:8008" -Username "site24x7" -Database "postgres" -DryRun
.EXAMPLE
    # Set MONITOR_PASSWORD securely in the deployment environment first.
    .\Site24x7PostgresClusterPluginInstaller.ps1 -PluginFolderName "postgres_cluster_dev" -Nodes "10.0.0.5:5432:none" -Username "site24x7" -Database "postgres" -NonInteractive -DryRun
#>

[CmdletBinding()]
param(
    [string]$ClusterHost = "",
    [string]$PostgresPort = "",
    [string]$Nodes = "",
    [string]$Username = "",
    [string]$Password = "",
    [string]$Database = "postgres",
    [string]$PatroniPort = "",
    [string]$AddressMap = "",
    [int]$ReplayWarnSeconds = 60,
    [long]$ReplayWarnBytes = 104857600,
    [int]$FailoverWarnSeconds = 900,
    [long]$SlotWarnBytes = 1073741824,
    [long]$SlotCriticalBytes = 10737418240,
    [string]$AgentDir = "C:\Program Files (x86)\Site24x7\WinAgent",
    [string]$PluginFolderName = "postgres_cluster",
    [switch]$NonInteractive,
    [switch]$SkipAdminCheck,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$InstallPasswordEnv = "S247_POSTGRES_CLUSTER_INSTALL_PASSWORD"
if (-not $Password) { $Password = [Environment]::GetEnvironmentVariable($InstallPasswordEnv) }
if (-not $Password) { $Password = $env:MONITOR_PASSWORD }
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
                if ($ClusterHost) { $argList += " -ClusterHost `"$ClusterHost`"" }
                if ($PostgresPort) { $argList += " -PostgresPort `"$PostgresPort`"" }
                if ($Nodes) { $argList += " -Nodes `"$Nodes`"" }
                if ($Username) { $argList += " -Username `"$Username`"" }
                if ($Database) { $argList += " -Database `"$Database`"" }
                if ($PatroniPort) { $argList += " -PatroniPort `"$PatroniPort`"" }
                if ($AddressMap) { $argList += " -AddressMap `"$AddressMap`"" }
                $argList += " -ReplayWarnSeconds $ReplayWarnSeconds -ReplayWarnBytes $ReplayWarnBytes"
                if ($AgentDir) { $argList += " -AgentDir `"$AgentDir`"" }
                if ($PluginFolderName) { $argList += " -PluginFolderName `"$PluginFolderName`"" }
                if ($NonInteractive) { $argList += " -NonInteractive" }
                if ($DryRun) { $argList += " -DryRun" }
                if ($Password) { [Environment]::SetEnvironmentVariable($InstallPasswordEnv, $Password, "Process") }
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

$pythonCandidates = @()
$pythonPathCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonPathCmd -and $pythonPathCmd.Source -notmatch "WindowsApps") {
    $pythonCandidates += $pythonPathCmd.Source
}
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
    foreach ($line in (& $pyLauncher.Source -0p 2>$null)) {
        if ($line -match '([A-Za-z]:\\.*\\python(?:3)?\.exe)\s*$') {
            $pythonCandidates += $matches[1]
        }
    }
}

$supportedPythonCandidates = @()
foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
    if (-not (Test-Path $candidate)) { continue }
    $versionText = (& $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null).ToString().Trim()
    if ($LASTEXITCODE -eq 0 -and $versionText -match '^(\d+)\.(\d+)$') {
        $candidateVersion = [version]::new([int]$matches[1], [int]$matches[2])
        if ($candidateVersion -ge [version]'3.9') {
            $supportedPythonCandidates += [pscustomobject]@{ Path = $candidate; Version = $candidateVersion }
        }
    }
}
$selectedPython = $supportedPythonCandidates | Sort-Object Version -Descending | Select-Object -First 1
if ($selectedPython) { $PythonExe = $selectedPython.Path }

if (-not $PythonExe) {
    Write-ErrorMsg "Python 3.9 or newer could not be located. Install it and add it to PATH or the Python launcher."
    exit 1
}

$pyVersion = (& $PythonExe --version 2>&1).ToString().Trim()
Write-Success "Found Python runtime: $PythonExe ($pyVersion)"

# Ensure psycopg2-binary is installed for this exact Python runtime
Write-Host "Verifying psycopg2 module..."
$psycopgCheck = & $PythonExe -c "import psycopg2; print(psycopg2.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($DryRun) {
        Write-ErrorMsg "psycopg2 is missing. DryRun will not install packages; install psycopg2-binary in $PythonExe and rerun."
        exit 1
    }
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

# Ensure Python directory is in Machine PATH for the LocalSystem agent service.
# DryRun must not change machine configuration.
if (-not $DryRun) {
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
}

# ==============================================================================
# 3. Solicit / Verify Configuration Parameters
# ==============================================================================
Write-Step "3/5 Configuration Parameters"

# There are no built-in defaults: every required value is asked for, or must be passed as a parameter.
if (-not $NonInteractive) {
    if ($ClusterHost -eq "" -and $Nodes -eq "") {
        $ClusterHost = Read-Host "PostgreSQL cluster seed host or IP (e.g. postgres-primary.prod.internal)"
    }
    if ($Username -eq "") { $Username = Read-Host "Monitoring username" }
    if ($Password -eq "") {
        $secPass = Read-Host -Prompt "Monitoring password" -AsSecureString
        $Password = [System.Net.NetworkCredential]::new("", $secPass).Password
    }
    if ($Database -eq "") {
        $dbInput = Read-Host "Database name [default: postgres]"
        $Database = if ($dbInput) { $dbInput } else { "postgres" }
    }
    if ($PatroniPort -eq "") { $PatroniPort = Read-Host "Patroni REST port (leave empty for default 8008; 'none' to disable)" }
}
if ($Database -eq "") { $Database = "postgres" }

$missingSettings = @()
if ($ClusterHost -eq "" -and $Nodes -eq "") { $missingSettings += "ClusterHost" }
if ($Username -eq "") { $missingSettings += "Username" }
if ($Password -eq "") { $missingSettings += "Password" }
if ($missingSettings.Count -gt 0) {
    Write-ErrorMsg ("Missing required setting(s): " + ($missingSettings -join ", ") + ". Pass connection settings as parameters or enter them when asked. For unattended use, provide the password through S247_POSTGRES_CLUSTER_INSTALL_PASSWORD or MONITOR_PASSWORD.")
    exit 1
}
if (($ReplayWarnSeconds -lt 0) -or ($ReplayWarnBytes -lt 0) -or ($FailoverWarnSeconds -lt 0) -or ($SlotWarnBytes -lt 0) -or ($SlotCriticalBytes -lt 0)) {
    Write-ErrorMsg "Health threshold values must be zero or greater."
    exit 1
}
if ($SlotCriticalBytes -le $SlotWarnBytes) {
    Write-ErrorMsg "SlotCriticalBytes must be greater than SlotWarnBytes."
    exit 1
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
    # The verification step runs the collector from where it is, so the source path is needed in a dry run too.
    $sourcePy = Join-Path $ScriptDir "postgres_cluster.py"
    if (-not (Test-Path $sourcePy)) { $sourcePy = Join-Path (Split-Path -Parent $ScriptDir) "postgres_cluster.py" }
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
            if (-not (Test-Path $sourcePy)) {
                $parentDir = Split-Path -Parent $ScriptDir
                $candidate = Join-Path $parentDir "postgres_cluster.py"
                if (Test-Path $candidate) {
                    $sourcePy = $candidate
                } else {
                    Write-Host "postgres_cluster.py not found locally. Attempting to download from repository..." -ForegroundColor Yellow
                    $rawUrl = "https://raw.githubusercontent.com/JoanathanPS/postgres-cluster-plugin/upstream-layout/upstream_layout/postgres_cluster/postgres_cluster.py"
                    try {
                        Invoke-WebRequest -Uri $rawUrl -OutFile $sourcePy -UseBasicParsing -ErrorAction Stop
                        Write-Success "Downloaded postgres_cluster.py from repository"
                    } catch {
                        Write-ErrorMsg "postgres_cluster.py not found locally and download failed: $_"
                        Write-ErrorMsg "If the repository is private, please clone the repository first: git clone -b upstream-layout https://github.com/JoanathanPS/postgres-cluster-plugin.git"
                        exit 1
                    }
                }
            }
            $destPy = Join-Path $targetPluginsDir "$PluginFolderName.py"

            # Copy Python collector
            Copy-Item -Path $sourcePy -Destination $destPy -Force
            Write-Success "Deployed collector to $destPy"

            # Deploy configuration file with redirect_output=1 under [global_configurations]
            $cfgLines = @(
                "[global_configurations]",
                "use_agent_python=0",
                "redirect_output=1",
                "",
                "[$PluginFolderName]"
            )
            if ($ClusterHost) {
                $cfgLines += "cluster_host=`"$ClusterHost`""
                if ($PostgresPort) { $cfgLines += "postgres_port=`"$PostgresPort`"" }
            } else {
                $cfgLines += "nodes=`"$Nodes`""
            }
            $cfgLines += @(
                "username=`"$Username`"",
                "password=`"$Password`"",
                "db=`"$Database`""
            )
            if ($PatroniPort) {
                $cfgLines += "patroni_port=`"$PatroniPort`""
            }
            $cfgLines += @(
                "replay_warn_seconds=$ReplayWarnSeconds",
                "replay_warn_bytes=$ReplayWarnBytes",
                "failover_warn_seconds=$FailoverWarnSeconds",
                "slot_warn_bytes=$SlotWarnBytes",
                "slot_critical_bytes=$SlotCriticalBytes"
            )
            if ($AddressMap) {
                $cfgLines += "address_map=`"$AddressMap`""
            }
            $cfgContent = $cfgLines -join "`r`n" + "`r`n"

            $targetCfg = Join-Path $targetPluginsDir "$PluginFolderName.cfg"
            Set-Content -Path $targetCfg -Value $cfgContent -Encoding Ascii
            & icacls.exe $targetCfg /inheritance:r /grant:r "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not restrict config file ACL with icacls." }
            (Get-Item $targetCfg).LastWriteTime = Get-Date
            Write-Success "Deployed configuration to $targetCfg with access limited to LocalSystem and Administrators. The password is stored in plaintext."
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

$scriptToRun = if ($DryRun) { $sourcePy } else { Join-Path $targetPluginsDir "$PluginFolderName.py" }
$testArgs = @($scriptToRun)
if ($ClusterHost) {
    $testArgs += @("--cluster_host", $ClusterHost)
    if ($PostgresPort) { $testArgs += @("--postgres_port", $PostgresPort) }
} else {
    $testArgs += @("--nodes", $Nodes)
}
$testArgs += @(
    "--username", $Username,
    "--db", $Database
)
if ($PatroniPort -and $PatroniPort -ne "none") {
    $testArgs += @("--patroni_port", $PatroniPort)
}
if ($AddressMap) {
    $testArgs += @("--address_map", $AddressMap)
}
if ($ReplayWarnSeconds -ne 60) { $testArgs += @("--replay_warn_seconds", $ReplayWarnSeconds) }
if ($ReplayWarnBytes -ne 104857600) { $testArgs += @("--replay_warn_bytes", $ReplayWarnBytes) }
$testArgs += @("--failover_warn_seconds", $FailoverWarnSeconds)
$testArgs += @("--slot_warn_bytes", $SlotWarnBytes)
$testArgs += @("--slot_critical_bytes", $SlotCriticalBytes)

Write-Host "Running collector verification via $PythonExe..."
$t0 = [System.Diagnostics.Stopwatch]::StartNew()
$previousPgpw = $env:PGPASSWORD
$env:PGPASSWORD = $Password
try {
    $output = & $PythonExe @testArgs 2>&1
} finally {
    $env:PGPASSWORD = $previousPgpw
}
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
    Write-Host "  Replication Slots:   $($json.'Replication Slots Total') total ($($json.'Replication Slots Active') active, $($json.'Inactive Slots Count') inactive)" -ForegroundColor Gray
    Write-Host "  Cluster Nodes:       $($json.Cluster_Nodes.Count) rows" -ForegroundColor Gray
    $linksCount = if ($json.Replication_Links) { $json.Replication_Links.Count } else { 0 }
    Write-Host "  Replication Links:   $linksCount rows" -ForegroundColor Gray
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
   - Verify: the Summary page and 5 tabs (Cluster, Replication, Node Performance,
     Transactions and Sessions, WAL and Recovery); Cluster_Info and Cluster_Nodes on the Cluster tab.
==================================================================
"@ -ForegroundColor Green
