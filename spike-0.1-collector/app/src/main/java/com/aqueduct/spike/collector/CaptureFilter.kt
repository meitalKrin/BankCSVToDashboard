package com.aqueduct.spike.collector

import android.content.Context

/**
 * Which packages get captured.
 *
 * The default is a short allowlist of Wallet candidates plus Gmail. None of
 * those names is confirmed — confirming the real one is the point of the spike,
 * which is why the allowlist is editable and why "capture everything" exists at
 * all. Read fresh on every notification: the listener process outlives the UI,
 * and a toggle that only takes effect after a restart is a toggle that loses
 * captures.
 */
class CaptureFilter(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences("capture_filter", Context.MODE_PRIVATE)

    var captureEverything: Boolean
        get() = prefs.getBoolean(KEY_CAPTURE_EVERYTHING, false)
        set(value) = prefs.edit().putBoolean(KEY_CAPTURE_EVERYTHING, value).apply()

    /** The allowlist as the user last saved it, one package per line. */
    var allowlistText: String
        get() = prefs.getString(KEY_ALLOWLIST, null) ?: DEFAULT_ALLOWLIST.joinToString("\n")
        set(value) = prefs.edit().putString(KEY_ALLOWLIST, value).apply()

    val allowlist: Set<String>
        get() = allowlistText.lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .toSet()

    fun shouldCapture(packageName: String): Boolean =
        captureEverything || packageName in allowlist

    companion object {
        private const val KEY_CAPTURE_EVERYTHING = "capture_everything"
        private const val KEY_ALLOWLIST = "allowlist"

        /**
         * Candidates, not facts. `walletnfcrel` is the current Google Wallet
         * package, `apps.wallet` the older Google Pay one, and `gms` is here
         * because tap notifications have historically been posted by Play
         * services on some devices. Spike 0.1 replaces this guess with an
         * observation.
         */
        val DEFAULT_ALLOWLIST = listOf(
            "com.google.android.apps.walletnfcrel",
            "com.google.android.apps.wallet",
            "com.google.android.gms",
            "com.google.android.gm",
        )
    }
}
