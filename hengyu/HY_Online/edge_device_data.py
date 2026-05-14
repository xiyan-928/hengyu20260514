"""
边缘设备 HTTP 上送载荷：与 SensorDataManager.get_snapshot() 字段一致，另含 device_id。
与 test1.py 原 DeviceData 定义保持同步；主服务 POST /upload 与本模块校验一致。

新增字段（来自 hy_server.BridgeDataManager）：
  temperature           — PT100/DDL 模块读到的温度（°C）
  level                 — 液位（原始浮点）
  bridge_state          — 桥接状态："reset"（待机）或 "triggered"（已触发）
  bridge_error          — 最近一次桥接读取异常信息，正常时为 None
  bridge_last_update_ts — 桥接数据最后更新的 Unix 时间戳
"""
from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeviceData(BaseModel):
    """
    与主服务监控 data 快照一致，另含 device_id 以区分设备。
    未传的字段用默认值，边缘可只上送部分字段。
    """

    device_id: str
    # ---- SensorDataManager 字段 ----
    ddl: float = 0.0
    ph: float = 0.0
    ph_temp: float = 0.0
    pt100: float = 0.0
    valves: Dict[str, bool] = Field(default_factory=dict)
    is_alarming: bool = False
    fan_speed: int = 0
    fan_read_ok: bool = False
    fan_last_error: Optional[str] = None
    fan_last_read_ts: Optional[float] = None
    last_update_ts: Optional[float] = None
    last_error: Optional[str] = None
    running: bool = True
    interval: float = 2.0
    # ---- BridgeDataManager 字段（来自 hy_server） ----
    temperature: float = 0.0
    level: float = 0.0
    bridge_state: str = "reset"
    bridge_error: Optional[str] = None
    bridge_last_update_ts: Optional[float] = None
    # ---- 工艺/批次元数据（可选，监控历史页侧栏展示） ----
    generation_batch: Optional[str] = None
    fabric_weight_g: Optional[float] = None
    fabric_length: Optional[float] = None
    fabric_width: Optional[float] = None
    fabric_height: Optional[float] = None
    fabric_thickness: Optional[float] = None
    fabric_density: Optional[float] = None
    fabric_material: Optional[str] = None
    bath_ratio: Optional[float] = None

    model_config = ConfigDict(extra="ignore")
