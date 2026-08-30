package com.aqueduct.spike.collector

import android.app.Notification
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.util.concurrent.Executors

/**
 * Records every notification that passes the filter, verbatim.
 *
 * What it deliberately does not do: parse, normalise, deduplicate, drop group
 * summaries, or decide what anything means. Group summaries are captured *with*
 * their flag so we can see how Wallet groups its notifications — dropping them
 * is Epic 2's job, and doing it here would hide the evidence.
 */
class CollectorService : NotificationListenerService() {

    private val writer = Executors.newSingleThreadExecutor()
    private lateinit var store: CaptureStore
    private lateinit var filter: CaptureFilter

    override fun onCreate() {
        super.onCreate()
        store = CaptureStore(this)
        filter = CaptureFilter(this)
    }

    override fun onDestroy() {
        writer.shutdown()
        super.onDestroy()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val notification = sbn?.notification ?: return
        if (!filter.shouldCapture(sbn.packageName)) return

        val extras: Bundle = notification.extras ?: Bundle.EMPTY
        val record = CaptureRecord(
            id = 0,
            capturedAtUtc = System.currentTimeMillis(),
            packageName = sbn.packageName,
            postedAtUtc = sbn.postTime,
            notificationKey = sbn.key,
            title = extras.charSequenceToStringOrNull(Notification.EXTRA_TITLE),
            text = extras.charSequenceToStringOrNull(Notification.EXTRA_TEXT),
            bigText = extras.charSequenceToStringOrNull(Notification.EXTRA_BIG_TEXT),
            subText = extras.charSequenceToStringOrNull(Notification.EXTRA_SUB_TEXT),
            extrasKeys = extras.keySet().sorted(),
            flags = notification.flags,
        )

        // Off the binder thread: the system is waiting on this callback.
        writer.execute {
            try {
                store.insert(record)
            } catch (e: Exception) {
                // A capture we cannot store is a capture we have lost, but
                // taking the listener down with it would lose all the rest too.
                Log.e(TAG, "failed to store capture from ${record.packageName}", e)
            }
        }
    }

    /**
     * Extras values are CharSequence, not String, and are sometimes a
     * SpannableString. Read them as CharSequence and convert, or Wallet's
     * styled text comes back null.
     */
    private fun Bundle.charSequenceToStringOrNull(key: String): String? =
        getCharSequence(key)?.toString()

    private companion object {
        const val TAG = "CollectorService"
    }
}
