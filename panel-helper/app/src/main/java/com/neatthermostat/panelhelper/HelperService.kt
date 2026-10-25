package com.neatthermostat.panelhelper

import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

/**
 * Runs all the time (started at boot): keeps Sonoff's floating button off, holds the
 * panel awake, reads its sensors and answers Neat on port 2424.
 */
class HelperService : Service() {
    private lateinit var prefs: HelperPrefs
    private lateinit var guard: AccessibilityGuard
    private lateinit var sensors: PanelSensors
    private var server: StatusServer? = null
    private var cpuLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var startedAt = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        running = true
        startedAt = System.currentTimeMillis()
        startForeground(NOTIFICATION_ID, notification())
        prefs = HelperPrefs(this)
        if (prefs.updateTarget != 0L && prefs.updateTarget <= BuildConfig.VERSION_CODE) {
            prefs.updateState = "Updated to ${BuildConfig.VERSION_NAME} at ${java.time.LocalDateTime.now().withNano(0)}"
            prefs.updateTarget = 0L
        }
        guard = AccessibilityGuard(this, prefs).also { it.start() }
        sensors = PanelSensors(this) { if (prefs.wakeOnApproach) wakeScreen() }.also { it.start() }
        applyStayAwake()
        server = StatusServer(prefs, ::handle).also {
            try {
                it.start()
            } catch (e: Exception) {
                Log.e(TAG, "status server failed to start", e)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        guard.enforce("start")
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        server?.stop()
        sensors.stop()
        guard.stop()
        releaseLocks()
        super.onDestroy()
    }

    // ---- Stay awake ----
    private fun applyStayAwake() {
        if (prefs.cpuLock && cpuLock == null) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            cpuLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "neat:helper").apply {
                setReferenceCounted(false)
                acquire()
            }
        } else if (!prefs.cpuLock) {
            cpuLock?.takeIf { it.isHeld }?.release()
            cpuLock = null
        }
        if (prefs.wifiLock && wifiLock == null) {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "neat:helper").apply {
                setReferenceCounted(false)
                acquire()
            }
        } else if (!prefs.wifiLock) {
            wifiLock?.takeIf { it.isHeld }?.release()
            wifiLock = null
        }
    }

    private fun releaseLocks() {
        cpuLock?.takeIf { it.isHeld }?.release()
        cpuLock = null
        wifiLock?.takeIf { it.isHeld }?.release()
        wifiLock = null
    }

    @Suppress("DEPRECATION")
    private fun wakeScreen() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (pm.isInteractive) return
        pm.newWakeLock(
            PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
            "neat:approach",
        ).acquire(3_000)
    }

    // ---- Fully Kiosk ----
    private fun usageAllowed(): Boolean {
        val ops = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        @Suppress("DEPRECATION")
        val mode = ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), packageName)
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /** App most recently brought to the front (needs usage access), or null. */
    private fun foregroundApp(): String? {
        if (!usageAllowed()) return null
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        val events = usm.queryEvents(now - 6 * 3600_000L, now)
        val event = UsageEvents.Event()
        var last: String? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            @Suppress("DEPRECATION")
            if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) last = event.packageName
        }
        return last
    }

    private fun launchFully(): Boolean {
        val intent = packageManager.getLaunchIntentForPackage(FULLY) ?: return false
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        startActivity(intent)
        return true
    }

    // ---- Local API ----
    private fun handle(method: String, path: String, body: JSONObject): JSONObject = when {
        method == "GET" && path == "/status" -> status()
        method == "POST" && path == "/config" -> {
            if (body.has("stay_awake")) { // 0.1.x name: both locks
                prefs.cpuLock = body.getBoolean("stay_awake")
                prefs.wifiLock = body.getBoolean("stay_awake")
            }
            if (body.has("cpu_lock")) prefs.cpuLock = body.getBoolean("cpu_lock")
            if (body.has("wifi_lock")) prefs.wifiLock = body.getBoolean("wifi_lock")
            if (body.has("wake_on_approach")) prefs.wakeOnApproach = body.getBoolean("wake_on_approach")
            if (body.has("blocked_services")) {
                prefs.blockedServices = if (body.isNull("blocked_services")) null else {
                    val arr = body.getJSONArray("blocked_services")
                    (0 until arr.length()).map { arr.getString(it) }.toSet()
                }
            }
            applyStayAwake()
            guard.enforce("settings changed")
            status()
        }
        method == "POST" && path == "/guard/apply" -> JSONObject().put("changed", guard.enforce("asked by Nook")).put("guard", guard.status())
        method == "POST" && path == "/fully/launch" -> JSONObject().put("launched", launchFully())
        method == "POST" && path == "/update" -> Updater.start(
            this, body.getString("url"), body.getString("sha256"), body.getLong("version_code"),
        )
        else -> throw NoSuchElementException()
    }

    private fun status(): JSONObject {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val wifi = wm.connectionInfo
        val fullyInstalled = packageManager.getLaunchIntentForPackage(FULLY) != null
        return JSONObject()
            .put("app", "neat-panel-helper")
            .put("version", BuildConfig.VERSION_NAME)
            .put("version_code", BuildConfig.VERSION_CODE)
            .put("device_owner", AdminReceiver.isDeviceOwner(this))
            .put("update", JSONObject()
                .put("state", prefs.updateState)
                .put("target", prefs.updateTarget))
            .put("device", JSONObject()
                .put("manufacturer", Build.MANUFACTURER)
                .put("model", Build.MODEL)
                .put("android", Build.VERSION.RELEASE)
                .put("sdk", Build.VERSION.SDK_INT)
                .put("build", Build.DISPLAY))
            .put("uptime_s", SystemClock.elapsedRealtime() / 1000)
            .put("helper_running_s", (System.currentTimeMillis() - startedAt) / 1000)
            .put("screen_on", pm.isInteractive)
            .put("stay_awake", JSONObject()
                .put("cpu_lock_enabled", prefs.cpuLock)
                .put("wifi_lock_enabled", prefs.wifiLock)
                .put("cpu_lock", cpuLock?.isHeld == true)
                .put("wifi_lock", wifiLock?.isHeld == true))
            .put("wifi", JSONObject()
                .put("rssi", wifi?.rssi ?: JSONObject.NULL)
                .put("link_mbps", wifi?.linkSpeed ?: JSONObject.NULL))
            .put("wake_on_approach", prefs.wakeOnApproach)
            .put("sensors", sensors.status())
            .put("guard", guard.status())
            .put("fully", JSONObject()
                .put("installed", fullyInstalled)
                .put("foreground_app", foregroundApp() ?: JSONObject.NULL)
                .put("usage_access", usageAllowed())
                .put("can_launch", Settings.canDrawOverlays(this)))
            .put("permissions", JSONArray(missingPermissions(this)))
    }

    private fun notification(): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "Nook Panel Helper", NotificationManager.IMPORTANCE_MIN),
        )
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Nook Panel Helper")
            .setContentText("Keeping the panel ready")
            .setSmallIcon(R.drawable.ic_helper)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "NookHelper"
        private const val CHANNEL = "helper"
        private const val NOTIFICATION_ID = 1
        const val FULLY = "de.ozerov.fully"

        @Volatile var running = false
            private set

        fun start(context: Context) {
            context.startForegroundService(Intent(context, HelperService::class.java))
        }

        /** One-time grants the user makes over adb; shown on the helper's screen. */
        fun missingPermissions(context: Context): List<String> {
            val missing = mutableListOf<String>()
            if (context.checkSelfPermission(android.Manifest.permission.WRITE_SECURE_SETTINGS) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED
            ) missing += "WRITE_SECURE_SETTINGS"
            val ops = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
            @Suppress("DEPRECATION")
            if (ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName) !=
                AppOpsManager.MODE_ALLOWED
            ) missing += "GET_USAGE_STATS"
            if (!Settings.canDrawOverlays(context)) missing += "SYSTEM_ALERT_WINDOW"
            return missing
        }
    }
}
