@echo off
cd /d "%~dp0"
title MM2 Bot Farm Launcher

git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Checking for updates from GitHub...
    git pull
)

echo [*] Installing dependencies...
py -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    python -m pip install -r requirements.txt --quiet
)
py -m playwright install chromium >nul 2>&1
if errorlevel 1 (
    python -m playwright install chromium >nul 2>&1
)

if not exist "config.json" (
    if exist "config.example.json" (
        copy /Y "config.example.json" "config.json" >nul
    ) else if exist "config_templates\\config.real.json" (
        copy /Y "config_templates\\config.real.json" "config.json" >nul
    )
)

echo [*] Starting MM2 Farm Manager GUI...
py farm_manager_gui.py
if errorlevel 1 (
    python farm_manager_gui.py
)

if errorlevel 1 pause
