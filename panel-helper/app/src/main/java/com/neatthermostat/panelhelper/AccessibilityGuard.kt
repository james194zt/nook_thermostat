package com.neatthermostat.panelhelper

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityManager
import org.json.JSONArray
import org.json.JSONObject

/**
 * Keeps chosen accessibility services switched off. Sonoff's floating "Return to main
 * program" button is one: its software switches it back on after every change and boot.
 * Watches the setting, so a re-enable is undone within a moment.
 */
class AccessibilityGuard(private val context: Context, private val prefs: HelperPrefs) {
    private val resolver = context.contentResolver
    private val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
        override fun onChange(selfChange: Boolean) {
            enforce("re-enabled")
        }
    }

    var timesTurnedOff = 0
        private set
    var lastAction = ""
        private set

    fun start() {
        resolver.registerContentObserver(
            Settings.Secure.getUriFor(Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES), false, observer,
        )
        enforce("start")
    }

    fun stop() {
        resolver.unregisterContentObserver(observer)
    }

    fun canWrite(): Boolean =
        context.checkSelfPermission(Manifest.permission.WRITE_SECURE_SETTINGS) == PackageManager.PERMISSION_GRANTED

    private fun installed(): List<AccessibilityServiceInfo> {
        val manager = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as AccessibilityManager
        return manager.installedAccessibilityServiceList ?: emptyList()
    }

    private fun label(info: AccessibilityServiceInfo): String =
        info.resolveInfo?.loadLabel(context.packageManager)?.toString() ?: ""

    private fun normalise(id: String): String =
        ComponentName.unflattenFromString(id)?.flattenToString() ?: id

    /** Components to keep off: the saved list, or automatically Sonoff's return button. */
    fun blocked(): Set<String> {
        prefs.blockedServices?.let { saved -> return saved.map(::normalise).toSet() }
        return installed()
            .filter { isSonoffReturnButton(normalise(it.id), label(it)) }
            .map { normalise(it.id) }
            .toSet()
    }

    /** NSPanel Pro (firmware 4.5): "Return to main program with accessibility service",
     *  com.eWeLinkControlPanel/com.coolkit.nspanelpro.service.accessibility.BackButtonService. */
    private fun isSonoffReturnButton(id: String, label: String): Boolean =
        label.contains("return to main program", ignoreCase = true) ||
            id.endsWith(".service.accessibility.BackButtonService")

    private fun enabledIds(): List<String> =
        (Settings.Secure.getString(resolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "")
            .split(':')
            .filter { it.isNotBlank() }

    /** Switch blocked services off now. Returns true if something was changed. */
    @Synchronized
    fun enforce(reason: String): Boolean {
        val blocked = blocked()
        if (blocked.isEmpty()) return false
        val enabled = enabledIds()
        val keep = enabled.filter { normalise(it) !in blocked }
        if (keep.size == enabled.size) return false
        if (!canWrite()) {
            lastAction = "Can't switch it off yet: grant WRITE_SECURE_SETTINGS (see the helper's screen)"
            return false
        }
        return try {
            Settings.Secure.putString(resolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, keep.joinToString(":"))
            if (keep.isEmpty()) Settings.Secure.putInt(resolver, Settings.Secure.ACCESSIBILITY_ENABLED, 0)
            timesTurnedOff++
            lastAction = "Switched off ${enabled.size - keep.size} service(s) ($reason) at ${java.time.LocalTime.now().withNano(0)}"
            Log.i(TAG, lastAction)
            true
        } catch (e: SecurityException) {
            lastAction = "Not allowed: ${e.message}"
            false
        }
    }

    fun status(): JSONObject {
        val blocked = blocked()
        val enabled = enabledIds().map(::normalise).toSet()
        val services = JSONArray()
        for (info in installed()) {
            val id = normalise(info.id)
            services.put(
                JSONObject()
                    .put("id", id)
                    .put("label", label(info))
                    .put("enabled", id in enabled)
                    .put("blocked", id in blocked),
            )
        }
        return JSONObject()
            .put("can_write", canWrite())
            .put("automatic", prefs.blockedServices == null)
            .put("blocked", JSONArray(blocked.toList()))
            .put("times_turned_off", timesTurnedOff)
            .put("last_action", lastAction)
            .put("services", services)
    }

    companion object {
        private const val TAG = "NookGuard"
    }
}
