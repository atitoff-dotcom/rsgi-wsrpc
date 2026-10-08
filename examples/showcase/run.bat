@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: rsgi-wsrpc Showcase Launcher for Windows (cmd.exe)
:: ============================================================================

cd /d "%~dp0"

echo ============================================================
echo  [rsgi-wsrpc] Starting Showcase Demo Server
echo ============================================================

:: Locate Python 3.11+
set "PYTHON_CMD="

:: Try Python Launcher (py -3.11 or py -3)
py -3.11 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py -3.11"
    goto :python_found
)

py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py -3"
    goto :python_found
)

:: Try python in PATH
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_found
)

echo [ERROR] Python 3.11+ not found. Please install Python from python.org.
pause
exit /b 1

:python_found
echo [*] Using: !PYTHON_CMD!

:: Create virtual environment if needed
if not exist ".venv" (
    echo [*] Creating virtual environment in .venv...
    !PYTHON_CMD! -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Install dependencies from PyPI
echo [*] Checking and installing dependencies from PyPI...
python -m pip install --quiet --upgrade pip
python -m pip install --upgrade -r requirements.txt

echo ============================================================
echo  Server is starting...
echo  Open in browser: http://127.0.0.1:8080
echo ============================================================

python server.py %*

if %errorlevel% neq 0 (
    echo [Server stopped with error]
    pause
)
