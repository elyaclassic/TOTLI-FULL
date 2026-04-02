package com.totli.totli_mobile

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity: FlutterActivity() {
    private val CHANNEL = "app.totli/installer"
    private val TAG = "TotliInstaller"
    private val REQUEST_INSTALL = 1001
    private var pendingApkPath: String? = null
    private var pendingResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            if (call.method == "installApk") {
                val path = call.argument<String>("path")
                if (path != null) {
                    pendingApkPath = path
                    pendingResult = result
                    tryInstallApk(path, result)
                } else {
                    result.error("NO_PATH", "APK path not provided", null)
                }
            } else {
                result.notImplemented()
            }
        }
    }

    private fun tryInstallApk(path: String, result: MethodChannel.Result) {
        try {
            // Android 8+ (API 26+) — "noma'lum manbalardan o'rnatish" ruxsatini tekshirish
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                if (!packageManager.canRequestPackageInstalls()) {
                    Log.d(TAG, "Install permission yo'q — sozlamalarga yo'naltirish")
                    val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                    intent.data = Uri.parse("package:$packageName")
                    startActivityForResult(intent, REQUEST_INSTALL)
                    return
                }
            }
            installApk(path)
            result.success(true)
        } catch (e: Exception) {
            Log.e(TAG, "Install xatosi: ${e.message}", e)
            result.error("INSTALL_ERROR", e.message, e.stackTraceToString())
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_INSTALL) {
            val path = pendingApkPath
            val result = pendingResult
            if (path != null && result != null) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && packageManager.canRequestPackageInstalls()) {
                    try {
                        installApk(path)
                        result.success(true)
                    } catch (e: Exception) {
                        Log.e(TAG, "Install xatosi (after permission): ${e.message}", e)
                        result.error("INSTALL_ERROR", e.message, e.stackTraceToString())
                    }
                } else {
                    result.error("PERMISSION_DENIED", "O'rnatish ruxsati berilmadi", null)
                }
            }
            pendingApkPath = null
            pendingResult = null
        }
    }

    private fun installApk(path: String) {
        val file = File(path)
        Log.d(TAG, "APK path: $path, exists: ${file.exists()}, size: ${file.length()}")
        if (!file.exists()) {
            throw Exception("APK fayl topilmadi: $path")
        }
        if (file.length() < 1000) {
            throw Exception("APK fayl juda kichik (${file.length()} bayt) — buzilgan bo'lishi mumkin")
        }

        val uri: Uri
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            uri = FileProvider.getUriForFile(this, "${applicationContext.packageName}.fileprovider", file)
            Log.d(TAG, "FileProvider URI: $uri")
        } else {
            uri = Uri.fromFile(file)
        }

        // Install intentni biroz kechiktirib yuborish — Flutter UI blokirovkasidan qochish
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        Log.d(TAG, "Install intent yuborilmoqda...")
        // Kechiktirish bilan yuborish — FlutterEngine blokini oldini olish
        Handler(Looper.getMainLooper()).postDelayed({
            try {
                startActivity(intent)
                Log.d(TAG, "Install intent yuborildi!")
            } catch (e: Exception) {
                Log.e(TAG, "startActivity xatosi: ${e.message}", e)
            }
        }, 500)
    }
}
