package com.quickcast.companion

import android.content.Context
import android.net.wifi.WifiManager
import android.text.format.Formatter
import android.util.Log
import java.io.BufferedReader
import java.io.DataOutputStream
import java.io.InputStreamReader
import java.net.Inet4Address
import java.net.NetworkInterface

object RootHelper {
    private const val TAG = "QuickCast_Root"

    /**
     * 开启手机的 5555 无线调试端口
     * 返回 (是否成功, 详细日志说明)
     */
    fun enableWirelessAdb(): Pair<Boolean, String> {
        var process: Process? = null
        var os: DataOutputStream? = null

        // 兼容常见 Root 环境（Magisk / KernelSU / APatch / 原生）的 su 路径
        val suCandidates = listOf("su", "/system/bin/su", "/system/xbin/su", "/sbin/su", "/data/adb/ksu/bin/su", "/data/adb/ap/bin/su")

        for (suCmd in suCandidates) {
            try {
                Log.d(TAG, "尝试通过 $suCmd 申请 Root 权限...")
                process = Runtime.getRuntime().exec(suCmd)
                os = DataOutputStream(process.outputStream)

                // 执行无线调试激活指令
                os.writeBytes("setprop service.adb.tcp.port 5555\n")
                os.writeBytes("stop adbd\n")
                os.writeBytes("start adbd\n")
                os.writeBytes("settings put global adb_wifi_enabled 1\n")
                os.writeBytes("exit\n")
                os.flush()

                val exitCode = process.waitFor()
                val stderr = BufferedReader(InputStreamReader(process.errorStream)).readText().trim()
                val stdout = BufferedReader(InputStreamReader(process.inputStream)).readText().trim()

                if (exitCode == 0) {
                    Log.d(TAG, "su 执行成功: $stdout")
                    return Pair(true, "Root 授权成功，5555 端口已开启")
                } else {
                    val errMsg = if (stderr.isNotEmpty()) stderr else "退出码 $exitCode"
                    Log.e(TAG, "su 执行返回错误: $errMsg")
                    return Pair(false, "Root 执行失败: $errMsg")
                }
            } catch (e: Exception) {
                // 如果是找不到 su 可执行文件，尝试下一个候选路径
                Log.w(TAG, "$suCmd 无法执行: ${e.message}")
            } finally {
                try { os?.close() } catch (_: Exception) {}
                try { process?.destroy() } catch (_: Exception) {}
            }
        }

        // 如果全部候选路径均未找到
        return Pair(false, "未检测到 su 二进制文件（请确认 Magisk/KernelSU/APatch 已对本应用授权）")
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
