# ==============================================================================
# PowerShell Runner for Failover Test
# Runs the failover assertion suite
# ==============================================================================

$ErrorActionPreference = "Continue"
Write-Host "Running PostgreSQL Cluster Failover Test Suite..." -ForegroundColor Cyan

$pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pyExe) { $pyExe = "python" }

& $pyExe tester/test_cluster_plugin.py --failover
exit $LASTEXITCODE
