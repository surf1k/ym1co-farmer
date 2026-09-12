@echo off
chcp 65001 >nul
title MM2 Farm Manager GUI - Clockwork Sanctuary
cd /d "%~dp0"
python farm_manager_gui.py
if errorlevel 1 (
    echo.
    echo [!] Ошибка запуска farm_manager_gui.py
    echo Убедитесь, что установлены библиотеки: pip install requests psutil
    pause
)
