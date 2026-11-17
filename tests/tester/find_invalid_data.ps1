$root = 'C:\Program Files (x86)\Site24x7\WinAgent'
$str = 'Invalid data'
$bytesAscii = [System.Text.Encoding]::ASCII.GetBytes($str)
$bytesUnicode = [System.Text.Encoding]::Unicode.GetBytes($str)

function Search-Bytes($file, $pattern) {
    $fileBytes = [System.IO.File]::ReadAllBytes($file)
    $flen = $fileBytes.Length
    $plen = $pattern.Length
    for ($i = 0; $i -le $flen - $plen; $i++) {
        $match = $true
        for ($j = 0; $j -lt $plen; $j++) {
            if ($fileBytes[$i + $j] -ne $pattern[$j]) {
                $match = $false
                break
            }
        }
        if ($match) { return $true }
    }
    return $false
}

Get-ChildItem -Path $root -Include *.exe,*.dll -Recurse | ForEach-Object {
    try {
        if (Search-Bytes $_.FullName $bytesAscii -or Search-Bytes $_.FullName $bytesUnicode) {
            Write-Output "Found in: $($_.FullName)"
        }
    } catch {}
}
