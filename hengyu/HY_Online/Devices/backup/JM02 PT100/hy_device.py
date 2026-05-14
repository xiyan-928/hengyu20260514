from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.exceptions import ModbusException, ConnectionException
import numpy as np
import struct
import os
import csv
import json
import time, datetime
import logging
import threading
from typing import Optional, Union, Tuple, Dict, Callable
import asyncio
import queue
from concurrent.futures import Future

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

buffer_dict = {
    0: None,
    1: None,
    2: None,
}

def get_random_value(ind, min_value=0.0, max_value=10.0) -> float:
    if buffer_dict.get(ind) is None:
        buffer_dict[ind] = 1
        return 0.0
    else:
        return float(np.random.uniform(min_value, max_value))


class ModbusTaskQueue:
    """
    Modbus 任务队列（单例）
    - 针对每个 (ip, port) 维护独立FIFO队列和工作线程
    - 保证同一设备的通信严格按任务提交顺序执行，避免冲突
    - 不同设备互不影响，可并行
    """

    _instance = None
    _lock = threading.Lock()

    class _Worker:
        def __init__(self, ip: str, port: int):
            self.ip = ip
            self.port = int(port)
            self.q: "queue.Queue[tuple[Callable[[], object], Future]]" = queue.Queue()
            self.stop_event = threading.Event()
            self.thread = threading.Thread(
                target=self._run, name=f"ModbusWorker-{self.ip}:{self.port}", daemon=True
            )
            self.thread.start()

        def _run(self):
            logger.info(f"Modbus工作线程启动: {self.ip}:{self.port}")
            while not self.stop_event.is_set():
                try:
                    task, fut = self.q.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    res = task()
                    if not fut.cancelled():
                        fut.set_result(res)
                except Exception as e:
                    if not fut.cancelled():
                        fut.set_exception(e)
                finally:
                    self.q.task_done()
            logger.info(f"Modbus工作线程退出: {self.ip}:{self.port}")

        def submit(self, task: Callable[[], object]) -> Future:
            fut: Future = Future()
            self.q.put((task, fut))
            return fut

        def stop(self, timeout: Optional[float] = 2.0):
            self.stop_event.set()
            try:
                self.thread.join(timeout)
            except Exception:
                pass

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._workers = {}
        return cls._instance

    @classmethod
    def instance(cls) -> "ModbusTaskQueue":
        return cls()

    def _get_worker(self, ip: str, port: int):
        key = (ip, int(port))
        with self._lock:
            w = self._workers.get(key)
            if w is None:
                w = ModbusTaskQueue._Worker(ip, int(port))
                self._workers[key] = w
            return w

    def execute(self, ip: str, port: int, task: Callable[[], object], timeout: Optional[float] = None):
        w = self._get_worker(ip, port)
        fut = w.submit(task)
        return fut.result(timeout=timeout)


