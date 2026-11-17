$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
foreach ($t in $asm.GetTypes()) {
    if ($t.FullName -like '*Crypto*' -or $t.FullName -like '*Decrypt*' -or $t.FullName -like '*AES*') {
        Write-Output "Type: $($t.FullName)"
        $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance,DeclaredOnly') | ForEach-Object {
            Write-Output "  $($_.ReturnType.Name) $($_.Name) ($([string]::Join(', ', ($_.GetParameters() | ForEach-Object { "$($_.ParameterType.Name) $($_.Name)" }))))"
        }
    }
}
