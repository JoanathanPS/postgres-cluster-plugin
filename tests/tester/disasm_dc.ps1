$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')

function Print-IL($method) {
    Write-Output "=================================================="
    Write-Output "METHOD: $($method.Name)"
    Write-Output "=================================================="
    $body = $method.GetMethodBody()
    if (-not $body) { Write-Output "No body"; return }
    $il = $body.GetILAsByteArray()
    
    # We can inspect the local variables and exception handling clauses
    Write-Output "Locals count: $($body.LocalVariables.Count)"
    foreach ($lv in $body.LocalVariables) {
        Write-Output "  Local $($lv.LocalIndex): $($lv.LocalType.FullName)"
    }
}

Print-IL ($dc.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance'))
Print-IL ($dc.GetMethod('RegisterPlugin', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance'))
