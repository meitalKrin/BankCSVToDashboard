package com.aqueduct.spike.collector

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import com.aqueduct.spike.collector.databinding.ActivityMainBinding
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/**
 * The whole UI: onboarding, a live count, the capture filter, and export.
 *
 * There is no list of captured text on this screen on purpose — reading the
 * corpus is a job for a laptop and the exported JSONL, not for scrolling a
 * phone. What the screen has to prove is that capture is alive and which
 * package the captures are coming from.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var store: CaptureStore
    private lateinit var filter: CaptureFilter

    private val io = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    private val timestamps = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)

    private val refresh = object : Runnable {
        override fun run() {
            refreshCounts()
            ui.postDelayed(this, REFRESH_MS)
        }
    }

    /**
     * Storage Access Framework: the user picks the destination, so the app needs
     * no storage permission at all.
     */
    private val createDocument =
        registerForActivityResult(ActivityResultContracts.CreateDocument(EXPORT_MIME)) { uri ->
            if (uri != null) writeExport(uri)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        store = CaptureStore(this)
        filter = CaptureFilter(this)

        binding.notificationAccessButton.setOnClickListener {
            startActivitySafely(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        binding.batteryButton.setOnClickListener { requestBatteryExemption() }

        binding.captureEverything.setOnCheckedChangeListener { _, checked ->
            filter.captureEverything = checked
        }

        binding.saveAllowlist.setOnClickListener {
            filter.allowlistText = binding.allowlist.text.toString()
            binding.allowlist.setText(filter.allowlistText)
            toast(getString(R.string.allowlist_saved))
        }

        binding.export.setOnClickListener { startExport() }
        binding.purgeNonAllowlisted.setOnClickListener {
            confirmDelete(R.string.purge_non_allowlisted_message) { store.deleteNotIn(filter.allowlist) }
        }
        binding.deleteAll.setOnClickListener {
            confirmDelete(R.string.delete_all_message) { store.deleteAll() }
        }
    }

    override fun onResume() {
        super.onResume()
        binding.captureEverything.isChecked = filter.captureEverything
        // Do not stomp on an edit in progress.
        if (!binding.allowlist.hasFocus()) binding.allowlist.setText(filter.allowlistText)
        refreshPermissionStatus()
        ui.post(refresh)
    }

    override fun onPause() {
        ui.removeCallbacks(refresh)
        super.onPause()
    }

    // --- status -----------------------------------------------------------

    private fun refreshPermissionStatus() {
        val access = if (isNotificationAccessGranted()) R.string.granted else R.string.not_granted
        binding.notificationAccessStatus.text =
            getString(R.string.notification_access) + ": " + getString(access)

        val exempt = if (isIgnoringBatteryOptimizations()) R.string.exempt else R.string.not_exempt
        binding.batteryStatus.text =
            getString(R.string.battery_exemption) + ": " + getString(exempt)
    }

    private fun isNotificationAccessGranted(): Boolean =
        packageName in NotificationManagerCompat.getEnabledListenerPackages(this)

    private fun isIgnoringBatteryOptimizations(): Boolean {
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        return power.isIgnoringBatteryOptimizations(packageName)
    }

    @SuppressLint("BatteryLife")
    private fun requestBatteryExemption() {
        if (isIgnoringBatteryOptimizations()) {
            startActivitySafely(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            return
        }
        val request = Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:$packageName"),
        )
        if (!startActivitySafely(request)) {
            startActivitySafely(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun startActivitySafely(intent: Intent): Boolean = try {
        startActivity(intent)
        true
    } catch (notInstalled: android.content.ActivityNotFoundException) {
        false
    }

    private fun refreshCounts() {
        io.execute {
            val total = store.count()
            val latest = store.latest()
            val byPackage = store.countsByPackage()
            ui.post {
                if (isFinishing || isDestroyed) return@post
                binding.count.text = getString(R.string.captured_count, total)
                binding.lastCapture.text = latest?.let {
                    getString(
                        R.string.last_capture,
                        "${it.packageName} @ ${timestamps.format(Date(it.postedAtUtc))}",
                    )
                } ?: getString(R.string.last_capture_none)
                binding.perPackage.text = byPackage.joinToString("\n") { (name, n) -> "$n  $name" }
            }
        }
    }

    // --- export -----------------------------------------------------------

    private fun startExport() {
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        createDocument.launch("aqueduct-capture-$stamp.jsonl")
    }

    private fun writeExport(uri: Uri) {
        io.execute {
            val result: Result<Int> = runCatching {
                val out = contentResolver.openOutputStream(uri)
                    ?: error("could not open the chosen file for writing")
                out.use { stream ->
                    stream.bufferedWriter(Charsets.UTF_8).use { writer ->
                        // The reported number is what was actually written, not
                        // a count taken separately and hoped to still match.
                        store.forEachRecord { record ->
                            writer.write(record.toJson().toString())
                            writer.write("\n")
                        }
                    }
                }
            }
            ui.post {
                result
                    .onSuccess { written ->
                        toast(
                            if (written == 0) getString(R.string.export_empty)
                            else getString(R.string.export_ok, written),
                        )
                    }
                    .onFailure { toast(getString(R.string.export_failed, it.message ?: it.javaClass.simpleName)) }
            }
        }
    }

    // --- purge ------------------------------------------------------------

    private fun confirmDelete(messageRes: Int, delete: () -> Int) {
        AlertDialog.Builder(this)
            .setTitle(R.string.purge_confirm_title)
            .setMessage(messageRes)
            .setNegativeButton(R.string.cancel, null)
            .setPositiveButton(R.string.delete) { _, _ ->
                io.execute {
                    val deleted = delete()
                    ui.post {
                        toast(getString(R.string.deleted_count, deleted))
                        refreshCounts()
                    }
                }
            }
            .show()
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    private companion object {
        const val REFRESH_MS = 1_000L
        const val EXPORT_MIME = "application/json"
    }
}
