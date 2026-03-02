# avtomat.py
import asyncio
import time
import logging
import hashlib
import os
from pathlib import Path
from typing import List, Dict, Set, Tuple
from PyQt6.QtCore import QThread, pyqtSignal
from workers import TransferWorker  # чтобы переиспользовать _smb_transfer_sync и _check_ip

logger = logging.getLogger("distributor")

class AvtomatWorker(QThread):
    progress = pyqtSignal(int, int)          # завершено, всего
    transfer_status = pyqtSignal(str, str, str)
    error_logged = pyqtSignal(str, str, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, errors_file: str, selected_files: List[str], max_concurrent: int = 50):
        super().__init__()
        self.errors_file = Path(errors_file)
        self.selected_files = selected_files
        self.max_concurrent = max_concurrent
        self.stop_requested = False
        self.check_integrity = True

    def run(self):
        try:
            if not self.errors_file.exists():
                self.error.emit("Файл ошибок не найден")
                return

            while not self.stop_requested:
                records = self._read_errors()
                if not records:
                    logger.info("[АВТОМАТ] Все записи обработаны")
                    break

                ip_to_records = self._group_by_ip(records)
                total = len(ip_to_records)
                success_count = 0

                logger.info(f"[АВТОМАТ] Обработка {total} IP")

                # Асинхронная обработка всех IP
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    success_count = loop.run_until_complete(
                        self._process_all_ips(ip_to_records)
                    )
                finally:
                    loop.close()

                if success_count == total:
                    break  # всё передано

                if not self.stop_requested:
                    logger.info("[АВТОМАТ] Ожидаю 10 минут до следующей попытки...")
                    for i in range(600):  # 10 минут
                        if self.stop_requested:
                            break
                        time.sleep(1)

            self.finished.emit()
        except Exception as e:
            logger.error(f"[АВТОМАТ] Критическая ошибка: {e}", exc_info=True)
            self.error.emit(str(e))

    def _read_errors(self) -> List[Dict]:
        try:
            import pandas as pd
            df = pd.read_excel(self.errors_file)
            return df.to_dict('records')
        except Exception as e:
            logger.error(f"[АВТОМАТ] Ошибка чтения: {e}")
            return []

    def _group_by_ip(self, records: List[Dict]) -> Dict[str, List[Dict]]:
        mapping = {}
        for r in records:
            try:
                ip = str(r.get("IP", "")).strip()
                if ip:
                    mapping.setdefault(ip, []).append(r)
            except Exception as e:
                logger.warning(f"[АВТОМАТ] Ошибка группировки: {e}")
        return mapping

    async def _process_all_ips(self, ip_map: Dict[str, List[Dict]]) -> int:
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = []
        for ip, records in ip_map.items():
            if self.stop_requested:
                break
            task = self._process_ip(ip, records, semaphore)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return sum(1 for r in results if r is True)

    async def _process_ip(self, ip: str, records: List[Dict], semaphore) -> bool:
        async with semaphore:
            if self.stop_requested:
                return False

            # Берём первый для логирования
            first = records[0]
            prefix = str(first.get("Префикс", "")).strip()
            name = str(first.get("Подразделение", "")).strip()

            # Проверка
            is_alive = await asyncio.get_event_loop().run_in_executor(
                None, self._check_ip, ip, 445, 2.0
            )
            if not is_alive:
                logger.info(f"[АВТОМАТ] {ip} недоступен")
                return False

            # Передача (через унаследованный метод)
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._smb_transfer_sync_with_integrity, prefix, ip
            )

            if result["success"]:
                logger.info(f"[АВТОМАТ] ✓ Успех: {ip}")
                self.transfer_status.emit(prefix, ip, "✓ Успешно")
                # Удалить ВСЕ записи с этим IP
                for rec in records:
                    self._remove_record(rec.get("Префикс"), rec.get("IP"))
                return True
            else:
                error_msg = result.get("error", "Неизвестно")
                logger.warning(f"[АВТОМАТ] ✗ {ip}: {error_msg}")
                self.transfer_status.emit(prefix, ip, f"✗ {error_msg}")
                self.error_logged.emit(prefix, name, error_msg)
                return False

    # --- Повторное использование логики из TransferWorker ---
    def _smb_transfer_sync_with_integrity(self, prefix: str, target_ip: str):
        try:
            from smbclient import open_file, mkdir, listdir
            smb_base = f"\\\\{target_ip}\\d$"
            for fp in self.selected_files:
                p = Path(fp)
                if p.is_file():
                    self._transfer_file_with_hash(p, smb_base, open_file, mkdir)
                elif p.is_dir():
                    self._transfer_dir_with_hash(p, smb_base, open_file, mkdir, listdir)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _transfer_file_with_hash(self, file_path: Path, smb_base: str, open_file, mkdir):
        name = file_path.name
        remote = f"{smb_base}/{name}"
        with open(file_path, 'rb') as src:
            data = src.read()
        with open_file(remote, mode='wb', username="Администратор", password="2445vr7") as dst:
            dst.write(data)

        if self.check_integrity:
            local_hash = self._calculate_sha256(file_path)
            with open_file(remote, mode='rb', username="Администратор", password="2445vr7") as f:
                remote_hash = hashlib.sha256(f.read()).hexdigest()
            if local_hash != remote_hash:
                raise RuntimeError("SHA256 mismatch!")

    def _transfer_dir_with_hash(self, dir_path: Path, smb_base: str, open_file, mkdir, listdir):
        root_name = dir_path.name
        remote_root = f"{smb_base}/{root_name}"
        try:
            listdir(remote_root, username="Администратор", password="2445vr7")
        except:
            mkdir(remote_root, username="Администратор", password="2445vr7")

        for root, dirs, files in os.walk(dir_path):
            rel = Path(root).relative_to(dir_path)
            for d in dirs:
                remote_dir = f"{remote_root}/{(rel / d).as_posix()}"
                try:
                    listdir(remote_dir, ...)
                except:
                    mkdir(remote_dir, ...)
            for f in files:
                local_file = Path(root) / f
                remote_file = f"{remote_root}/{(rel / f).as_posix()}"
                self._transfer_file_with_hash(local_file, smb_base, open_file, mkdir)

    def _calculate_sha256(self, filepath: Path) -> str:
        hash_sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    def _check_ip(self, ip: str, port: int = 445, timeout: float = 5.0) -> bool:
        try:
            import socket
            sock = socket.socket()
            sock.settimeout(timeout)
            res = sock.connect_ex((ip.strip(), port))
            sock.close()
            return res == 0
        except:
            return False

    def _remove_record(self, prefix, ip):
        try:
            import pandas as pd
            df = pd.read_excel(self.errors_file)
            df = df[~((df['Префикс'].astype(str).str.strip() == str(prefix).strip()) &
                      (df['IP'].astype(str).str.strip() == str(ip).strip()))]
            df.to_excel(self.errors_file, index=False)
        except Exception as e:
            logger.warning(f"[АВТОМАТ] Не удалено {prefix}/{ip}: {e}")