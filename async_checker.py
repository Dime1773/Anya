"""
async_checker.py v1.1.1 - Асинхронная проверка доступности IP адресов

Исправления v1.1.1:
- Убрана двухэтапная проверка - она даёт ложные отрицания
- Увеличено количество попыток до 3
- Добавлена прогрессивная проверка с реальным обновлением
- Проверка становится фоновой с мгновенным отображением результатов
"""

import asyncio
import socket
import logging
from typing import Callable, Optional, List, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("distributor")


@dataclass
class IPCheckResult:
    """Результат проверки одного IP"""
    ip: str
    port: int
    role: str  # "server", "operator", "operator2"
    status: bool
    error: Optional[str] = None
    response_time: float = 3.0  # в миллисекундах
    attempts: int = 1  # количество попыток


class AsyncNetworkChecker:
    """Асинхронная проверка доступности IP адресов"""
    
    def __init__(self, default_port: int = 445, timeout_s: float = 1.0):
        """
        Args:
            default_port: порт по умолчанию (445 для SMB)
            timeout_s: таймаут подключения в секундах
        """
        self.default_port = default_port
        self.timeout_s = timeout_s
    
    async def check_tcp_connection(
        self,
        ip: str,
        port: Optional[int] = None,
        max_attempts: int = 64,
        attempt_delay: float = 3.0
    ) -> Tuple[bool, Optional[str], float, int]:
        """
        Надёжная проверка TCP подключения с несколькими попытками
        
        Args:
            ip: IP адрес
            port: порт (если None, используется default_port)
            max_attempts: максимальное количество попыток
            attempt_delay: задержка между попытками в секундах
            
        Returns:
            (успех, ошибка, время_ответа_ms, попытки)
        """
        if port is None:
            port = self.default_port
        
        last_error = None
        total_response_time = 1
        
        for attempt in range(max_attempts):
            try:
                start_time = asyncio.get_event_loop().time()
                
                # Асинхронно пытаемся подключиться
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=self.timeout_s
                )
                
                response_time = (asyncio.get_event_loop().time() - start_time) * 1000
                
                # Закрываем соединение
                writer.close()
                await writer.wait_closed()
                
                logger.debug(f"TCP {ip}:{port} успешно ({response_time:.0f}ms, попытка {attempt+1}/{max_attempts})")
                return True, None, response_time, attempt + 1
            
            except asyncio.TimeoutError:
                last_error = f"Таймаут ({self.timeout_s*1000:.0f}ms)"
                logger.debug(f"TCP {ip}:{port} - {last_error} (попытка {attempt+1}/{max_attempts})")
                
            except ConnectionRefusedError:
                last_error = "Соединение отклонено (порт закрыт)"
                logger.debug(f"TCP {ip}:{port} - {last_error}")
                # Если порт закрыт - нет смысла в повторных попытках
                return False, last_error, 0, attempt + 1
            
            except OSError as e:
                last_error = f"Ошибка сети: {str(e)}"
                logger.debug(f"TCP {ip}:{port} - {last_error}")
                # Сетевые ошибки могут быть временными, пробуем снова
                
            except Exception as e:
                last_error = f"Ошибка: {str(e)}"
                logger.debug(f"TCP {ip}:{port} - {last_error}")
                # Неизвестные ошибки - пробуем снова
            
            # Если не последняя попытка - ждём перед следующей
            if attempt < max_attempts - 1:
                await asyncio.sleep(attempt_delay)
        
        # Все попытки неудачны
        logger.debug(f"TCP {ip}:{port} - все {max_attempts} попыток неудачны")
        return False, last_error, 0, max_attempts
    
    async def check_all_ips_async(
        self,
        main_ip: str,
        alt_ips: List[str],
        port: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        prefix: str = ""
    ) -> Tuple[List[IPCheckResult], str, bool]:
        """
        Асинхронно проверить все IP адреса (основной + альтернативные)
        с немедленным callback для каждого результата
        
        Args:
            main_ip: основной IP (роль "server")
            alt_ips: список альтернативных IP (роли "operator", "operator2", ...)
            port: порт
            progress_callback: функция обратного вызова при каждом результате
            prefix: префикс подразделения для callback
            
        Returns:
            (результаты, активный_ip, найден_рабочий_ip)
        """
        if port is None:
            port = self.default_port
        
        # Подготавливаем список для проверки: (ip, role)
        ips_to_check = [
            (main_ip, "server"),
        ]
        
        for idx, alt_ip in enumerate(alt_ips):
            role = f"operator" if idx == 0 else f"operator{idx+1}"
            ips_to_check.append((alt_ip, role))
        
        # Запускаем все проверки одновременно
        tasks = []
        for ip, role in ips_to_check:
            task = self._check_with_role(ip, port, role, progress_callback, prefix)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Определяем активный IP (первый успешный или основной)
        active_ip = main_ip
        found_online = False
        
        for result in results:
            if result.status:
                active_ip = result.ip
                found_online = True
                break
        
        return results, active_ip, found_online
    
    async def _check_with_role(
        self,
        ip: str,
        port: int,
        role: str,
        progress_callback: Optional[Callable] = None,
        prefix: str = ""
    ) -> IPCheckResult:
        """Вспомогательный метод для проверки одного IP с указанной ролью"""
        success, error, response_time, attempts = await self.check_tcp_connection(ip, port)
        
        result = IPCheckResult(
            ip=ip,
            port=port,
            role=role,
            status=success,
            error=error,
            response_time=response_time,
            attempts=attempts
        )
        
        # Немедленный callback при получении результата
        if progress_callback:
            try:
                status_text = "online" if success else "offline"
                progress_callback(
                    prefix=prefix,
                    ip=ip,
                    role=role,
                    status=status_text,
                    response_time=response_time,
                    attempts=attempts,
                    error=error
                )
            except Exception as e:
                logger.warning(f"Ошибка в progress_callback: {e}")
        
        return result
    
    async def check_many_realtime(
        self,
        branches: List[Dict],
        port: Optional[int] = None,
        max_concurrent: int = 50,
        update_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Проверка с реальным обновлением - каждая проверка сразу отображается
        
        Args:
            branches: список словарей подразделений
                (каждый содержит ip, alt_ips, prefix, name и т.д.)
            port: порт для проверки
            max_concurrent: максимум одновременных TCP коннектов
            update_callback: функция обратного вызова для обновления UI
                (prefix, status, active_ip, all_ips_results, is_final)
        
        Returns:
            словарь результатов
        """
        if port is None:
            port = self.default_port
        
        # Семафор для ограничения одновременных TCP коннектов
        semaphore = asyncio.Semaphore(max_concurrent)
        
        total = len(branches)
        results_dict = {
            'branches': [],
            'total_checked': total,
            'total_online': 0,
            'total_offline': 0,
            'duration_ms': 0
        }
        
        start_time = asyncio.get_event_loop().time()
        completed_count = 0
        online_count = 0
        
        async def check_branch_with_semaphore(branch: Dict, index: int):
            """Вспомогательная функция с семафором и реальным обновлением"""
            nonlocal completed_count, online_count
            
            async with semaphore:
                try:
                    prefix = branch.get('prefix', '')
                    main_ip = branch.get('ip', '')
                    alt_ips = branch.get('alt_ips', [])
                    
                    # Локальная функция callback для каждого IP
                    def ip_callback(ip_prefix, ip_addr, ip_role, ip_status, 
                                  response_time, attempts, error):
                        # Эта функция вызывается для каждого проверенного IP
                        # Можно использовать для детального отображения
                        pass
                    
                    # Проверяем все IP для этого подразделения
                    all_ips_results, active_ip, is_online = await self.check_all_ips_async(
                        main_ip, alt_ips, port, ip_callback, prefix
                    )
                    
                    completed_count += 1
                    if is_online:
                        online_count += 1
                    
                    status = 'online' if is_online else 'offline'
                    error = None if is_online else 'Все IP недоступны'
                    
                    branch_result = {
                        'prefix': prefix,
                        'status': status,
                        'active_ip': active_ip,
                        'error': error,
                        'all_ips': [
                            {
                                'ip': r.ip,
                                'role': r.role,
                                'status': r.status,
                                'error': r.error,
                                'response_time': r.response_time,
                                'attempts': r.attempts
                            }
                            for r in all_ips_results
                        ]
                    }
                    
                    # Обновляем UI с промежуточными результатами
                    if update_callback:
                        try:
                            update_callback(
                                prefix=prefix,
                                status=status,
                                active_ip=active_ip,
                                all_ips_results=all_ips_results,
                                is_final=False,  # Промежуточный результат
                                progress=f"{completed_count}/{total}",
                                online_count=online_count,
                                offline_count=completed_count - online_count
                            )
                        except Exception as e:
                            logger.warning(f"Ошибка в update_callback: {e}")
                    
                    return branch_result
                
                except Exception as e:
                    logger.error(f"Ошибка при проверке подразделения: {e}", exc_info=True)
                    
                    completed_count += 1
                    
                    if update_callback:
                        try:
                            update_callback(
                                prefix=branch.get('prefix', ''),
                                status='error',
                                active_ip='',
                                all_ips_results=[],
                                is_final=False,
                                progress=f"{completed_count}/{total}",
                                online_count=online_count,
                                offline_count=completed_count - online_count - 1,
                                error=str(e)
                            )
                        except:
                            pass
                    
                    return {
                        'prefix': branch.get('prefix', ''),
                        'status': 'unknown',
                        'active_ip': branch.get('ip', ''),
                        'error': str(e),
                        'all_ips': []
                    }
        
        # Создаём задачи для всех подразделений
        tasks = [
            check_branch_with_semaphore(branch, idx)
            for idx, branch in enumerate(branches)
        ]
        
        # Запускаем все задачи одновременно
        logger.info(f"Начинаем проверку {total} подразделений...")
        
        if update_callback:
            try:
                # Начальное обновление
                update_callback(
                    prefix="",
                    status="started",
                    active_ip="",
                    all_ips_results=[],
                    is_final=False,
                    progress=f"0/{total}",
                    online_count=0,
                    offline_count=0
                )
            except:
                pass
        
        branch_results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Заполняем финальные результаты
        results_dict['branches'] = branch_results
        results_dict['total_online'] = sum(
            1 for b in branch_results if b.get('status') == 'online'
        )
        results_dict['total_offline'] = sum(
            1 for b in branch_results if b.get('status') in ['offline', 'unknown']
        )
        results_dict['duration_ms'] = (
            asyncio.get_event_loop().time() - start_time
        ) * 1000
        
        # Финальное обновление UI
        if update_callback:
            try:
                update_callback(
                    prefix="",
                    status="completed",
                    active_ip="",
                    all_ips_results=[],
                    is_final=True,
                    progress=f"{total}/{total}",
                    online_count=results_dict['total_online'],
                    offline_count=results_dict['total_offline'],
                    duration_ms=results_dict['duration_ms']
                )
            except:
                pass
        
        logger.info(
            f"Проверка завершена: {results_dict['total_online']} online, "
            f"{results_dict['total_offline']} offline за {results_dict['duration_ms']:.0f}ms"
        )
        
        return results_dict
    
    async def background_check(
        self,
        branches: List[Dict],
        port: Optional[int] = None,
        interval_minutes: int = 5,
        update_callback: Optional[Callable] = None
    ) -> asyncio.Task:
        """
        Запустить фоновую проверку с заданным интервалом
        
        Args:
            branches: список подразделений для проверки
            port: порт для проверки
            interval_minutes: интервал проверки в минутах
            update_callback: функция для обновления результатов
            
        Returns:
            Task фоновой проверки
        """
        if port is None:
            port = self.default_port
        
        async def background_worker():
            """Фоновая задача для периодической проверки"""
            while True:
                try:
                    logger.info(f"Запуск фоновой проверки {len(branches)} подразделений...")
                    
                    # Выполняем проверку с реальным обновлением
                    await self.check_many_realtime(
                        branches=branches,
                        port=port,
                        max_concurrent=50,
                        update_callback=update_callback
                    )
                    
                    logger.info(f"Фоновая проверка завершена, следующая через {interval_minutes} минут")
                    
                except Exception as e:
                    logger.error(f"Ошибка в фоновой проверке: {e}")
                
                # Ждём перед следующей проверкой
                await asyncio.sleep(interval_minutes * 60)
        
        # Запускаем фоновую задачу
        return asyncio.create_task(background_worker())


# Глобальный экземпляр
_global_async_checker = None


def get_async_checker(port: int = 445, timeout_s: float = 1.0) -> AsyncNetworkChecker:
    """Получить или создать глобальный экземпляр AsyncNetworkChecker"""
    global _global_async_checker
    
    if _global_async_checker is None:
        _global_async_checker = AsyncNetworkChecker(port, timeout_s)
    
    return _global_async_checker