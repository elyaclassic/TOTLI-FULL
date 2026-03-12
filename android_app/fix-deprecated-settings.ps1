# Deprecated Android Gradle Plugin Settings Tuzatish Skripti
# Bu skript global gradle.properties faylidan deprecated sozlamalarni olib tashlaydi

$gradlePropsPath = "$env:USERPROFILE\.gradle\gradle.properties"
$deprecatedSettings = @(
    "android.enableAppCompileTimeRClass",
    "android.usesSdkInManifest.disallowed",
    "android.builtInKotlin",
    "android.r8.optimizedResourceShrinking",
    "android.defaults.buildfeatures.resvalues",
    "android.sdk.defaultTargetSdkToCompileSdkIfUnset",
    "android.newDsl"
)

Write-Host "Deprecated Android Gradle Plugin sozlamalarini tuzatish..." -ForegroundColor Yellow
Write-Host ""

if (Test-Path $gradlePropsPath) {
    Write-Host "Global gradle.properties topildi: $gradlePropsPath" -ForegroundColor Green
    
    $content = Get-Content $gradlePropsPath
    $originalLineCount = $content.Count
    $removedCount = 0
    
    # Deprecated sozlamalarni olib tashlash
    $filtered = $content | Where-Object {
        $line = $_.Trim()
        $shouldKeep = $true
        
        foreach ($dep in $deprecatedSettings) {
            if ($line -like "$dep=*") {
                Write-Host "  O'chirilmoqda: $line" -ForegroundColor Red
                $shouldKeep = $false
                $removedCount++
                break
            }
        }
        $shouldKeep
    }
    
    if ($removedCount -gt 0) {
        # Backup yaratish
        $backupPath = "$gradlePropsPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item $gradlePropsPath $backupPath
        Write-Host "  Backup yaratildi: $backupPath" -ForegroundColor Cyan
        
        # Yangi kontentni yozish
        $filtered | Set-Content $gradlePropsPath
        Write-Host ""
        Write-Host "✅ $removedCount ta deprecated sozlama olib tashlandi!" -ForegroundColor Green
        Write-Host "   Backup fayl: $backupPath" -ForegroundColor Cyan
    } else {
        Write-Host "✅ Deprecated sozlamalar topilmadi - fayl allaqachon toza!" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "Keyingi qadamlar:" -ForegroundColor Yellow
    Write-Host "1. Android Studio'ni qayta ishga tushiring"
    Write-Host "2. File → Sync Project with Gradle Files"
    
} else {
    Write-Host "⚠️  Global gradle.properties fayli topilmadi: $gradlePropsPath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Bu deprecated sozlamalar quyidagi joylardan kelishi mumkin:" -ForegroundColor Yellow
    Write-Host "1. Android Studio IDE sozlamalari"
    Write-Host "2. Project-level gradle.properties (tekshirildi - topilmadi)"
    Write-Host "3. Gradle cache"
    Write-Host ""
    Write-Host "Yechim:" -ForegroundColor Cyan
    Write-Host "1. Android Studio'da File → Invalidate Caches / Restart"
    Write-Host "2. Build → Clean Project"
    Write-Host "3. File → Sync Project with Gradle Files"
}

Write-Host ""
Write-Host "Skript tugadi." -ForegroundColor Green
