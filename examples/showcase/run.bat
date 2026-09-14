@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: rsgi-wsrpc Showcase Launcher for Windows (cmd.exe)
:: ============================================================================

cd /d "%~dp0"

echo ============================================================
echo  [rsgi-wsrpc] Запуск демонстрационного сервера Showcase
echo ============================================================

:: Поиск Python 3.11+
set "PYTHON_CMD="

:: Попытка через Python Launcher (py -3.11 или py -3)
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

:: Попытка через python в PATH
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_found
)

echo [ОШИБКА] Не найден Python 3.11 или новее. Установите Python с python.org.
pause
exit /b 1

:python_found
echo [*] Используется: !PYTHON_CMD!

:: Создание venv при необходимости
if not exist ".venv" (
    echo [*] Создание виртуального окружения в .venv...
    !PYTHON_CMD! -m venv .venv
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)

:: Активация виртуального окружения
call .venv\Scripts\activate.bat

:: Установка зависимостей
echo [*] Проверка и установка зависимостей...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ..\..
python -m pip install --quiet -r requirements.txt

echo ============================================================
echo  Сервер запускается...
echo  Откройте в браузере: http://127.0.0.1:8080
echo ============================================================

python server.py

if %errorlevel% neq 0 (
    echo [Сервер остановлен с ошибкой]
    pause
)
