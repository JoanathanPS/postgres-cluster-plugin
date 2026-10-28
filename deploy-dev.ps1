# ==============================================================================
# deploy-dev.ps1
# Deploys the postgres_cluster plugin to an isolated agent dev directory:
#   C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_dev
#
# Rules:
#   - Plugin folder = Plugin file = Plugin name: postgres_cluster_dev
#   - Plain configuration written to postgres_cluster_dev.cfg
#   - Global configs: use_agent_python=0, redirect_output=1
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$RestartService,
    [string]$Nodes = "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443",
    [string]$Username = "site24x7",
    [string]$Password = "site24x7",
    [string]$Database = "postgres",
    [string]$PatroniPort = "8008"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourcePy = Join-Path $scriptDir "postgres_cluster\postgres_cluster.py"
$agentPluginsDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins"
$targetDir = Join-Path $agentPluginsDir "postgres_cluster_dev"

Write-Host "=== Site24x7 PostgreSQL Cluster Dev Deployment ===" -ForegroundColor Cyan
Write-Host "Source script: $sourcePy"
Write-Host "Target folder: $targetDir"

if (-not (Test-Path $targetDir)) {
    Write-Host "Creating target plugin folder: $targetDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

# Copy python script to postgres_cluster_dev.py
$targetPy = Join-Path $targetDir "postgres_cluster_dev.py"
Write-Host "Deploying script to $targetPy" -ForegroundColor Green
Copy-Item -Path $sourcePy -Destination $targetPy -Force

# Write plain cfg file
$targetCfg = Join-Path $targetDir "postgres_cluster_dev.cfg"
Write-Host "Writing plain configuration to $targetCfg" -ForegroundColor Green

$cfgContent = @"
[global_configurations]
use_agent_python=0
redirect_output=1

[pg_cluster_dev]
nodes="$Nodes"
username="$Username"
password="$Password"
db="$Database"
patroni_port="$PatroniPort"
"@

Set-Content -Path $targetCfg -Value $cfgContent -Encoding Ascii

# Touch LastWriteTime on cfg to signal agent file-watcher
(Get-Item $targetCfg).LastWriteTime = (Get-Date)
Write-Host "Updated LastWriteTime on $targetCfg" -ForegroundColor Green

if ($RestartService) {
    Write-Host "Restarting Site24x7 services..." -ForegroundColor Yellow
    Restart-Service -Name "Site24x7 Windows Agent" -Force -ErrorAction SilentlyContinue
    Restart-Service -Name "Site24x7 Plugin Agent" -Force -ErrorAction SilentlyContinue
    Write-Host "Services restarted." -ForegroundColor Green
}

Write-Host "`nDev deployment completed successfully!" -ForegroundColor Cyan
Write-Host "Monitor directory: $targetDir"
Write-Host "To monitor agent registration and execution logs, run:"
Write-Host "  Get-Content -Tail 30 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\logs\Details\PluginRegisterLog.log'"
Write-Host "  Get-Content -Tail 30 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\logs\Details\PluginLog.log'"
