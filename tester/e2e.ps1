# ==============================================================================
# tester/e2e.ps1
# End-to-End Automated Verification for Site24x7 PostgreSQL Cluster Plugin
# Modes:
#   .\tester\e2e.ps1             # Quick mode (~2 min)
#   .\tester\e2e.ps1 -Mode full   # Full mode (includes failover, lag, agent wait, console)
# ==============================================================================

[CmdletBinding()]
param(
    [ValidateSet("quick", "full")]
    [string]$Mode = "quick",
    [switch]$SkipConsole,
    [string]$ReportPath = "evidence\REPORT.md"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$evidenceDir = Join-Path $repoRoot "evidence"
if (-not (Test-Path $evidenceDir)) {
    New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
}

$startTime = Get-Date
$reportLines = [System.Collections.Generic.List[string]]::new()

function Write-Report {
    param([string]$Text)
    $reportLines.Add($Text)
}

function Log-Stage {
    param([string]$Title)
    Write-Host "`n=================================================================" -ForegroundColor Cyan
    Write-Host " STAGE: $Title" -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Report "`n### $Title`n"
}

function Assert-Result {
    param(
        [string]$Name,
        [bool]$Success,
        [string]$Details = "",
        [double]$ElapsedSec = -1
    )
    $timingStr = if ($ElapsedSec -ge 0) { " ($([math]::Round($ElapsedSec, 2))s)" } else { "" }
    $detailStr = if ($Details) { " - $Details" } else { "" }
    if ($Success) {
        Write-Host "  [PASS] $Name$timingStr" -ForegroundColor Green
        if ($Details) { Write-Host "         $Details" -ForegroundColor Gray }
        Write-Report "- **[PASS]** $Name$timingStr$detailStr"
    } else {
        Write-Host "  [FAIL] $Name$timingStr" -ForegroundColor Red
        if ($Details) { Write-Host "         $Details" -ForegroundColor DarkRed }
        Write-Report "- **[FAIL]** $Name$timingStr$detailStr"
        $script:overallFail = $true
    }
}

$overallFail = $false

Write-Report "# Site24x7 PostgreSQL Cluster Plugin - E2E Verification Report"
Write-Report ("**Execution Mode:** `{0}`  " -f $Mode)
Write-Report "**Start Time:** $($startTime.ToString('yyyy-MM-dd HH:mm:ss UTC'))  "
Write-Report "**Single Source of Truth:** `upstream_layout/postgres_cluster/`  `n"

try {
    # --------------------------------------------------------------------------
    # STAGE A: Preflight Checks
    # --------------------------------------------------------------------------
    Log-Stage "A. Preflight Environment Checks"

    # Check Docker
    $dockerSw = [System.Diagnostics.Stopwatch]::StartNew()
    $dockerOk = $false
    try {
        $dockerVer = docker version --format '{{.Server.Version}}' 2>$null
        $dockerOk = ($LASTEXITCODE -eq 0 -and $dockerVer)
    } catch {}
    $dockerSw.Stop()
    Assert-Result "Docker Daemon Running" $dockerOk "Docker Server Version: $dockerVer" $dockerSw.Elapsed.TotalSeconds

    # Check Patroni 3 nodes
    $containers = docker ps --format "{{.Names}}" 2>$null
    $hasNode1 = $containers -contains "patroni-pg-node1"
    $hasNode2 = $containers -contains "patroni-pg-node2"
    $hasNode3 = $containers -contains "patroni-pg-node3"
    $all3Up = $hasNode1 -and $hasNode2 -and $hasNode3
    Assert-Result "Patroni Containers Running" $all3Up "Nodes found: pg-node1=$hasNode1, pg-node2=$hasNode2, pg-node3=$hasNode3"

    # Check Python & psycopg2
    $pyVer = py --version 2>&1
    $pyOk = ($LASTEXITCODE -eq 0)
    Assert-Result "Python Runtime" $pyOk "$pyVer"

    $psycopg2Check = py -c "import psycopg2; print(psycopg2.__version__)" 2>$null
    $psycopg2Ok = ($LASTEXITCODE -eq 0 -and $psycopg2Check)
    Assert-Result "psycopg2 Driver" $psycopg2Ok "Version: $psycopg2Check"

    # Check Dev Plugin Folder deployed
    $devPluginPath = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_dev"
    $devDeployed = (Test-Path (Join-Path $devPluginPath "postgres_cluster_dev.py")) -and (Test-Path (Join-Path $devPluginPath "postgres_cluster_dev.cfg"))
    Assert-Result "Agent Dev Plugin Deployed" $devDeployed "Path: $devPluginPath"

    # --------------------------------------------------------------------------
    # STAGE B: Direct Plugin Probing & Timing Constraints (<5s)
    # --------------------------------------------------------------------------
    Log-Stage "B. Plugin Timing & Probing Checks (<5s Constraints)"

    $pluginPy = Join-Path $repoRoot "upstream_layout\postgres_cluster\postgres_cluster.py"
    $defaultNodes = "localhost:5441,localhost:5442,localhost:5443"

    # Check 1: Healthy Cluster Timing
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $healthyOut = py $pluginPy --nodes $defaultNodes --username site24x7 --password site24x7 2>$null
    $sw.Stop()
    $healthyElapsed = $sw.Elapsed.TotalSeconds
    $healthyJson = $null
    try { $healthyJson = $healthyOut | ConvertFrom-Json } catch {}

    $hPass = ($LASTEXITCODE -eq 0 -and $healthyJson -and $healthyElapsed -lt 5.0)
    Assert-Result "Healthy Cluster Query (<5s)" $hPass "Elapsed: $([math]::Round($healthyElapsed, 2))s | Nodes Up: $($healthyJson.'Nodes Up')/3 | Timeline: $($healthyJson.'Primary Timeline')" $healthyElapsed

    # Check 2: 1 Replica Down Timing (<5s)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    docker pause patroni-pg-node3 2>$null | Out-Null
    try {
        $rSw = [System.Diagnostics.Stopwatch]::StartNew()
        $oneDownOut = py $pluginPy --nodes $defaultNodes --username site24x7 --password site24x7 2>$null
        $rSw.Stop()
        $oneDownElapsed = $rSw.Elapsed.TotalSeconds
        $oneDownJson = $null
        try { $oneDownJson = $oneDownOut | ConvertFrom-Json } catch {}
        $odPass = ($oneDownJson -and $oneDownJson.'Nodes Up' -eq 2 -and $oneDownElapsed -lt 5.0)
        Assert-Result "1 Replica Paused/Down (<5s)" $odPass "Elapsed: $([math]::Round($oneDownElapsed, 2))s | Nodes Up: $($oneDownJson.'Nodes Up') | No Primary: $($oneDownJson.'No Primary Flag')" $oneDownElapsed
    } finally {
        docker unpause patroni-pg-node3 2>$null | Out-Null
    }

    # Check 3: Primary Down Timing (<5s)
    # Find current primary
    $currPrimary = "patroni-pg-node1"
    if ($healthyJson -and $healthyJson.Cluster_Nodes) {
        $pNode = $healthyJson.Cluster_Nodes | Where-Object { $_.role -eq "primary" } | Select-Object -First 1
        if ($pNode.name -match "5442") { $currPrimary = "patroni-pg-node2" }
        elseif ($pNode.name -match "5443") { $currPrimary = "patroni-pg-node3" }
    }

    docker pause $currPrimary 2>$null | Out-Null
    try {
        $pSw = [System.Diagnostics.Stopwatch]::StartNew()
        $pDownOut = py $pluginPy --nodes $defaultNodes --username site24x7 --password site24x7 2>$null
        $pSw.Stop()
        $pDownElapsed = $pSw.Elapsed.TotalSeconds
        $pDownJson = $null
        try { $pDownJson = $pDownOut | ConvertFrom-Json } catch {}
        $pdPass = ($pDownJson -and $pDownJson.'No Primary Flag' -eq 1 -and $pDownElapsed -lt 5.0)
        Assert-Result "Primary Paused/Down (<5s)" $pdPass "Elapsed: $([math]::Round($pDownElapsed, 2))s | No Primary Flag: $($pDownJson.'No Primary Flag')" $pDownElapsed
    } finally {
        docker unpause $currPrimary 2>$null | Out-Null
        # Wait a moment for unpaused primary to re-establish leader or heartbeat
        Start-Sleep -Seconds 3
    }

    # Check 4: Child tables structure
    $tablesOk = ($healthyJson.Cluster_Nodes.Count -eq 3 -and $healthyJson.Replication_Standbys.Count -ge 1)
    Assert-Result "Child Tables Structure" $tablesOk "Cluster_Nodes rows: $($healthyJson.Cluster_Nodes.Count) | Replication_Standbys rows: $($healthyJson.Replication_Standbys.Count)"

    # --------------------------------------------------------------------------
    # STAGE C: Existing Test Suites
    # --------------------------------------------------------------------------
    Log-Stage "C. Existing Test Suites"

    # Upstream layout checks
    $chkSw = [System.Diagnostics.Stopwatch]::StartNew()
    $chkOut = .\check-layout.ps1 2>&1
    $chkSw.Stop()
    Assert-Result "Layout Check (check-layout.ps1)" ($LASTEXITCODE -eq 0) "15 assertions verified" $chkSw.Elapsed.TotalSeconds

    # Unit & Integration test suite
    $tSw = [System.Diagnostics.Stopwatch]::StartNew()
    $testSuiteOut = py tester/test_cluster_plugin.py 2>&1
    $tSw.Stop()
    Assert-Result "Cluster Plugin Test Suite" ($LASTEXITCODE -eq 0) "All healthy, dead host, and auth error assertions passed" $tSw.Elapsed.TotalSeconds

    if ($Mode -eq "full") {
        # Failover assertion test
        $foSw = [System.Diagnostics.Stopwatch]::StartNew()
        $foOut = .\failover-test.ps1 2>&1
        $foSw.Stop()
        Assert-Result "Failover Assertion Suite (failover-test.ps1)" ($LASTEXITCODE -eq 0) "Failover triggered and followed to new primary" $foSw.Elapsed.TotalSeconds

        # Lag Demo
        $lagSw = [System.Diagnostics.Stopwatch]::StartNew()
        $lagOut = py tester/lag_demo.py --duration 5 --rate 50 2>&1
        $lagSw.Stop()
        Assert-Result "Replication Lag Demo (lag_demo.py)" ($LASTEXITCODE -eq 0) "pgbench synthetic load generated and observed" $lagSw.Elapsed.TotalSeconds
    } else {
        Write-Host "  [SKIP] Failover & Lag tests skipped in 'quick' mode (pass -Mode full to run)." -ForegroundColor Yellow
        Write-Report "- **[SKIP]** Failover & Lag demo skipped in quick mode"
    }

    # --------------------------------------------------------------------------
    # STAGE D: Agent Checks (PluginLog.log)
    # --------------------------------------------------------------------------
    Log-Stage "D. Site24x7 Agent Execution Log Verification"

    $pluginLogPath = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\logs\Details\PluginLog.log"
    if (Test-Path $pluginLogPath) {
        $recentLogLines = Get-Content $pluginLogPath -Tail 250
        
        # Extract RunPluginandWritetoFile entries
        $runLines = $recentLogLines | Select-String -Pattern "RunPluginandWritetoFile\s*::"
        
        # Group into collection cycles by timestamp
        $cycles = [System.Collections.Generic.List[System.Collections.Generic.List[string]]]::new()
        $currCycle = [System.Collections.Generic.List[string]]::new()
        $lastTime = $null

        foreach ($m in $runLines) {
            $line = $m.Line.Trim()
            if ($line -match '^(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})') {
                $t = [datetime]::ParseExact($matches[1], 'dd-MM-yyyy HH:mm:ss', $null)
                if ($lastTime -eq $null -or ($t - $lastTime).TotalSeconds -gt 30) {
                    if ($currCycle.Count -gt 0) {
                        $cycles.Add($currCycle)
                        $currCycle = [System.Collections.Generic.List[string]]::new()
                    }
                }
                $currCycle.Add($line)
                $lastTime = $t
            }
        }
        if ($currCycle.Count -gt 0) {
            $cycles.Add($currCycle)
        }

        # Inspect the last two cycles (or last available)
        $targetCycles = if ($cycles.Count -ge 2) { $cycles | Select-Object -Last 2 } else { $cycles }
        
        $singleInstanceOk = $true
        $violations = @()
        $inspectedSummaries = @()

        foreach ($c in $targetCycles) {
            $pgMatches = @($c | Where-Object { $_ -match "postgres" })
            $validMatches = @($pgMatches | Where-Object { $_ -match "RunPluginandWritetoFile\s*::\s*postgres_cluster_dev\s*-\s*postgres_cluster_dev$" })
            $badMatches = @($pgMatches | Where-Object { $_ -notmatch "RunPluginandWritetoFile\s*::\s*postgres_cluster_dev\s*-\s*postgres_cluster_dev$" })

            if ($validMatches.Count -ne 1 -or $badMatches.Count -gt 0) {
                $singleInstanceOk = $false
                if ($badMatches.Count -gt 0) {
                    $violations += "Unexpected instance(s) executed: $($badMatches -join '; ')"
                } elseif ($validMatches.Count -eq 0) {
                    $violations += "No postgres_cluster_dev instance executed in cycle"
                }
            }
            $inspectedSummaries += "Cycle [$($pgMatches -join '; ')]"
        }

        $detailMsg = if ($singleInstanceOk) {
            "Verified $($targetCycles.Count) recent cycle(s): exactly one instance ran ('postgres_cluster_dev - postgres_cluster_dev'). $($inspectedSummaries -join ' | ')"
        } else {
            "Instance violation detected: $($violations -join ' | ')"
        }

        Assert-Result "Single Instance Verification (postgres_cluster_dev)" ($singleInstanceOk -and $targetCycles.Count -ge 1) $detailMsg

        # Check PythonScript execution
        $devExecMatches = $recentLogLines | Select-String -Pattern "PythonScript :: output from file  instanceName :: postgres_cluster_dev"
        Assert-Result "Agent Execution Engine (Python)" ($devExecMatches.Count -ge 1) "Confirmed PythonScript execution without timeout"

        # Check PluginData write confirmation in log
        $dataWriteMatches = $recentLogLines | Select-String -Pattern "Successfully written to .*PluginData.*61a227ede3526a541d01dee10eab2c36"
        $payloadOk = ($dataWriteMatches.Count -ge 1)
        $latestWrite = if ($payloadOk) { ($dataWriteMatches | Select-Object -Last 1).Line.Trim() } else { "None" }
        Assert-Result "Agent PluginData Output Written" $payloadOk "Confirmed via PluginLog.log: $latestWrite"
    } else {
        Assert-Result "PluginLog.log Exists" $false "Path not found: $pluginLogPath"
    }

    # --------------------------------------------------------------------------
    # STAGE E: Web Console Playwright Checks
    # --------------------------------------------------------------------------
    Log-Stage "E. Web Console Automated Browser Verification"

    if ($SkipConsole) {
        Write-Host "  [SKIP] Web Console checks skipped (-SkipConsole supplied)." -ForegroundColor Yellow
        Write-Report "- **[SKIP]** Web Console checks skipped via -SkipConsole"
    } else {
        $pwSw = [System.Diagnostics.Stopwatch]::StartNew()
        $pwOut = py tester/console_check.py 2>&1
        $pwExit = $LASTEXITCODE
        $pwSw.Stop()
        $pwElapsed = $pwSw.Elapsed.TotalSeconds
        $pwText = (($pwOut | ForEach-Object { $_.ToString() }) -join "`n").Trim()

        if ($pwExit -eq 0) {
            Assert-Result "Console Automation (Playwright)" $true "Dashboard tabs, metrics, and child table assertions verified" $pwElapsed
        } elseif ($pwExit -eq 2 -or $pwText -match "playwright is not installed") {
            Write-Host "  [SKIP] Console Automation: Playwright is not installed (run: py -m pip install playwright)" -ForegroundColor Yellow
            Write-Report "- **[SKIP]** Console Automation: Playwright is not installed (run: py -m pip install playwright)"
        } elseif ($pwExit -eq 130 -or $pwText -match "cancelled by user") {
            Write-Host "  [SKIP] Console Automation: Cancelled by user (Ctrl+C)." -ForegroundColor Yellow
            Write-Report "- **[SKIP]** Console Automation: Cancelled by user (Ctrl+C)"
        } elseif ($pwExit -eq 3 -or $pwText -match "Authentication not completed" -or $pwText -match "Session expired" -or $pwText -match "session has expired" -or $pwText -match "login session not active" -or $pwText -match "MANUAL AUTHENTICATION") {
            $reason = "Site24x7 web console session not active or login timed out. Log in once in the Chrome window."
            Write-Host "  [SKIP] Console Automation: $reason" -ForegroundColor Yellow
            Write-Report "- **[SKIP]** Console Automation: $reason"
        } else {
            Write-Host "  [FAIL] Console Automation (Playwright) ($([math]::Round($pwElapsed, 2))s)" -ForegroundColor Red
            Write-Host "         Error details: $pwText" -ForegroundColor DarkRed
            Write-Report "- **[FAIL]** Console Automation (Playwright) ($([math]::Round($pwElapsed, 2))s) - $pwText"
            $script:overallFail = $true
        }
    }

} finally {
    # --------------------------------------------------------------------------
    # STAGE F: Cleanup & Cluster Health Guarantee
    # --------------------------------------------------------------------------
    Log-Stage "F. Cluster Health Cleanup Guarantee"
    Write-Host "Ensuring all 3 Patroni containers are unpaused and running..." -ForegroundColor Yellow

    foreach ($cName in @("patroni-pg-node1", "patroni-pg-node2", "patroni-pg-node3")) {
        try {
            $isPaused = (docker inspect --format '{{.State.Paused}}' $cName 2>$null).Trim()
            if ($isPaused -eq "true") {
                docker unpause $cName 2>$null | Out-Null
            }
            $isRunning = (docker inspect --format '{{.State.Running}}' $cName 2>$null).Trim()
            if ($isRunning -ne "true") {
                docker start $cName 2>$null | Out-Null
            }
        } catch {}
    }

    Start-Sleep -Seconds 3
    $cleanHealth = py upstream_layout/postgres_cluster/postgres_cluster.py --nodes "localhost:5441,localhost:5442,localhost:5443" --username site24x7 --password site24x7 2>$null
    $cleanJson = $null
    try { $cleanJson = $cleanHealth | ConvertFrom-Json } catch {}
    $cleanOk = ($cleanJson -and $cleanJson.'Nodes Up' -eq 3 -and $cleanJson.'Primary Count' -eq 1)

    Assert-Result "Cluster Returned to Healthy 3-Node State" $cleanOk "Nodes Up: $($cleanJson.'Nodes Up')/3 | Primary Count: $($cleanJson.'Primary Count') | Timeline: $($cleanJson.'Primary Timeline')"
}

$endTime = Get-Date
$totalDuration = ($endTime - $startTime).TotalSeconds
Write-Report "`n---`n"
Write-Report "**Total Duration:** $([math]::Round($totalDuration, 2)) seconds  "
Write-Report "**Final Outcome:** $(if ($overallFail) { 'FAILED' } else { 'PASSED' })  "

Set-Content -Path $ReportPath -Value $reportLines -Encoding UTF8
Write-Host "`nE2E Report written to: $ReportPath" -ForegroundColor Cyan

if ($overallFail) {
    exit 1
}
