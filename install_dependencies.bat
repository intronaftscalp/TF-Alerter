@echo off
REM ============================================
REM Installation script for TF-Alerter
REM ============================================

echo.
echo === TF-Alerter Dependencies Installation ===
echo.

REM Find Python on PATH or through the Windows Python launcher
set "PY_CMD="
set "PY_ARGS="
where python >nul 2>&1
if not errorlevel 1 set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=py"
        set "PY_ARGS=-3"
    )
)
if not defined PY_CMD (
    echo ERROR: Python 3 is not installed.
    echo Please install Python 3.10 or newer from https://www.python.org/
    echo Ensure the Python launcher or Python is available on PATH.
    pause
    exit /b 1
)

echo [*] Python found:
%PY_CMD% %PY_ARGS% --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    %PY_CMD% %PY_ARGS% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment
        pause
        exit /b 1
    )
)

REM Upgrade pip
echo [*] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
echo.

REM Install all dependencies
echo [*] Installing required packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install packages
    pause
    exit /b 1
)

echo.
echo === Installation Complete! ===
echo.
echo You can now run the application:
echo   python main.py
echo.
pause
