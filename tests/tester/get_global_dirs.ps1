$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$t = $asm.GetType('Site24x7PluginAgent.Global')
foreach ($f in $t.GetFields([System.Reflection.BindingFlags]'Public,NonPublic,Static')) {
    if ($f.FieldType -eq [string]) {
        Write-Host "$($f.Name) = $($f.GetValue($null))"
    }
}
