@echo off
chcp 65001 >nul
title QuickCast 日志查看器

set LOG_FILE=%~dp0pc-server\quick_cast.log

echo ========================================================
echo             QuickCast 实时连接日志
echo ========================================================
echo 日志文件路径: %LOG_FILE%
echo.

if not exist "%LOG_FILE%" (
    echo [提示] 尚未产生日志记录，正在创建...
    type nul > "%LOG_FILE%"
)

start notepad.exe "%LOG_FILE%"
exit
