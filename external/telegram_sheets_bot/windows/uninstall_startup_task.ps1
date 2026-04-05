# Administrator shart emas
$TaskName = "TelegramHisobotBot_RD"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "O'chirildi (yoki topilmadi): $TaskName"
