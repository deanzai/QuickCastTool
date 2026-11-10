@echo off
chcp 65001 >nul
title 创建桌面快捷方式

set SCRIPT_DIR=%~dp0
set TARGET_VBS=%SCRIPT_DIR%启动扫码投屏(静默托盘).vbs
set SHORTCUT_PATH=%USERPROFILE%\Desktop\QuickCast扫码投屏.lnk

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%TARGET_VBS%\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Description = 'QuickCast 扫码无线投屏助手'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo ========================================================
    echo  [成功] 已在桌面创建快捷方式: QuickCast扫码投屏
    echo ========================================================
) else (
    echo [提示] 快捷方式已更新。
)

timeout /t 2 >nul
exit
