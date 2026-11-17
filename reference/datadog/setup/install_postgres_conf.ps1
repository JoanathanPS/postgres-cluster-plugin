# =============================================================================
# install_postgres_conf.ps1
# Deploys conf.yaml into Datadog Agent's config directory on Windows.
# NOTE: Must be run from an elevated (Administrator) PowerShell session.
# =============================================================================

[CmdletBinding()]
param(
    [string]$ConfigPath = "$PSScriptRoot\conf.yaml",
    [string]$TargetDir = "C:\ProgramData\Datadog\conf.d\postgres.d"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Deploying Datadog PostgreSQL Configuration" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Administrator Privileges
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "This script requires Administrator privileges to write into C:\ProgramData\Datadog."
    Write-Host "Please reopen PowerShell as Administrator and run:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -ForegroundColor Yellow
    exit 1
}

# 2. Check source config exists
if (-not (Test-Path $ConfigPath)) {
    Write-Error "Source configuration file not found at: $ConfigPath"
}

# 3. Create target directory
if (-not (Test-Path $TargetDir)) {
    Write-Host "[+] Creating directory: $TargetDir" -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
}

# 4. Copy config
$targetFile = Join-Path $TargetDir "conf.yaml"
Write-Host "[+] Copying configuration to: $targetFile" -ForegroundColor Green
Copy-Item -Path $ConfigPath -Destination $targetFile -Force

# 5. Restart Datadog Agent Service
Write-Host "[+] Restarting 'datadogagent' Windows service..." -ForegroundColor Green
Restart-Service -Name "datadogagent" -Force
Start-Sleep -Seconds 3

# 6. Run verification check
$agentExe = "C:\Program Files\Datadog\Datadog Agent\bin\agent.exe"
if (Test-Path $agentExe) {
    Write-Host "[+] Running test check: agent.exe check postgres..." -ForegroundColor Cyan
    & $agentExe check postgres
} else {
    Write-Warning "Agent executable not found at $agentExe"
}

Write-Host "`n[✓] Datadog PostgreSQL Check successfully installed and verified!" -ForegroundColor Green
