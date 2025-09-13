@echo off
setlocal enabledelayedexpansion
cls
echo ==============================
echo       Project Setup Script
echo ==============================
echo.

:: ----------------------------
:: Check for Python
:: ----------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo Python not found in PATH. Please install Python or add it to PATH.
    pause
    exit /b
)

:: ----------------------------
:: Check Python version
:: ----------------------------
for /f "tokens=2 delims= " %%v in ('python -V 2^>^&1') do set pyver=%%v
echo Detected Python version: %pyver%

:: Extract major and minor version
for /f "tokens=1,2 delims=." %%a in ("%pyver%") do (
    set pymaj=%%a
    set pymin=%%b
)

if %pymaj% LSS 3 (
    echo Python 3 is required. Detected version: %pyver%
    pause
    exit /b
)
if %pymaj%==3 if %pymin% LSS 8 (
    echo Python 3.8 or higher is required. Detected version: %pyver%
    pause
    exit /b
)

:: ----------------------------
:: Check for requirements.txt
:: ----------------------------
if not exist requirements.txt (
    echo requirements.txt not found! Make sure it exists in the same folder as this script.
    pause
    exit /b
)

:: ----------------------------
:: Upgrade pip, setuptools, wheel
:: ----------------------------
echo Upgrading pip, setuptools, and wheel...
call python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo Failed to upgrade pip. Check your Python installation.
    pause
    exit /b
)

:: ----------------------------
:: Install requirements
:: ----------------------------
echo Installing required Python libraries...
call python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install required Python libraries.
    pause
    exit /b
)

echo.
set /p choice="Do you want to install NaturalVoice support now? (y/n): "
if /i "%choice%"=="y" (
    set "nv_installer=%~dp0voiceadaptor\installer.exe"
    if exist "!nv_installer!" (
        echo Running NaturalVoice installer...
        echo Click on Install 32-bit and Install 64-bit
        start "" "!nv_installer!"
    ) else (
        echo NaturalVoice installer not found at "!nv_installer!"
    )
) else (
    echo Skipping NaturalVoice installation.
)

:: ----------------------------
:: Setup complete
:: ----------------------------
echo.
echo ==============================
echo ✅ Setup complete!
echo ==============================
pause
