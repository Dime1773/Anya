#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
logger.py - Система логирования для Anya Distributor v1.11.1
ПРАВКА: Добавлен pyqtSignal для log_message
"""

import logging
from pathlib import Path
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal


class LogSignalEmitter(QObject):
    """Эмиттер сигналов для логирования в UI"""
    
    log_message = pyqtSignal(str, str)  # message, level
    

def init_logging(logs_dir: str = "logs"):
    """Инициализировать логирование в файл и консоль"""
    logs_path = Path(logs_dir)
    logs_path.mkdir(exist_ok=True)
    
    logger = logging.getLogger("distributor")
    logger.setLevel(logging.DEBUG)
    
    # Очищаем существующие обработчики
    if logger.handlers:
        logger.handlers.clear()
    
    # Файловый обработчик
    log_file = logs_path / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    
    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Форматер
    formatter = logging.Formatter(
        "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def init_ui_logging(emitter: LogSignalEmitter):
    """Подключить сигналы UI к логированию"""
    logger = logging.getLogger("distributor")
    
    class UILogHandler(logging.Handler):
        def emit(self, record):
            try:
                msg = self.format(record)
                emitter.log_message.emit(msg, record.levelname)
            except Exception:
                pass
    
    ui_handler = UILogHandler()
    ui_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ui_handler)
