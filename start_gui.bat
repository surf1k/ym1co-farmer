@echo off
chcp 65001 >nul
title MM2 Farm Manager GUI - Clockwork Sanctuary
cd /d "%~dp0"

echo =========================================================
echo       MM2 FARM MANAGER GUI - CLOCKWORK SANCTUARY
echo =========================================================
echo.

echo [*] Проверка и установка библиотек...
py -m pip install requests psutil
if errorlevel 1 (
    python -m pip install requests psutil
)

echo.
echo [*] Запуск MM2 Farm Manager GUI...
py farm_manager_gui.py
if errorlevel 1 (
    python farm_manager_gui.py
)

if errorlevel 1 (
    echo.
    echo [!] Ошибка при запуске менеджера.
    pause
)
