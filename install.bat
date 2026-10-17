@echo off
rem One-time setup: downloads Python into .\python, installs libraries, creates Translator.exe
chcp 65001 >nul
cd /d "%~dp0"
setlocal

set "PY_VERSION=3.12.8"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"

echo ============================================
echo   Screen Translator - installation
echo ============================================
echo.

rem --- the folder path must be plain Latin letters (the translation engine can't open models otherwise)
powershell -NoProfile -Command "if ('%~dp0' -match '[^\x00-\x7F]') { exit 1 }"
if errorlevel 1 (
    echo ERROR: the folder path contains non-Latin characters:
    echo   "%~dp0"
    echo Move this folder to something like C:\ScreenTranslator and run install.bat again.
    echo.
    pause
    exit /b 1
)

rem --- 0. Visual C++ runtime (needed by PySide6 / translation engine on a clean Windows)
if exist "installer\vc_redist.x64.exe" (
    echo Installing Microsoft Visual C++ runtime ^(Windows may ask for permission^)...
    start /wait "" "installer\vc_redist.x64.exe" /install /quiet /norestart
)

rem --- 1. Python (kept inside this folder, nothing is changed in Windows)
if exist "python\python.exe" goto have_python

set "PY_SETUP="
for %%F in ("installer\python-*.exe") do set "PY_SETUP=%%~fF"
if defined PY_SETUP (
    echo [1/3] Installing bundled Python...
    goto run_python_setup
)

echo [1/3] Downloading Python %PY_VERSION% ^(about 25 MB^)...
set "PY_SETUP=%TEMP%\screen-translator-python-setup.exe"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_SETUP%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo.
    echo ERROR: could not download Python. Check the internet connection and run install.bat again.
    echo Or download it manually: %PY_URL%
    pause
    exit /b 1
)

:run_python_setup
start /wait "" "%PY_SETUP%" /quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0 AssociateFiles=0 PrependPath=0 "TargetDir=%~dp0python"
if not exist "python\python.exe" (
    echo.
    echo ERROR: Python installation failed.
    pause
    exit /b 1
)

:have_python
echo [1/3] Python is ready.
echo.

rem --- 2. Libraries (from the bundled "wheels" folder when present - no internet needed)
if exist "wheels\" (
    echo [2/3] Installing libraries from the bundled files, several minutes...
    "python\python.exe" -m pip install --no-warn-script-location --disable-pip-version-check --no-index --find-links wheels -r requirements.txt
) else (
    echo [2/3] Installing libraries ^(several minutes, needs internet^)...
    "python\python.exe" -m pip install --no-warn-script-location --disable-pip-version-check -r requirements.txt
)
if errorlevel 1 (
    echo.
    echo ERROR: library installation failed.
    pause
    exit /b 1
)
echo.

rem --- language models (only needed when they are not bundled in the "models" folder)
if not exist "models\" (
    echo No bundled language models found - downloading them...
    "python\python.exe" tools\install_models.py
)

rem --- 3. Translator.exe
echo [3/3] Creating Translator.exe...
set "CSC="
for %%D in ("%WINDIR%\Microsoft.NET\Framework64\v4.0.30319" "%WINDIR%\Microsoft.NET\Framework\v4.0.30319") do (
    if exist "%%~D\csc.exe" if not defined CSC set "CSC=%%~D\csc.exe"
)
if defined CSC (
    "%CSC%" /nologo /target:winexe /codepage:65001 /win32icon:assets\icon.ico /reference:System.Windows.Forms.dll /out:Translator.exe tools\launcher.cs >nul
)
if not exist "Translator.exe" (
    echo Could not create Translator.exe - use Translator.bat instead.
)

echo.
echo ============================================
echo   Done! Start the program with Translator.exe
echo ============================================
pause
