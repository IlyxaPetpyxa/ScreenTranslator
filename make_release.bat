@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup_dev.bat
".venv\Scripts\python.exe" tools\make_release.py %*
pause
