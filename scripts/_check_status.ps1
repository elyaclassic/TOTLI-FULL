Write-Host "=== Jami backup fayllar ===" -ForegroundColor Cyan
$files = Get-ChildItem 'D:\TOTLI_BI_BACKUPS\live' -Filter '*.db.gz'
Write-Host ("Soni: " + $files.Count)
$total_mb = ($files | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Jami hajm: {0:N2} MB" -f $total_mb)
Write-Host ""

Write-Host "=== So'nggi 15 ta ===" -ForegroundColor Cyan
$files | Sort-Object LastWriteTime -Descending | Select-Object -First 15 Name, @{N='MB';E={[math]::Round($_.Length/1MB,2)}}, LastWriteTime | Format-Table -AutoSize

Write-Host "=== Eng eski 3 ta (retention uchun) ===" -ForegroundColor Cyan
$files | Sort-Object LastWriteTime | Select-Object -First 3 Name, LastWriteTime | Format-Table -AutoSize

Write-Host "=== Log oxiri (10 qator) ===" -ForegroundColor Cyan
Get-Content 'D:\TOTLI_BI_BACKUPS\backup_live.log' -Tail 10
Write-Host ""

Write-Host "=== Task holati ===" -ForegroundColor Cyan
Get-ScheduledTaskInfo -TaskName 'TOTLI_BI_Live_Backup' | Select-Object LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns | Format-List

Write-Host "=== Hozirgi vaqt ===" -ForegroundColor Cyan
Get-Date
