# ==============================================================================
# check-layout.ps1
# Validates the upstream_layout/postgres_cluster directory structure, syntax,
# imports, configuration standards, and runtime execution.
# ==============================================================================

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$upstreamDir = Join-Path $scriptDir "upstream_layout\postgres_cluster"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " Site24x7 Upstream Layout Compliance & Health Check" -ForegroundColor Cyan
Write-Host " Target Directory: $upstreamDir" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$passed = 0
$failed = 0

function Assert-Check {
    param(
        [string]$Description,
        [scriptblock]$Test
    )
    try {
        $result = & $Test
        if ($result -eq $false) {
            Write-Host "  [FAIL] $Description" -ForegroundColor Red
            $script:failed++
        } else {
            Write-Host "  [PASS] $Description" -ForegroundColor Green
            $script:passed++
        }
    } catch {
        Write-Host "  [FAIL] $Description : $_" -ForegroundColor Red
        $script:failed++
    }
}

Write-Host "`n--- Step 1: Directory & File Structure Integrity ---" -ForegroundColor Yellow

$requiredFiles = @(
    "postgres_cluster.py",
    "postgres_cluster.cfg",
    "README.md",
    "installer\Site24x7PostgresClusterPluginInstaller.ps1",
    "installer\Site24x7PostgresClusterPluginInstaller.sh",
    "prerequisites\create_user.sql",
    "prerequisites\create_user.sh",
    "wc_automation\installer.sh"
)

foreach ($relPath in $requiredFiles) {
    $fullPath = Join-Path $upstreamDir $relPath
    Assert-Check "File exists: $relPath" { Test-Path $fullPath }
}

Write-Host "`n--- Step 2: Configuration Standards Integrity ---" -ForegroundColor Yellow

$cfgPath = Join-Path $upstreamDir "postgres_cluster.cfg"
Assert-Check "Configuration contains [global_configurations] with redirect_output=1" {
    $content = Get-Content $cfgPath -Raw
    $content -match '\[global_configurations\]' -and $content -match 'redirect_output\s*=\s*1'
}

Assert-Check "Configuration uses standardized section [postgres_cluster]" {
    $content = Get-Content $cfgPath -Raw
    $content -match '\[postgres_cluster\]' -and (-not ($content -match '\[pg_cluster\]')) -and (-not ($content -match '\[pg_cluster_dev\]'))
}

Write-Host "`n--- Step 3: Script Syntax & Import Validation ---" -ForegroundColor Yellow

$pyPath = Join-Path $upstreamDir "postgres_cluster.py"
Assert-Check "Python syntax compilation check (py_compile)" {
    $compOut = py -m py_compile $pyPath 2>&1
    $LASTEXITCODE -eq 0
}

$ps1Installer = Join-Path $upstreamDir "installer\Site24x7PostgresClusterPluginInstaller.ps1"
Assert-Check "PowerShell installer syntax check (AST parser)" {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($ps1Installer, [ref]$tokens, [ref]$errors) | Out-Null
    $errors.Count -eq 0
}

$shInstaller = Join-Path $upstreamDir "installer\Site24x7PostgresClusterPluginInstaller.sh"
Assert-Check "Bash installer uses standardized [postgres_cluster] section" {
    $content = Get-Content $shInstaller -Raw
    $content -match '\[\$plugin\]' -or $content -match '\[postgres_cluster\]'
}

Write-Host "`n--- Step 4: Live Execution Smoke Test ---" -ForegroundColor Yellow

Assert-Check "Plugin runs cleanly against active cluster with valid JSON output" {
    $output = py $pyPath --nodes "localhost:5441,localhost:5442,localhost:5443" --username "site24x7" --password "site24x7" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $json = $output | ConvertFrom-Json
    if (-not $json) { return $false }
    if ($json.plugin_version -lt 1) { return $false }
    if (-not $json.Cluster_Nodes) { return $false }
    if (-not $json.Replication_Standbys) { return $false }
    if (-not $json.tabs.Cluster) { return $false }
    return $true
}

Write-Host "`n--- Step 5: Parity with Working Collector ---" -ForegroundColor Yellow

$workingPy = Join-Path $scriptDir "postgres_cluster\postgres_cluster.py"
Assert-Check "upstream_layout collector matches working collector logic" {
    $h1 = (Get-FileHash $pyPath -Algorithm SHA256).Hash
    $h2 = (Get-FileHash $workingPy -Algorithm SHA256).Hash
    $h1 -eq $h2
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host " RESULT: $passed Passed, $failed Failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "=================================================================" -ForegroundColor Cyan

if ($failed -gt 0) {
    exit 1
}
