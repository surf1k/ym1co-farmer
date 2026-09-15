@echo off
cd /d "%~dp0"
title MM2 Farm Manager

echo [*] Installing dependencies...
py -m pip install requests psutil beautifulsoup4 playwright
if errorlevel 1 (
    python -m pip install requests psutil beautifulsoup4 playwright
)

echo [*] Starting MM2 Farm Manager...
py farm_manager.py
if errorlevel 1 (
    python farm_manager.py
)

if errorlevel 1 pause
