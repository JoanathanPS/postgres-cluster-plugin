$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")
$globType = $asm.GetType('Site24x7PluginAgent.Global')
$inst = [Activator]::CreateInstance($globType)
$m = $globType.GetMethod('Init', [System.Reflection.BindingFlags]'Public,NonPublic,Instance')

try {
    $m.Invoke($inst, $null)
    Write-Output "Init instance succeeded!"
} catch {
    Write-Output "Init instance failed: $_"
}

foreach ($f in $globType.GetFields([System.Reflection.BindingFlags]'Public,NonPublic,Static')) {
    if ($f.FieldType -eq [string]) {
        $val = $f.GetValue($null)
        if ($f.Name -like "*seckey*") {
            if ($val) { Write-Output "$($f.Name) = [SET]" } else { Write-Output "$($f.Name) = [EMPTY]" }
        } else {
            Write-Output "$($f.Name) = $val"
        }
    }
}
