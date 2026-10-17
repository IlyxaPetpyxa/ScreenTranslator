@echo off
rem Starts Screen Translator from source (for development). Family: use Translator.exe instead.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Environment not found. Running setup_dev.bat first...
    call setup_dev.bat
)
start "" ".venv\Scripts\pythonw.exe" src\main.py
