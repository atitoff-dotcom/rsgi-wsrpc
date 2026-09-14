# ==============================================================================
# rsgi-wsrpc Showcase Launcher for Windows PowerShell
# ==============================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " 🚀 [rsgi-wsrpc] Запуск демонстрационного сервера Showcase" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Поиск Python 3.11+
$pythonCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        $ver = & py -3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
        if ($ver -and [float]$ver -ge 3.11) {
            $pythonCmd = "py -3"
        }
    } catch {}
}

if (-not $pythonCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try {
        $ver = & python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
        if ($ver -and [float]$ver -ge 3.11) {
            $pythonCmd = "python"
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "❌ Ошибка: Не найден Python 3.11+. Установите Python с python.org." -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода..."
    exit 1
}

Write-Host "✔ Найден интерпретатор Python: $pythonCmd" -ForegroundColor Green

# Проверка или создание .venv
$venvPath = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "⚙ Создание виртуального окружения в $venvPath..." -ForegroundColor Yellow
    Invoke-Expression "$pythonCmd -m venv `"$venvPath`""
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"

# Установка зависимостей
Write-Host "📦 Проверка и установка зависимостей..." -ForegroundColor Yellow
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e (Join-Path $PSScriptRoot "..\..")
& $venvPython -m pip install --quiet -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " 🌐 Сервер запускается..." -ForegroundColor Green
Write-Host " Откройте в браузере: http://127.0.0.1:8080" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

& $venvPython (Join-Path $PSScriptRoot "server.py")
