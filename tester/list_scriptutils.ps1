$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)

foreach ($t in $asm.GetTypes()) {
    if ($t.FullName -like '*ScriptUtils*') {
        Write-Output "Type: $($t.FullName)"
        foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly')) {
            Write-Output "   Method: $($m.Name)"
        }
    }
}