class SensorDataManager:
    """
    传感器数据管理器
    - 提供读取DDL/PH/PH_TEMP/PT100的最近一次数据
    - 新增: 多线程定时更新功能 start_auto_update/stop_auto_update
    """

    # ---- 单例支持 ----
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # 双重检查锁，确保多线程下只创建一个实例
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> "SensorDataManager":
        """获取单例实例的便捷方法。等价于直接调用 SensorDataManager()。"""
        return cls()

    def __init__(self):
        # 防止重复初始化
        if getattr(self, "_initialized", False):
            return
        # 数据字段
        self.ddl = 0.0
        self.ph = 0.0
        self.ph_temp = 0.0
        self.pt100 = 0.0

        # 运行状态
        self._lock = threading.Lock()
        self._stop_event: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._interval: float = 3.0
        self._last_error: Optional[Exception] = None
        self._last_update_ts: Optional[float] = None
        self._on_update: Optional[Callable[[dict], None]] = None
        
        # 仅第一次完成时标记
        self._initialized = True
        
    # ------------ 同步读取API（加锁保护） ------------
    def get_ddl(self) -> float:
        with self._lock:
            return self.ddl

    def get_ph(self) -> float:
        with self._lock:
            return self.ph

    def get_ph_temp(self) -> float:
        with self._lock:
            return self.ph_temp

    def get_pt100(self) -> float:
        with self._lock:
            return self.pt100

    def get_snapshot(self) -> dict:
        """一次性拷贝当前所有数值，避免读取过程中的竞争。"""
        with self._lock:
            return {
                "ddl": self.ddl,
                "ph": self.ph,
                "ph_temp": self.ph_temp,
                "pt100": self.pt100,
                "last_update_ts": self._last_update_ts,
                "last_error": str(self._last_error) if self._last_error else None,
                "running": self.is_running(),
                "interval": self._interval,
            }

    def _set_values(self, ddl: float, ph: float, ph_temp: float, pt100: float) -> None:
        with self._lock:
            self.ddl = ddl
            self.ph = ph
            self.ph_temp = ph_temp
            self.pt100 = pt100
            self._last_update_ts = time.time()

    def get_last_error(self) -> Optional[str]:
        with self._lock:
            return str(self._last_error) if self._last_error else None

    # ------------ 与设备交互 ------------
    def update_sensor(self, ip, port):
        try:
            def task():
                client = ModbusTcpClient(ip, port=port, timeout=1.0)
                try:
                    ddl_response = client.read_holding_registers(9, 2, unit=8)
                    if ddl_response.isError():
                        ddl = self.ddl
                    else:
                        ddl = (ddl_response.registers[0] * 65536 + ddl_response.registers[1]) / 100

                    # ph_response = client.read_holding_registers(0, 8, unit=9)
                    # if ph_response.isError():
                    #     ph = self.ph
                    #     ph_temp = self.ph_temp
                    # else:
                    #     ph = ph_response.registers[3] / 100.0
                    #     ph_temp = ph_response.registers[5] / 10.0

                    pt100_response = client.read_input_registers(address=0, count=2, unit=20)
                    if pt100_response.isError():
                        pt100 = self.pt100
                    else:
                        pt100 = pt100_response.registers[1] / 100.0
                    
                    response = client.read_holding_registers(address=52, count=4, unit=9)
                    bytes_ddl = struct.pack('<HHHH', response.registers[0], response.registers[1], response.registers[2], response.registers[3])
                    ph, temp = struct.unpack('<ff', bytes_ddl)
                    
                    return ddl, ph, ph_temp, pt100
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass

            ddl, ph, ph_temp, pt100 = ModbusTaskQueue.instance().execute(ip, port, task)

            # 更新传感器值
            self._set_values(ddl, ph, ph_temp, pt100)
            with self._lock:
                self._last_error = None
            logger.info(
                f"传感器数据更新成功 - DDL: {ddl}, PH: {ph}, PH_TEMP: {ph_temp}, PT100: {pt100}"
            )

        except Exception as e:
            with self._lock:
                self._last_error = e
            logger.error(f"更新传感器数据时发生错误: {e}")

    # ------------ 后台自动更新（多线程） ------------
    def start_auto_update(
        self,
        ip: str,
        port: int,
        interval_seconds: float = 2.0,
        on_update: Optional[Callable[[dict], None]] = None,
        daemon: bool = True,
    ) -> None:
        """
        启动后台线程，周期性调用 update_sensor。

        Args:
            ip: 设备IP
            port: 设备端口
            interval_seconds: 调用间隔秒数
            on_update: 每次更新成功后的回调，接收一个snapshot字典
            daemon: 是否将线程设置为守护线程
        """
        logger.info(f"请求启动自动更新线程: {ip}:{port}, interval={interval_seconds}s")
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.info("自动更新线程已在运行，忽略重复启动。")
                return
            self._interval = max(0.1, float(interval_seconds))
            self._on_update = on_update
            self._stop_event = threading.Event()

        def _loop():
            logger.info(
                f"自动更新线程启动: {ip}:{port}, interval={self._interval}s"
            )
            while True:
                # 检查停止
                if self._stop_event.is_set():
                    logger.info("自动更新线程收到停止信号，准备退出。")
                    break

                # 更新一次
                try:
                    self.update_sensor(ip, port)
                    if self._on_update:
                        # 提供只读快照
                        snap = self.get_snapshot()
                        try:
                            self._on_update(snap)
                        except Exception as cb_e:
                            logger.error(f"更新回调执行失败: {cb_e}")
                except Exception:
                    # update_sensor内部已记录错误
                    pass

                # 等待下一轮，允许提前停止
                if self._stop_event.wait(self._interval):
                    logger.info("自动更新线程在等待间隔时被停止。")
                    break

            logger.info("自动更新线程已退出。")

        # 启动线程
        t = threading.Thread(target=_loop, name="SensorAutoUpdater", daemon=daemon)
        t.start()
        with self._lock:
            self._thread = t

    def stop_auto_update(self, timeout: Optional[float] = 2.0) -> None:
        """停止后台自动更新线程。"""
        with self._lock:
            ev = self._stop_event
            th = self._thread
        if ev is None or th is None:
            return
        ev.set()
        th.join(timeout=timeout)
        with self._lock:
            self._stop_event = None
            self._thread = None

    def is_running(self) -> bool:
        th = None
        with self._lock:
            th = self._thread
        return bool(th and th.is_alive())

    def set_interval(self, interval_seconds: float) -> None:
        """在下一个周期生效。"""
        with self._lock:
            self._interval = max(0.1, float(interval_seconds))


