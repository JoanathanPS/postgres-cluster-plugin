$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)

foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static')) {
        if ($m.Name -like '*Python*' -or $m.Name -like '*Execute*' -or $m.Name -like '*Script*' -or $m.Name -like '*Process*') {
            Write-Output "$($t.FullName)::$($m.Name)"
        }
    }
}
