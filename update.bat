@echo off
chcp 65001 >nul
title ym1co farmer - Автообновление
echo ==================================================
echo        ym1co farmer - СКАЧИВАНИЕ ОБНОВЛЕНИЯ
echo ==================================================

where git >nul 2>nul
if %errorlevel% == 0 (
    echo [*] Обновление через Git...
    git pull origin main
) else (
    echo [*] Git не найден, загрузка файлов через curl...
    curl -s -L -o farm_manager.py https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/farm_manager.py
    curl -s -L -o main.lua https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/main.lua
    curl -s -L -o obfuscated.lua https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/obfuscated.lua
)

:: Удаление устаревших мусорных файлов
if exist cookie_grabber.py del /f /q cookie_grabber.py >nul 2>&1
if exist farm_manager_gui.py del /f /q farm_manager_gui.py >nul 2>&1
if exist get_cookies.bat del /f /q get_cookies.bat >nul 2>&1
if exist auto_block_all.py del /f /q auto_block_all.py >nul 2>&1
if exist real_chrome_unlocker.py del /f /q real_chrome_unlocker.py >nul 2>&1
if exist unban_accounts.py del /f /q unban_accounts.py >nul 2>&1
if exist script.lua del /f /q script.lua >nul 2>&1
if exist start_all.bat del /f /q start_all.bat >nul 2>&1
if exist start_gui.sh del /f /q start_gui.sh >nul 2>&1
if exist config_templates rmdir /s /q config_templates >nul 2>&1

echo.
echo [✓] Все файлы обновлены и зачищены до минимального набора!
pause
