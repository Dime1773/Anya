#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database.py - Менеджер работы с БД для Anya Distributor v1.10.8

Этот файл - ШАБЛОН. Используйте свою реализацию если она есть.
Обязательные методы для MainWindow:
  - load_base() -> List[Dict]
  - update_branch_status(prefix, status, alive_ips)
  - rescan_bases()
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("distributor")


class DatabaseManager:
    """Менеджер работы с БД подразделений (apteki.json)"""

    def __init__(self, primary_file: str = "apteki.json", backup_file: str = "base.json"):
        self.primary_path = Path(primary_file)
        self.backup_path = Path(backup_file)
        self.branches: List[Dict] = []

    def load_base(self) -> List[Dict]:
        """Загрузить справочник подразделений"""
        try:
            # Пытаемся загрузить основной файл
            if self.primary_path.exists():
                logger.info(f"Загружаю основной файл: {self.primary_path}")
                with open(self.primary_path, 'r', encoding='utf-8') as f:
                    self.branches = json.load(f)
                logger.info(f"✓ Загружено {len(self.branches)} подразделений")
                return self.branches

            # Если основного нет, пытаемся резервный
            if self.backup_path.exists():
                logger.warning(f"Основной файл не найден, загружаю резервный: {self.backup_path}")
                with open(self.backup_path, 'r', encoding='utf-8') as f:
                    self.branches = json.load(f)
                logger.info(f"✓ Загружено {len(self.branches)} подразделений (из резервной копии)")
                return self.branches

            logger.error(f"Ни основной ({self.primary_path}), ни резервный ({self.backup_path}) файлы не найдены")
            return []

        except Exception as e:
            logger.error(f"Ошибка загрузки БД: {e}", exc_info=True)
            return []

    def rescan_bases(self):
        """Перезагрузить БД (перескан файлов)"""
        logger.info("Перезагружаю БД...")
        self.branches = []
        self.load_base()

    def update_branch_status(self, prefix: str, status: str, alive_ips: str = ""):
        """Обновить статус подразделения"""
        try:
            for branch in self.branches:
                if branch.get("prefix") == prefix:
                    branch["status"] = status
                    if alive_ips:
                        branch["alive_ips"] = alive_ips
                    logger.debug(f"Обновлён статус {prefix}: {status}")
                    return

            logger.warning(f"Подразделение {prefix} не найдено в БД")

        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса: {e}", exc_info=True)

    def save_base(self, filepath: Optional[str] = None):
        """Сохранить БД в файл"""
        try:
            target_path = Path(filepath) if filepath else self.primary_path
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(self.branches, f, ensure_ascii=False, indent=2)
            logger.info(f"✓ БД сохранена в: {target_path}")
        except Exception as e:
            logger.error(f"Ошибка сохранения БД: {e}", exc_info=True)

    def get_branch_by_prefix(self, prefix: str) -> Optional[Dict]:
        """Получить подразделение по префиксу"""
        for branch in self.branches:
            if branch.get("prefix") == prefix:
                return branch
        return None

    def get_all_branches(self) -> List[Dict]:
        """Получить все подразделения"""
        return self.branches

    def get_online_branches(self) -> List[Dict]:
        """Получить только online подразделения"""
        return [b for b in self.branches if b.get("status") == "online"]

    def get_offline_branches(self) -> List[Dict]:
        """Получить только offline подразделения"""
        return [b for b in self.branches if b.get("status") == "offline"]


# ============================================================================
# ПРИМЕРЫ СТРУКТУРЫ ДАННЫХ
# ============================================================================

# Структура apteki.json:
EXAMPLE_APTEKI_JSON = [
    {
        "prefix": "apt_001",
        "name": "Аптека №1, Нижний Новгород",
        "vneip": "91.245.1.1",
        "ip": "10.0.8.1",
        "alt_ips": [
            "20.0.8.1",
            "30.0.8.1"
        ],
        "status": "online",
        "alive_ips": "10.0.8.1,20.0.8.1"
    },
    {
        "prefix": "apt_002",
        "name": "Аптека №2, Казань",
        "vneip": "91.245.1.2",
        "ip": "10.0.8.2",
        "alt_ips": [
            "20.0.8.2",
            "30.0.8.2"
        ],
        "status": "offline",
        "alive_ips": ""
    },
    {
        "prefix": "apt_003",
        "name": "Аптека №3, Самара",
        "vneip": "91.245.1.3",
        "ip": "10.0.8.3",
        "alt_ips": [
            "20.0.8.3",
            "30.0.8.3"
        ],
        "status": "online",
        "alive_ips": "10.0.8.3"
    }
]

# Описание полей:
FIELD_DESCRIPTIONS = {
    "prefix": "Уникальный идентификатор подразделения (без пробелов, латиница)",
    "name": "Полное название подразделения (например, 'Аптека №1, Город')",
    "vneip": "Внешний IP адрес (для справки, не используется в передаче)",
    "ip": "Основной внутренний IP адрес сервера (10.x.x.x)",
    "alt_ips": "Список альтернативных IP адресов [ОП1 (20.x.x.x), ОП2 (30.x.x.x)]",
    "status": "Текущий статус подключения: 'online' или 'offline'",
    "alive_ips": "Доступные IP адреса (заполняется после проверки подключения)",
}

# Примеры IP адресов:
IP_EXAMPLES = {
    "основной (сервер)": "10.0.8.1 (сетка 10.x.x.x)",
    "оператор 1": "20.0.8.1 (сетка 20.x.x.x)",
    "оператор 2": "30.0.8.1 (сетка 30.x.x.x)",
    "внешний IP": "91.245.1.1 (публичный IP для справки)",
}

# ============================================================================

if __name__ == "__main__":
    # Пример использования
    print("DatabaseManager v1.10.8")
    print("=" * 60)

    # Инициализация
    db = DatabaseManager("apteki.json", "base.json")

    # Загрузка
    print("\n1. Загрузка БД:")
    branches = db.load_base()
    print(f"   Загружено: {len(branches)} подразделений")

    # Вывод онлайн
    print("\n2. Online подразделения:")
    for b in db.get_online_branches():
        print(f"   - {b.get('prefix')}: {b.get('name')}")

    # Обновление статуса
    print("\n3. Обновление статуса:")
    db.update_branch_status("apt_001", "offline", "")
    print(f"   apt_001: обновлён на 'offline'")

    # Сохранение
    print("\n4. Сохранение БД:")
    db.save_base()
    print("   ✓ Готово")