def read_ph_value(ip, port, *args) -> Optional[float]:
    sdm = SensorDataManager.instance()
    return sdm.get_ph()

def read_ph_temp(ip: str, port: int, *args) -> Optional[float]:
    sdm = SensorDataManager.instance()
    return sdm.get_ph_temp()
    
def read_pt100_temp(ip: str, port: int, *args) -> Optional[float]:
    sdm = SensorDataManager.instance()
    return sdm.get_pt100()

def read_ddl(ip: str, port: int, *args) -> Optional[float]:
    sdm = SensorDataManager.instance()
    return sdm.get_ddl()

def switch_valve(ip: str, port: int, *args) -> Optional[float]:
    """
    切换阀门状态
    
    Args:
        ip: 设备IP地址
        port: 端口号
        *args: 可选参数
            第一个参数为阀的位点，可选为0-7
            第二个参数为开关状态，0为关闭，1为打开
        
    Returns:
        成功或失败
        
    Raises:
        ConnectionException: 连接失败
        ModbusException: Modbus通信异常
    """
    try:
        pos = int(args[0]) if len(args) > 0 else 0
        state = int(args[1]) if len(args) > 1 else 0
        def task():
            client = ModbusTcpClient(ip, port=port, timeout=1.0)
            try:
                response = client.write_coil(pos, state, unit=1)
                if response.isError():
                    raise ModbusException(f"切换继电器失败: {response}")
                return True
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        res = ModbusTaskQueue.instance().execute(ip, port, task)
        logger.info(f"继电器切换成功: {pos} 状态: {'打开' if state else '关闭'}")
        return res
        
    except Exception as e:
        logger.error(f"切换继电器时发生错误: {e}")
        raise
    
