import logging
import os
import struct
import threading
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.exceptions import ModbusException, ConnectionException

UNIT_ID = 10

# ---------------------------------------------------------------------------
# 日志配置：终端（INFO+）+ 按大小滚动的文件 logs/hy_bridge.log
# ---------------------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "hy_bridge.log")

os.makedirs(_LOG_DIR, exist_ok=True)

logger = logging.getLogger("hy.bridge")
logger.setLevel(logging.INFO)
logger.propagate = False  # 不向 root logger 传播，避免与 main.py 的 basicConfig 冲突

if not logger.handlers:
    _fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)

    # 控制台输出
    _sh = logging.StreamHandler()
    _sh.setLevel(logging.INFO)
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)

    # 文件输出（最大 5 MB，保留 5 个备份）
    _fh = RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)


# ---------------------------------------------------------------------------
# BridgeDataManager：单例，供 main.py /hy-device/sensors 合并上传
# ---------------------------------------------------------------------------
class BridgeDataManager:
    """
    桥接数据管理器（单例）：
    存储从 192.168.1.200 Modbus 设备读取的温度、液位、状态切换及异常信息，
    供主服务 /hy-device/sensors 一同上传。
    """

    _instance: Optional["BridgeDataManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.temperature: float = 0.0
        self.level: float = 0.0
        self.bridge_state: str = "reset"   # "reset"（待机）或 "triggered"（已触发）
        self.bridge_error: Optional[str] = None
        self.bridge_last_update_ts: Optional[float] = None
        self._initialized = True

    @classmethod
    def instance(cls) -> "BridgeDataManager":
        return cls()

    def update(self, temperature: float, level: float, state: str,
               error: Optional[str] = None) -> None:
        self.temperature = temperature
        self.level = level
        self.bridge_state = state
        self.bridge_error = error
        self.bridge_last_update_ts = time.time()

    def set_error(self, error: str) -> None:
        self.bridge_error = error
        self.bridge_last_update_ts = time.time()

    def get_snapshot(self) -> dict:
        return {
            "temperature": self.temperature,
            "level": self.level,
            "bridge_state": self.bridge_state,
            "bridge_error": self.bridge_error,
            "bridge_last_update_ts": self.bridge_last_update_ts,
        }


# ---------------------------------------------------------------------------
# Modbus 读写函数
# ---------------------------------------------------------------------------
def read_rg_info():
    """读取 Modbus 设备温度和液位，返回 (temp, level)。浮点格式 ABCD。"""
    client = ModbusTcpClient('192.168.1.200', port=502)
    client.connect()
    response = client.read_holding_registers(address=1, count=4, unit=1)
    bytes_ddl = struct.pack(
        '>HHHH',
        response.registers[0], response.registers[1],
        response.registers[2], response.registers[3],
    )
    temp, level = struct.unpack('>ff', bytes_ddl)
    client.close()
    return temp, level


def set_server_value(v: int, server_id: int) -> None:
    """向本地 Modbus 服务写寄存器。"""
    logger.info("写本地 Modbus 寄存器  unit=%d  value=%d", server_id, v)
    client = ModbusTcpClient('localhost', port=5020)
    client.connect()
    client.write_register(1, v, unit=server_id)
    client.close()


# ---------------------------------------------------------------------------
# 桥接主循环
# ---------------------------------------------------------------------------
def run_modbus_bridge(server_id: int) -> None:
    bdm = BridgeDataManager.instance()
    RESET = True
    logger.info("桥接线程启动  server_id=%d", server_id)

    while True:
        try:
            temp, level = read_rg_info()
            logger.info("传感器读取  温度=%.2f°C  液位=%.4f  状态=%s",
                        temp, level, "reset" if RESET else "triggered")

            if RESET and temp > 85:
                # 温度超限：待机 → 触发
                RESET = False
                logger.warning("状态切换: reset → triggered  (温度=%.2f°C > 85°C)", temp)
                set_server_value(1, server_id)

            elif not RESET and temp < 45:
                # 温度降至低阈值：触发 → 待机（优先判断，避免重复写 0）
                RESET = True
                logger.info("状态切换: triggered → reset  (温度=%.2f°C < 45°C)", temp)
                set_server_value(0, server_id)

            elif not RESET and temp < 85:
                # 触发状态下温度回落至中间区间：保持清零信号
                set_server_value(0, server_id)

            state = "reset" if RESET else "triggered"
            bdm.update(temp, level, state)

        except Exception as e:
            logger.error("读取/处理数据失败: %s", e, exc_info=True)
            bdm.set_error(str(e))

        time.sleep(2)


# ---------------------------------------------------------------------------
# 服务器启动入口
# ---------------------------------------------------------------------------
def run_server(unit_id: int) -> None:
    store = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [1] * 100),
        co=ModbusSequentialDataBlock(0, [1] * 100),
        hr=ModbusSequentialDataBlock(0, [1] * 100),
        ir=ModbusSequentialDataBlock(0, [1] * 100),
    )
    context = ModbusServerContext(slaves={unit_id: store}, single=False)

    logger.info("启动 Modbus TCP 服务器  地址=0.0.0.0:5020  unit_id=%d", unit_id)
    logger.info("日志文件: %s", _LOG_FILE)

    t = threading.Thread(target=run_modbus_bridge, args=(unit_id,), daemon=True)
    t.start()

    StartTcpServer(context, address=("0.0.0.0", 5020))


if __name__ == "__main__":
    run_server(UNIT_ID)
