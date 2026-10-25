package com.neatthermostat.panelhelper

import android.util.Log
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.security.MessageDigest
import kotlin.concurrent.thread

/**
 * A tiny HTTP API on the panel for Neat (port 2424). Pairing: Neat posts the 6-digit code
 * shown on the helper's screen to /pair and gets a key; every other call needs that key in
 * the X-Neat-Key header. No HA token ever lives on the panel.
 */
class StatusServer(
    private val prefs: HelperPrefs,
    private val handler: (method: String, path: String, body: JSONObject) -> JSONObject,
) {
    private var server: ServerSocket? = null
    @Volatile private var failedPairs = 0
    @Volatile private var pairBlockedUntil = 0L

    fun start() {
        if (server != null) return
        val socket = ServerSocket(PORT)
        server = socket
        thread(name = "neat-status-server", isDaemon = true) {
            while (!socket.isClosed) {
                try {
                    val client = socket.accept()
                    thread(isDaemon = true) { serve(client) }
                } catch (e: SocketException) {
                    break
                } catch (e: Exception) {
                    Log.w(TAG, "accept failed", e)
                }
            }
        }
    }

    fun stop() {
        server?.close()
        server = null
    }

    private fun serve(client: Socket) {
        client.use { sock ->
            sock.soTimeout = 10_000
            val reader = BufferedReader(InputStreamReader(sock.getInputStream(), Charsets.UTF_8))
            val requestLine = reader.readLine() ?: return
            val parts = requestLine.split(" ")
            if (parts.size < 2) return
            val method = parts[0].uppercase()
            val path = parts[1].substringBefore('?')
            val headers = mutableMapOf<String, String>()
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
                val idx = line.indexOf(':')
                if (idx > 0) headers[line.substring(0, idx).trim().lowercase()] = line.substring(idx + 1).trim()
            }
            val length = headers["content-length"]?.toIntOrNull()?.coerceIn(0, 65_536) ?: 0
            val chars = CharArray(length)
            var read = 0
            while (read < length) {
                val n = reader.read(chars, read, length - read)
                if (n < 0) break
                read += n
            }
            val body = try {
                if (read > 0) JSONObject(String(chars, 0, read)) else JSONObject()
            } catch (e: Exception) {
                JSONObject()
            }
            val (code, result) = route(method, path, headers["x-neat-key"] ?: "", body)
            val bytes = result.toString().toByteArray(Charsets.UTF_8)
            val out = sock.getOutputStream()
            out.write(
                ("HTTP/1.1 $code ${if (code == 200) "OK" else "Error"}\r\n" +
                    "Content-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n")
                    .toByteArray(Charsets.UTF_8),
            )
            out.write(bytes)
            out.flush()
        }
    }

    private fun route(method: String, path: String, key: String, body: JSONObject): Pair<Int, JSONObject> {
        if (method == "GET" && path == "/") {
            // Lets Neat find the helper without a key.
            return 200 to JSONObject().put("app", "neat-panel-helper").put("version", BuildConfig.VERSION_NAME).put("paired", prefs.apiKey.isNotEmpty())
        }
        if (method == "POST" && path == "/pair") return pair(body)
        if (prefs.apiKey.isEmpty() || !sameKey(key, prefs.apiKey)) {
            return 401 to JSONObject().put("error", "not paired")
        }
        return try {
            200 to handler(method, path, body)
        } catch (e: NoSuchElementException) {
            404 to JSONObject().put("error", "unknown $method $path")
        } catch (e: Exception) {
            Log.w(TAG, "request failed", e)
            500 to JSONObject().put("error", e.message ?: e.javaClass.simpleName)
        }
    }

    @Synchronized
    private fun pair(body: JSONObject): Pair<Int, JSONObject> {
        val now = System.currentTimeMillis()
        if (now < pairBlockedUntil) return 429 to JSONObject().put("error", "too many wrong codes, wait a minute")
        if (body.optString("code") != prefs.pairingCode) {
            failedPairs++
            if (failedPairs >= 5) {
                pairBlockedUntil = now + 60_000
                failedPairs = 0
            }
            return 403 to JSONObject().put("error", "wrong code")
        }
        failedPairs = 0
        val key = prefs.newApiKey()
        prefs.newPairingCode() // a code works once
        return 200 to JSONObject().put("key", key)
    }

    private fun sameKey(a: String, b: String): Boolean =
        MessageDigest.isEqual(a.toByteArray(Charsets.UTF_8), b.toByteArray(Charsets.UTF_8))

    companion object {
        const val PORT = 2424
        private const val TAG = "NookServer"
    }
}
