"""
modbus_coils 专用：长连接 + 按端点互斥。

线圈侧需周期性（如每 5s）读状态，短连接频繁 connect/close 易触发设备拒连；
此处对 (ip, port) 维持单个 ModbusTcpClient，直至 TCP 级错误或显式 invalidate。
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Tuple, TypeVar

from pymodbus.client.sync import ModbusTcpClient
from pymodbus.exceptions import ConnectionException

T = TypeVar("T")

_clients: Dict[Tuple[str, int], ModbusTcpClient] = {}
_locks: Dict[Tuple[str, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def _key(ip: str, port: int) -> Tuple[str, int]:
    return (str(ip).strip().lower(), int(port))


def _endpoint_lock(ip: str, port: int) -> threading.Lock:
    k = _key(ip, port)
    with _locks_guard:
        if k not in _locks:
            _locks[k] = threading.Lock()
        return _locks[k]


def _invalidate_unlocked(ip: str, port: int) -> None:
    k = _key(ip, port)
    c = _clients.pop(k, None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


def invalidate_coils_client(ip: str, port: int) -> None:
    """丢弃连接，下次 run_coils_session 会重连（如修改 device_config 线圈 IP 后）。"""
    with _endpoint_lock(ip, port):
        _invalidate_unlocked(ip, port)


def _ensure_client(ip: str, port: int) -> ModbusTcpClient:
    k = _key(ip, port)
    c = _clients.get(k)
    if c is not None:
        try:
            if c.is_socket_open():
                return c
        except Exception:
            pass
        try:
            c.close()
        except Exception:
            pass
        _clients.pop(k, None)

    c = ModbusTcpClient(ip, port=int(port), timeout=2.0)
    if not c.connect():
        raise ConnectionException(f"无法连接 Modbus 线圈网关 {ip}:{port}")
    _clients[k] = c
    return c


def run_coils_session(ip: str, port: int, task: Callable[[ModbusTcpClient], T]) -> T:
    """
    在同一条 TCP 上执行 task(client)。同一 (ip,port) 全局串行（锁）。
    Modbus 业务异常不主动断线；TCP 级异常会 invalidate 后向上抛出。
    """
    with _endpoint_lock(ip, port):
        client = _ensure_client(ip, port)
        try:
            return task(client)
        except (ConnectionException, OSError, BrokenPipeError, ConnectionResetError):
            _invalidate_unlocked(ip, port)
            raise


def read_coil_point_states(
    client: ModbusTcpClient,
    name_to_addr: Dict[str, int],
    unit: int = 1,
) -> Dict[str, bool]:
    """
    读基础点位对应线圈。在 [min_addr, max_addr] 内合并为一次 read_coils，减少请求次数。
    """
    if not name_to_addr:
        return {}
    addrs = list(name_to_addr.values())
    min_a = min(addrs)
    max_a = max(addrs)
    count = max_a - min_a + 1
    if count <= 0:
        return {n: False for n in name_to_addr}

    resp = client.read_coils(min_a, count, unit=unit)
    if resp is None or (hasattr(resp, "isError") and resp.isError()):
        return {n: False for n in name_to_addr}

    bits: List[bool] = getattr(resp, "bits", []) or []
    out: Dict[str, bool] = {}
    for name, addr in name_to_addr.items():
        idx = int(addr) - int(min_a)
        if 0 <= idx < len(bits):
            out[name] = bool(bits[idx])
        else:
            out[name] = False
    return out


def get_coils_persistent_snapshot() -> dict:
    with _locks_guard:
        endpoints = [f"{h}:{p}" for h, p in _clients.keys()]
        n = len(_clients)
    return {
        "mode": "modbus_coils_persistent",
        "open_endpoints": n,
        "endpoints": endpoints,
    }
