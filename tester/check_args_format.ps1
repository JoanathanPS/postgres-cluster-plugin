$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('RunPluginandWriteToRegFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$flags = [System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static'
$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$util.GetMethods($flags) | Where-Object { $_.Name -like '*Arg*' -or $_.Name -like '*Param*' -or $_.Name -like '*Decrypt*' } | ForEach-Object {
    Write-Output "Util::$($_.Name)"
}

$crypto = $asm.GetType('Site24x7PluginAgent.Utils.AES')
if ($crypto) {
    Write-Output "AES methods:"
    $crypto.GetMethods($flags) | ForEach-Object { Write-Output "  $($_.Name)" }
}
