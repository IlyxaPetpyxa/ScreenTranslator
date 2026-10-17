@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo Close Screen Translator first (tray icon - Exit) if it is running.
echo.
for %%V in (.venv venv env) do (
    if exist "%%V\Scripts\python.exe" (
        "%%V\Scripts\python.exe" tools\build_lookup.py
        goto :done
    )
)
python tools\build_lookup.py && goto :done
py tools\build_lookup.py && goto :done
echo Python not found. Run setup_dev.bat first.
:done
pause
