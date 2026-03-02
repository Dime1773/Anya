# ИНСТРУКЦИЯ ПО СБОРКЕ ANYA DISTRIBUTOR В ИСПОЛНЯЕМЫЙ ФАЙЛ (.EXE)

## Способ 1: PyInstaller (Рекомендуется)

### Установка PyInstaller
```bash
pip install pyinstaller
```

### Создание spec файла
```bash
pyinstaller --onefile --windowed --icon=icon.ico --name "Anya Distributor" main.py
```

### Параметры
- `--onefile` - Один файл .exe
- `--windowed` - Без консольного окна
- `--icon=icon.ico` - Иконка приложения
- `--name` - Имя исполняемого файла

### Структура папок при сборке

```
project/
├── main.py
├── main_window.py
├── left_panel_anya.py
├── logger.py
├── workers.py
├── database.py
├── async_checker.py
├── vnesh_ip/                 # ВАЖНО: копируется автоматически
│   ├── fon.png
│   ├── podklychenie.png
│   ├── success.png
│   └── error.png
├── apteki.json               # ВАЖНО: копируется в dist/
├── base.json
├── requirements.txt
├── icon.ico                  # Иконка (опционально)
└── build/                    # Создаётся PyInstaller
└── dist/                     # Создаётся PyInstaller
    └── Anya Distributor.exe
```

### Добавление файлов в сборку

Создайте файл `build_spec.py`:

```python
# build_spec.py
import os
from PyInstaller.utils.hooks import get_module_collection_mode

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('vnesh_ip', 'vnesh_ip'),           # Картинки
        ('apteki.json', '.'),               # БД
        ('base.json', '.'),                 # Резервная БД
    ],
    hiddenimports=[
        'PyQt6',
        'pysmb',
        'openpyxl',
        'pandas',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Anya Distributor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Anya Distributor'
)
```

Сборка с использованием spec файла:
```bash
pyinstaller build_spec.py
```

## Способ 2: Через bat файл (Простой)

Создайте файл `build.bat`:

```batch
@echo off
echo Building Anya Distributor...

REM Проверяем PyInstaller
python -m pip install pyinstaller 2>nul

REM Собираем exe
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "Anya Distributor" ^
    --add-data "vnesh_ip;vnesh_ip" ^
    --add-data "apteki.json;." ^
    --add-data "base.json;." ^
    --hidden-import=PyQt6 ^
    --hidden-import=pysmb ^
    --hidden-import=openpyxl ^
    --hidden-import=pandas ^
    main.py

echo Done! Find .exe in dist/ folder
pause
```

Запуск:
```bash
build.bat
```

## Способ 3: Рlz (Упакованный дистрибьютив)

### Создание инсталлятора с NSIS

1. Установите NSIS: https://nsis.sourceforge.io/
2. Создайте файл `installer.nsi`:

```nsis
; installer.nsi
!include "MUI2.nsh"

Name "Anya Distributor v1.10.8"
OutFile "Anya_Distributor_Installer.exe"
InstallDir "$PROGRAMFILES\AnyaDistributor"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"

Section "Install"
  SetOutPath "$INSTDIR"
  
  ; Копируем файлы из dist/
  File /r "dist\Anya Distributor\*"
  
  ; Создаём ярлык в меню Пуск
  CreateDirectory "$SMPROGRAMS\Anya Distributor"
  CreateShortCut "$SMPROGRAMS\Anya Distributor\Anya Distributor.lnk" "$INSTDIR\Anya Distributor.exe"
  CreateShortCut "$SMPROGRAMS\Anya Distributor\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  
  ; Создаём uninstaller
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  RMDir /r "$SMPROGRAMS\Anya Distributor"
  RMDir /r "$INSTDIR"
SectionEnd
```

Компиляция:
```bash
"C:\Program Files (x86)\NSIS\makensis.exe" installer.nsi
```

## Проверка перед сборкой

1. **Все файлы на месте**
   ```bash
   python main.py  # Работает нормально?
   ```

2. **Картинки загружаются**
   - Папка `vnesh_ip/` рядом с `main.py`
   - Все .png файлы присутствуют

3. **БД файлы доступны**
   - `apteki.json` в корне проекта
   - `base.json` в корне проекта

## Типичные ошибки при сборке

### "ModuleNotFoundError: No module named 'xxx'"
**Решение**: Добавьте в `--hidden-import`:
```bash
--hidden-import=module_name
```

### "FileNotFoundError: 'vnesh_ip' not found"
**Решение**: Убедитесь, что папка `vnesh_ip/` копируется в сборку:
```bash
--add-data "vnesh_ip;vnesh_ip"
```

### "Картинки не показываются в exe"
**Решение**: Исправьте код в `left_panel_anya.py`:
```python
from pathlib import Path
import sys

if getattr(sys, 'frozen', False):
    # Запуск из exe
    self.img_dir = Path(sys.executable).parent / "vnesh_ip"
else:
    # Запуск из исходников
    self.img_dir = Path(__file__).resolve().parent / "vnesh_ip"
```

### "Приложение зависает при запуске"
**Решение**: Убедитесь, что все модули импортируются правильно:
```bash
pyinstaller --hidden-import=PyQt6.QtCore --hidden-import=PyQt6.QtGui --hidden-import=PyQt6.QtWidgets main.py
```

## Распространение

### Для одного ПК
1. Скопируйте папку `dist/Anya Distributor/` на целевой ПК
2. Создайте ярлык на рабочем столе для `Anya Distributor.exe`
3. Убедитесь, что `vnesh_ip/` скопирована вместе с exe

### Для множества ПК (Инсталлятор)
1. Создайте инсталлятор через NSIS (см. выше)
2. Распространяйте `Anya_Distributor_Installer.exe`
3. Пользователи запускают инсталлятор, который:
   - Спросит папку установки
   - Скопирует файлы
   - Создаст ярлыки в меню Пуск

## Требования для целевого ПК

- Windows 7+ (64-bit)
- .NET Framework 4.0+ (обычно предустановлено)
- НЕ требуется установка Python!

## Размер сборки

- Однофайловый exe: ~150-200 MB
- Папка dist с зависимостями: ~300-400 MB

Большой размер из-за PyQt6 и зависимостей.

## Автоматизация сборки

Создайте файл `build_all.py`:

```python
# build_all.py
import os
import shutil
import subprocess

# Удаляем старые сборки
if os.path.exists('build'):
    shutil.rmtree('build')
if os.path.exists('dist'):
    shutil.rmtree('dist')

# Собираем
subprocess.run([
    'pyinstaller',
    '--onefile',
    '--windowed',
    '--name', 'Anya Distributor',
    '--add-data', 'vnesh_ip;vnesh_ip',
    '--add-data', 'apteki.json;.',
    '--add-data', 'base.json;.',
    '--hidden-import=PyQt6',
    '--hidden-import=pysmb',
    '--hidden-import=openpyxl',
    '--hidden-import=pandas',
    'main.py'
])

print("\n✓ Сборка завершена!")
print("Исполняемый файл: dist/Anya Distributor.exe")
```

Запуск:
```bash
python build_all.py
```

---

**Успешной сборки!** 🚀
