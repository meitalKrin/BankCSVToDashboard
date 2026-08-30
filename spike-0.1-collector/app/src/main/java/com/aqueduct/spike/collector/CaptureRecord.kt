package com.aqueduct.spike.collector

import android.app.Notification
import org.json.JSONArray
import org.json.JSONObject

/**
 * One captured notification, exactly as the system handed it over.
 *
 * Nothing here is parsed, normalised or interpreted. Spike 0.1 exists to find
 * out what the strings actually look like, so the strings are stored verbatim
 * and every judgement about them is deferred to Epic 2.
 */
data class CaptureRecord(
    val id: Long,
    val capturedAtUtc: Long,
    val packageName: String,
    val postedAtUtc: Long,
    val notificationKey: String?,
    val title: String?,
    val text: String?,
    val bigText: String?,
    val subText: String?,
    /** Every key present in the notification's extras bundle, not just the ones read above. */
    val extrasKeys: List<String>,
    val flags: Int,
) {

    val isGroupSummary: Boolean get() = flags and Notification.FLAG_GROUP_SUMMARY != 0

    /** One JSONL line. Field names are snake_case so the corpus reads cleanly in Python. */
    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("captured_at_utc", capturedAtUtc)
        put("package", packageName)
        put("posted_at_utc", postedAtUtc)
        put("notification_key", notificationKey ?: JSONObject.NULL)
        put("title", title ?: JSONObject.NULL)
        put("text", text ?: JSONObject.NULL)
        put("big_text", bigText ?: JSONObject.NULL)
        put("sub_text", subText ?: JSONObject.NULL)
        put("extras_keys", JSONArray(extrasKeys))
        put("flags", flags)
        put("flags_decoded", JSONArray(decodeFlags(flags)))
        put("group_summary", isGroupSummary)
    }

    companion object {

        /**
         * The flag names worth having in the corpus. FLAG_GROUP_SUMMARY is the
         * one that matters — a group summary is a rollup, not a payment — but
         * the others are free and we do not yet know which will turn out to
         * distinguish a real tap from an echo of one.
         */
        fun decodeFlags(flags: Int): List<String> = buildList {
            fun check(mask: Int, name: String) {
                if (flags and mask != 0) add(name)
            }
            check(Notification.FLAG_SHOW_LIGHTS, "FLAG_SHOW_LIGHTS")
            check(Notification.FLAG_ONGOING_EVENT, "FLAG_ONGOING_EVENT")
            check(Notification.FLAG_INSISTENT, "FLAG_INSISTENT")
            check(Notification.FLAG_ONLY_ALERT_ONCE, "FLAG_ONLY_ALERT_ONCE")
            check(Notification.FLAG_AUTO_CANCEL, "FLAG_AUTO_CANCEL")
            check(Notification.FLAG_NO_CLEAR, "FLAG_NO_CLEAR")
            check(Notification.FLAG_FOREGROUND_SERVICE, "FLAG_FOREGROUND_SERVICE")
            check(Notification.FLAG_HIGH_PRIORITY, "FLAG_HIGH_PRIORITY")
            check(Notification.FLAG_LOCAL_ONLY, "FLAG_LOCAL_ONLY")
            check(Notification.FLAG_GROUP_SUMMARY, "FLAG_GROUP_SUMMARY")
            check(FLAG_BUBBLE, "FLAG_BUBBLE")
        }

        /** Notification.FLAG_BUBBLE is API 29+; inline the constant to keep minSdk 26. */
        private const val FLAG_BUBBLE = 0x00001000
    }
}
