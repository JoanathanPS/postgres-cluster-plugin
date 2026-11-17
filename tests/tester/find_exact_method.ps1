$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$mod = $asm.GetModules()[0]

foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
        $body = $m.GetMethodBody()
        if ($body) {
            $il = $body.GetILAsByteArray()
            for ($i = 0; $i -lt $il.Length - 4; $i++) {
                if ($il[$i] -eq 0x72) { # ldstr opcode
                    $token = [System.BitConverter]::ToInt32($il, $i + 1)
                    try {
                        $s = $mod.ResolveString($token)
                        if ($s -match 'already registered') {
                            Write-Host "FOUND in $($t.FullName)::$($m.Name) -> $s"
                        }
                    } catch {}
                }
            }
        }
    }
}
