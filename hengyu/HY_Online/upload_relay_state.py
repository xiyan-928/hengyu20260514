"""
独立进程 upload_client_example 通过 GET /api/upload-relay/status 读取的开关（传感器 JSON / SPC 是否继续上报到 test1 等）。

默认均为 False，需由前端或脚本 POST /api/upload-relay/start 后才为 True。

线程安全，供 sync urllib 与 FastAPI 协程共同使用（状态变更极轻量，短持锁）。"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

_lock = threading.Lock()
_upload_sensor: bool = False
_upload_spc: bool = False


def get_flags() -> Tuple[bool, bool]:
    with _lock:
        return _upload_sensor, _upload_spc


def as_dict() -> Dict[str, Any]:
    us, up = get_flags()
    return {"upload_sensor": us, "upload_spc": up}


def set_both(sensor: bool, spc: bool) -> Dict[str, Any]:
    global _upload_sensor, _upload_spc
    with _lock:
        _upload_sensor = bool(sensor)
        _upload_spc = bool(spc)
        return {
            "upload_sensor": _upload_sensor,
            "upload_spc": _upload_spc,
        }


def set_partial(
    upload_sensor: Optional[bool] = None, upload_spc: Optional[bool] = None
) -> Dict[str, Any]:
    """仅更新传入的字段，其余保持原值。"""
    global _upload_sensor, _upload_spc
    with _lock:
        if upload_sensor is not None:
            _upload_sensor = bool(upload_sensor)
        if upload_spc is not None:
            _upload_spc = bool(upload_spc)
        return {
            "upload_sensor": _upload_sensor,
            "upload_spc": _upload_spc,
        }
