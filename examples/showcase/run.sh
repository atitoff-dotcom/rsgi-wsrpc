#!/usr/bin/env bash
# ==============================================================================
# rsgi-wsrpc Showcase Launcher for Linux and macOS (Terminal)
# ==============================================================================
set -e

# Переход в директорию скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo " 🚀 Запуск демонстрационного сервера rsgi-wsrpc Showcase"
echo "============================================================"

# Поиск интерпретатора Python 3.11+
PYTHON_BIN=""
for cmd in python3 python python3.12 python3.11; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Ошибка: Не найден Python 3.11 или новее. Установите Python 3.11+."
    exit 1
fi

echo "✔ Найден Python: $($PYTHON_BIN --version) ($PYTHON_BIN)"

# Проверка или создание виртуального окружения
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙ Создание виртуального окружения в $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Активация venv
source "$VENV_DIR/bin/activate"

# Установка зависимостей
echo "📦 Проверка и установка зависимостей..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e "$SCRIPT_DIR/../.."
python -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

echo "============================================================"
echo " 🌐 Сервер запускается..."
echo " Откройте в браузере: http://127.0.0.1:8080"
echo "============================================================"

# Запуск сервера
exec python "$SCRIPT_DIR/server.py"
