$cipherB64 = "45cPtZ8oRlWaZi+W8l9xww=="
$data = [System.Convert]::FromBase64String($cipherB64)
$iv = New-Object byte[] 16

$candidates = @(
    "577111673237472603",
    "E//l5Rmnj6zjNh1y05RQHj9swVDRIqje5brl8ithEYJf8OK5oHSPaE4EvqIWCsCc"
)

foreach ($c in $candidates) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $keyBytes = $sha256.ComputeHash([System.Text.Encoding]::ASCII.GetBytes($c))
    
    $rijn = [System.Security.Cryptography.Rijndael]::Create()
    $rijn.Key = $keyBytes
    $rijn.IV = $iv
    $rijn.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
    $rijn.Mode = [System.Security.Cryptography.CipherMode]::CBC

    try {
        $dec = $rijn.CreateDecryptor()
        $ms = New-Object System.IO.MemoryStream(@(,$data))
        $cs = New-Object System.Security.Cryptography.CryptoStream($ms, $dec, [System.Security.Cryptography.CryptoStreamMode]::Read)
        $sr = New-Object System.IO.StreamReader($cs)
        $plain = $sr.ReadToEnd()
        Write-Output "SUCCESS! Candidate '$c' decrypted plain: $plain"
    } catch {
        Write-Output "Candidate '$c' failed: $_"
    }
}
