"""
HY_Online 控制台日志策略：
- 默认仅 WARNING 及以上（减少噪声）
- hy.signal：自动控制监视寄存器与内部标志位、脚本写线圈、阀门/继电器切换
- hy.sensor：每次传感器采集成功后的数值快照
- 各模块的 logger.error / logger.warning 仍会输出（异常与告警）
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from modbus_logging import configure_modbus_file_logging

LOG_SIGNAL = logging.getLogger("hy.signal")
LOG_SENSOR = logging.getLogger("hy.sensor")
LOG_MODBUS = logging.getLogger("hy.modbus")

LOG_DIR_NAME = "logs"
APP_LOG_FILE_NAME = "hy_online.log"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 10


def configure_app_file_logging(base_dir: str | None = None) -> str:
    """将主服务 WARNING/ERROR 日志写入文件，避免设备错误只出现在控制台。"""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, LOG_DIR_NAME)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, APP_LOG_FILE_NAME)

    root_logger = logging.getLogger()
    abs_log_path = os.path.abspath(log_path)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == abs_log_path
        for handler in root_logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setLevel(logging.WARNING)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(handler)

    return log_path


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
    configure_app_file_logging()
    configure_modbus_file_logging()
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.WARNING)
