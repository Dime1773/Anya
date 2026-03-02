#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workers.py - Асинхронные потоки для Anya Distributor v1.11.2 (исправленный 3)
ОБНОВЛЕНИЯ:
- TransferWorker: исправлена ошибка 'open_file' is not defined
- AutomatErrorWorker: исправлена обработка IP из errors.xlsx без привязки к all_branches
- TransferWorker: исправлена передача папок с использованием os.walk
- AutomatErrorWorker: исправлена передача папок с использованием os.walk
- Оба: передаётся содержимое папки, структура сохраняется, корневая папка не создаётся.
"""
import logging
import time
import socket
import asyncio
import os # Добавлен импорт os
from pathlib import Path
from typing import List, Dict
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("distributor")

# ============================================================================
# ASYNC CHECKER - Проверка доступности IP (параллельно до 40 устройств)
# ============================================================================

class AsyncCheckWorker(QThread):
    """Асинхронная проверка доступности подразделений"""
    progress = pyqtSignal(int, int)  # current, total
    status_updated = pyqtSignal(str, str, str, str, str, str, str)  # prefix, status, active_ip, srv, op1, op2, error
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, branches: List[Dict], db, max_concurrent: int = 5):
        super().__init__()
        self.branches = branches
        self.db = db
        self.max_concurrent = max_concurrent
        self.stop_requested = False

    def run(self):
        """Запуск асинхронной проверки в потоке"""
        try:
            logger.info(f"Запуск AsyncCheckWorker для {len(self.branches)} подразделений")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._check_all_async())
            finally:
                loop.close()
            logger.info("AsyncCheckWorker завершён")
            self.finished.emit()
        except Exception as e:
            logger.error(f"Критическая ошибка в AsyncCheckWorker: {e}", exc_info=True)
            self.error.emit(str(e))

    async def _check_all_async(self):
        """Асинхронная проверка всех подразделений"""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = []

        for idx, branch in enumerate(self.branches):
            if self.stop_requested:
                logger.info("AsyncCheckWorker: Остановка по запросу в _check_all_async")
                break
            task = asyncio.create_task(self._check_branch_async(branch, idx, semaphore))
            tasks.append(task)

        # Обработка завершения с поддержкой отмены
        for task in asyncio.as_completed(tasks):
            try:
                await task
                if self.stop_requested:
                    logger.info("AsyncCheckWorker: Отмена оставшихся задач")
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    break
            except asyncio.CancelledError:
                continue
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки: {e}", exc_info=True)

    async def _check_branch_async(self, branch: Dict, idx: int, semaphore):
        """Параллельная проверка трёх IP одного подразделения"""
        async with semaphore:
            if self.stop_requested:
                return

            try:
                prefix = branch.get("prefix", "")
                ip = branch.get("ip", "").strip()
                alt_ips = branch.get("alt_ips", [])
                op1_ip = alt_ips[0].strip() if len(alt_ips) > 0 else ""
                op2_ip = alt_ips[1].strip() if len(alt_ips) > 1 else ""

                logger.info(f"[{idx+1}/{len(self.branches)}] Проверка {prefix}...")

                # === ПАРАЛЛЕЛЬНАЯ ПРОВЕРКА ===
                ip_checks = {
                    'server': ip,
                    'op1': op1_ip,
                    'op2': op2_ip
                }

                check_tasks = {
                    key: asyncio.create_task(self._check_ip_async(addr))
                    for key, addr in ip_checks.items() if addr
                }

                results = {'server': 'Нет', 'op1': 'Нет', 'op2': 'Нет'}
                for key, task in check_tasks.items():
                    try:
                        if await task:
                            results[key] = 'Да'
                    except Exception:
                        pass

                server_status = results['server']
                op1_status = results['op1']
                op2_status = results['op2']

                # Определяем активный IP (первый живой)
                active_ip = ""
                if server_status == "Да":
                    active_ip = ip
                elif op1_status == "Да":
                    active_ip = op1_ip
                elif op2_status == "Да":
                    active_ip = op2_ip

                status = "online" if "Да" in results.values() else "offline"

                # Обновляем данные
                branch["status"] = status
                branch["alive_ips"] = ",".join([
                    ip if server_status == "Да" else "",
                    op1_ip if op1_status == "Да" else "",
                    op2_ip if op2_status == "Да" else ""
                ]).strip(",")

                self.db.update_branch_status(prefix, active_ip, status)

                # Сигнал в UI
                self.status_updated.emit(
                    prefix, status, active_ip, server_status, op1_status, op2_status, ""
                )

                logger.info(f"✓ {prefix}: {status} (srv={server_status}, op1={op1_status}, op2={op2_status})")

                if not self.stop_requested:
                    self.progress.emit(idx + 1, len(self.branches))

            except Exception as e:
                logger.error(f"Ошибка при проверке {branch.get('prefix', 'unknown')}: {e}", exc_info=True)
                self.status_updated.emit(
                    branch.get("prefix", "unknown"), "error", "", "?", "?", "?", str(e)
                )
                if not self.stop_requested:
                    self.progress.emit(idx + 1, len(self.branches))

    async def _check_ip_async(self, ip: str, port: int = 445, timeout: float = 1.0) -> bool:
        """Асинхронная проверка доступности IP через TCP-соединение на порт 445"""
        if not ip or not ip.strip():
            return False
        try:
            await asyncio.wait_for(
                asyncio.open_connection(ip.strip(), port),
                timeout=timeout
            )
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False
        except Exception:
            return False

# ============================================================================
# TRANSFER WORKER - Передача файлов по SMB
# ============================================================================

class TransferWorker(QThread):
    """Передача файлов на подразделения по SMB"""
    progress = pyqtSignal(int, int)  # current, total
    transfer_status = pyqtSignal(str, str, str)  # prefix, ip, status
    error_logged = pyqtSignal(str, str, str)  # prefix, branch_name, error_msg
    finished = pyqtSignal()
    error = pyqtSignal(str)

    SMB_USERNAME = "Администратор"
    SMB_PASSWORD = "2445vr7"
    SMB_SHARE = "d$"
    SMB_PORT = 445
    SMB_TIMEOUT = 10

    def __init__(self, branches: List[Dict], files: List[str], ip_selection: Dict[str, List[str]], db):
        super().__init__()
        self.branches = branches
        self.files = files
        self.ip_selection = ip_selection  # {prefix: [ips]}
        self.db = db
        self.stop_requested = False

    def run(self):
        try:
            # --- Подсчёт общего количества операций (файлов * IPs) ---
            total_files_to_process = 0
            for file_path_str in self.files:
                file_path = Path(file_path_str)
                if file_path.is_file():
                    total_files_to_process += len(self.ip_selection.get(self._get_prefix_for_file(file_path_str), []))
                elif file_path.is_dir():
                    # Подсчитываем файлы в папке рекурсивно
                    prefix = self._get_prefix_for_file(file_path_str)
                    ip_count = len(self.ip_selection.get(prefix, []))
                    file_count_in_dir = sum(1 for p in file_path.rglob('*') if p.is_file())
                    total_files_to_process += file_count_in_dir * ip_count
            # ----------------------------------------------------------

            logger.info(f"Начало передачи (файлов для обработки: {total_files_to_process})...")
            processed_count = 0
            for branch in self.branches:
                if self.stop_requested:
                    logger.info("Передача прервана пользователем")
                    self.transfer_status.emit("!", "!", "Прервано пользователем")
                    break
                prefix = branch.get("prefix", "")
                name = branch.get("name", prefix)
                selected_ips = self.ip_selection.get(prefix, [])
                if not selected_ips:
                    logger.warning(f"Нет IP для {prefix}")
                    continue
                for target_ip in selected_ips:
                    if self.stop_requested:
                        logger.info("Передача прервана пользователем")
                        self.transfer_status.emit("!", "!", "Прервано пользователем")
                        break
                    try:
                        logger.info(f"Передача на {prefix} ({target_ip})...")
                        result = self._transfer_files(prefix, target_ip, self.files)
                        if result["success"]:
                            msg = f"✓ Передача успешна"
                            logger.info(f"{prefix} ({target_ip}): {msg}")
                            self.transfer_status.emit(prefix, target_ip, msg)
                        else:
                            error_msg = result.get("error", "Неизвестная ошибка")
                            logger.warning(f"{prefix} ({target_ip}): Ошибка передачи - {error_msg}")
                            self.transfer_status.emit(prefix, target_ip, f"✗ {error_msg}")
                            self.error_logged.emit(prefix, name, f"Ошибка передачи: {error_msg}")
                    except Exception as e:
                        logger.error(f"Ошибка при передаче на {prefix} ({target_ip}): {e}", exc_info=True)
                        self.transfer_status.emit(prefix, target_ip, f"✗ Исключение")
                        self.error_logged.emit(prefix, name, f"Ошибка: {str(e)}")
            logger.info("✓ Передача завершена")
            self.finished.emit()
        except Exception as e:
            logger.error(f"Критическая ошибка в TransferWorker: {e}", exc_info=True)
            self.error.emit(str(e))

    def _get_prefix_for_file(self, file_path_str: str) -> str:
        """
        Вспомогательная функция для получения префикса, связанного с передаваемым файлом/папкой.
        В текущей реализации мы не можем точно знать, для какого префикса передаётся файл,
        если файл был выбран напрямую, а не через таблицу.
        Для упрощения, мы можем вернуть префикс, связанный с первым выбранным подразделением,
        или использовать глобальную переменную/свойство, если оно доступно.
        Пока используем первый префикс из ip_selection, если он есть.
        """
        # Это неидеальное решение, но для текущего потока оно может сработать.
        # Лучше передавать список (prefix, files_list) в конструктор.
        if self.ip_selection:
            return next(iter(self.ip_selection.keys()))
        return "unknown_prefix"
    

    def _transfer_single_file(self, file_path: Path, smb_base_path: str, prefix: str, target_ip: str, open_file_func, mkdir_func, listdir_func) -> Dict:
        """Передать один файл, используя переданные функции smbclient"""
        try:
            file_name = file_path.name
            smb_file_path = f"{smb_base_path}/{file_name}"
            logger.info(f"[{prefix}] Копирование {file_path} -> {smb_file_path}")
            with open(file_path, 'rb') as local_file:
                with open_file_func(smb_file_path, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as smb_file:
                    smb_file.write(local_file.read())
            logger.info(f"[{prefix}] Файл {file_name} успешно передан на {target_ip}")
            return {"success": True}
        except Exception as e:
            logger.error(f"[{prefix}] Ошибка передачи файла {file_path}: {e}", exc_info=True)
            return {"success": False, "error": f"Ошибка передачи файла {file_path}: {e}"}

    def _transfer_directory_contents(self, dir_path: Path, smb_base_path: str, prefix: str, target_ip: str, open_file_func, mkdir_func, listdir_func) -> Dict:
        """Передать ПАПКУ целиком (включая её имя) и её содержимое рекурсивно по SMB"""
        try:
            dir_name = dir_path.name  # Имя корневой папки
            smb_root_path = f"{smb_base_path}/{dir_name}"
            logger.info(f"[{prefix}] Передача папки {dir_path} как '{dir_name}' на {target_ip}")

            # Создаём корневую папку на SMB
            try:
                listdir_func(smb_root_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                logger.debug(f"[{prefix}] Корневая папка {smb_root_path} уже существует")
            except:
                mkdir_func(smb_root_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                logger.info(f"[{prefix}] Создана корневая папка {smb_root_path} на {target_ip}")

            # Рекурсивно обходим содержимое
            for root, dirs, files in os.walk(dir_path):
                root_path = Path(root)
                # Относительный путь от исходной папки (включая вложенные подпапки)
                rel_path = root_path.relative_to(dir_path)

                # Создаём все подпапки
                for d in dirs:
                    local_subdir = root_path / d
                    rel_subdir = rel_path / d
                    smb_subdir_path = f"{smb_root_path}/{rel_subdir.as_posix()}"
                    try:
                        listdir_func(smb_subdir_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                    except:
                        mkdir_func(smb_subdir_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                        logger.info(f"[{prefix}] Создана подпапка {smb_subdir_path}")

                # Передаём файлы
                for f in files:
                    if self.stop_requested:
                        logger.info(f"[{prefix}] Передача прервана при обработке файла {f} в {root_path}")
                        return {"success": False, "error": "Прервано пользователем"}

                    local_file = root_path / f
                    rel_file = rel_path / f
                    smb_file_path = f"{smb_root_path}/{rel_file.as_posix()}"

                    logger.info(f"[{prefix}] Копирование {local_file} -> {smb_file_path}")
                    try:
                        with open(local_file, 'rb') as src:
                            with open_file_func(smb_file_path, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as dst:
                                dst.write(src.read())
                        logger.info(f"[{prefix}] Файл {rel_file} успешно передан")
                    except Exception as e:
                        logger.error(f"[{prefix}] Ошибка передачи {local_file}: {e}", exc_info=True)
                        return {"success": False, "error": f"Ошибка передачи {local_file}: {e}"}

            logger.info(f"[{prefix}] Папка {dir_name} успешно передана на {target_ip}")
            return {"success": True}
        except Exception as e:
            logger.error(f"[{prefix}] Ошибка передачи папки {dir_path}: {e}", exc_info=True)
            return {"success": False, "error": f"Ошибка передачи папки {dir_path}: {e}"}
        
    def _transfer_files(self, prefix: str, target_ip: str, file_paths: List[str]) -> Dict:
            """Передать файлы или папки по SMB (основной метод для TransferWorker)"""
            try:
                # Проверка доступности IP
                if not self._check_ip(target_ip, self.SMB_PORT, self.SMB_TIMEOUT):
                    return {"success": False, "error": f"Не удалось подключиться на порт {self.SMB_PORT}"}

                # Импорт библиотеки для SMB
                try:
                    from smbclient import open_file, mkdir, listdir
                except ImportError:
                    logger.error("smbclient не установлен. Установите: pip install smbprotocol[smbclient]")
                    return {"success": False, "error": "smbclient не установлен. pip install smbprotocol[smbclient]"}

                # Формирование URL для SMB
                smb_base_path = f"\\\\{target_ip}\\{self.SMB_SHARE.lstrip('/')}"
                logger.info(f"[{prefix}] Подключение к SMB: {smb_base_path}")

                # Передача файлов/папок
                for file_path_str in file_paths:
                    file_path = Path(file_path_str)
                    if file_path.is_file():
                        if self.stop_requested:
                            return {"success": False, "error": "Прервано пользователем"}
                        result = self._transfer_single_file(file_path, smb_base_path, prefix, target_ip, open_file, mkdir, listdir)
                        if not result["success"]:
                            return result
                    elif file_path.is_dir():
                        if self.stop_requested:
                            return {"success": False, "error": "Прервано пользователем"}
                        result = self._transfer_directory_contents(file_path, smb_base_path, prefix, target_ip, open_file, mkdir, listdir)
                        if not result["success"]:
                            return result
                    else:
                        logger.warning(f"[{prefix}] Пропускаю не файл/папку: {file_path_str}")
                        continue

                return {"success": True}
            except Exception as e:
                logger.error(f"[{prefix}] Ошибка передачи на {target_ip}: {e}", exc_info=True)
                return {"success": False, "error": str(e)}


    @staticmethod
    def _check_ip(ip: str, port: int = 445, timeout: float = 5.0) -> bool:
        """Проверка доступности IP"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip.strip(), port))
            sock.close()
            return result == 0
        except Exception:
            return False

