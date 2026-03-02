#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py - Конфигурация Anya Distributor v1.12.0 (Windows-оптимизация)
"""

import json
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    # SMB настройки
    "smb_port": 445,
    "smb_username": "Администратор",
    "smb_password": "2445vr7",
    "smb_share": "d$",
    
    # 🔥 НАСТРОЙКИ БЫСТРОЙ ПРОВЕРКИ (Windows)
    "check": {
        "max_concurrent": 100,        # Параллельных проверок
        "ping_timeout": 0.2,          # Таймаут ping.exe (сек)
        "port_timeout": 0.3,          # Таймаут проверки порта (сек)
        "batch_size": 100,            # Размер пачки для обработки
        "pause_between_batches": 0.1, # Пауза между пачками (сек)
        "cache_ttl": 300,             # Время жизни кэша IP (сек)
        "retry_count": 1,             # Повторных попыток при ошибке
    },
    
    # Логи
    "log_rotation_size_mb": 10,
    "log_rotation_count": 5,
    
    # Прочее
    "check_integrity": True,
    "theme": "dark"
}

def load_config():
    """Загрузить конфигурацию из файла или создать с дефолтами"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # Мердж с дефолтами (рекурсивно для вложенных dict)
            def merge_defaults(cfg, defaults):
                for key, default_value in defaults.items():
                    if key not in cfg:
                        cfg[key] = default_value
                    elif isinstance(default_value, dict) and isinstance(cfg[key], dict):
                        merge_defaults(cfg[key], default_value)
            merge_defaults(config, DEFAULT_CONFIG)
            return config
        except Exception as e:
            print(f"⚠️ Ошибка загрузки конфига: {e}, используем дефолт")
    # Создаём файл с дефолтными значениями
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG

def save_config(config):
    """Сохранить конфигурацию в файл"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения конфига: {e}")

# Загружаем конфиг при импорте
config = load_config()

# 🔥 Публичные переменные для быстрой проверки
CHECK_MAX_CONCURRENT = config["check"]["max_concurrent"]
CHECK_PING_TIMEOUT = config["check"]["ping_timeout"]
CHECK_PORT_TIMEOUT = config["check"]["port_timeout"]
CHECK_BATCH_SIZE = config["check"]["batch_size"]
CHECK_PAUSE_BETWEEN_BATCHES = config["check"]["pause_between_batches"]
CHECK_CACHE_TTL = config["check"]["cache_ttl"]
CHECK_RETRY_COUNT = config["check"]["retry_count"]

# SMB переменные
SMB_PORT = config["smb_port"]
SMB_USERNAME = config["smb_username"]
SMB_PASSWORD = config["smb_password"]
SMB_SHARE = config["smb_share"]

def get_config():
    return config.copy()