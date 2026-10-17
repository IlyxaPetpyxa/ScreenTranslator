@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
for %%V in (.venv venv env) do (
    if exist "%%V\Scripts\python.exe" (
        "%%V\Scripts\python.exe" tools\install_models.py
        goto :done
    )
)
python -c "import argostranslate" >nul 2>&1 && (python tools\install_models.py & goto :done)
py -c "import argostranslate" >nul 2>&1 && (py tools\install_models.py & goto :done)
echo Python with argostranslate not found. Run setup_dev.bat first.
:done
pause
