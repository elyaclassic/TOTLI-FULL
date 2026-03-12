# Deprecated Android Gradle Plugin Settings - Yechim

## Muammo
Quyidagi deprecated sozlamalar global `gradle.properties` faylida mavjud va AGP 10.0 da olib tashlanadi:

- `android.enableAppCompileTimeRClass=false` (default endi `true`)
- `android.usesSdkInManifest.disallowed=false` (default endi `true`)
- `android.builtInKotlin=false` (default endi `true`)
- `android.r8.optimizedResourceShrinking=false` (default endi `true`)
- `android.defaults.buildfeatures.resvalues=true` (default endi `false`)
- `android.sdk.defaultTargetSdkToCompileSdkIfUnset=false` (default endi `true`)
- `android.newDsl=false` (default endi `true`)

## Yechim

### 1-qadam: Global gradle.properties faylini topish
Global `gradle.properties` fayli quyidagi joyda:
```
C:\Users\ELYOR\.gradle\gradle.properties
```

### 2-qadam: Faylni ochish
Faylni matn muharririda oching (Notepad, VS Code, yoki boshqa).

### 3-qadam: Deprecated sozlamalarni olib tashlash
Quyidagi qatorlarni topib, **o'chiring** yoki **comment qiling** (`#` qo'shib):

```properties
# Bu qatorlarni O'CHIRISH yoki # bilan comment qilish kerak:
android.enableAppCompileTimeRClass=false
android.usesSdkInManifest.disallowed=false
android.builtInKotlin=false
android.r8.optimizedResourceShrinking=false
android.defaults.buildfeatures.resvalues=true
android.sdk.defaultTargetSdkToCompileSdkIfUnset=false
android.newDsl=false
```

### 4-qadam: Faylni saqlash
Faylni saqlang va Android Studio'ni qayta ishga tushiring.

### 5-qadam: Gradle sync
Android Studio'da:
- **File** → **Sync Project with Gradle Files**

## Alternativ: PowerShell orqali avtomatik tuzatish

PowerShell'da quyidagi buyruqni bajaring:

```powershell
$gradleProps = "$env:USERPROFILE\.gradle\gradle.properties"
if (Test-Path $gradleProps) {
    $content = Get-Content $gradleProps
    $deprecated = @(
        "android.enableAppCompileTimeRClass",
        "android.usesSdkInManifest.disallowed",
        "android.builtInKotlin",
        "android.r8.optimizedResourceShrinking",
        "android.defaults.buildfeatures.resvalues",
        "android.sdk.defaultTargetSdkToCompileSdkIfUnset",
        "android.newDsl"
    )
    $filtered = $content | Where-Object {
        $line = $_.Trim()
        $shouldKeep = $true
        foreach ($dep in $deprecated) {
            if ($line -like "$dep=*") {
                $shouldKeep = $false
                break
            }
        }
        $shouldKeep
    }
    $filtered | Set-Content $gradleProps
    Write-Host "Deprecated sozlamalar olib tashlandi!"
} else {
    Write-Host "Global gradle.properties fayli topilmadi."
}
```

## Eslatma
- Bu faqat **ogohlantirishlar** - build ishlashiga ta'sir qilmaydi
- AGP 10.0 versiyasida bu sozlamalar butunlay olib tashlanadi
- Agar siz bu sozlamalarni o'zgartirmasangiz, Gradle default qiymatlarni ishlatadi
