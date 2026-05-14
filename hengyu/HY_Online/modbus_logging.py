from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "modbus_debug.log"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 10

LOG_MODBUS = logging.getLogger("hy.modbus")

FUNCTION_CODE_MAP = {
    "read_coils": 1,
    "read_discrete_inputs": 2,
    "read_holding_registers": 3,
    "read_input_registers": 4,
    "write_coil": 5,
    "write_register": 6,
    "write_coils": 15,
    "write_registers": 16,
}


def configure_modbus_file_logging(base_dir: Optional[str] = None) -> str:
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, LOG_DIR_NAME)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, LOG_FILE_NAME)

    if not any(
        isinstance(handler, RotatingFileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == os.path.abspath(log_path)
        for handler in LOG_MODBUS.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        LOG_MODBUS.addHandler(handler)

    LOG_MODBUS.setLevel(logging.INFO)
    LOG_MODBUS.propagate = False
    return log_path


def modbus_context(**kwargs: Any) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


def mock_modbus_context(**kwargs: Any) -> Dict[str, Any]:
    return modbus_context(mock_mode=True, simulated=True, **kwargs)


def merge_modbus_context(
    *parts: Optional[Dict[str, Any]], **kwargs: Any
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        merged.update({k: v for k, v in part.items() if v is not None})
    merged.update({k: v for k, v in kwargs.items() if v is not None})
    return merged


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def elapsed_ms(start_ms: float) -> float:
    return round(now_ms() - start_ms, 3)


def function_code_for(operation: Optional[str]) -> Optional[int]:
    if not operation:
        return None
    return FUNCTION_CODE_MAP.get(operation)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "registers"):
        return list(getattr(value, "registers", []) or [])
    if hasattr(value, "bits"):
        bits = getattr(value, "bits", None)
        if bits is not None:
            return list(bits)
    return str(value)


def log_modbus_event(
    *,
    operation: str,
    ip: Optional[str] = None,
    port: Optional[int] = None,
    unit: Optional[int] = None,
    address: Optional[int] = None,
    count: Optional[int] = None,
    data: Any = None,
    success: Optional[bool] = None,
    error: Optional[str] = None,
    elapsed_ms_value: Optional[float] = None,
    context: Optional[Dict[str, Any]] = None,
    result: Any = None,
) -> None:
    payload = merge_modbus_context(
        context,
        operation=operation,
        function_code=function_code_for(operation),
        ip=ip,
        port=port,
        unit=unit,
        address=address,
        count=count,
        data=_normalize_value(data),
        result=_normalize_value(result),
        success=success,
        elapsed_ms=elapsed_ms_value,
        error=error,
    )
    LOG_MODBUS.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
