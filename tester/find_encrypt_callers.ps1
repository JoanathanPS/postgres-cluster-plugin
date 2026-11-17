$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$aes = $asm.GetType('Site24x7PluginAgent.Utils.AES')
$encryptMethod = $aes.GetMethod('Encrypt', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
$tok = $encryptMethod.MetadataToken

Write-Output "AES::Encrypt token: $tok (0x$($tok.ToString('X')))"

foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly')) {
        $body = $m.GetMethodBody()
        if ($body) {
            $il = $body.GetILAsByteArray()
            for ($i = 0; $i -lt $il.Length - 4; $i++) {
                if ($il[$i] -eq 0x28) { # call
                    $callee = [BitConverter]::ToInt32($il, $i + 1)
                    if ($callee -eq $tok) {
                        Write-Output "Called from: $($t.FullName)::$($m.Name) at IL_$($i.ToString('X4'))"
                    }
                }
            }
        }
    }
}