# ============================================================================
# AUTOMAT ERROR WORKER - Автоматическая передача из errors.xlsx v1.11.1 (исправленный 2)
# ============================================================================

class AutomatErrorWorker(QThread):
    """Автоматическая передача файлов из errors.xlsx с параллельной проверкой IP"""
    progress = pyqtSignal(int, int)  # current, total
    transfer_status = pyqtSignal(str, str, str)  # prefix, ip, status
    error_logged = pyqtSignal(str, str, str)  # prefix, branch_name, error_msg
    finished = pyqtSignal()
    error = pyqtSignal(str)

    SMB_USERNAME = "Администратор"
    SMB_PASSWORD = "2445vr7"
    SMB_SHARE = "d$"
    SMB_PORT = 445
    SMB_TIMEOUT = 10

    def __init__(self, errors_file: str, db, all_branches: List[Dict], # all_branches больше не используется для поиска
                 selected_files: List[str], max_concurrent: int = 10):
        super().__init__()
        self.errors_file = Path(errors_file)
        self.db = db
        # self.all_branches больше не используется для поиска IP в AutomatErrorWorker
        # self.all_branches = all_branches
        self.selected_files = selected_files # Список файлов для передачи
        self.max_concurrent = max_concurrent  # Параллельная проверка до 10 IP
        self.stop_requested = False

    def run(self):
        try:
            logger.info(f"[АВТОМАТ] Запуск автоматической передачи")
            logger.info(f"[АВТОМАТ] Файл ошибок: {self.errors_file}")
            if not self.errors_file.exists():
                logger.error(f"[АВТОМАТ] Файл {self.errors_file} не найден")
                self.error.emit(f"Файл {self.errors_file} не найден")
                return

            # Читаем ошибки из xlsx
            error_records = self._read_errors_file()
            if not error_records:
                logger.info("[АВТОМАТ] Нет записей для обработки")
                self.finished.emit()
                return

            logger.info(f"[АВТОМАТ] Найдено {len(error_records)} записей для обработки")

            # Извлекаем IP и связанные с ними префиксы/имена из файла
            # Теперь будем хранить {ip: set_of_tuples(prefix, branch_name)} чтобы избежать дубликатов
            ips_to_process = {}  # {ip: {(prefix, branch_name)}}
            for record in error_records:
                try:
                    # ИСПРАВЛЕНИЕ: Убеждаемся что это строка, а не int!
                    prefix = str(record.get("Префикс", "")).strip()
                    ip = str(record.get("IP", "")).strip()
                    branch_name = str(record.get("Подразделение", "")).strip()
                    if ip: # Теперь ключевой - IP
                        if ip not in ips_to_process:
                            ips_to_process[ip] = set()
                        ips_to_process[ip].add((prefix, branch_name))
                except Exception as e:
                    logger.warning(f"[АВТОМАТ] Ошибка обработки записи: {e}")
                    continue

            logger.info(f"[АВТОМАТ] К обработке: {len(ips_to_process)} уникальных IP из ошибок")

            # Асинхронная обработка
            # Создаём новый event loop ВНУТРИ потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Запускаем корутину в этом loop
                loop.run_until_complete(self._process_all_async(ips_to_process))
            finally:
                # Обязательно закрываем loop
                loop.close()
            logger.info("[АВТОМАТ] Работа завершена")
            self.finished.emit()
        except Exception as e:
            logger.error(f"[АВТОМАТ] Критическая ошибка: {e}", exc_info=True)
            self.error.emit(str(e))

    async def _process_all_async(self, ips_to_process: Dict):
        """Асинхронная обработка всех IP из ошибок"""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = []
        # Подсчёт общего количества IP к обработке
        total_operations = len(ips_to_process)
        current_counter = {"count": 0}

        for ip in ips_to_process:
            # Проверяем stop_requested перед созданием задачи
            if self.stop_requested:
                logger.info("[АВТОМАТ] Остановка по запросу в _process_all_async")
                break
            task = asyncio.create_task(self._process_ip_async(
                ip, ips_to_process[ip], semaphore, current_counter, total_operations
            ))
            tasks.append(task)

        # Ждём выполнения задач, проверяя stop_requested
        for task in asyncio.as_completed(tasks):
            try:
                await task
                if self.stop_requested:
                    logger.info("[АВТОМАТ] Отмена оставшихся задач по запросу")
                    # Отменяем оставшиеся задачи
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    break
            except asyncio.CancelledError:
                continue # Игнорируем отменённые задачи
            except Exception as e:
                logger.error(f"[АВТОМАТ] Ошибка в задаче обработки: {e}", exc_info=True)

    async def _process_ip_async(self, ip: str, prefixes_and_names: set, semaphore,
                                       counter: dict, total: int):
        """Асинхронная обработка одного IP из ошибок"""
        async with semaphore:
            # Проверяем stop_requested при входе в задачу
            if self.stop_requested:
                return
            try:
                counter["count"] += 1
                current = counter["count"]

                # Берём первое попавшееся имя/префикс для логирования, если они есть
                example_prefix = "unknown_prefix"
                example_branch_name = "unknown_branch"
                if prefixes_and_names:
                    example_prefix, example_branch_name = next(iter(prefixes_and_names))

                logger.info(f"[АВТОМАТ] ({current}/{total}) Проверка IP {ip} (из ошибок)...")

                # Асинхронная проверка доступности
                if not await self._check_ip_async(ip, self.SMB_PORT, 2.0):
                    logger.info(f"[АВТОМАТ] IP {ip} - недоступен, пропускаем")
                    # Проверяем stop_requested перед обновлением прогресса
                    if not self.stop_requested:
                        self.progress.emit(current, total)
                    return

                logger.info(f"[АВТОМАТ] IP {ip} - доступен, начинаем передачу...")

                # IP доступен - передаём файлы
                result = self._transfer_files_to_d(example_prefix, ip, self.selected_files)
                if result["success"]:
                    logger.info(f"[АВТОМАТ] ✓ IP {ip}: Передача успешна")
                    self.transfer_status.emit(example_prefix, ip, "✓ Передача успешна")
                    # Удаляем *все* записи для этого IP из xlsx
                    for prefix, _ in prefixes_and_names:
                        self._remove_error_record(prefix, ip)
                else:
                    error_msg = result.get("error", "Неизвестная ошибка")
                    logger.warning(f"[АВТОМАТ] ✗ IP {ip}: {error_msg}")
                    self.transfer_status.emit(example_prefix, ip, f"✗ {error_msg}")
                    self.error_logged.emit(example_prefix, example_branch_name, error_msg)
                # Проверяем stop_requested перед обновлением прогресса
                if not self.stop_requested:
                    self.progress.emit(current, total)
            except Exception as e:
                counter["count"] += 1
                logger.error(f"[АВТОМАТ] Ошибка обработки IP {ip}: {e}", exc_info=True)
                # Проверяем stop_requested перед обновлением прогресса
                if not self.stop_requested:
                    self.progress.emit(counter["count"], total)

    async def _check_ip_async(self, ip: str, port: int = 445, timeout: float = 2.0) -> bool:
        """Асинхронная проверка доступности IP"""
        if not ip or not ip.strip():
            return False
        try:
            _, _ = await asyncio.wait_for(
                asyncio.open_connection(ip.strip(), port),
                timeout=timeout
            )
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False
        except Exception:
            return False

    def _transfer_files_to_d(self, prefix: str, target_ip: str, file_paths: List[str]) -> Dict:
        """Передача файлов на D$ по SMB (копия из TransferWorker с исправлениями)"""
        try:
            # Проверка доступности IP
            if not self._check_ip(target_ip, self.SMB_PORT, self.SMB_TIMEOUT):
                return {"success": False, "error": f"Не удалось подключиться на порт {self.SMB_PORT}"}

            # Импорт библиотеки для SMB (установите: pip install smbprotocol)
            try:
                from smbclient import open_file, mkdir, listdir
            except ImportError:
                logger.error("smbclient не установлен. Установите: pip install smbprotocol[smbclient]")
                return {"success": False, "error": "smbclient не установлен. pip install smbprotocol[smbclient]"}

            # Формирование URL для SMB
            smb_base_path = f"\\\\{target_ip}\\{self.SMB_SHARE.lstrip('/')}"
            logger.info(f"[{prefix}] Подключение к SMB: {smb_base_path}")

            # Проверка доступности шары
            try:
                listdir(smb_base_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                logger.debug(f"[{prefix}] Шара {self.SMB_SHARE} доступна на {target_ip}")
            except Exception as e:
                logger.error(f"[{prefix}] Ошибка доступа к шаре {smb_base_path}: {e}")
                return {"success": False, "error": f"Ошибка доступа к шаре: {e}"}

            # Передача файлов/папок
            for file_path_str in file_paths:
                file_path = Path(file_path_str)
                if file_path.is_file():
                    # Передаём один файл
                    if self.stop_requested:
                        logger.info(f"[{prefix}] Передача прервана пользователем при обработке {file_path}")
                        return {"success": False, "error": "Прервано пользователем"}
                    result = self._transfer_single_file(file_path, smb_base_path, prefix, target_ip, open_file, mkdir, listdir)
                    if not result["success"]:
                        return result
                elif file_path.is_dir():
                    # Передаём содержимое папки
                    if self.stop_requested:
                        logger.info(f"[{prefix}] Передача прервана пользователем при обработке папки {file_path}")
                        return {"success": False, "error": "Прервано пользователем"}
                    result = self._transfer_directory_contents(file_path, smb_base_path, prefix, target_ip, open_file, mkdir, listdir)
                    if not result["success"]:
                        return result
                else:
                    logger.warning(f"[{prefix}] Пропускаю не файл/папку в Automat: {file_path_str}")
                    continue

            return {"success": True}
        except Exception as e:
            logger.error(f"[{prefix}] Ошибка передачи на {target_ip}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _transfer_single_file(self, file_path: Path, smb_base_path: str, prefix: str, target_ip: str, open_file_func, mkdir_func, listdir_func) -> Dict:
        """Передать один файл (копия из TransferWorker)"""
        try:
            file_name = file_path.name
            smb_file_path = f"{smb_base_path}/{file_name}"
            logger.info(f"[{prefix}] Копирование {file_path} -> {smb_file_path}")
            with open(file_path, 'rb') as local_file:
                with open_file_func(smb_file_path, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as smb_file:
                    smb_file.write(local_file.read())
            logger.info(f"[{prefix}] Файл {file_name} успешно передан на {target_ip}")
            return {"success": True}
        except Exception as e:
            logger.error(f"[{prefix}] Ошибка передачи файла {file_path}: {e}", exc_info=True)
            return {"success": False, "error": f"Ошибка передачи файла {file_path}: {e}"}

    def _transfer_directory_contents(self, dir_path: Path, smb_base_path: str, prefix: str, target_ip: str, open_file_func, mkdir_func, listdir_func) -> Dict:
        """Передать ПАПКУ целиком (включая её имя) и её содержимое рекурсивно по SMB"""
        try:
            dir_name = dir_path.name  # Имя корневой папки
            smb_root_path = f"{smb_base_path}/{dir_name}"
            logger.info(f"[{prefix}] Передача папки {dir_path} как '{dir_name}' на {target_ip}")

            # Создаём корневую папку на SMB
            try:
                listdir_func(smb_root_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                logger.debug(f"[{prefix}] Корневая папка {smb_root_path} уже существует")
            except:
                mkdir_func(smb_root_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                logger.info(f"[{prefix}] Создана корневая папка {smb_root_path} на {target_ip}")

            # Рекурсивно обходим содержимое
            for root, dirs, files in os.walk(dir_path):
                root_path = Path(root)
                # Относительный путь от исходной папки (включая вложенные подпапки)
                rel_path = root_path.relative_to(dir_path)

                # Создаём все подпапки
                for d in dirs:
                    local_subdir = root_path / d
                    rel_subdir = rel_path / d
                    smb_subdir_path = f"{smb_root_path}/{rel_subdir.as_posix()}"
                    try:
                        listdir_func(smb_subdir_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                    except:
                        mkdir_func(smb_subdir_path, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                        logger.info(f"[{prefix}] Создана подпапка {smb_subdir_path}")

                # Передаём файлы
                for f in files:
                    if self.stop_requested:
                        logger.info(f"[{prefix}] Передача прервана при обработке файла {f} в {root_path}")
                        return {"success": False, "error": "Прервано пользователем"}

                    local_file = root_path / f
                    rel_file = rel_path / f
                    smb_file_path = f"{smb_root_path}/{rel_file.as_posix()}"

                    logger.info(f"[{prefix}] Копирование {local_file} -> {smb_file_path}")
                    try:
                        with open(local_file, 'rb') as src:
                            with open_file_func(smb_file_path, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as dst:
                                dst.write(src.read())
                        logger.info(f"[{prefix}] Файл {rel_file} успешно передан")
                    except Exception as e:
                        logger.error(f"[{prefix}] Ошибка передачи {local_file}: {e}", exc_info=True)
                        return {"success": False, "error": f"Ошибка передачи {local_file}: {e}"}

            logger.info(f"[{prefix}] Папка {dir_name} успешно передана на {target_ip}")
            return {"success": True}
        except Exception as e:
            logger.error(f"[{prefix}] Ошибка передачи папки {dir_path}: {e}", exc_info=True)
            return {"success": False, "error": f"Ошибка передачи папки {dir_path}: {e}"}


    def _read_errors_file(self) -> List[Dict]:
        """Прочитать данные из errors.xlsx"""
        try:
            import pandas as pd
        except ImportError:
            logger.error("[АВТОМАТ] pandas не установлена")
            return []

        try:
            df = pd.read_excel(str(self.errors_file))
            records = df.to_dict('records')
            logger.info(f"[АВТОМАТ] Прочитано {len(records)} строк из {self.errors_file}")
            return records
        except Exception as e:
            logger.error(f"[АВТОМАТ] Ошибка чтения файла: {e}", exc_info=True)
            return []

    def _remove_error_record(self, prefix: str, ip: str):
        """Удалить запись из errors.xlsx"""
        try:
            import pandas as pd
            df = pd.read_excel(str(self.errors_file))
            # ИСПРАВЛЕНИЕ: Конвертируем в строки перед сравнением
            # Удаляем все строки, где префикс и IP совпадают
            df_filtered = df[
                ~((df['Префикс'].astype(str).str.strip() == prefix.strip()) &
                  (df['IP'].astype(str).str.strip() == ip.strip()))
            ]
            if len(df_filtered) < len(df):
                # Есть что удалять
                df_filtered.to_excel(str(self.errors_file), index=False)
                logger.info(f"[АВТОМАТ] Удалены записи: {prefix} ({ip})")
        except Exception as e:
            logger.warning(f"[АВТОМАТ] Не удалось удалить запись: {e}")

    @staticmethod
    def _check_ip(ip: str, port: int = 445, timeout: float = 5.0) -> bool:
        """Проверка доступности IP (копия из TransferWorker)"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip.strip(), port))
            sock.close()
            return result == 0
        except Exception:
            return False
