@echo off
rem Fallback launcher if Translator.exe could not be created.
cd /d "%~dp0"
start "" "python\pythonw.exe" "src\main.py"
