"""
network.py - Проверка доступности IP/портов, TCP и ICMP ping

Функции:
- Проверка TCP подключения к основному IP
- Перебор альтернативных IP (*.10, *.20, *.30)
- ICMP ping для диагностики
- Повторная попытка при ошибке передачи
- Возврат информации о каждом проверенном IP
"""

import socket
import logging
import subprocess
import sys
from typing import Tuple, Optional, List, Dict
import time
import platform

logger = logging.getLogger("distributor")


class IPCheckResult:
    """Результат проверки IP"""
    def __init__(self, ip: str, port: int, role: str, status: bool, error: Optional[str] = None, response_time: float = 0):
        self.ip = ip
        self.port = port
        self.role = role  # "server", "operator", "operator2"
        self.status = status
        self.error = error
        self.response_time = response_time
    
    def to_dict(self) -> Dict:
        return {
            'ip': self.ip,
            'port': self.port,
            'role': self.role,
            'status': self.status,
            'error': self.error,
            'response_time': self.response_time
        }


class NetworkChecker:
    """Проверка доступности сетевых узлов"""
    
    def __init__(self, default_port: int = 445, timeout_ms: int = 3000):
        """
        Args:
            default_port: порт по умолчанию для проверки (445 для SMB)
            timeout_ms: таймаут подключения в миллисекундах
        """
        self.default_port = default_port
        self.timeout_s = timeout_ms / 1000.0  # конвертируем в секунды
    
    def check_tcp_connection(self, ip: str, port: int = None) -> Tuple[bool, Optional[str], float]:
        """
        Попытка подключиться к IP:port через TCP
        
        Args:
            ip: IP адрес
            port: номер порта (если None, используется default_port)
        
        Returns:
            (успех, ошибка, время_ответа_ms) - кортеж
            Если успех=True, ошибка=None
            Если успех=False, ошибка содержит описание проблемы
        """
        if port is None:
            port = self.default_port
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout_s)
            
            start_time = time.time()
            sock.connect((ip, port))
            response_time = (time.time() - start_time) * 1000  # в миллисекундах
            sock.close()
            
            logger.debug(f"TCP подключение к {ip}:{port} успешно ({response_time:.0f}ms)")
            return True, None, response_time
            
        except socket.timeout:
            error = f"Таймаут подключения ({self.timeout_s*1000:.0f}ms)"
            logger.debug(f"TCP подключение к {ip}:{port} - {error}")
            return False, error, 0
        except socket.gaierror:
            error = "Неизвестный хост"
            logger.debug(f"TCP подключение к {ip}:{port} - {error}")
            return False, error, 0
        except ConnectionRefusedError:
            error = "Соединение отклонено (порт закрыт)"
            logger.debug(f"TCP подключение к {ip}:{port} - {error}")
            return False, error, 0
        except OSError as e:
            error = f"Ошибка сети: {str(e)}"
            logger.debug(f"TCP подключение к {ip}:{port} - {error}")
            return False, error, 0
        except Exception as e:
            error = f"Неизвестная ошибка: {str(e)}"
            logger.debug(f"TCP подключение к {ip}:{port} - {error}")
            return False, error, 0
    
    def check_all_ips(self, main_ip: str, alt_ips: List[str], port: int = None) -> Tuple[List[IPCheckResult], str]:
        """
        Проверить все IP адреса (основной и альтернативные) и вернуть результаты
        
        Args:
            main_ip: основной IP адрес
            alt_ips: список альтернативных IP
            port: порт (опционально)
        
        Returns:
            (список_результатов, активный_ip)
            где активный_ip - первый успешный IP или main_ip если все недоступны
        """
        results = []
        active_ip = main_ip
        found_online = False
        
        if port is None:
            port = self.default_port
        
        # Проверяем основной IP (Сервер)
        success, error, response_time = self.check_tcp_connection(main_ip, port)
        result = IPCheckResult(main_ip, port, "server", success, error, response_time)
        results.append(result)
        
        if success:
            active_ip = main_ip
            found_online = True
        
        # Проверяем альтернативные IP (Операторы)
        for idx, alt_ip in enumerate(alt_ips):
            role = f"operator" if idx == 0 else f"operator{idx+1}"
            success, error, response_time = self.check_tcp_connection(alt_ip, port)
            result = IPCheckResult(alt_ip, port, role, success, error, response_time)
            results.append(result)
            
            # Если найден первый успешный IP и основной был недоступен
            if success and not found_online:
                active_ip = alt_ip
                found_online = True
        
        return results, active_ip
    
    def check_branch_availability(self, main_ip: str, alt_ips: list, port: int = None) -> Tuple[str, bool, Optional[str]]:
        """
        Проверить доступность подразделения: основной IP, потом alt_ips
        
        Логика:
        1. Проверяем основной IP (main_ip)
        2. Если не доступен, по очереди проверяем alt_ips в порядке *.10, *.20, *.30
        3. Возвращаем первый успешный IP и статус
        
        Args:
            main_ip: основной IP адрес
            alt_ips: список альтернативных IP
            port: порт (опционально)
        
        Returns:
            (активный_ip, доступен, ошибка)
            активный_ip - IP который ответил или основной, если ошибка
            доступен - True если найден работающий IP
            ошибка - описание проблемы если недоступна
        """
        # Проверяем основной IP
        success, error, _ = self.check_tcp_connection(main_ip, port)
        if success:
            return main_ip, True, None
        
        # Проверяем альтернативные IP (если указаны)
        if alt_ips:
            for alt_ip in alt_ips:
                success, error, _ = self.check_tcp_connection(alt_ip, port)
                if success:
                    logger.info(f"Найден доступный альтернативный IP: {alt_ip} (основной {main_ip} был недоступен)")
                    return alt_ip, True, None
        
        # Ни один IP не доступен
        logger.warning(f"Подразделение недоступно (основной IP {main_ip}, alt_ips {alt_ips}): {error}")
        return main_ip, False, error
    
    def ping_host(self, ip: str) -> Tuple[bool, Optional[str]]:
        """
        ICMP ping для диагностики доступности хоста
        
        Args:
            ip: IP адрес для пинга
        
        Returns:
            (успех, ошибка)
        """
        try:
            if platform.system().lower() == 'windows':
                # Windows: ping с параметром -n
                result = subprocess.run(
                    ['ping', '-n', '1', '-w', '1000', ip],
                    capture_output=True,
                    timeout=5
                )
                success = result.returncode == 0
            else:
                # Linux/Mac: ping с параметром -c
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', '1000', ip],
                    capture_output=True,
                    timeout=5
                )
                success = result.returncode == 0
            
            if success:
                logger.debug(f"ICMP ping к {ip} успешен")
                return True, None
            else:
                error = "Нет ответа на ping"
                logger.debug(f"ICMP ping к {ip} - {error}")
                return False, error
                
        except subprocess.TimeoutExpired:
            error = "Таймаут ping"
            logger.debug(f"ICMP ping к {ip} - {error}")
            return False, error
        except Exception as e:
            error = f"Ошибка ping: {str(e)}"
            logger.debug(f"ICMP ping к {ip} - {error}")
            return False, error


# Глобальный экземпляр
_global_checker = None


def get_network_checker(port: int = 445, timeout_ms: int = 3000) -> NetworkChecker:
    """Получить или создать глобальный экземпляр NetworkChecker"""
    global _global_checker
    if _global_checker is None:
        _global_checker = NetworkChecker(port, timeout_ms)
    return _global_checker
