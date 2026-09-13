@echo off
chcp 65001 >nul
title ym1co farmer - АВТО-КУКИ ВСЕГО (Real / BloxGen)
cd /d "%~dp0"

echo =====================================================================
echo    👑 ym1co farmer - АВТОКУКИ ВСЕГО (Real / BloxGen / Farm)
echo =====================================================================
echo.

where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py"
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    ) else (
        echo [ОШИБКА] Python не найден в системе!
        pause
        exit /b 1
    )
)

echo [*] Проверка Playwright...
%PY_CMD% -m pip install playwright --quiet
%PY_CMD% -m playwright install chromium

echo.
echo [*] Запуск автоматического сборщика куки...
echo.
%PY_CMD% cookie_grabber.py %*

echo.
pause
