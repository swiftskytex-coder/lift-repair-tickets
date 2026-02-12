#!/bin/bash

echo "🛠️  Система заявок на ремонт лифтового оборудования"
echo "============================================================"

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не найден. Установите Python 3.8+"
    exit 1
fi

echo "📋 Python: $(python3 --version)"
echo ""

# Создание виртуального окружения
if [ ! -d "venv" ]; then
    echo "📦 Создание виртуального окружения..."
    python3 -m venv venv
fi

# Активация виртуального окружения
echo "🔄 Активация виртуального окружения..."
source venv/bin/activate

# Установка зависимостей
echo "📥 Установка зависимостей..."
pip install -q flask werkzeug jinja2 markupsafe itsdangerous click python-dateutil requests

# Проверка и установка MCP SDK
echo "🔍 Проверка MCP SDK..."
if ! python3 -c "import mcp" 2>/dev/null; then
    echo "📥 Установка MCP SDK..."
    pip install -q mcp
fi

echo ""
echo "✅ Установка завершена!"
echo ""
echo "🚀 Запуск сервера заявок..."
echo ""
echo "📞 Веб-интерфейс оператора: http://localhost:8081"
echo "📚 API документация: http://localhost:8081/api/docs"
echo ""

# Запуск сервера
python3 ticket_system.py
