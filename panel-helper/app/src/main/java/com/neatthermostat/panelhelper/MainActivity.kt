package com.neatthermostat.panelhelper

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.net.wifi.WifiManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * The helper's only screen: is it running, the pairing code for Neat, and the one-time
 * adb commands still needed. Everything else happens in the background.
 */
class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var body: LinearLayout
    private lateinit var prefs: HelperPrefs

    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 2000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = HelperPrefs(this)
        HelperService.start(this)
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(20))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#16191D"))
            addView(body)
        })
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    private fun render() {
        body.removeAllViews()
        text("Nook Panel Helper", 22f, bold = true)
        text("Version ${BuildConfig.VERSION_NAME} · ${if (HelperService.running) "running" else "starting…"}", 14f, muted = true)

        gap()
        text("Pair with Nook", 16f, bold = true)
        if (prefs.apiKey.isNotEmpty()) {
            text("Paired. To pair again, use this code in Nook:", 14f, muted = true)
        } else {
            text("In Nook: Wall panels → this panel → Sonoff NSPanel Pro → Pair, and enter:", 14f, muted = true)
        }
        text(prefs.pairingCode.chunked(3).joinToString(" "), 40f, bold = true, colour = "#19D4DE")
        text("Panel address: ${ip()}:${StatusServer.PORT}", 14f, muted = true)

        val missing = HelperService.missingPermissions(this)
        val owner = AdminReceiver.isDeviceOwner(this)
        gap()
        text("One-time setup", 16f, bold = true)
        if (missing.isEmpty() && owner) {
            text("All set. Nook keeps this helper up to date.", 14f, colour = "#52C41A")
        }
        if (!owner) {
            text("For silent updates from Nook (needs no accounts on the panel):", 14f, muted = true)
            text("adb shell dpm set-device-owner $packageName/.AdminReceiver", 12f, mono = true)
        }
        if (missing.isNotEmpty()) {
            text("Run these once over adb (they stay after a reboot):", 14f, muted = true)
            val pkg = packageName
            for (perm in missing) {
                val cmd = when (perm) {
                    "WRITE_SECURE_SETTINGS" -> "adb shell pm grant $pkg android.permission.WRITE_SECURE_SETTINGS"
                    "GET_USAGE_STATS" -> "adb shell appops set $pkg GET_USAGE_STATS allow"
                    else -> "adb shell appops set $pkg SYSTEM_ALERT_WINDOW allow"
                }
                text(cmd, 12f, mono = true)
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun ip(): String {
        val wm = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        val raw = wm.connectionInfo?.ipAddress ?: 0
        if (raw == 0) return "(no Wi-Fi)"
        return listOf(raw and 0xff, raw shr 8 and 0xff, raw shr 16 and 0xff, raw shr 24 and 0xff).joinToString(".")
    }

    private fun text(s: String, size: Float, bold: Boolean = false, muted: Boolean = false, mono: Boolean = false, colour: String? = null) {
        body.addView(TextView(this).apply {
            text = s
            setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
            setTextColor(Color.parseColor(colour ?: if (muted) "#99F4F5F6" else "#F4F5F6"))
            typeface = when {
                mono -> Typeface.MONOSPACE
                bold -> Typeface.DEFAULT_BOLD
                else -> Typeface.DEFAULT
            }
            gravity = Gravity.START
            setTextIsSelectable(mono)
            setPadding(0, dp(2), 0, dp(2))
        })
    }

    private fun gap() {
        body.addView(TextView(this).apply { height = dp(16) })
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}