async def reset_devices(ip: str, port: int, reg: int, mock_mode: bool = False):
    """
    异步重置设备
    
    Args:
        ip: 设备IP地址
        port: 端口号
        reg: 需要重置的寄存器地址
        mock_mode: 是否使用模拟模式
        
    Returns:
        dict: 重置结果信息
        
    Raises:
        ConnectionException: 连接失败
        ModbusException: Modbus通信异常
        ValueError: 参数错误
    """
    try:
        if not isinstance(reg, int) or reg < 0:
            raise ValueError(f"无效的寄存器地址: {reg}")
            
        logger.info(f"开始重置设备 - IP: {ip}, Port: {port}, Register: {reg}, 模拟模式: {mock_mode}")
        
        if mock_mode:
            # 模拟模式：不连接真实设备，只模拟重置过程
            logger.info("🔧 [模拟模式] 开始模拟设备重置...")
            
            # 模拟第一步：设置重置信号
            logger.info(f"🔧 [模拟模式] 设置重置信号 - 寄存器 {reg} 设置为 True")
            await asyncio.sleep(1)  # 模拟网络延迟
            
            # 模拟30秒重置过程（加速到3秒用于测试）
            reset_duration = 3  # 测试时缩短到3秒
            logger.info(f"🔧 [模拟模式] 等待设备重置完成 ({reset_duration}秒)...")
            
            # 分阶段显示进度
            for i in range(reset_duration):
                await asyncio.sleep(1)
                progress = ((i + 1) / reset_duration) * 100
                logger.info(f"🔧 [模拟模式] 重置进度: {progress:.0f}% ({i + 1}/{reset_duration}秒)")
            
            # 模拟第二步：清除重置信号
            logger.info(f"🔧 [模拟模式] 清除重置信号 - 寄存器 {reg} 设置为 False")
            await asyncio.sleep(1)  # 模拟网络延迟
            
            logger.info("✅ [模拟模式] 设备重置完成")
            
            return {
                "success": True,
                "mode": "mock",
                "ip": ip,
                "port": port,
                "register": reg,
                "duration_seconds": reset_duration + 2,  # 包含网络延迟
                "steps_completed": [
                    "设置重置信号为True",
                    f"等待重置完成({reset_duration}秒)",
                    "设置重置信号为False"
                ]
            }
        else:
            # 真实模式：连接真实设备
            client = ModbusTcpClient(ip, port=port, timeout=0.5)
            
            # 第一步：设置重置信号为True
            response1 = client.write_coil(reg, True, unit=1)
            if response1.isError():
                raise ModbusException(f"设置重置信号失败: {response1}")
                
            logger.info(f"🔧 [真实模式] 传感器重置开始 - 寄存器 {reg} 设置为 True")
            
            # 等待30秒重置时间
            reset_duration = 30
            logger.info(f"🔧 [真实模式] 等待设备重置完成 ({reset_duration}秒)...")
            await asyncio.sleep(reset_duration)
            
            # 第二步：设置重置信号为False
            response2 = client.write_coil(reg, False, unit=1)
            if response2.isError():
                raise ModbusException(f"清除重置信号失败: {response2}")
                
            logger.info(f"✅ [真实模式] 传感器重置完成 - 寄存器 {reg} 设置为 False")
            
            # 更新连接最后使用时间
            # connection_pool.update_last_used(ip, port)
            client.close()
            
            return {
                "success": True,
                "mode": "real",
                "ip": ip,
                "port": port,
                "register": reg,
                "duration_seconds": reset_duration + 2,
                "steps_completed": [
                    "设置重置信号为True",
                    f"等待重置完成({reset_duration}秒)",
                    "设置重置信号为False"
                ]
            }
        
    except Exception as e:
        logger.error(f"❌ 重置设备时发生错误: {e}")
        raise


