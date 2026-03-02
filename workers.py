#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workers.py - Асинхронные потоки для Anya Distributor v1.11.2 (исправленный 3)
ОБНОВЛЕНИЯ:
- TransferWorker: исправлена ошибка 'open_file' is not defined
- TransferWorker: исправлена передача папок с использованием os.walk
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
# ASYNC CHECKER - МАКСИМАЛЬНО БЫСТРАЯ проверка (Windows) v1.12.0
# ============================================================================

class AsyncCheckWorker(QThread):
    """
    🔥 Быстрая проверка доступности подразделений для Windows
    Стратегия: ping.exe (0.2с) → если не ответил, порт 445 (0.3с)
    Параллелизм: до 100 одновременных проверок
    """
    progress = pyqtSignal(int, int)
    status_updated = pyqtSignal(str, str, str, str, str, str, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, branches: List[Dict], db, 
                 max_concurrent: int = 100,
                 ping_timeout: float = 0.2,
                 port_timeout: float = 0.3,
                 batch_size: int = 100,
                 pause_between_batches: float = 0.1):
        super().__init__()
        self.branches = branches
        self.db = db
        self.max_concurrent = max_concurrent
        self.ping_timeout = ping_timeout
        self.port_timeout = port_timeout
        self.batch_size = batch_size
        self.pause_between_batches = pause_between_batches
        self.stop_requested = False
        self._ip_cache: Dict[str, tuple] = {}  # {ip: (result, timestamp)}

    def run(self):
        try:
            logger.info(f"🚀 FastCheck: {len(self.branches)} подразделений, "
                        f"параллелизм={self.max_concurrent}, ping={self.ping_timeout}s, port={self.port_timeout}s")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._check_all_async())
            finally:
                loop.close()
            logger.info("✅ FastCheck завершён")
            self.finished.emit()
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в AsyncCheckWorker: {e}", exc_info=True)
            self.error.emit(str(e))

    async def _check_all_async(self):
        """Проверка пачками с кэшированием IP"""
        total = len(self.branches)
        current_global = 0

        for start in range(0, total, self.batch_size):
            if self.stop_requested:
                break

            batch = self.branches[start:start + self.batch_size]
            batch_semaphore = asyncio.Semaphore(self.max_concurrent)

            tasks = [
                self._check_branch_fast_async(branch, idx, batch_semaphore)
                for idx, branch in enumerate(batch, start=start)
            ]

            for coro in asyncio.as_completed(tasks):
                try:
                    await coro
                    current_global += 1
                    if not self.stop_requested:
                        self.progress.emit(current_global, total)
                except asyncio.CancelledError:
                    continue
                except Exception as e:
                    logger.error(f"Ошибка в задаче: {e}", exc_info=True)
                    current_global += 1
                    if not self.stop_requested:
                        self.progress.emit(current_global, total)

            # Пауза между пачками (не для последней)
            if start + self.batch_size < total and not self.stop_requested:
                await asyncio.sleep(self.pause_between_batches)

    async def _check_branch_fast_async(self, branch: Dict, idx: int, semaphore):
        """Проверка одного подразделения (3 IP параллельно)"""
        async with semaphore:
            if self.stop_requested:
                return

            try:
                prefix = branch.get("prefix", "")
                ip = branch.get("ip", "").strip()
                alt_ips = branch.get("alt_ips", [])
                op1_ip = alt_ips[0].strip() if len(alt_ips) > 0 else ""
                op2_ip = alt_ips[1].strip() if len(alt_ips) > 1 else ""

                logger.debug(f"[{idx+1}/{len(self.branches)}] Проверка {prefix}...")

                # 🔥 Параллельная проверка всех 3 IP
                checks = {}
                if ip: checks['server'] = ip
                if op1_ip: checks['op1'] = op1_ip
                if op2_ip: checks['op2'] = op2_ip

                tasks = {key: asyncio.create_task(self._fast_check_ip(addr)) 
                        for key, addr in checks.items()}
                results = {key: 'Нет' for key in checks}

                for key, task in tasks.items():
                    try:
                        if await task:
                            results[key] = 'Да'
                    except Exception:
                        pass

                server_status = results.get('server', 'Нет')
                op1_status = results.get('op1', 'Нет')
                op2_status = results.get('op2', 'Нет')

                active_ip = (ip if server_status == "Да" else 
                            op1_ip if op1_status == "Да" else 
                            op2_ip if op2_status == "Да" else "")
                status = "online" if any(v == "Да" for v in results.values()) else "offline"

                # Обновляем БД
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
                logger.debug(f"✓ {prefix}: {status}")

            except Exception as e:
                logger.error(f"Ошибка при проверке {branch.get('prefix', 'unknown')}: {e}", exc_info=True)
                self.status_updated.emit(
                    branch.get("prefix", "unknown"), "error", "", "?", "?", "?", str(e)
                )

    async def _fast_check_ip(self, ip: str) -> bool:
        """
        🔥 БЫСТРАЯ проверка: ping.exe → порт 445
        Windows-специфичная оптимизация
        """
        if not ip or not ip.strip():
            return False
        
        ip = ip.strip()
        now = time.time()
        
        # 🔥 Кэш: если IP проверяли недавно — возвращаем результат
        if ip in self._ip_cache:
            cached_result, cached_time = self._ip_cache[ip]
            if now - cached_time < 300:  # 5 минут TTL
                logger.debug(f"📦 Кэш: {ip} → {cached_result}")
                return cached_result

        # 1️⃣ Быстрый ping через ping.exe (Windows)
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-n", "1", "-w", f"{int(self.ping_timeout * 1000)}", ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.ping_timeout + 0.1)
            if proc.returncode == 0:
                self._ip_cache[ip] = (True, now)
                return True
        except:
            pass  # ping не прошёл → пробуем порт

        # 2️⃣ Проверка порта 445
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 445),
                timeout=self.port_timeout
            )
            writer.close()
            await writer.wait_closed()
            self._ip_cache[ip] = (True, now)
            return True
        except:
            self._ip_cache[ip] = (False, now)
            return False

    def _cleanup_cache(self):
        """Очистить устаревшие записи кэша"""
        now = time.time()
        expired = [ip for ip, (_, t) in self._ip_cache.items() if now - t > 300]
        for ip in expired:
            del self._ip_cache[ip]

