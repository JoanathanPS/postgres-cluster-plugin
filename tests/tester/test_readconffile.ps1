[System.Environment]::CurrentDirectory = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64'
[System.Reflection.Assembly]::LoadFrom('C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\DotNetAgent.Util.dll') | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom('C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe')

$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m = $util.GetMethod('ReadConfFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')
$cfgFileWithoutExt = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v6\postgres_cluster_v6'

$res = $m.Invoke($null, @('postgres_cluster_v6', $cfgFileWithoutExt))
Write-Output "Result is null: $($null -eq $res)"
if ($res) {
    Write-Output "Result type: $($res.GetType().FullName)"
    foreach ($k in $res.Keys) {
        Write-Output "Key: $k = $($res[$k])"
        if ($res[$k] -is [System.Collections.Hashtable] -or $res[$k] -is [System.Collections.IDictionary]) {
            foreach ($subk in $res[$k].Keys) {
                Write-Output "   $subk = $($res[$k][$subk])"
            }
        }
    }
}