class DeviceConfig:
    """设备配置类，用于管理Modbus设备连接和数据读取"""
    
    def __init__(self, mock_mode: bool = False):
        self.ip_address = '192.168.1.12'
        self.port = 502
        self.mock_mode = mock_mode  # 添加模拟模式标志
        self.modbus_config_settings = {
            "DDL": [read_ddl, ],
            "PT100": [read_pt100_temp, 20, 1],
            "PH": [read_ph_value, 9],
            "PH_TEMP": [read_ph_temp, 9],
            "VALVE_IN_ON": [switch_valve, 2, 1],
            "VALVE_IN_OFF": [switch_valve, 2, 0],
            "VALVE_OUT_ON": [switch_valve, 1, 1],
            "VALVE_OUT_OFF": [switch_valve, 1, 0],
            "LIGHT_ON": [switch_valve, 0, 1],
            "LIGHT_OFF": [switch_valve, 0, 0],
        }
        self.sdm = SensorDataManager()
        self.sdm.start_auto_update(self.ip_address, self.port, interval_seconds=5.0, daemon=True)
        
    
    def set_address(self, ip: str, port: int) -> None:
        """
        设置设备地址
        
        Args:
            ip: IP地址
            port: 端口号
        """
        self.ip_address = "192.168.1.12"
        self.port = port
        logger.info(f"设备地址已更新为: {ip}:{port}")
        
    async def run_modbus_inquire(self, device_type: str) -> Union[float, None]:
        """
        执行Modbus查询
        
        Args:
            device_type: 设备类型 ("DDL", "PT100", "PH", "PH_TEMP")
            
        Returns:
            查询结果值或None
            
        Raises:
            ValueError: 不支持的设备类型
            ConnectionException: 连接失败
            ModbusException: Modbus通信异常
        """
        try:
            if device_type not in self.modbus_config_settings:
                raise ValueError(f"不支持的设备类型: {device_type}")
            
            # 如果是模拟模式，返回模拟数据
            if self.mock_mode:
                return await self._get_mock_data(device_type)
            
            func, *args = self.modbus_config_settings[device_type]
            result = func(self.ip_address, self.port, *args)
            logger.info(f"成功查询设备 {device_type}, 结果: {result}")
            return result
            
        except Exception as e:
            logger.error(f"查询设备 {device_type} 时发生错误: {e}")
            raise
    
    async def _get_mock_data(self, device_type: str) -> Union[float, bool]:
        """
        获取模拟数据 - 直接返回随机数据，无需通过Modbus客户端通信
        
        Args:
            device_type: 设备类型
            
        Returns:
            模拟的设备数据
        """
        import random
        import asyncio
        
        logger.info(f"🎭 模拟模式 - 开始获取设备数据: {device_type}")
        
        # 为不同类型的设备返回不同的模拟数据
        mock_data_map = {
            "DDL": lambda: round(random.uniform(0.5, 10.0), 2),  # DDL值 0.5-10.0
            "PT100": lambda: round(random.uniform(15.0, 85.0), 2),  # 温度 15-85℃
            "PH": lambda: round(random.uniform(6.0, 8.5), 2),  # PH值 6.0-8.5
            "PH_TEMP": lambda: round(random.uniform(20.0, 30.0), 2),  # PH温度 20-30℃
            "VALVE_IN_ON": lambda: True,  # 阀门操作成功
            "VALVE_IN_OFF": lambda: True,
            "VALVE_OUT_ON": lambda: True,
            "VALVE_OUT_OFF": lambda: True,
            "LIGHT_ON": lambda: True,
            "LIGHT_OFF": lambda: True,
        }
        
        if device_type in mock_data_map:
            # 模拟硬件响应延时：1秒（使用异步睡眠）
            logger.info(f"⏳ 模拟硬件延时 1 秒...")
            await asyncio.sleep(1.0)
            
            result = mock_data_map[device_type]()
            logger.info(f"✅ 模拟模式 - 成功获取设备数据 [{device_type}]: {result}")
            return result
        else:
            raise ValueError(f"模拟模式不支持的设备类型: {device_type}")
    
    def get_device_types(self) -> list:
        """
        获取支持的设备类型列表
        
        Returns:
            支持的设备类型列表
        """
        return list(self.modbus_config_settings.keys())
    
    async def test_connection(self) -> bool:
        """
        测试设备连接
        
        Returns:
            连接成功返回True，否则返回False
        """
        if self.mock_mode:
            import asyncio
            logger.info("🎭 模拟模式 - 开始连接测试")
            logger.info("⏳ 模拟连接测试延时 1 秒...")
            await asyncio.sleep(1.0)
            logger.info("✅ 模拟模式 - 连接测试成功")
            return True
            
        try:
            # 使用连接池获取连接进行测试
            # client = connection_pool.get_client(self.ip_address, self.port)
            client = ModbusTcpClient(self.ip_address, port=self.port, timeout=3.0)
            # # 如果能成功获取client，说明连接正常
            # connection_pool.update_last_used(self.ip_address, self.port)
            client.close()
            logger.info(f"✅ 连接测试成功 - {self.ip_address}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"连接测试失败: {e}")
            return False
        
        

    