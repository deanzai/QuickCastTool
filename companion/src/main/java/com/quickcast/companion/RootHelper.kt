package com.quickcast.companion

import android.content.Context
import android.net.wifi.WifiManager
import android.text.format.Formatter
import android.util.Log
import java.io.BufferedReader
import java.io.DataOutputStream
import java.io.InputStreamReader
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket

object RootHelper {
    private const val TAG = "QuickCast_Root"
    private const val ADB_PORT = 5555

    /**
     * 通过本地回环探测 5555 端口是否已经处于监听状态
     */
    fun isLocalAdbPortOpen(timeoutMs: Int = 250): Boolean {
        return try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress("127.0.0.1", ADB_PORT), timeoutMs)
                true
            }
        } catch (_: Exception) {
            false
        }
    }

    /**
     * 开启手机的 5555 无线调试端口并等待端口真正就绪
     * 返回 (是否成功, 详细日志说明)
     */
    fun enableWirelessAdb(): Pair<Boolean, String> {
        // 1. 如果 5555 端口已经在监听，直接复用，避免无意义重启 adbd
        if (isLocalAdbPortOpen()) {
            Log.d(TAG, "5555 端口已在监听，跳过重启 adbd")
            return Pair(true, "5555 端口已就绪")
        }

        // 2. 兼容常见 Root 环境（Magisk / KernelSU / APatch / 原生）的 su 路径
        val suCandidates = listOf(
            "su",
            "/system/bin/su",
            "/system/xbin/su",
            "/sbin/su",
            "/data/adb/ksu/bin/su",
            "/data/adb/ap/bin/su"
        )

        var lastError = ""
        for (suCmd in suCandidates) {
            var process: Process? = null
            var os: DataOutputStream? = null
            try {
                Log.d(TAG, "尝试通过 $suCmd 申请 Root 权限...")
                process = Runtime.getRuntime().exec(suCmd)
                os = DataOutputStream(process.outputStream)

                // 先关闭可能占用并切换 adbd 端口的原生无线调试，再固定设置 5555 并重启 adbd
                os.writeBytes("settings put global adb_enabled 1\n")
                os.writeBytes("settings put global adb_wifi_enabled 0\n")
                os.writeBytes("setprop persist.adb.tcp.port $ADB_PORT\n")
                os.writeBytes("setprop service.adb.tcp.port $ADB_PORT\n")
                os.writeBytes("stop adbd\n")
                os.writeBytes("start adbd\n")
                os.writeBytes("exit\n")
                os.flush()

                val exitCode = process.waitFor()
                val stderr = BufferedReader(InputStreamReader(process.errorStream)).readText().trim()
                val stdout = BufferedReader(InputStreamReader(process.inputStream)).readText().trim()

                if (exitCode == 0) {
                    Log.d(TAG, "su ($suCmd) 执行成功: $stdout，等待 5555 端口就绪...")
                    // 轮询等待 adbd 拉起并绑定 5555 端口（最多等待 2.4 秒）
                    repeat(16) {
                        if (isLocalAdbPortOpen(200)) {
                            return Pair(true, "Root 授权成功，5555 端口已就绪")
                        }
                        try {
                            Thread.sleep(150)
                        } catch (_: InterruptedException) {}
                    }
                    return Pair(false, "已执行 Root 指令，但 5555 端口未监听（请检查系统开发者选项总开关是否关闭）")
                } else {
                    lastError = if (stderr.isNotEmpty()) stderr else "退出码 $exitCode"
                    Log.e(TAG, "$suCmd 执行返回错误: $lastError")
                    // su 存在但明确拒绝或执行失败时直接返回提示
                    return Pair(false, "Root 执行失败: $lastError")
                }
            } catch (e: Exception) {
                lastError = e.message ?: e.javaClass.simpleName
                Log.w(TAG, "$suCmd 无法执行: $lastError")
            } finally {
                try { os?.close() } catch (_: Exception) {}
                try { process?.destroy() } catch (_: Exception) {}
            }
        }

        return Pair(false, "未获得 Root 权限（$lastError）")
    }

    /**
     * 获取手机当前的局域网 IPv4 地址
     */
    fun getLocalIpAddress(context: Context): String {
        try {
            val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val ipInt = wifiManager?.connectionInfo?.ipAddress ?: 0
            if (ipInt != 0) {
                return Formatter.formatIpAddress(ipInt)
            }
        } catch (e: Exception) {
            Log.w(TAG, "WifiManager ip failed", e)
        }

        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val intf = interfaces.nextElement()
                val addrs = intf.inetAddresses
                while (addrs.hasMoreElements()) {
                    val addr = addrs.nextElement()
                    if (!addr.isLoopbackAddress && addr is Inet4Address) {
                        val host = addr.hostAddress ?: ""
                        if (!host.startsWith("127.") && !host.startsWith("169.254.")) {
                            return host
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "NetworkInterface failed", e)
        }

        return ""
    }
}
