@echo off
chcp 65001 >nul
title QuickCast 扫码投屏助手

echo ========================================================
echo             QuickCast 扫码投屏助手
echo ========================================================
echo 正在启动后台托盘服务与二维码监听...

start "" python "%~dp0pc-server\quick_cast_server.py"
exit
