. .\tester\il_disasm.ps1
$cfgParser = $asm.GetType('Site24x7PluginAgent.Utils.ConfigParser')
$m = $cfgParser.GetMethod('ReadConfigFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')
$res = $m.Invoke($null, @('C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v6\postgres_cluster_v6.cfg'))

foreach ($sec in $res.Keys) {
    Write-Output "Section: $sec"
    $h = $res[$sec]
    foreach ($k in $h.Keys) {
        Write-Output "  $k = $($h[$k])"
    }
}
