<#
.SYNOPSIS
    Deploys the unmodified v1 plugin (site24x7/plugins PR #442) to Site24x7 Windows Agent.
.DESCRIPTION
    Installs v1 as plugin 'postgres_cluster_v1' monitoring Docker cluster nodes:
    - Primary: 127.0.0.1:5441 (section [pg_primary])
    - Standby: 127.0.0.1:5442 (section [pg_replica])
    Enables [global_configurations] use_agent_python=0 and redirect_output=1.
#>

[CmdletBinding()]
param(
    [string]$SourceV1Dir = "$PSScriptRoot\..\..\pcp-v1\postgres_cluster",
    [string]$AgentPluginsDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins"
)

$ErrorActionPreference = "Stop"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " Deploying Site24x7 PostgreSQL Cluster Plugin v1 (Unmodified)" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Fallback path if pcp-v1 is at repo parent
if (-not (Test-Path $SourceV1Dir)) {
    $alt = Resolve-Path "$PSScriptRoot\..\..\pcp-v1\postgres_cluster" -ErrorAction SilentlyContinue
    if ($alt) { $SourceV1Dir = $alt.Path }
}

if (-not (Test-Path "$SourceV1Dir\postgres_cluster.py")) {
    throw "Source v1 file not found at: $SourceV1Dir\postgres_cluster.py"
}

$targetDir = Join-Path $AgentPluginsDir "postgres_cluster_v1"
if (-not (Test-Path $targetDir)) {
    Write-Host "Creating target plugin directory: $targetDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$targetPy = Join-Path $targetDir "postgres_cluster_v1.py"
Write-Host "Copying v1 python script to: $targetPy" -ForegroundColor Yellow
Copy-Item -Path "$SourceV1Dir\postgres_cluster.py" -Destination $targetPy -Force

# Create v1 configuration file
$targetCfg = Join-Path $targetDir "postgres_cluster_v1.cfg"
$cfgContent = @"
[global_configurations]
use_agent_python = 0
redirect_output = 1

[pg_primary]
host = 127.0.0.1
port = 5441
username = site24x7
password = site24x7

[pg_replica]
host = 127.0.0.1
port = 5442
username = site24x7
password = site24x7
"@

Write-Host "Writing v1 configuration to: $targetCfg" -ForegroundColor Yellow
Set-Content -Path $targetCfg -Value $cfgContent -Encoding Ascii

Write-Host "=================================================================" -ForegroundColor Green
Write-Host " v1 Deployment Completed Successfully!" -ForegroundColor Green
Write-Host " Target Plugin: $targetDir" -ForegroundColor Green
Write-Host " Script:        $targetPy" -ForegroundColor Green
Write-Host " Configuration: $targetCfg" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
