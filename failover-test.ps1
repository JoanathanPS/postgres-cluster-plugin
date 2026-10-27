# ==============================================================================
# PowerShell Runner for Failover Test
# Runs the failover assertion suite
# ==============================================================================

$ErrorActionPreference = "Stop"
Write-Host "Running PostgreSQL Cluster Failover Test Suite..." -ForegroundColor Cyan

py tester/test_cluster_plugin.py --failover
