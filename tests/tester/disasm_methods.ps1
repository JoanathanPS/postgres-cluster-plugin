$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)

function Disassemble-Method($type, $methodName) {
    $m = $type.GetMethod($methodName, [System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static')
    if (-not $m) {
        Write-Output "Method $methodName not found in $($type.FullName)"
        return
    }
    Write-Output "=== $($type.FullName)::$($m.Name) ==="
    $body = $m.GetMethodBody()
    if (-not $body) {
        Write-Output "No body"
        return
    }
    $il = $body.GetILAsByteArray()
    Write-Output "IL byte count: $($il.Length)"
}

$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
Disassemble-Method $dc 'RegisterPlugin'
Disassemble-Method $dc 'RunPluginandWriteForReg'
Disassemble-Method $dc 'RunPluginandWritetoFile'

$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
Disassemble-Method $util 'GetPythonPath'
