#!/bin/bash
# run.sh - Скрипт запуска приложения Distributor

# Проверить наличие Python
if ! command -v python3 &> /dev/null; then
    echo "Ошибка: Python3 не найден в PATH"
    exit 1
fi

echo "Запуск приложения Distributor..."
echo "================================"

# Проверить наличие виртуального окружения (опционально)
if [ -d "venv" ]; then
    echo "Активирую виртуальное окружение..."
    source venv/bin/activate  # или venv\Scripts\activate на Windows
fi

# Проверить требования
if [ ! -f "requirements.txt" ]; then
    echo "Ошибка: requirements.txt не найден"
    exit 1
fi

# Установить зависимости (если нужно)
echo "Проверяю зависимости..."
pip install -r requirements.txt -q

# Запустить приложение
echo "Запускаю main.py..."
python3 main.py

exit $?
