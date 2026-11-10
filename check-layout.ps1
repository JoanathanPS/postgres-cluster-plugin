# ==============================================================================
# check-layout.ps1
# Validates the postgres_cluster directory structure, syntax, imports,
# configuration standards, runtime execution, and standalone plugin integrity.
# ==============================================================================

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$clusterDir = Join-Path $scriptDir "postgres_cluster"
$standaloneDir = Join-Path $scriptDir "postgres"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " Site24x7 Layout Compliance & Health Check" -ForegroundColor Cyan
Write-Host " Target Directory: $clusterDir" -ForegroundColor Cyan
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
    $fullPath = Join-Path $clusterDir $relPath
    Assert-Check "File exists: $relPath" { Test-Path $fullPath }
}

Write-Host "`n--- Step 2: Configuration Standards Integrity ---" -ForegroundColor Yellow

$cfgPath = Join-Path $clusterDir "postgres_cluster.cfg"
Assert-Check "Configuration contains [global_configurations] with redirect_output=1" {
    $content = Get-Content $cfgPath -Raw
    $content -match '\[global_configurations\]' -and $content -match 'redirect_output\s*=\s*1'
}

Assert-Check "Configuration uses standardized section [postgres_cluster]" {
    $content = Get-Content $cfgPath -Raw
    $content -match '\[postgres_cluster\]' -and (-not ($content -match '\[pg_cluster\]')) -and (-not ($content -match '\[pg_cluster_dev\]'))
}

Write-Host "`n--- Step 3: Script Syntax & Import Validation ---" -ForegroundColor Yellow

$pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pyExe) { $pyExe = "python" }

$pyPath = Join-Path $clusterDir "postgres_cluster.py"
Assert-Check "Python syntax compilation check (py_compile)" {
    $compOut = & $pyExe -m py_compile $pyPath 2>&1
    $LASTEXITCODE -eq 0
}

$ps1Installer = Join-Path $clusterDir "installer\Site24x7PostgresClusterPluginInstaller.ps1"
Assert-Check "PowerShell installer syntax check (AST parser)" {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($ps1Installer, [ref]$tokens, [ref]$errors) | Out-Null
    $errors.Count -eq 0
}

$shInstaller = Join-Path $clusterDir "installer\Site24x7PostgresClusterPluginInstaller.sh"
Assert-Check "Bash installer uses standardized [postgres_cluster] section" {
    $content = Get-Content $shInstaller -Raw
    $content -match '\[\$plugin\]' -or $content -match '\[postgres_cluster\]'
}

Write-Host "`n--- Step 4: Live Execution Smoke Test ---" -ForegroundColor Yellow

Assert-Check "Plugin runs cleanly against active cluster with valid JSON output" {
    $previousPgpw = $env:PGPASSWORD
    $env:PGPASSWORD = "site24x7"
    try {
        $output = & $pyExe $pyPath --nodes "localhost:5441,localhost:5442,localhost:5443" --username "site24x7" --db "appdb" 2>$null
    } finally {
        $env:PGPASSWORD = $previousPgpw
    }
    if ($LASTEXITCODE -ne 0) { return $false }
    $json = $output | ConvertFrom-Json
    if (-not $json) { return $false }
    if ($json.plugin_version -lt 1) { return $false }
    if (-not $json.Cluster_Nodes) { return $false }
    if (-not $json.Replication_Links) { return $false }
    if (-not $json.tabs.Cluster) { return $false }
    return $true
}

Write-Host "`n--- Step 5: Standalone Plugin Integrity ---" -ForegroundColor Yellow

Assert-Check "Standalone plugin exists: postgres/postgres.py" {
    Test-Path (Join-Path $standaloneDir "postgres.py")
}

Assert-Check "Standalone plugin exists: postgres/postgres.cfg" {
    Test-Path (Join-Path $standaloneDir "postgres.cfg")
}

Assert-Check "Standalone README exists: postgres/README.md" {
    Test-Path (Join-Path $standaloneDir "README.md")
}

Assert-Check "Standalone Python syntax compilation check (py_compile)" {
    $stCompOut = & $pyExe -m py_compile (Join-Path $standaloneDir "postgres.py") 2>&1
    $LASTEXITCODE -eq 0
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host " RESULT: $passed Passed, $failed Failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "=================================================================" -ForegroundColor Cyan

if ($failed -gt 0) {
    exit 1
}
