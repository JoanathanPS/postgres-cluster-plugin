
 = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
 = [System.Reflection.Assembly]::Load([System.IO.File]::ReadAllBytes())
foreach ( in .GetTypes()) {
    Write-Output .FullName
}
