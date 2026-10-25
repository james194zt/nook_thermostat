package com.neatthermostat.panelhelper

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlin.concurrent.thread

/**
 * Self-update from Neat: download the APK Neat ships, check its hash and version, and
 * install it over this app. As device owner it installs silently; otherwise Android asks
 * on the panel. Settings, pairing and permission grants carry over; the service restarts
 * itself afterwards (MY_PACKAGE_REPLACED).
 */
object Updater {
    private const val TAG = "NookUpdater"
    @Volatile private var busy = false

    fun start(context: Context, url: String, sha256: String, versionCode: Long): JSONObject {
        val prefs = HelperPrefs(context)
        if (versionCode <= BuildConfig.VERSION_CODE) {
            return JSONObject().put("started", false).put("reason", "already on ${BuildConfig.VERSION_NAME}")
        }
        if (busy) return JSONObject().put("started", false).put("reason", "an update is already running")
        busy = true
        prefs.updateTarget = versionCode
        prefs.updateState = "Downloading"
        thread(name = "neat-update", isDaemon = true) {
            try {
                val file = download(context, url)
                val hash = sha256(file)
                if (!hash.equals(sha256, ignoreCase = true)) throw IllegalStateException("download didn't match its checksum")
                val info = context.packageManager.getPackageArchiveInfo(file.path, 0)
                    ?: throw IllegalStateException("downloaded file isn't an app")
                @Suppress("DEPRECATION")
                val gotCode = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
                if (info.packageName != context.packageName || gotCode != versionCode) {
                    throw IllegalStateException("downloaded ${info.packageName} $gotCode, expected $versionCode")
                }
                prefs.updateState = "Installing"
                install(context, file)
            } catch (e: Exception) {
                Log.w(TAG, "update failed", e)
                prefs.updateState = "Failed: ${e.message ?: e.javaClass.simpleName}"
                busy = false
            }
        }
        return JSONObject().put("started", true)
    }

    private fun download(context: Context, url: String): File {
        val out = File(context.cacheDir, "update.apk")
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 60_000
        try {
            if (conn.responseCode != 200) throw IllegalStateException("HTTP ${conn.responseCode} from Nook")
            conn.inputStream.use { input -> out.outputStream().use { input.copyTo(it) } }
        } finally {
            conn.disconnect()
        }
        return out
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                digest.update(buf, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun install(context: Context, file: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        val sessionId = installer.createSession(params)
        installer.openSession(sessionId).use { session ->
            file.inputStream().use { input ->
                session.openWrite("helper.apk", 0, file.length()).use { output ->
                    input.copyTo(output)
                    session.fsync(output)
                }
            }
            val intent = Intent(context, InstallResultReceiver::class.java)
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
            val pending = PendingIntent.getBroadcast(context, sessionId, intent, flags)
            session.commit(pending.intentSender)
        }
    }

    internal fun finished() {
        busy = false
    }
}

/** Android's answer to the install: done, failed, or "ask the person" (not device owner). */
class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val prefs = HelperPrefs(context)
        when (val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -999)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                prefs.updateState = "Waiting for a tap on the panel"
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                if (confirm != null) context.startActivity(confirm)
            }
            PackageInstaller.STATUS_SUCCESS -> {
                // Usually never seen: the new version replaces this process first.
                prefs.updateState = "Installed"
                Updater.finished()
            }
            else -> {
                val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "status $status"
                prefs.updateState = "Failed: $msg"
                Updater.finished()
            }
        }
    }
}
