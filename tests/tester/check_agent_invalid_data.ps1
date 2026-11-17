. .\tester\il_disasm.ps1

$found = @()
foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance,DeclaredOnly')) {
        $body = $m.GetMethodBody()
        if (-not $body) { continue }
        $il = $body.GetILAsByteArray()
        $module = $m.Module
        $pos = 0
        while ($pos -lt $il.Length) {
            $b = $il[$pos++]
            if ($b -eq 0x72) { # ldstr opcode
                $tok = [System.BitConverter]::ToInt32($il, $pos)
                $pos += 4
                try {
                    $s = $module.ResolveString($tok)
                    if ($s -like '*Invalid data*') {
                        $found += "$($t.FullName).$($m.Name): `"$s`""
                    }
                } catch {}
            }
        }
    }
}

if ($found.Count -eq 0) {
    Write-Output "No occurrence of 'Invalid data' in any method of Site24x7PluginAgent.exe!"
} else {
    $found | ForEach-Object { Write-Output $_ }
}
