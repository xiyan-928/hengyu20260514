"""
HY_Online 控制台日志策略：
- 默认仅 WARNING 及以上（减少噪声）
- hy.signal：自动控制监视寄存器与内部标志位、脚本写线圈、阀门/继电器切换
- hy.sensor：每次传感器采集成功后的数值快照
- 各模块的 logger.error / logger.warning 仍会输出（异常与告警）
"""

from __future__ import annotations

import logging

from modbus_logging import configure_modbus_file_logging

LOG_SIGNAL = logging.getLogger("hy.signal")
LOG_SENSOR = logging.getLogger("hy.sensor")
LOG_MODBUS = logging.getLogger("hy.modbus")


def configure_hy_logging() -> None:
    """应在导入会调用 basicConfig 的模块之前执行（例如 main 最先调用）。"""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOG_SIGNAL.setLevel(logging.INFO)
    LOG_SENSOR.setLevel(logging.INFO)
    LOG_MODBUS.setLevel(logging.INFO)
    configure_modbus_file_logging()
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.WARNING)
