@echo off
cd /d "%~dp0"
title MM2 Farm Manager GUI

echo [*] Installing dependencies...
py -m pip install requests psutil beautifulsoup4
if errorlevel 1 (
    python -m pip install requests psutil beautifulsoup4
)

echo [*] Starting GUI...
py farm_manager_gui.py
if errorlevel 1 (
    python farm_manager_gui.py
)

if errorlevel 1 pause
