"""
光源：Modbus 单线圈读写；mock 模式下使用内存状态。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from config import app_config
from spectrum_app_config import load_config

logger = logging.getLogger(__name__)

_mock_coil: bool = False


def is_mock() -> bool:
    if app_config.is_mock_mode():
        return True
    cfg = load_config()
    return str(cfg.get("light_source", {}).get("mode", "mock")).lower() == "mock"


def get_mock_coil() -> bool:
    return _mock_coil


def _write_coil_real(host: str, port: int, unit: int, address: int, value: bool) -> None:
    from Devices.modbus_ephemeral import run_ephemeral
    from pymodbus.exceptions import ModbusException

    def task(client):
        rr = client.write_coil(address, value, unit=unit)
        if rr.isError():
            raise ModbusException(str(rr))
        return True

    run_ephemeral(host, port, task)


def _read_coil_real(host: str, port: int, unit: int, address: int) -> bool:
    from Devices.modbus_ephemeral import run_ephemeral
    from pymodbus.exceptions import ModbusException

    def task(client):
        rr = client.read_coils(address, 1, unit=unit)
        if rr.isError():
            raise ModbusException(str(rr))
        bits = getattr(rr, "bits", None)
        if not bits:
            raise ModbusException("read_coils 无 bits")
        return bool(bits[0])

    return run_ephemeral(host, port, task)


def write_coil(value: bool) -> Dict[str, Any]:
    global _mock_coil
    cfg = load_config()
    ls = cfg["light_source"]
    if is_mock():
        _mock_coil = bool(value)
        logger.debug("光源(mock): write_coil -> %s", _mock_coil)
        return {"mode": "mock", "value": _mock_coil}
    _write_coil_real(
        str(ls["host"]),
        int(ls["port"]),
        int(ls["unit"]),
        int(ls["address"]),
        value,
    )
    return {"mode": "real", "value": value}


def read_coil() -> Dict[str, Any]:
    cfg = load_config()
    ls = cfg["light_source"]
    if is_mock():
        return {"mode": "mock", "value": _mock_coil}
    v = _read_coil_real(
        str(ls["host"]),
        int(ls["port"]),
        int(ls["unit"]),
        int(ls["address"]),
    )
    return {"mode": "real", "value": v}
