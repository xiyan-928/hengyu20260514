"""
Modbus 短连接辅助：每次通讯新建 client，完成后 close 并延时（无连接池）。

对同一 (ip, port) 使用互斥锁，避免多线程同时访问同一从站。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional, Tuple, TypeVar

from pymodbus.client.sync import ModbusTcpClient
from pymodbus.exceptions import ConnectionException
from modbus_logging import elapsed_ms, log_modbus_event, merge_modbus_context, now_ms

T = TypeVar("T")

POST_CLOSE_DELAY_SEC = 0.3

_locks: Dict[Tuple[str, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def _endpoint_lock(ip: str, port: int) -> threading.Lock:
    key = (str(ip).strip().lower(), int(port))
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def _connect(
    ip: str, port: int, context: Optional[dict] = None
) -> ModbusTcpClient:
    last_err = None
    connect_start_ms = now_ms()
    for delay in (0.0, 0.06, 0.14):
        if delay > 0:
            time.sleep(delay)
        c = ModbusTcpClient(ip, port=int(port), timeout=2.0)
        try:
            if c.connect():
                log_modbus_event(
                    operation="connect",
                    ip=ip,
                    port=int(port),
                    success=True,
                    elapsed_ms_value=elapsed_ms(connect_start_ms),
                    context=merge_modbus_context(context, stage="connect"),
                )
                return c
        except Exception as ex:
            last_err = ex
        try:
            c.close()
        except Exception:
            pass

    detail = f"{ip}:{port}"
    if last_err is not None:
        detail = f"{detail} ({last_err})"
    log_modbus_event(
        operation="connect",
        ip=ip,
        port=int(port),
        success=False,
        error=detail,
        elapsed_ms_value=elapsed_ms(connect_start_ms),
        context=merge_modbus_context(context, stage="connect"),
    )
    raise ConnectionException(f"无法连接 Modbus {detail}")


def run_ephemeral(
    ip: str,
    port: int,
    task: Callable[[ModbusTcpClient], T],
    context: Optional[dict] = None,
) -> T:
    """
    在锁保护下：connect → task(client) → close → sleep(POST_CLOSE_DELAY_SEC)。
    """
    with _endpoint_lock(ip, port):
        client = None
        total_start_ms = now_ms()
        try:
            client = _connect(ip, port, context=context)
            result = task(client)
            log_modbus_event(
                operation="session",
                ip=ip,
                port=int(port),
                success=True,
                elapsed_ms_value=elapsed_ms(total_start_ms),
                context=merge_modbus_context(context, stage="session"),
            )
            return result
        except Exception as ex:
            log_modbus_event(
                operation="session",
                ip=ip,
                port=int(port),
                success=False,
                error=str(ex),
                elapsed_ms_value=elapsed_ms(total_start_ms),
                context=merge_modbus_context(context, stage="session"),
            )
            raise
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            time.sleep(POST_CLOSE_DELAY_SEC)


def get_ephemeral_status_snapshot() -> dict:
    with _locks_guard:
        n = len(_locks)
    return {
        "mode": "ephemeral",
        "post_close_delay_sec": POST_CLOSE_DELAY_SEC,
        "tracked_endpoints": n,
        "total_workers": 0,
        "total_connections": 0,
        "workers": [],
    }
