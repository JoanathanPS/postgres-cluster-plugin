<#
.SYNOPSIS
    Site24x7 PostgreSQL Cluster Plugin Windows Installer (Companion/Alias)
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

$target = Join-Path $PSScriptRoot "Install-Site24x7PostgresClusterPlugin.ps1"
& $target @PSBoundParameters
