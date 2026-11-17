$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$taskObj = $asm.GetType('Site24x7PluginAgent.TaskObject')
$field = $taskObj.GetField('instanceData')
$tok = $field.MetadataToken

Write-Output "instanceData token: 0x$($tok.ToString('X'))"

foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly')) {
        $body = $m.GetMethodBody()
        if ($body) {
            $il = $body.GetILAsByteArray()
            for ($i = 0; $i -lt $il.Length - 4; $i++) {
                if ($il[$i] -eq 0x7d) { # stfld
                    $callee = [BitConverter]::ToInt32($il, $i + 1)
                    if ($callee -eq $tok) {
                        Write-Output "Set in: $($t.FullName)::$($m.Name) at IL_$($i.ToString('X4'))"
                    }
                }
            }
        }
    }
}
