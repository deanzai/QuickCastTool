package com.quickcast.companion

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import com.journeyapps.barcodescanner.CompoundBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory
import com.quickcast.companion.databinding.ActivityScanBinding
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import kotlin.concurrent.thread

class ScanActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "QuickCast_Scan"
    }

    private lateinit var binding: ActivityScanBinding
    private lateinit var barcodeView: CompoundBarcodeView
    private var isTorchOn = false
    private var isProcessing = false
    private var wifiDialog: AlertDialog? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val logBuilder = StringBuilder()

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        if (isGranted) {
            appendLog("已获取相机权限，启动扫码引擎...")
            initAndStartScanner()
            checkWifiStatus(isExplicitTrigger = false)
        } else {
            appendLog("错误: 相机权限被拒绝，无法扫码")
            Toast.makeText(this, R.string.need_camera, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityScanBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.tvTitle.text = "${getString(R.string.tile_name)} v${BuildConfig.VERSION_NAME}"
        barcodeView = binding.barcodeScanner

        // 配置手电筒
        binding.btnTorch.setOnClickListener {
            if (isTorchOn) {
                barcodeView.setTorchOff()
                isTorchOn = false
            } else {
                barcodeView.setTorchOn()
                isTorchOn = true
            }
        }

        // 重新扫描按钮
        binding.btnRetry.setOnClickListener {
            resumeScanningState()
            appendLog("重置扫码，请重新对准二维码...")
            checkWifiStatus(isExplicitTrigger = false)
        }

        // 长按日志区域复制全部日志
        binding.tvDetailLog.setOnLongClickListener {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("QuickCast Logs", logBuilder.toString()))
            Toast.makeText(this, "日志已复制到剪贴板", Toast.LENGTH_SHORT).show()
            true
        }

        appendLog("应用启动成功 (v${BuildConfig.VERSION_NAME} / #${BuildConfig.VERSION_CODE})，检查相机权限...")
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            initAndStartScanner()
            checkWifiStatus(isExplicitTrigger = false)
        } else {
            requestPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun appendLog(msg: String) {
        Log.i(TAG, msg)
        logBuilder.append(msg).append("\n")
        runOnUiThread {
            binding.tvDetailLog.text = logBuilder.toString()
            binding.scrollLog.post {
                binding.scrollLog.fullScroll(View.FOCUS_DOWN)
            }
        }
    }

    private fun initAndStartScanner() {
        try {
            // 显式指定只解码 QR_CODE，极大提高识别速度与准确率
            val formats = listOf(BarcodeFormat.QR_CODE)
            barcodeView.barcodeView.decoderFactory = DefaultDecoderFactory(formats)
            barcodeView.initializeFromIntent(intent)
            barcodeView.setStatusText("") // 清空自带提示

            startScanning()
            barcodeView.resume()
            appendLog("扫码相机已就绪，对准屏幕即可")
        } catch (e: Exception) {
            appendLog("初始化扫码引擎异常: ${e.message}")
        }
    }

    private fun startScanning() {
        barcodeView.decodeContinuous(object : BarcodeCallback {
            override fun barcodeResult(result: BarcodeResult?) {
                val rawText = result?.text ?: return
                if (isProcessing) return

                if (rawText.startsWith("http://") || rawText.startsWith("https://") || rawText.startsWith("quickcast://")) {
                    // 当扫码时，如果设备 Wi-Fi 未开启或未连接，进行拦截并弹出对话框提示手动连接 Wi-Fi
                    if (!checkWifiStatus(isExplicitTrigger = true)) {
                        isProcessing = true
                        barcodeView.pause()
                        return
                    }

                    isProcessing = true
                    barcodeView.pause()
                    vibrate()
                    appendLog(">>> 成功扫到二维码: $rawText")
                    handleScanResult(rawText)
                } else {
                    appendLog("扫描到未知格式内容: $rawText (忽略)")
                }
            }
        })
    }

    /**
     * 检查 Wi-Fi 开启和连接状态，如果异常则弹出引导弹窗
     * @param isExplicitTrigger 是否是在扫码触发时进行拦截
     * @return true 表示已就绪可以进行网络通信，false 表示需要等待用户开启或连接 Wi-Fi
     */
    private fun checkWifiStatus(isExplicitTrigger: Boolean = false): Boolean {
        val isEnabled = NetworkHelper.isWifiEnabled(this)
        val isConnected = NetworkHelper.isWifiConnected(this)

        if (isEnabled && isConnected) {
            if (wifiDialog?.isShowing == true) {
                wifiDialog?.dismiss()
            }
            return true
        }

        // 如果用户已开启 Wi-Fi 且已有局域网有效 IP（如热点、以太网等），允许通信
        if (isEnabled && !isConnected) {
            val localIp = RootHelper.getLocalIpAddress(this)
            if (localIp.isNotEmpty()) {
                return true
            }
        }

        // 若弹窗已经在展示中，避免重复弹窗
        if (wifiDialog?.isShowing == true) {
            return false
        }

        val titleRes = if (!isEnabled) R.string.wifi_disabled_title else R.string.wifi_not_connected_title
        val msgRes = if (!isEnabled) R.string.wifi_disabled_message else R.string.wifi_not_connected_message

        appendLog(if (!isEnabled) "提示: 设备 Wi-Fi 未开启，请手动开启并连接" else "提示: 设备尚未连接 Wi-Fi 局域网")

        wifiDialog = MaterialAlertDialogBuilder(this)
            .setTitle(titleRes)
            .setMessage(msgRes)
            .setCancelable(true)
            .setPositiveButton(R.string.action_open_wifi) { dialog, _ ->
                dialog.dismiss()
                openWifiSettings()
            }
            .setNegativeButton(R.string.action_cancel) { dialog, _ ->
                dialog.dismiss()
                if (isExplicitTrigger) {
                    resumeScanningState("已取消 Wi-Fi 设置，请重新扫码")
                }
            }
            .setOnCancelListener {
                if (isExplicitTrigger) {
                    resumeScanningState("请连接 Wi-Fi 后重新扫码")
                }
            }
            .show()

        return false
    }

    /**
     * 重置扫码状态并恢复相机取景
     */
    private fun resumeScanningState(statusText: String? = null) {
        runOnUiThread {
            isProcessing = false
            binding.progressBar.visibility = View.GONE
            binding.layoutRetry.visibility = View.GONE
            binding.tvStatus.text = statusText ?: getString(R.string.scan_hint)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED
            ) {
                barcodeView.resume()
            }
        }
    }

    /**
     * 打开系统 Wi-Fi 快捷操作面板或设置界面
     */
    private fun openWifiSettings() {
        var opened = false
        // Android 10 (Q) 及以上系统支持快捷浮层面板
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val panelIntent = Intent(Settings.Panel.ACTION_WIFI)
                startActivity(panelIntent)
                opened = true
            } catch (e: Exception) {
                Log.w(TAG, "启动 Settings.Panel.ACTION_WIFI 异常: ${e.message}")
            }
        }

        if (!opened) {
            try {
                val settingsIntent = Intent(Settings.ACTION_WIFI_SETTINGS)
                startActivity(settingsIntent)
            } catch (e: Exception) {
                Log.e(TAG, "启动 Settings.ACTION_WIFI_SETTINGS 异常", e)
                Toast.makeText(this, "无法自动打开设置，请手动开启 Wi-Fi", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun handleScanResult(rawUrl: String) {
        runOnUiThread {
            binding.progressBar.visibility = View.VISIBLE
            binding.tvStatus.text = getString(R.string.connecting)
        }

        thread {
            // 步骤 1: 请求 Root 开启无线调试
            appendLog("[1/3] 正在申请 Root 权限并激活 5555 端口...")
            val (rootOk, rootMsg) = RootHelper.enableWirelessAdb()
            appendLog("[1/3] $rootMsg")

            // 步骤 2: 获取手机局域网 IP
            val localIp = RootHelper.getLocalIpAddress(this)
            appendLog("[2/3] 获取本机 IP: ${if (localIp.isNotEmpty()) localIp else "未知(由电脑自动识别)"}")

            // 步骤 3: 构建请求目标 URL（附加 Root 与 5555 端口自检结果）
            val targetUrlStr = if (rawUrl.startsWith("quickcast://")) {
                "http://" + rawUrl.removePrefix("quickcast://")
            } else {
                rawUrl
            }

            val separator = if (targetUrlStr.contains("?")) "&" else "?"
            val queryParts = mutableListOf<String>()
            if (localIp.isNotEmpty()) {
                queryParts.add("ip=${URLEncoder.encode(localIp, "UTF-8")}")
            }
            queryParts.add("adb_ok=${if (rootOk) "1" else "0"}")
            queryParts.add("adb_msg=${URLEncoder.encode(rootMsg, "UTF-8")}")
            val finalUrl = "$targetUrlStr$separator${queryParts.joinToString("&")}"

            appendLog("[3/3] 正在向电脑发送握手请求: $finalUrl")

            var success = false
            var errorMsg = ""
            var responseCode = -1

            // 增加重试机制（最多尝试 3 次，避免局域网瞬间抖动导致的单次超时）
            val maxRetries = 3
            for (attempt in 1..maxRetries) {
                var conn: HttpURLConnection? = null
                try {
                    if (attempt > 1) {
                        appendLog("第 ${attempt} 次尝试握手...")
                    }
                    val url = URL(finalUrl)
                    conn = url.openConnection() as HttpURLConnection
                    conn.connectTimeout = 6000
                    conn.readTimeout = 6000
                    conn.requestMethod = "GET"
                    conn.setRequestProperty("Connection", "close")
                    responseCode = conn.responseCode
                    if (responseCode in 200..299) {
                        success = true
                        break
                    } else {
                        errorMsg = "HTTP $responseCode"
                    }
                } catch (e: Exception) {
                    errorMsg = "${e.javaClass.simpleName}: ${e.message}"
                    Log.w(TAG, "握手尝试 $attempt 失败: $errorMsg")
                } finally {
                    try { conn?.disconnect() } catch (_: Exception) {}
                }

                if (!success && attempt < maxRetries) {
                    try { Thread.sleep(600) } catch (_: Exception) {}
                }
            }

            runOnUiThread {
                if (success && rootOk) {
                    appendLog(">>> 电脑握手成功 (HTTP $responseCode)！正在拉起投屏...")
                    binding.tvStatus.text = "投屏已拉起！"
                    Toast.makeText(this, "投屏已连接！", Toast.LENGTH_SHORT).show()
                    mainHandler.postDelayed({
                        finishAndRemoveTask()
                    }, 800)
                } else if (success && !rootOk) {
                    appendLog(">>> 已通知电脑，但手机端 5555 端口自检未就绪")
                    appendLog("排查建议: 请打开 Magisk/KernelSU/APatch 确认已授予「扫码投屏伴侣」Root 权限，或手动开启开发者选项")
                    binding.tvStatus.text = "5555 端口未开启"
                    binding.progressBar.visibility = View.GONE
                    binding.layoutRetry.visibility = View.VISIBLE
                } else {
                    val failText = if (errorMsg.isNotEmpty()) errorMsg else "HTTP 错误码 $responseCode"
                    appendLog(">>> 握手失败: $failText")
                    appendLog("排查建议: 请确认手机和电脑连在同一 Wi-Fi，且电脑端防火墙未拦截")
                    binding.tvStatus.text = "连接失败"
                    binding.progressBar.visibility = View.GONE
                    binding.layoutRetry.visibility = View.VISIBLE
                }
            }
        }
    }

    private fun vibrate() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vibratorManager = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                vibratorManager?.defaultVibrator?.vibrate(
                    VibrationEffect.createOneShot(60, VibrationEffect.DEFAULT_AMPLITUDE)
                )
            } else {
                @Suppress("DEPRECATION")
                val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
                @Suppress("DEPRECATION")
                vibrator?.vibrate(60)
            }
        } catch (_: Exception) {}
    }

    override fun onResume() {
        super.onResume()
        val hasCameraPermission = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

        val isEnabled = NetworkHelper.isWifiEnabled(this)
        val isConnected = NetworkHelper.isWifiConnected(this)

        if (isEnabled && isConnected) {
            if (wifiDialog?.isShowing == true) {
                wifiDialog?.dismiss()
            }
            if (isProcessing) {
                resumeScanningState("Wi-Fi 已就绪，请对准电脑屏幕二维码")
                appendLog("Wi-Fi 已连接，恢复扫码取景")
            } else if (hasCameraPermission) {
                barcodeView.resume()
            }
        } else {
            if (!isEnabled && hasCameraPermission) {
                checkWifiStatus(isExplicitTrigger = false)
            }
            if (hasCameraPermission && !isProcessing) {
                barcodeView.resume()
            }
        }
    }

    override fun onPause() {
        super.onPause()
        barcodeView.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        wifiDialog?.dismiss()
        wifiDialog = null
    }
}
