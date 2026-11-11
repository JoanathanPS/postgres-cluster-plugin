# =============================================================================
# launch_datadog_gui.ps1
# Opens the Datadog Agent Manager Windows GUI / Web Interface.
# =============================================================================

[CmdletBinding()]
param()

$ddTray = "C:\Program Files\Datadog\Datadog Agent\bin\agent\ddtray.exe"
$agentExe = "C:\Program Files\Datadog\Datadog Agent\bin\agent.exe"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Datadog Agent Manager Window Launcher" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check if Datadog Agent service is running
$svc = Get-Service -Name "datadogagent" -ErrorAction SilentlyContinue
if ($null -eq $svc) {
    Write-Warning "Datadog Agent service is not installed on this machine."
    exit 1
}

Write-Host "[i] Datadog Service Status: $($svc.Status)" -ForegroundColor Cyan
if ($svc.Status -ne "Running") {
    Write-Host "[+] Starting datadogagent service..." -ForegroundColor Yellow
    try {
        Start-Service -Name "datadogagent"
    } catch {
        Write-Warning "Could not start datadogagent service automatically. Please start it via Services.msc or as Administrator."
    }
}

# 2. Launch GUI via ddtray
if (Test-Path $ddTray) {
    Write-Host "[+] Launching Datadog Agent Manager GUI window..." -ForegroundColor Green
    Start-Process -FilePath $ddTray -ArgumentList "--launch-gui"
    Write-Host "[✓] Datadog Agent Manager launched! Check your system tray or browser window." -ForegroundColor Green
} else {
    Write-Warning "ddtray.exe not found at $ddTray. Attempting launch-gui via agent.exe..."
    if (Test-Path $agentExe) {
        & $agentExe launch-gui
    }
}
