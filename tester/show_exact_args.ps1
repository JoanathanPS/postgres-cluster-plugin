$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")

$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$mRead = $util.GetMethod('ReadConfFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')
# arg0 is plugin name, arg1 is path without extension
$cfgPathNoExt = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v5\postgres_cluster_v5'
$res = $mRead.Invoke($null, @('postgres_cluster_v5', $cfgPathNoExt))

$glob = $asm.GetType('Site24x7PluginAgent.Global')
$pluginConfig = $glob.GetField('pluginConfig', [System.Reflection.BindingFlags]'Public,NonPublic,Static').GetValue($null)

Write-Output "pluginConfig keys: $($pluginConfig.Keys -join ', ')"
$sec = $pluginConfig['postgres_cluster_v5']
if ($sec) {
    Write-Output "Section entries:"
    foreach ($k in $sec.Keys) {
        $sub = $sec[$k]
        if ($sub -is [System.Collections.Hashtable]) {
            Write-Output "  Subtable $k :"
            foreach ($sk in $sub.Keys) {
                if ($sk -like "*password*") {
                    Write-Output "    $sk = [REDACTED]"
                } else {
                    Write-Output "    $sk = $($sub[$sk])"
                }
            }
        }
    }
}
