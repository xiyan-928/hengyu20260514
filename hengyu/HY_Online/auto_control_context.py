"""
自动控制脚本化接口：统一上下文，供 auto_control_func 与 AutoControlManager 共享。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AutoControlContext:
    """注入依赖，业务函数内不新建 Modbus 等连接，由 Manager 负责连接与生命周期。"""

    settings: Any  # DeviceSettings
    modbus_client: Optional[Any] = None
    modbus_host: Optional[str] = None
    modbus_port: Optional[int] = None
    coils_modbus_client: Optional[Any] = None
    coils_modbus_host: Optional[str] = None
    coils_modbus_port: Optional[int] = None
    modbus_unit_id: int = 1
    monitor_register: int = 1
    get_cds350_device: Callable[[], Any] = field(default=lambda: None)
    current_hook_name: Optional[str] = None
    current_script_command: Optional[str] = None
    current_mode_name: Optional[str] = None
