$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$cfgParser = $asm.GetType('Site24x7PluginAgent.Utils.ConfigParser')
$m = $cfgParser.GetMethod('ReadConfigFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')
$cfgPath = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v5\postgres_cluster_v5.cfg'
$res = $m.Invoke($null, @($cfgPath))

foreach ($sec in $res.Keys) {
    Write-Output "Section: $sec"
    $h = $res[$sec]
    foreach ($k in $h.Keys) {
        $val = $h[$k]
        if ($k -like '*password*') {
            Write-Output "  $k = [REDACTED]"
        } else {
            Write-Output "  $k = $val"
        }
    }
}