# ============================================================================
# TRANSFER WORKER - Параллельная передача файлов по SMB
# ============================================================================

class TransferWorker(QThread):
    """Параллельная асинхронная передача файлов на подразделения по SMB"""
    progress = pyqtSignal(int, int)  # current, total
    transfer_status = pyqtSignal(str, str, str)  # prefix, ip, status
    error_logged = pyqtSignal(str, str, str)  # prefix, branch_name, error_msg
    finished = pyqtSignal()
    error = pyqtSignal(str)

    SMB_USERNAME = "Администратор"
    SMB_PASSWORD = "2445vr7"
    SMB_SHARE = "d$"
    SMB_PORT = 445
    SMB_TIMEOUT = 1.0

    def __init__(self, branches: List[Dict], files: List[str], ip_selection: Dict[str, List[str]], db, max_concurrent: int = 50):
        super().__init__()
        self.branches = branches
        self.files = files
        self.ip_selection = ip_selection
        self.db = db
        self.max_concurrent = max_concurrent
        self.stop_requested = False
        self._total_tasks = 0
        self._completed_tasks = 0

    def _count_total_tasks(self) -> int:
        total = 0
        for file_path_str in self.files:
            file_path = Path(file_path_str)
            if file_path.is_file():
                for ips in self.ip_selection.values():
                    total += len(ips)
            elif file_path.is_dir():
                file_count = sum(1 for _ in file_path.rglob('*') if _.is_file())
                for ips in self.ip_selection.values():
                    total += file_count * len(ips)
        return total

    def run(self):
        try:
            self._total_tasks = self._count_total_tasks()
            logger.info(f"[TRANSFER] Начало передачи: {self._total_tasks} задач, max_concurrent={self.max_concurrent}")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._transfer_all_async())
            finally:
                loop.close()

            logger.info("✓ Передача завершена")
            self.finished.emit()
        except Exception as e:
            logger.error(f"Критическая ошибка в TransferWorker: {e}", exc_info=True)
            self.error.emit(str(e))

    async def _transfer_all_async(self):
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = []

        for branch in self.branches:
            if self.stop_requested:
                break
            prefix = branch.get("prefix", "")
            name = branch.get("name", prefix)
            selected_ips = self.ip_selection.get(prefix, [])
            if not selected_ips:
                continue

            for target_ip in selected_ips:
                if self.stop_requested:
                    break
                task = asyncio.create_task(
                    self._transfer_to_target_async(prefix, name, target_ip, semaphore)
                )
                tasks.append(task)

        for task in asyncio.as_completed(tasks):
            try:
                await task
            except asyncio.CancelledError:
                continue
            except Exception as e:
                logger.error(f"[TRANSFER] Ошибка в задаче: {e}", exc_info=True)

    async def _transfer_to_target_async(self, prefix: str, name: str, target_ip: str, semaphore):
        async with semaphore:
            if self.stop_requested:
                return

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._smb_transfer_sync,
                prefix, target_ip, self.files
            )

            if result["success"]:
                msg = "✓ Передача успешна"
                logger.info(f"{prefix} ({target_ip}): {msg}")
                self.transfer_status.emit(prefix, target_ip, msg)
            else:
                error_msg = result.get("error", "Неизвестная ошибка")
                logger.warning(f"{prefix} ({target_ip}): {error_msg}")
                self.transfer_status.emit(prefix, target_ip, f"✗ {error_msg}")
                self.error_logged.emit(prefix, name, f"Ошибка передачи: {error_msg}")

            # Обновляем прогресс (одна цель = одна операция)
            self._completed_tasks += 1
            if not self.stop_requested:
                self.progress.emit(self._completed_tasks, self._total_tasks)

    def _smb_transfer_sync(self, prefix: str, target_ip: str, file_paths: List[str]) -> Dict:
        """Синхронная передача (выполняется в executor)"""
        if self.stop_requested:
            return {"success": False, "error": "Прервано пользователем"}

        try:
            if not self._check_ip(target_ip, self.SMB_PORT, self.SMB_TIMEOUT):
                return {"success": False, "error": f"Порт {self.SMB_PORT} недоступен"}

            from smbclient import open_file, mkdir, listdir
            smb_base = f"\\\\{target_ip}\\{self.SMB_SHARE.lstrip('/')}"

            for fp in file_paths:
                p = Path(fp)
                if p.is_file():
                    self._transfer_file_sync(p, smb_base, prefix, target_ip, open_file, mkdir, listdir)
                elif p.is_dir():
                    self._transfer_dir_sync(p, smb_base, prefix, target_ip, open_file, mkdir, listdir)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Общие методы передачи (могут быть вынесены в миксин) ---
    def _transfer_file_sync(self, file_path: Path, smb_base: str, prefix: str, ip: str, open_file, mkdir, listdir):
        name = file_path.name
        remote = f"{smb_base}/{name}"
        with open(file_path, 'rb') as src:
            with open_file(remote, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as dst:
                dst.write(src.read())

    def _transfer_dir_sync(self, dir_path: Path, smb_base: str, prefix: str, ip: str, open_file, mkdir, listdir):
        root_name = dir_path.name
        remote_root = f"{smb_base}/{root_name}"
        try:
            listdir(remote_root, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
        except:
            mkdir(remote_root, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)

        for root, dirs, files in os.walk(dir_path):
            rel = Path(root).relative_to(dir_path)
            for d in dirs:
                remote_dir = f"{remote_root}/{(rel / d).as_posix()}"
                try:
                    listdir(remote_dir, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                except:
                    mkdir(remote_dir, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
            for f in files:
                if self.stop_requested:
                    raise RuntimeError("Прервано пользователем")
                local_file = Path(root) / f
                remote_file = f"{remote_root}/{(rel / f).as_posix()}"
                with open(local_file, 'rb') as src:
                    with open_file(remote_file, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as dst:
                        dst.write(src.read())

    @staticmethod
    def _check_ip(ip: str, port: int = 445, timeout: float = 1.0) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip.strip(), port))
            sock.close()
            return result == 0
        except Exception:
            return False


# ============================================================================
# AUTOMAT ERROR WORKER - Параллельная автоматическая передача из errors.xlsx
# ============================================================================

class AutomatErrorWorker(QThread):
    """Автоматическая передача файлов из errors.xlsx с параллельной проверкой IP"""
    progress = pyqtSignal(int, int)
    transfer_status = pyqtSignal(str, str, str)
    error_logged = pyqtSignal(str, str, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    SMB_USERNAME = "Администратор"
    SMB_PASSWORD = "2445vr7"
    SMB_SHARE = "d$"
    SMB_PORT = 445
    SMB_TIMEOUT = 1.0

    def __init__(self, errors_file: str, db, all_branches: List[Dict],
                 selected_files: List[str], max_concurrent: int = 100,
                 check_settings: dict = None):
        super().__init__()
        self.errors_file = Path(errors_file)
        self.db = db
        self.all_branches = all_branches
        self.selected_files = selected_files
        self.max_concurrent = max_concurrent
        self.stop_requested = False
        # 🔥 Настройки проверки из конфига
        self.check_settings = check_settings or {}
        self._ip_cache: Dict[str, tuple] = {}

    def run(self):
        try:
            logger.info(f"[АВТОМАТ] Запуск автоматической передачи")
            if not self.errors_file.exists():
                logger.error(f"[АВТОМАТ] Файл {self.errors_file} не найден")
                self.error.emit(f"Файл {self.errors_file} не найден")
                return

            error_records = self._read_errors_file()
            if not error_records:
                logger.info("[АВТОМАТ] Нет записей для обработки")
                self.finished.emit()
                return

            branches_to_process = {}
            for record in error_records:
                try:
                    prefix = str(record.get("Префикс", "")).strip()
                    ip = str(record.get("IP", "")).strip()
                    if prefix and ip:
                        if prefix not in branches_to_process:
                            branches_to_process[prefix] = []
                        if ip not in branches_to_process[prefix]:
                            branches_to_process[prefix].append(ip)
                except Exception as e:
                    logger.warning(f"[АВТОМАТ] Ошибка обработки записи: {e}")
                    continue

            logger.info(f"[АВТОМАТ] К обработке: {len(branches_to_process)} подразделений")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._process_all_async(branches_to_process))
            finally:
                loop.close()

            logger.info("[АВТОМАТ] Работа завершена")
            self.finished.emit()
        except Exception as e:
            logger.error(f"[АВТОМАТ] Критическая ошибка: {e}", exc_info=True)
            self.error.emit(str(e))

    async def _process_all_async(self, branches_to_process: Dict[str, List[str]]):
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = []
        total = sum(len(ips) for ips in branches_to_process.values())
        current_counter = {"count": 0}

        for prefix, ips in branches_to_process.items():
            for ip in ips:
                task = self._process_branch_ip_async(prefix, ip, semaphore, current_counter, total)
                tasks.append(task)

        await asyncio.gather(*tasks)

    async def _process_branch_ip_async(self, prefix: str, ip: str, semaphore, counter: dict, total: int):
        async with semaphore:
            if self.stop_requested:
                return
            try:
                counter["count"] += 1
                current = counter["count"]

                branch = next((b for b in self.all_branches if b.get("prefix") == prefix), None)
                if not branch:
                    self.progress.emit(current, total)
                    return

                branch_name = branch.get("name", prefix)
                if not await self._check_ip_async(ip, self.SMB_PORT, 2.0):
                    self.progress.emit(current, total)
                    return

                result = await asyncio.get_event_loop().run_in_executor(
                    None, self._smb_transfer_sync, prefix, ip, self.selected_files
                )

                if result["success"]:
                    self.transfer_status.emit(prefix, ip, "✓ Передача успешна")
                    self._remove_error_record(prefix, ip)
                else:
                    error_msg = result.get("error", "Неизвестная ошибка")
                    self.transfer_status.emit(prefix, ip, f"✗ {error_msg}")
                    self.error_logged.emit(prefix, branch_name, error_msg)

                self.progress.emit(current, total)
            except Exception as e:
                logger.error(f"[АВТОМАТ] Ошибка обработки {prefix} ({ip}): {e}", exc_info=True)
                self.progress.emit(counter["count"], total)

    async def _check_ip_async(self, ip: str, port: int = 445, timeout: float = 0.3) -> bool:
        """Быстрая проверка для Автомата (использует ping + порт)"""
        if not ip or not ip.strip():
            return False
        
        ip = ip.strip()
        
        # 🔥 Ping через ping.exe (Windows)
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-n", "1", "-w", "200", ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=0.3)
            if proc.returncode == 0:
                return True
        except:
            pass
        
        # 🔥 Порт 445
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except:
            return False

    def _smb_transfer_sync(self, prefix: str, target_ip: str, file_paths: List[str]) -> Dict:
        if self.stop_requested:
            return {"success": False, "error": "Прервано пользователем"}
        try:
            if not self._check_ip(target_ip, self.SMB_PORT, self.SMB_TIMEOUT):
                return {"success": False, "error": f"Порт {self.SMB_PORT} недоступен"}
            from smbclient import open_file, mkdir, listdir
            smb_base = f"\\\\{target_ip}\\{self.SMB_SHARE.lstrip('/')}"
            for fp in file_paths:
                p = Path(fp)
                if p.is_file():
                    self._transfer_file_sync(p, smb_base, prefix, target_ip, open_file, mkdir, listdir)
                elif p.is_dir():
                    self._transfer_dir_sync(p, smb_base, prefix, target_ip, open_file, mkdir, listdir)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _transfer_file_sync(self, file_path: Path, smb_base: str, prefix: str, ip: str, open_file, mkdir, listdir):
        name = file_path.name
        remote = f"{smb_base}/{name}"
        with open(file_path, 'rb') as src:
            with open_file(remote, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as dst:
                dst.write(src.read())

    def _transfer_dir_sync(self, dir_path: Path, smb_base: str, prefix: str, ip: str, open_file, mkdir, listdir):
        root_name = dir_path.name
        remote_root = f"{smb_base}/{root_name}"
        try:
            listdir(remote_root, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
        except:
            mkdir(remote_root, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
        for root, dirs, files in os.walk(dir_path):
            rel = Path(root).relative_to(dir_path)
            for d in dirs:
                remote_dir = f"{remote_root}/{(rel / d).as_posix()}"
                try:
                    listdir(remote_dir, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
                except:
                    mkdir(remote_dir, username=self.SMB_USERNAME, password=self.SMB_PASSWORD)
            for f in files:
                if self.stop_requested:
                    raise RuntimeError("Прервано пользователем")
                local_file = Path(root) / f
                remote_file = f"{remote_root}/{(rel / f).as_posix()}"
                with open(local_file, 'rb') as src:
                    with open_file(remote_file, mode='wb', username=self.SMB_USERNAME, password=self.SMB_PASSWORD) as dst:
                        dst.write(src.read())

    @staticmethod
    def _check_ip(ip: str, port: int = 445, timeout: float = 1.0) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip.strip(), port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _read_errors_file(self) -> List[Dict]:
        try:
            import pandas as pd
            df = pd.read_excel(str(self.errors_file))
            return df.to_dict('records')
        except Exception as e:
            logger.error(f"[АВТОМАТ] Ошибка чтения: {e}", exc_info=True)
            return []

    def _remove_error_record(self, prefix: str, ip: str):
        try:
            import pandas as pd
            df = pd.read_excel(str(self.errors_file))
            df = df[~((df['Префикс'].astype(str).str.strip() == prefix.strip()) &
                      (df['IP'].astype(str).str.strip() == ip.strip()))]
            df.to_excel(str(self.errors_file), index=False)
            logger.info(f"[АВТОМАТ] Удалено: {prefix} ({ip})")
        except Exception as e:
            logger.warning(f"[АВТОМАТ] Не удалось удалить: {e}")