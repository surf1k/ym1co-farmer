@echo off
chcp 65001 >nul
title MM2 Bot Farm & FunPay Auto-Seller Launcher
color 0B

echo =========================================================
echo       MM2 BOT FARM & FUNPAY AUTO-SELLER SETUP
echo =========================================================
echo.

:: 0. Автоматическая синхронизация с GitHub
git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Проверка и загрузка обновлений скриптов с GitHub...
    git pull
    echo.
)

:: 1. Проверка наличия Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ОШИБКА] Python не найден на вашем компьютере!
    echo Пожалуйста, установите Python с официального сайта: https://www.python.org/
    echo ВАЖНО: При установке обязательно поставьте галочку "Add Python to PATH"!
    echo.
    pause
    exit /b
)

echo [+] Python обнаружен:
python --version
echo.

:: 2. Скачивание и установка необходимых библиотек
echo [*] Проверка и установка библиотек Python (requests, beautifulsoup4, psutil)...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install requests beautifulsoup4 psutil
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [ОШИБКА] Не удалось установить библиотеки через pip!
    echo Проверьте подключение к интернету.
    pause
    exit /b
)
echo [+] Все зависимости успешно установлены!
echo.

:: 3. Проверка и создание config.json при его отсутствии
if not exist "config.json" (
    echo [!] Файл config.json не найден.
    if exist "config.example.json" (
        echo [*] Копируем готовый шаблон из config.example.json...
        copy /Y "config.example.json" "config.json" >nul
    ) else if exist "config_templates\config.xeno.json" (
        echo [*] Копируем готовый шаблон из config_templates\config.xeno.json...
        copy /Y "config_templates\config.xeno.json" "config.json" >nul
    ) else (
        echo [*] Создаём стандартный шаблон config.json под Xeno...
        (
            echo {
            echo   "hardware_limits": {
            echo     "max_ram_usage_percent": 100.0,
            echo     "min_free_ram_mb": 0,
            echo     "max_cpu_usage_percent": 100.0,
            echo     "spawn_cooldown_sec": 10,
            echo     "absolute_max_bots_safety_cap": 50,
            echo     "ram_limit_per_bot_mb": 0
            echo   },
            echo   "farm": {
            echo     "roblox_executable_path": "",
            echo     "target_level": 100,
            echo     "target_coins": 0,
            echo     "executor_workspace_path": "%%LOCALAPPDATA%%/Xeno/workspace",
            echo     "ram_account_data_path": "",
            echo     "place_id": 142823291,
            echo     "check_stats_interval_sec": 10
            echo   },
            echo   "funpay": {
            echo     "enabled": false
            echo   }
            echo }
        ) > config.json
    )
    echo [+] Файл config.json успешно подготовлен!
    echo.
)

:: 4. Проверка управляющего скрипта
if not exist "farm_manager.py" (
    color 0C
    echo [ОШИБКА] Файл farm_manager.py не найден в текущей папке!
    echo Поместите farm_manager.py рядом с этим батником.
    pause
    exit /b
)

:: 5. Напоминание по инжектору
echo ---------------------------------------------------------
echo [НАПОМИНАНИЕ]:
echo 1. Убедитесь, что main.lua лежит в папке autoexec инжектора.
echo 2. Убедитесь, что запущена утилита разблокировки окон (Multiple Roblox).
echo ---------------------------------------------------------
echo.

echo [*] Запуск фермы...
python farm_manager.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Работа скрипта завершилась с ошибкой.
    pause
)
