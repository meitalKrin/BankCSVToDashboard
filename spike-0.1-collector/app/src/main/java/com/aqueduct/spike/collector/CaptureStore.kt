package com.aqueduct.spike.collector

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray

/**
 * Append-only local storage for captured notifications.
 *
 * Deliberately plain SQLite: this app is a throwaway. The only writes are
 * inserts; the only deletes are the two explicit purges the user triggers from
 * the UI (the privacy requirement in the spike spec — "capture everything" will
 * pick up WhatsApp and SMS, and that has to be removable without uninstalling,
 * because uninstalling takes the corpus with it).
 */
class CaptureStore(context: Context) : SQLiteOpenHelper(
    context.applicationContext,
    DB_NAME,
    null,
    DB_VERSION,
) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE $TABLE (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at_utc INTEGER NOT NULL,
                package_name TEXT NOT NULL,
                posted_at_utc INTEGER NOT NULL,
                notification_key TEXT,
                title TEXT,
                text TEXT,
                big_text TEXT,
                sub_text TEXT,
                extras_keys TEXT NOT NULL,
                flags INTEGER NOT NULL
            )
            """.trimIndent(),
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // There is no version 2. A throwaway does not get migrations.
    }

    fun insert(record: CaptureRecord) {
        val values = ContentValues().apply {
            put("captured_at_utc", record.capturedAtUtc)
            put("package_name", record.packageName)
            put("posted_at_utc", record.postedAtUtc)
            put("notification_key", record.notificationKey)
            put("title", record.title)
            put("text", record.text)
            put("big_text", record.bigText)
            put("sub_text", record.subText)
            put("extras_keys", JSONArray(record.extrasKeys).toString())
            put("flags", record.flags)
        }
        writableDatabase.insert(TABLE, null, values)
    }

    fun count(): Int =
        readableDatabase.rawQuery("SELECT COUNT(*) FROM $TABLE", null).use { cursor ->
            if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }

    /** Package name and count, most-captured first — the fastest way to spot Wallet. */
    fun countsByPackage(): List<Pair<String, Int>> =
        readableDatabase.rawQuery(
            "SELECT package_name, COUNT(*) AS n FROM $TABLE GROUP BY package_name ORDER BY n DESC",
            null,
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) add(cursor.getString(0) to cursor.getInt(1))
            }
        }

    /** The most recent capture, for the "it is alive" line on screen. */
    fun latest(): CaptureRecord? =
        readableDatabase.rawQuery("SELECT $COLUMNS FROM $TABLE ORDER BY id DESC LIMIT 1", null)
            .use { cursor -> if (cursor.moveToFirst()) cursor.toRecord() else null }

    /**
     * Streams every record in capture order so a long corpus is never held in
     * memory all at once. Returns how many were handed to [block].
     */
    fun forEachRecord(block: (CaptureRecord) -> Unit): Int {
        var seen = 0
        readableDatabase.rawQuery("SELECT $COLUMNS FROM $TABLE ORDER BY id ASC", null).use { cursor ->
            while (cursor.moveToNext()) {
                block(cursor.toRecord())
                seen++
            }
        }
        return seen
    }

    fun deleteAll(): Int = writableDatabase.delete(TABLE, null, null)

    /** Drops everything captured from a package that is not on the allowlist. */
    fun deleteNotIn(allowlist: Set<String>): Int {
        if (allowlist.isEmpty()) return deleteAll()
        val placeholders = allowlist.joinToString(",") { "?" }
        return writableDatabase.delete(
            TABLE,
            "package_name NOT IN ($placeholders)",
            allowlist.toTypedArray(),
        )
    }

    private fun Cursor.toRecord(): CaptureRecord = CaptureRecord(
        id = getLong(0),
        capturedAtUtc = getLong(1),
        packageName = getString(2),
        postedAtUtc = getLong(3),
        notificationKey = getStringOrNull(4),
        title = getStringOrNull(5),
        text = getStringOrNull(6),
        bigText = getStringOrNull(7),
        subText = getStringOrNull(8),
        extrasKeys = parseKeys(getString(9)),
        flags = getInt(10),
    )

    private fun Cursor.getStringOrNull(index: Int): String? =
        if (isNull(index)) null else getString(index)

    private fun parseKeys(json: String): List<String> {
        val array = JSONArray(json)
        return buildList {
            for (i in 0 until array.length()) add(array.optString(i))
        }
    }

    private companion object {
        const val DB_NAME = "captures.db"
        const val DB_VERSION = 1
        const val TABLE = "capture"
        const val COLUMNS =
            "id, captured_at_utc, package_name, posted_at_utc, notification_key, " +
                "title, text, big_text, sub_text, extras_keys, flags"
    }
}
