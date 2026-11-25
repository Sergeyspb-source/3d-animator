# Downloads the TRELLIS.2 weights for trellis.cpp (ilintar/trellis2-gguf, Q8, the res-512 set: 8 files, 7.2 GB)
# into D:\conda\hf\trellis2-gguf\q8 and checks every file's SHA-256. Resumable: just run again.
# The res-1024 cascade files (*_1024.gguf) are not taken: the cascade needs a 16 GB card.
$ErrorActionPreference = 'Continue'   # curl's exit code is not trusted: every file is judged by its hash
$ProgressPreference = 'SilentlyContinue'
$env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
$dst = 'D:\conda\hf\trellis2-gguf\q8'
$base = 'https://huggingface.co/ilintar/trellis2-gguf/resolve/main/q8'
$files = [ordered]@{
    'ss_flow.gguf'        = @('ea6d8a42b20661a5c6a52e5ffbdc1df7aca9b212792193873b418c69f871422c', 1376059040)
    'ss_dec.gguf'         = @('2790b5eecb261cc877d9bf175ce2bd6dd48cd65be8c042c5f5bc023dfca01cf7', 147379392)
    'shape_flow_512.gguf' = @('29b639f4ff22ded8f91b619376a835f64b9874b0ebcadb9ac6c305195bf5d1f9', 1376125952)
    'shape_dec.gguf'      = @('0de7c7a675022dd8696d526a9279e5a50b2a35c8a79452f434a72dc53d40f169', 881361568)
    'tex_flow_512.gguf'   = @('389a2cbdda59d53b21e5989650d9d36b7ac603266eaef06712cd07a9fc377210', 1376178176)
    'tex_dec.gguf'        = @('88b4fced46455e02f316664d5c43584a311921dd9a1cdc1b7b7d981cca9214d4', 881344576)
    'dinov3.gguf'         = @('0dd4ffd4b46a248f5b7d49c35275d68461fbf73f57ddb4c1fa8afb4f7bb45a0d', 323657920)
    'birefnet.gguf'       = @('10c5dd4dcac904cf81c9a16180eb66f167dd52ab55867f54a44567b0b2babbc1', 882749024)
}
New-Item -ItemType Directory -Force $dst | Out-Null
$bad = @()
foreach ($name in $files.Keys) {
    $sha, $size = $files[$name]
    $path = Join-Path $dst $name
    if ((Test-Path $path) -and (Get-Item $path).Length -eq $size -and (Get-FileHash $path -Algorithm SHA256).Hash -eq $sha) {
        Write-Output "ok        $name"
        continue
    }
    Write-Output "download  $name ($([math]::Round($size / 1GB, 2)) GB)"
    curl.exe -L --fail --retry 5 --retry-delay 5 -C - -s -S -o $path "$base/$name"
    if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $sha) {
        Remove-Item $path -Confirm:$false        # a broken or changed file: drop it, the next run fetches it again
        $bad += $name
        Write-Output "BAD SHA-256 $name (removed)"
    }
}
if ($bad) { throw "not verified: $($bad -join ', ') - run again" }
Write-Output "WEIGHTS_DONE $dst"
