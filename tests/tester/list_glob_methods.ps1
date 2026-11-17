$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")
$glob = $asm.GetType('Site24x7PluginAgent.Global')
$glob.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance') | ForEach-Object {
    Write-Output $_.Name
}
