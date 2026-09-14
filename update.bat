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
    curl -s -L -o cookie_grabber.py https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/cookie_grabber.py
    curl -s -L -o farm_manager_gui.py https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/farm_manager_gui.py
    curl -s -L -o main.lua https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/main.lua
    curl -s -L -o obfuscated.lua https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/obfuscated.lua
)

echo.
echo [✓] Все файлы обновлены до последней версии!
pause
