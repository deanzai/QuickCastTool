# -*- coding: utf-8 -*-
"""
QuickCast PC Server
Windows 托盘 + 二维码悬浮窗 + 局域网握手服务 + scrcpy 自动化投屏
带完整文件日志与可视化诊断
"""

import sys
import os
import re
import time
import shutil
import socket
import subprocess
import threading
import logging
from datetime import datetime
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import qrcode
from PIL import Image, ImageDraw

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QPoint
from PySide6.QtGui import QIcon, QPixmap, QImage, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QSystemTrayIcon, QMenu, QFrame, QGraphicsDropShadowEffect
)

SERVER_PORT = 15555
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quick_cast.log")

# 配置全局日志（pythonw 无控制台时 sys.stdout 为 None，仅保留文件日志）
_log_handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stdout is not None:
    _log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_log_handlers
)
logger = logging.getLogger("QuickCast")


def _decode_bytes(data):
    """安全解码子进程字节输出，兼容 UTF-8 与中文 Windows GBK，绝不抛出解码或 NoneType 异常"""
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _is_adb_server_running():
    """检查本地 ADB 守护进程 (5037 端口) 是否已在监听"""
    try:
        with socket.create_connection(("127.0.0.1", 5037), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_adb_server():
    """确保 adb server 在脱离任何管道句柄的独立后台启动，防止子进程继承 stdout/stderr 导致死锁"""
    if _is_adb_server_running():
        return
    try:
        flags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        subprocess.run(
            ["adb", "start-server"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=6,
            creationflags=flags
        )
    except Exception as e:
        logger.warning(f"独立启动 ADB server 提示: {e}")


def run_adb_command(args, timeout=8):
    """安全执行 adb 命令，避免管道句柄继承死锁和字符编码导致的 NoneType + str 异常"""
    ensure_adb_server()
    proc = subprocess.Popen(
        ["adb"] + args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    try:
        raw_out, raw_err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        raise
    out_str = _decode_bytes(raw_out).strip()
    err_str = _decode_bytes(raw_err).strip()
    combined = "\n".join(part for part in (out_str, err_str) if part)
    return proc.returncode, combined


def get_all_lan_ips():
    """获取所有有效的局域网 IPv4 地址"""
    ips = []
    # 优先使用 socket
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                if ip not in ips:
                    ips.append(ip)
    except Exception as e:
        logger.warning(f"Socket 获取 IP 失败: {e}")

    # ipconfig 补充检查
    try:
        output = subprocess.check_output("ipconfig", encoding="gbk", errors="ignore")
        for match in re.finditer(r"IPv4.*?:?\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", output):
            ip = match.group(1)
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                if ip not in ips:
                    ips.append(ip)
    except Exception as e:
        logger.warning(f"ipconfig 获取 IP 失败: {e}")

    # 排序：192.168.x > 10.x > 172.x > 其余
    def priority(ip):
        if ip.startswith("192.168."):
            return 1
        if ip.startswith("10."):
            return 2
        if ip.startswith("172."):
            return 3
        return 4

    ips.sort(key=priority)
    return ips if ips else ["127.0.0.1"]


def find_scrcpy_executable():
    """定位真实的 scrcpy.exe 路径，避开 Chocolatey Shim 拦截 GUI 窗口"""
    which_path = shutil.which("scrcpy")
    if which_path:
        # Chocolatey 的 shim 通常位于 ...\chocolatey\bin\scrcpy.exe，真实二进制位于 ..\lib\scrcpy\tools\scrcpy.exe
        norm = os.path.normpath(which_path)
        parts = norm.lower().split(os.sep)
        if "chocolatey" in parts and len(parts) >= 2 and parts[-2] == "bin":
            choco_root = os.path.dirname(os.path.dirname(norm))
            real_choco = os.path.join(choco_root, "lib", "scrcpy", "tools", "scrcpy.exe")
            if os.path.exists(real_choco):
                return real_choco
        return norm

    default_choco = r"C:\ProgramData\chocolatey\lib\scrcpy\tools\scrcpy.exe"
    if os.path.exists(default_choco):
        return default_choco

    return "scrcpy"


def create_tray_icon_image():
    """生成托盘图标"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_color = (30, 144, 255, 255)
    draw.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, fill=bg_color)
    draw.rounded_rectangle([14, 16, size - 15, size - 16], radius=6, outline=(255, 255, 255, 255), width=3)
    draw.line([24, size - 10, size - 25, size - 10], fill=(255, 255, 255, 255), width=3)

    return img


class HttpBridge(QObject):
    """跨线程传递 HTTP 手机连接信号与状态更新"""
    connect_signal = Signal(str, str)  # phone_ip, adb_note
    log_signal = Signal(str, str)      # text, color


class QuickCastRequestHandler(BaseHTTPRequestHandler):
    bridge: HttpBridge = None

    def log_message(self, format, *args):
        logger.info(f"HTTP: {self.client_address[0]} - " + (format % args))

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        parsed = urlparse(self.path)
        client_ip = self.client_address[0]
        logger.info(f"收到 HTTP 请求: {self.command} {self.path} 来自 {client_ip}")

        if parsed.path.rstrip("/") == "/connect":
            params = parse_qs(parsed.query)
            phone_ip = params.get("ip", [client_ip])[0] or client_ip
            adb_ok = params.get("adb_ok", [""])[0]
            adb_msg = params.get("adb_msg", [""])[0]

            adb_note = ""
            if adb_ok == "0":
                adb_note = adb_msg or "手机端 Root 开启 5555 端口失败"
                logger.warning(f"手机端上报 Root/调试状态异常: {adb_note}")
            elif adb_ok == "1":
                logger.info(f"手机端已确认 5555 端口就绪: {adb_msg}")

            logger.info(f"识别到待投屏手机 IP: {phone_ip}")
            if self.bridge:
                self.bridge.log_signal.emit(f"收到握手: {phone_ip}", "#ffa502")
                self.bridge.connect_signal.emit(phone_ip, adb_note)

            # 返回给手机端响应页面
            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>QuickCast 已连接</title>
    <style>
        body {{
            background: #121212;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 90vh;
            margin: 0;
            text-align: center;
        }}
        .card {{
            background: #1e1e1e;
            padding: 30px;
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            max-width: 320px;
        }}
        .check {{
            font-size: 50px;
            color: #00e676;
            margin-bottom: 10px;
        }}
        h2 {{ margin: 0 0 10px; font-size: 20px; }}
        p {{ color: #aaa; font-size: 14px; margin: 0; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="check">✓</div>
        <h2>扫码成功，投屏已拉起</h2>
        <p>设备 IP: {phone_ip}<br>按 Alt+O 可随时熄灭手机屏幕，电脑耳机可直接听音看视频。</p>
    </div>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif parsed.path.rstrip("/") == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"pong")
        else:
            self.send_response(404)
            self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HttpServerThread(threading.Thread):
    def __init__(self, port, bridge):
        super().__init__(daemon=True)
        self.port = port
        self.bridge = bridge
        self.server = None

    def run(self):
        QuickCastRequestHandler.bridge = self.bridge
        try:
            self.server = ThreadedHTTPServer(("0.0.0.0", self.port), QuickCastRequestHandler)
            logger.info(f"HTTP 服务已成功在 0.0.0.0:{self.port} 监听就绪")
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP 服务监听异常: {e}")

    def stop(self):
        if self.server:
            self.server.shutdown()


class QRCodeCard(QWidget):
    """现代卡片风格二维码悬浮窗口"""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.ips = get_all_lan_ips()
        self.current_ip_index = 0

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(340, 480)

        self.drag_position = QPoint()
        self.init_ui()
        self.update_qr()

    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(12, 12, 12, 12)

        self.card = QFrame()
        self.card.setStyleSheet("""
            QFrame {
                background-color: #1e1e24;
                border-radius: 16px;
                border: 1px solid #33333f;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 6)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 18, 20, 20)
        card_layout.setSpacing(12)

        # 1. 顶部标题栏
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("QuickCast 扫码投屏")
        self.title_label.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold; border: none;")

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888899;
                font-size: 13px;
                border: none;
                border-radius: 12px;
            }
            QPushButton:hover {
                background: #ff4757;
                color: white;
            }
        """)
        self.btn_close.clicked.connect(self.hide)

        top_bar.addWidget(self.title_label)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_close)
        card_layout.addLayout(top_bar)

        # 2. 中间二维码
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(230, 230)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet("""
            QLabel {
                background-color: #ffffff;
                border-radius: 12px;
                padding: 6px;
                border: none;
            }
        """)
        qr_container = QHBoxLayout()
        qr_container.addStretch()
        qr_container.addWidget(self.qr_label)
        qr_container.addStretch()
        card_layout.addLayout(qr_container)

        # 3. 网卡切换控制条
        net_layout = QHBoxLayout()
        net_layout.setSpacing(8)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(28, 28)
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.setStyleSheet(self._button_style())
        self.btn_prev.clicked.connect(self.prev_ip)

        self.ip_label = QLabel()
        self.ip_label.setAlignment(Qt.AlignCenter)
        self.ip_label.setStyleSheet("color: #00d2d3; font-size: 13px; font-weight: 500; border: none;")

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(28, 28)
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setStyleSheet(self._button_style())
        self.btn_next.clicked.connect(self.next_ip)

        net_layout.addWidget(self.btn_prev)
        net_layout.addWidget(self.ip_label, 1)
        net_layout.addWidget(self.btn_next)
        card_layout.addLayout(net_layout)

        # 4. 底部状态指示
        self.status_label = QLabel("等待手机扫码...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #a4b0be; font-size: 12px; border: none;")
        card_layout.addWidget(self.status_label)

        # 5. 底部快捷日志按钮
        bottom_tools = QHBoxLayout()
        self.btn_view_log = QPushButton("📋 打开日志")
        self.btn_view_log.setCursor(Qt.PointingHandCursor)
        self.btn_view_log.setStyleSheet("""
            QPushButton {
                background-color: #2b2b36;
                color: #8888aa;
                border-radius: 4px;
                border: 1px solid #3c3c4c;
                font-size: 11px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #3b3b4c;
            }
        """)
        self.btn_view_log.clicked.connect(self.parent_app.open_log_file)

        bottom_tools.addStretch()
        bottom_tools.addWidget(self.btn_view_log)
        bottom_tools.addStretch()
        card_layout.addLayout(bottom_tools)

        outer_layout.addWidget(self.card)

    def _button_style(self):
        return """
            QPushButton {
                background-color: #2f3542;
                color: #ffffff;
                border-radius: 6px;
                border: 1px solid #57606f;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1e90ff;
                border-color: #1e90ff;
            }
            QPushButton:pressed {
                background-color: #0984e3;
            }
        """

    def refresh_ips(self):
        self.ips = get_all_lan_ips()
        if self.current_ip_index >= len(self.ips):
            self.current_ip_index = 0
        self.update_qr()
        logger.info(f"刷新网卡列表: {self.ips}")

    def prev_ip(self):
        if not self.ips:
            return
        self.current_ip_index = (self.current_ip_index - 1) % len(self.ips)
        self.update_qr()

    def next_ip(self):
        if not self.ips:
            return
        self.current_ip_index = (self.current_ip_index + 1) % len(self.ips)
        self.update_qr()

    def get_current_ip(self):
        if 0 <= self.current_ip_index < len(self.ips):
            return self.ips[self.current_ip_index]
        return "127.0.0.1"

    def update_qr(self):
        current_ip = self.get_current_ip()
        total = len(self.ips)
        self.ip_label.setText(f"{current_ip} ({self.current_ip_index + 1}/{total})")

        qr_content = f"http://{current_ip}:{SERVER_PORT}/connect"
        logger.info(f"更新二维码 URL: {qr_content}")

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")

        data = img.tobytes("raw", "RGBA")
        qimage = QImage(data, img.size[0], img.size[1], QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)

        self.qr_label.setPixmap(pixmap.scaled(218, 218, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_status(self, text, color="#00e676"):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px; border: none;")

    def show_at_bottom_right(self):
        screen = QApplication.primaryScreen().geometry()
        margin_x = 24
        margin_y = 60
        x = screen.width() - self.width() - margin_x
        y = screen.height() - self.height() - margin_y
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()


class QuickCastApp:
    def __init__(self):
        logger.info("=== QuickCast 启动 ===")
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        tray_pil_img = create_tray_icon_image()
        data = tray_pil_img.tobytes("raw", "RGBA")
        qimg = QImage(data, tray_pil_img.size[0], tray_pil_img.size[1], QImage.Format_RGBA8888)
        self.icon = QIcon(QPixmap.fromImage(qimg))

        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setToolTip("QuickCast 扫码投屏助手")

        self.qr_window = QRCodeCard(self)

        self.init_tray_menu()
        self.tray.activated.connect(self.on_tray_activated)

        self.bridge = HttpBridge()
        self.bridge.connect_signal.connect(self.on_phone_connected)
        self.bridge.log_signal.connect(self.qr_window.set_status)

        self.http_thread = HttpServerThread(SERVER_PORT, self.bridge)
        self.http_thread.start()

        self.scrcpy_proc = None
        self.scrcpy_pid = None

        self.tray.show()
        self.qr_window.show_at_bottom_right()
        # 后台独立预热 ADB Server，避免首次扫码时才触发 fork-server
        threading.Thread(target=ensure_adb_server, daemon=True).start()
        self.tray.showMessage(
            "QuickCast 准备就绪",
            f"已开启局域网监听 (端口 {SERVER_PORT})，右键可查看日志",
            QSystemTrayIcon.Information,
            3000
        )

    def init_tray_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #23272e;
                color: #ffffff;
                border: 1px solid #3c4048;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1e90ff;
            }
        """)

        action_show = menu.addAction("📱 扫码连接 (显示二维码)")
        action_show.triggered.connect(self.qr_window.show_at_bottom_right)

        action_refresh_net = menu.addAction("🔄 刷新本地网卡")
        action_refresh_net.triggered.connect(self.qr_window.refresh_ips)

        action_open_log = menu.addAction("📋 查看实时日志 (Log)")
        action_open_log.triggered.connect(self.open_log_file)

        menu.addSeparator()

        action_kill_adb = menu.addAction("⚡ 重启 ADB 服务")
        action_kill_adb.triggered.connect(self.restart_adb)

        action_disconnect = menu.addAction("🔌 断开所有无线设备")
        action_disconnect.triggered.connect(self.disconnect_all)

        menu.addSeparator()

        action_quit = menu.addAction("❌ 退出 QuickCast")
        action_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)

    def open_log_file(self):
        """用系统记事本打开日志文件"""
        try:
            if not os.path.exists(LOG_FILE):
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("QuickCast Log Init\n")
            os.system(f'start notepad.exe "{LOG_FILE}"')
        except Exception as e:
            logger.error(f"打开日志失败: {e}")

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.qr_window.isVisible():
                self.qr_window.hide()
            else:
                self.qr_window.show_at_bottom_right()

    def restart_adb(self):
        def _task():
            logger.info("执行 adb kill-server...")
            try:
                subprocess.run(
                    ["adb", "kill-server"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception as e:
                logger.warning(f"adb kill-server 提示: {e}")
            ensure_adb_server()
            logger.info("ADB 服务已重启")
            QTimer.singleShot(0, lambda: self.tray.showMessage("ADB", "ADB 服务已完成重启", QSystemTrayIcon.Information, 2000))
        threading.Thread(target=_task, daemon=True).start()
        self.tray.showMessage("ADB", "正在重启 ADB 服务...", QSystemTrayIcon.Information, 2000)

    def disconnect_all(self):
        def _task():
            logger.info("执行 adb disconnect...")
            try:
                _, out = run_adb_command(["disconnect"], timeout=5)
                logger.info(f"所有 ADB 无线连接已断开: {out}")
            except Exception as e:
                logger.warning(f"adb disconnect 异常: {e}")
        threading.Thread(target=_task, daemon=True).start()
        self.tray.showMessage("ADB", "已断开所有设备连接", QSystemTrayIcon.Information, 2000)

    def on_phone_connected(self, phone_ip, adb_note=""):
        logger.info(f"收到握手信号，手机目标 IP: {phone_ip}")
        self.qr_window.set_status(f"握手成功: {phone_ip}，正在连接...", "#ffa502")
        threading.Thread(target=self._connect_and_launch_scrcpy, args=(phone_ip, adb_note), daemon=True).start()

    def _connect_and_launch_scrcpy(self, phone_ip, adb_note=""):
        target = f"{phone_ip}:5555"
        output = ""
        connected = False

        # 最多尝试 3 次 adb connect，兼容手机端 adbd 刚重启监听尚未就绪的瞬间
        for attempt in range(1, 4):
            logger.info(f"执行 adb connect {target} (第 {attempt}/3 次)...")
            try:
                _, output = run_adb_command(["connect", target], timeout=6)
                logger.info(f"adb connect 输出结果: {output}")
                if "connected to" in output.lower():
                    connected = True
                    break
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
                logger.error(f"adb connect 异常 (第 {attempt}/3 次): {output}")

            if attempt < 3:
                time.sleep(0.8)

        if connected:
            logger.info(f"设备 {target} 连接成功！正在隐藏二维码并唤起 scrcpy...")
            QTimer.singleShot(0, self.qr_window.hide)
            QTimer.singleShot(0, lambda: self.tray.showMessage(
                "投屏已启动",
                f"手机 {phone_ip} 已连接成功！\n按 Alt+O 可熄灭手机屏幕，耳机沉浸听音。",
                QSystemTrayIcon.Information,
                3000
            ))

            # 定位真实的 scrcpy.exe，跳过可能拦截 GUI 窗口的 Chocolatey Shim
            real_scrcpy = find_scrcpy_executable()
            tools_dir = os.path.dirname(real_scrcpy) if os.path.exists(real_scrcpy) else None

            # 直接使用独立进程拉起原生的 scrcpy GUI 程序
            # 不经由 cmd.exe /c start 包装，避免弹出多余的黑框命令行窗口，同时确保 SDL3 窗口获得主桌面交互焦点
            scrcpy_cmd = [
                real_scrcpy,
                "-s", target,
                "--always-on-top",
                "--audio-source=output",
                "--max-size=1920",
                "--video-bit-rate=12M",
                "--stay-awake",
                "--audio-buffer=50",
                "--window-title", f"QuickCast - {phone_ip}"
            ]
            cmd_str = subprocess.list2cmdline(scrcpy_cmd)
            logger.info(f"启动原生 scrcpy 投屏窗口: {cmd_str}")

            try:
                # 若之前已有 scrcpy 运行，先关闭
                self._terminate_scrcpy()

                # 指定在主用户的活动桌面 (WinSta0\Default) 上启动 GUI 窗口，避免隔离桌面
                import win32process
                si = win32process.STARTUPINFO()
                si.lpDesktop = r"WinSta0\Default"

                hProcess, hThread, dwProcessId, dwThreadId = win32process.CreateProcess(
                    None, cmd_str, None, None, False, 0, None, tools_dir, si
                )
                self.scrcpy_pid = dwProcessId
                logger.info(f"已在主桌面 WinSta0\\Default 启动 scrcpy (PID: {dwProcessId})")

                # 启动后台守护：监控并在窗口创建时自动将其前置激活
                def _focus_window():
                    try:
                        import win32gui
                        import ctypes
                        import time
                        user32 = ctypes.windll.user32
                        hdesk_input = user32.OpenInputDesktop(0, False, 0x10000000)
                        if hdesk_input:
                            user32.SetThreadDesktop(hdesk_input)

                        for _ in range(20):
                            time.sleep(0.3)
                            sdl_hwnd = None
                            def _enum(h, l):
                                nonlocal sdl_hwnd
                                if win32gui.GetClassName(h) == "SDL_app":
                                    t = win32gui.GetWindowText(h)
                                    if "quickcast" in t.lower() or phone_ip in t:
                                        sdl_hwnd = h
                                return True
                            win32gui.EnumWindows(_enum, None)
                            if sdl_hwnd:
                                user32.ShowWindow(sdl_hwnd, 9)  # SW_RESTORE
                                user32.SetWindowPos(sdl_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002) # HWND_TOPMOST | SWP_NOMOVE | SWP_NOSIZE
                                user32.SetForegroundWindow(sdl_hwnd)
                                logger.info(f"已成功将投屏窗口 (HWND: {sdl_hwnd}) 强制置顶激活至前台！")
                                break
                    except Exception as ex:
                        logger.warning(f"窗口前置辅助线程提示: {ex}")

                threading.Thread(target=_focus_window, daemon=True).start()

            except Exception as e:
                logger.error(f"scrcpy 前台拉起失败: {e}")
        else:
            if adb_note and ("10061" in output or "refused" in output.lower() or "无法连接" in output):
                detail = f"手机未开启5555端口({adb_note})"
            elif "10061" in output or "无法连接" in output:
                detail = "目标端口5555未开启，请检查手机Root权限是否已永久授权"
            else:
                detail = output or "连接超时，请检查局域网互通"

            err_msg = f"连接失败: {detail[:34]}"
            logger.warning(f"无法建立 ADB 连接 ({target}): {detail} | 原始输出: {output}")
            QTimer.singleShot(0, lambda m=err_msg: self.qr_window.set_status(m, "#ff4757"))
            QTimer.singleShot(0, lambda d=detail: self.tray.showMessage("连接失败", f"无法连接到 {target}：\n{d}", QSystemTrayIcon.Warning, 5000))

    def _terminate_scrcpy(self):
        if self.scrcpy_proc and self.scrcpy_proc.poll() is None:
            self.scrcpy_proc.terminate()
        if self.scrcpy_pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(self.scrcpy_pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass
            self.scrcpy_pid = None

    def quit_app(self):
        logger.info("QuickCast 正在退出...")
        self._terminate_scrcpy()
        self.http_thread.stop()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    server = QuickCastApp()
    server.run()
