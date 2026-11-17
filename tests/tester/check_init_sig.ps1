$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")
$glob = $asm.GetType('Site24x7PluginAgent.Global')
$methods = $glob.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance') | Where-Object { $_.Name -eq 'Init' }
foreach ($m in $methods) {
    Write-Output "Method: $($m.Name)"
    $params = $m.GetParameters()
    Write-Output "  Param count: $($params.Count)"
    foreach ($p in $params) {
        Write-Output "  Param: $($p.Name) ($($p.ParameterType))"
    }
}
