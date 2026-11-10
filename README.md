# QuickCastTool

> 一键扫码无线投屏工具：Windows 桌面托盘扫码 + Android 伴侣 App（下拉快捷磁贴 + Root 自动开启无线调试）+ scrcpy 自动拉起与高保真音频转发。

针对日常办公环境下**电脑插耳机看视频、听有声书、处理手机消息**的场景设计，彻底解决传统无线投屏每次都要手动进开发者选项、手动输入配对码与端口、手动敲 `scrcpy` 命令的痛点。

---

## ✨ 核心特性

- **一扫即连，全自动闭环**：手机下拉控制中心点击「扫码投屏」磁贴，对准电脑屏幕二维码即可自动开启无线调试 `5555` 端口、完成局域网握手并拉起 `scrcpy`。
- **多路径 Root 自适应提权**：兼容 Magisk、KernelSU、APatch 等主流 Root 方案（自动扫描 `su` 路径），无需进系统设置手动开开关或核对配对码。
- **独立极简 Android 伴侣端（`:companion`）**：
  - 仅专注 QR 码识别、Wi-Fi 连通性引导检测、Root 激活与 HTTP 握手，扫完自动退出后台零驻留耗电。
  - 内置底部实时屏显日志（支持长按复制到剪贴板）与 3 次自动容错重试机制。
- **Windows 托盘常驻服务（`pc-server/`）**：
  - PySide6 深色悬浮二维码卡片，底部支持 `[◀]` / `[▶]` 一键切换多网卡 IP。
  - 多线程 HTTP 服务（默认端口 `15555`）实时接收扫码握手信号，自动隐藏旧有 Chocolatey Shim 拦截与规避后台桌面隔离（绑定 `WinSta0\Default` 主桌面并自动置顶投屏窗）。
  - 预设办公体验参数：`--always-on-top`（置顶）、`--audio-source=output`（高保真系统音频转发到电脑耳机）、`1080P / 12Mbps` 均衡流畅画质、`--stay-awake`（防休眠断连）。
- **防窥熄屏与快捷键支持**：规避 Android 15/16 部分机型启动即熄屏导致首帧死锁的问题，窗口弹出后随时按 `Alt + O` 即可熄灭手机物理屏幕，`Alt + Shift + O` 随时重新点亮。

---

## 📁 项目结构

```text
QuickCastTool/
├── pc-server/                          # Windows 电脑端托盘服务端
│   ├── quick_cast_server.py            # 托盘应用、二维码悬浮窗、HTTP 握手与 scrcpy 调度
│   └── requirements.txt                # Python 依赖清单
├── companion/                          # Android 手机端伴侣模块 (com.quickcast.companion)
│   └── src/main/java/com/quickcast/companion/
│       ├── ScanActivity.kt             # 全屏 QR 扫码、Wi-Fi 状态引导、屏显日志与握手重试
│       ├── QuickCastTileService.kt     # Android 下拉快捷设置磁贴（「扫码投屏」）
│       ├── RootHelper.kt               # 多路径 su 自适应激活 5555 无线调试端口
│       └── NetworkHelper.kt            # Wi-Fi 硬件状态与连接校验
├── app/                                # 原 WADBS（无线调试开关）主应用模块
├── widget-factory/ & hidden-api-stub/  # WADBS 桌面小部件与隐藏 API 依赖模块
├── scripts/                            # WADBS 剪贴板自动连接脚本
├── 启动扫码投屏(静默托盘).vbs           # Windows 无黑框静默启动脚本
├── 启动扫码投屏(带日志).bat             # Windows 带控制台调试启动脚本
├── 一键创建桌面快捷方式.bat             # 自动在桌面创建「QuickCast扫码投屏」快捷方式
├── 查看连接日志.bat                     # 快速用记事本打开 pc-server/quick_cast.log
├── 使用指南.md                          # 详细操作、排查与快捷键速查手册
└── README.WADBS.md                     # 上游 WADBS 项目说明
```

---

## 🚀 快速开始

### 1. 环境要求

- **电脑端（Windows）**：
  - Python 3.10+
  - 已安装并配置好环境变量的 `adb` 与 `scrcpy`（推荐通过 Chocolatey 安装 `scrcpy`，服务端会自动定位真实二进制避开 Shim）
- **手机端（Android 11+ / SDK 30+）**：
  - 已获取 Root 权限（Magisk / KernelSU / APatch）
  - 与电脑处于同一局域网 Wi-Fi 下

### 2. 部署与启动电脑端

1. 克隆仓库并安装 Python 依赖：
   ```bash
   git clone https://github.com/deanzai/QuickCastTool.git
   cd QuickCastTool
   pip install -r pc-server/requirements.txt
   ```
2. 双击运行 **`启动扫码投屏(静默托盘).vbs`**（或先运行 **`一键创建桌面快捷方式.bat`** 生成桌面图标）。
3. 启动后任务栏托盘将常驻蓝色投屏图标，屏幕右下角会弹出当前局域网 IP 对应的二维码卡片。

### 3. 编译并安装手机端伴侣 APK

可以使用 Android Studio 打开本项目，或直接通过 Gradle 命令行编译 `:companion` 模块：

```bash
./gradlew :companion:assembleRelease
```

编译产物位于 `companion/build/outputs/apk/release/` 下，传输至手机安装后：
1. 打开应用并授予**相机权限**。
2. 在手机下拉控制中心 -> 编辑快捷开关 -> 将 **【扫码投屏】** 磁贴拖到常用位置。
3. 首次扫码时，在弹出的 Root 授权框中勾选**永久允许**即可。

> 更多图文细节与日常排查技巧请查阅 [使用指南.md](./使用指南.md)。

---

## ⌨️ 常用投屏快捷键（scrcpy 默认）

在电脑投屏窗口获得焦点时使用：

| 快捷键 | 功能 | 说明 |
| :--- | :--- | :--- |
| **`Alt + O`** | 熄灭手机屏幕 | 办公室防窥屏、省电不发热（不断开投屏与音频） |
| **`Alt + Shift + O`** | 唤醒手机屏幕 | 重新点亮手机物理屏幕 |
| **`Alt + P`** | 模拟电源键 | 锁屏 / 亮屏切换 |
| **`Alt + F`** / `F11` | 全屏切换 | 视频/网课全屏观看 |
| **`Alt + Up / Down`** | 手机音量调节 | 调整手机媒体输出音量 |
| **`Alt + B`** / 鼠标右键 | 返回上一级 | Android Back 键 |
| **`Alt + H`** / 鼠标中键 | 返回桌面 | Android Home 键 |
| **`Ctrl + V`** | 粘贴剪贴板 | 将电脑复制的文本粘贴到手机 |

---

## 🙏 致谢与许可

- 本项目基于开源项目 [**WADBS (Wireless ADB Switch)**](https://github.com/Smooth-E/wireless-adb-switch) 扩展开发，保留其原始 `:app`、`:widget-factory`、`:hidden-api-stub` 与 `scripts/` 模块（详见 [README.WADBS.md](./README.WADBS.md) 与 [readme.zh_cn.md](./readme.zh_cn.md)）。
- 投屏与音频转发核心能力由 [**scrcpy**](https://github.com/Genymobile/scrcpy) 强力驱动。
- 手机端扫码与 Root 能力使用了 [zxing-android-embedded](https://github.com/journeyapps/zxing-android-embedded) 与 [libsu](https://github.com/topjohnwu/libsu)。

本项目遵循 **GNU General Public License v3.0**（详见 [license](./license)）。
