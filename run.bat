@echo off
REM run.bat - Скрипт запуска приложения Distributor для Windows

setlocal enabledelayedexpansion

echo.
echo ========================================
echo  Distributor - Запуск приложения
echo ========================================
echo.

REM Проверить наличие Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден в PATH
    echo Пожалуйста, установите Python 3.8+ и добавьте его в PATH
    pause
    exit /b 1
)

REM Проверить наличие requirements.txt
if not exist "requirements.txt" (
    echo [ОШИБКА] Файл requirements.txt не найден
    pause
    exit /b 1
)

REM Проверить виртуальное окружение
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Найдено виртуальное окружение, активирую...
    call venv\Scripts\activate.bat
)

REM Установить зависимости
echo [INFO] Проверяю Python зависимости...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [ОШИБКА] Ошибка при установке зависимостей
    pause
    exit /b 1
)

REM Запустить приложение
echo [INFO] Запускаю Distributor...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ОШИБКА] Приложение завершилось с ошибкой (код %errorlevel%)
    pause
)

exit /b %errorlevel%
