#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Точка входа приложения Anya Distributor v1.10.8
"""

import sys
import logging
import os
import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtCore import Qt

# Включение DPI-масштабирования
if hasattr(Qt, 'AA_EnableHighDpiScaling'):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

# Можно также принудительно задать масштаб, если нужно:
# os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

logger = logging.getLogger("distributor")

def resource_path(relative_path):
    """ Получить абсолютный путь к ресурсу, работает для dev и для PyInstaller """
    try:
        # PyInstaller создаёт временную папку _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def main():
    """Запустить приложение"""
    try:
        from main_window import MainWindow
        
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
        
    except Exception as e:
        logger.critical(f"✗ Критическая ошибка при запуске приложения: {e}", exc_info=True)
        print(f"✗ ОШИБКА: {e}")
        
        # Пытаемся показать диалог ошибки (если возможно)
        try:
            app = QApplication.instance()
            if not app:
                app = QApplication(sys.argv)
            QMessageBox.critical(None, "Критическая ошибка", f"Ошибка при запуске:\n{e}")
        except:
            pass
        
        sys.exit(1)


if __name__ == "__main__":
    main()
