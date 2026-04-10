$ErrorActionPreference = 'Stop'
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$dest = "D:\TOTLI_BI_BACKUP_$ts.zip"
$source = 'D:\TOTLI BI'
Write-Host "Manba: $source"
Write-Host "Maqsad: $dest"
Write-Host "Boshlandi: $(Get-Date -Format 'HH:mm:ss')"

$sevenZip = 'C:\Program Files\7-Zip\7z.exe'
if (Test-Path $sevenZip) {
    Write-Host "7-Zip topildi, ishlatilmoqda..."
    & $sevenZip a -tzip -mx=5 -ssw -bso0 -bsp1 $dest "$source\*"
    if ($LASTEXITCODE -gt 1) { throw "7z exit code: $LASTEXITCODE" }
    if ($LASTEXITCODE -eq 1) { Write-Host "DIQQAT: 7z warning bilan yakunladi (band fayllar bo'lishi mumkin)" }
} else {
    Write-Host "Compress-Archive ishlatilmoqda..."
    Compress-Archive -Path "$source\*" -DestinationPath $dest -CompressionLevel Optimal -Force
}

$info = Get-Item $dest
$sizeMB = [math]::Round($info.Length / 1MB, 2)
Write-Host "Tugadi: $(Get-Date -Format 'HH:mm:ss')"
Write-Host "Fayl: $dest"
Write-Host "Hajmi: $sizeMB MB"
