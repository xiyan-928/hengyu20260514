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
from typing import Optional, Union, Tuple, Dict, Callable, List, Any, TypeVar
import asyncio
from concurrent.futures import ThreadPoolExecutor

T_io = TypeVar("T_io")

# 同步 Modbus（run_ephemeral / pymodbus）在专用线程池执行，避免阻塞 uvicorn 事件循环
_DEVICE_IO_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hy_device_io")


async def run_device_io(fn: Callable[[], T_io]) -> T_io:
    """在固定大小线程池中运行同步设备 I/O，供 async 路由 await。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_DEVICE_IO_EXECUTOR, fn)
from .drivers import DriverFactory
from .device_settings import DeviceSettings
from .modbus_ephemeral import run_ephemeral, get_ephemeral_status_snapshot
try:
    from ..config import app_config
except ImportError:
    # Fallback for when running directly or different path structure
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
    from HY_Online.config import app_config

from hy_logging import LOG_SIGNAL, LOG_SENSOR
from modbus_logging import (
    elapsed_ms,
    log_modbus_event,
    merge_modbus_context,
    mock_modbus_context,
    modbus_context,
    now_ms,
)

logger = logging.getLogger(__name__)

# 报警紧急关阀：若 xlsx「模式定义」中存在该 NAME，则整段 write_coils；否则按基础点位写 0
MANUAL_EMERGENCY_CLOSE_MODE = "EMERGENCY_CLOSE"


def _get_script_engine_safe():
    try:
        from auto_control_script_engine import get_script_engine

        return get_script_engine()
    except Exception:
        return None


def manual_valve_address_map() -> Dict[str, int]:
    """从 script_define「基础点位配置」取全部点位名称与线圈地址（不固定 LIGHT/VALVE_* 等）。"""
    eng = _get_script_engine_safe()
    if not eng:
        return {}
    pts = eng.registry.points
    return {str(k): int(pts[k]) for k in pts}


def _manual_coil_outlet_point() -> Optional[str]:
    return DeviceSettings.instance().get_manual_coil_outlet_point()


def mode_segments_for(mode_name: str):
    eng = _get_script_engine_safe()
    if not eng:
        return None
    return eng.registry.mode_segments.get(mode_name)


def parse_manual_mode_name(mode_name: str) -> Tuple[str, bool]:
    """如 进水阀_ON -> (进水阀, True)；MY_VALVE_OFF -> (MY_VALVE, False)（后缀 _ON/_OFF）。"""
    if not mode_name or "_" not in mode_name:
        raise ValueError(f"无效的手动模式名: {mode_name!r}")
    base, suffix = mode_name.rsplit("_", 1)
    suffix_u = suffix.upper()
    if suffix_u not in ("ON", "OFF"):
        raise ValueError(f"手动模式名须以 _ON/_OFF 结尾: {mode_name!r}")
    return base, suffix_u == "ON"


def write_coils_segments(
    client: ModbusTcpClient,
    segments: List[Tuple[int, List[bool]]],
    unit: int = 1,
    *,
    ip: Optional[str] = None,
    port: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    for start_addr, vals in segments:
        started_ms = now_ms()
        rr = client.write_coils(start_addr, vals, unit=unit)
        if rr is not None and hasattr(rr, "isError") and rr.isError():
            log_modbus_event(
                operation="write_coils",
                ip=ip,
                port=port,
                unit=unit,
                address=start_addr,
                count=len(vals),
                data=list(vals),
                success=False,
                error=str(rr),
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            raise ModbusException(f"write_coils 失败 addr={start_addr} unit={unit}: {rr}")
        log_modbus_event(
            operation="write_coils",
            ip=ip,
            port=port,
            unit=unit,
            address=start_addr,
            count=len(vals),
            data=list(vals),
            success=True,
            elapsed_ms_value=elapsed_ms(started_ms),
            context=context,
        )


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
        # 数据字段 - 使用原子类型，Python 的 GIL 保证单个赋值操作的原子性
        self.ddl = 0.0
        self.ph = 0.0
        self.ph_temp = 0.0
        self.pt100 = 0.0
        
        # 阀门/线圈状态缓存：键为 script_define 基础点位「名称」，启动后随 xlsx 同步
        self.valves: Dict[str, bool] = {}
        self.is_alarming = False
        self.fan_speed = 0
        self.fan_read_ok = False
        self.fan_last_error: Optional[str] = None
        self.fan_last_read_ts: Optional[float] = None

        # Valve Request Cache (target state)
        self._valve_requests = {}  # {name: state}
        self._valve_req_lock = threading.RLock()
        # 阀门逐一切断节流（防止同时切断造成电压冲击）
        self._valve_close_interval = 2.0
        self._last_valve_close_ts = 0.0
        self._valve_close_cursor = 0
        
        # 运行状态 - 只在需要时使用锁（启动/停止线程）
        self._lock = threading.Lock()  # 仅用于线程管理
        self._stop_event: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._interval: float = 3.0
        self._last_error: Optional[Exception] = None
        self._last_update_ts: Optional[float] = None
        self._on_update: Optional[Callable[[dict], None]] = None
        # 模拟模式：随机工艺参数，仅进程内首次初始化时生成一次
        self._mock_process_params: Optional[Dict[str, Any]] = None

        # 仅第一次完成时标记
        self._initialized = True
        self._init_mock_process_params_if_needed()

    def _init_mock_process_params_if_needed(self) -> None:
        """模拟模式下生成一批随机工艺参数，整个进程生命周期内保持不变。"""
        if self._mock_process_params is not None:
            return
        try:
            if not app_config.is_mock_mode():
                return
        except Exception:
            return
        import random

        materials = ("涤纶", "棉", "尼龙", "混纺", "羊毛")
        self._mock_process_params = {
            "generation_batch": f"MOCK-{random.randint(20250001, 20259999)}",
            "fabric_weight_g": round(random.uniform(800.0, 3500.0), 2),
            "fabric_length": round(random.uniform(50.0, 200.0), 2),
            "fabric_width": round(random.uniform(1.0, 3.5), 3),
            "fabric_height": round(random.uniform(0.05, 0.35), 4),
            "fabric_thickness": round(random.uniform(0.2, 2.5), 3),
            "fabric_density": round(random.uniform(0.8, 1.5), 3),
            "fabric_material": random.choice(materials),
            "bath_ratio": round(random.uniform(5.0, 15.0), 2),
        }
        logger.info(
            "模拟模式：工艺参数已生成（单次） batch=%s material=%s",
            self._mock_process_params.get("generation_batch"),
            self._mock_process_params.get("fabric_material"),
        )

    # ------------ 同步读取API（无锁 - Python GIL 保证原子性） ------------
    def get_ddl(self) -> float:
        return self.ddl

    def get_ph(self) -> float:
        return self.ph

    def get_ph_temp(self) -> float:
        return self.ph_temp

    def get_pt100(self) -> float:
        return self.pt100

    def get_valve_statuses(self) -> dict:
        """获取缓存的阀门状态"""
        return self.valves.copy()

    def get_alarm_status(self) -> bool:
        return self.is_alarming
            
    def get_fan_speed(self) -> int:
        return self.fan_speed

    def set_fan_speed_to_zero(self, reason: str = "manual_stop") -> bool:
        """Best-effort 将风扇速度写为 0（用于手动停采/停监控）。"""
        settings = DeviceSettings.instance()
        fan_conf = settings.config.get("fan", {})
        if not fan_conf.get("enabled", False):
            logger.info(f"跳过风扇停转: fan.enabled=False, reason={reason}")
            self.fan_speed = 0
            return False

        unit = int(fan_conf.get("unit", 7))
        reg_ip, reg_port = settings.get_modbus_holding_endpoint()
        is_mock = False
        try:
            is_mock = app_config.is_mock_mode()
        except Exception:
            pass

        try:
            from .alert_and_fan import set_new_fan_speed

            set_new_fan_speed(
                reg_ip,
                reg_port,
                0,
                fan_unit=unit,
                mock_mode=is_mock,
            )
            self.fan_speed = 0
            self.fan_last_error = None
            self.fan_last_read_ts = time.time()
            logger.info(
                f"手动停采触发风扇停转成功: speed=0 unit={unit} endpoint={reg_ip}:{reg_port} reason={reason}"
            )
            return True
        except Exception as e:
            self.fan_last_error = str(e)
            logger.warning(f"手动停采触发风扇停转失败 reason={reason}: {e}")
            return False

    def update_valve_cache(self, name: str, state: bool):
        """主动更新阀门缓存（用于控制操作后立即同步）"""
        self.valves[name] = state

    def sync_valves_from_script_points(self, valve_map: Dict[str, int]) -> None:
        """使 self.valves 的键与 script_define 基础点位一致。"""
        for k in valve_map:
            if k not in self.valves:
                self.valves[k] = False
        for stale in list(self.valves.keys()):
            if stale not in valve_map:
                del self.valves[stale]

    def set_valve_request(self, name: str, state: bool):
        """设置阀门期望状态，将在线圈平面任务中尽快执行"""
        with self._valve_req_lock:
            self._valve_requests[name] = state
        self.update_valve_cache(name, state)

    def get_valve_requests(self) -> dict:
        with self._valve_req_lock:
            return self._valve_requests.copy()

    def clear_valve_request(self, name: str):
        with self._valve_req_lock:
            self._valve_requests.pop(name, None)

    def apply_script_mode_to_cache(self, mode_name: str) -> bool:
        """
        按 script_define 模式定义更新各阀门缓存（用于 mock 或与写入后一致）。
        若模式中未包含某点位列，则该阀门缓存不变。
        """
        segs = mode_segments_for(mode_name)
        if not segs:
            return False
        eng = _get_script_engine_safe()
        if not eng:
            return False
        inv = {v: k for k, v in eng.registry.points.items()}
        addr_to_val: Dict[int, bool] = {}
        for start, vals in segs:
            for i, b in enumerate(vals):
                addr_to_val[int(start) + i] = bool(b)
        for addr, b in addr_to_val.items():
            pname = inv.get(addr)
            if pname is None:
                continue
            if pname not in self.valves:
                self.valves[pname] = False
            self.valves[pname] = b
        return True

    def get_snapshot(self) -> dict:
        """一次性拷贝当前所有数值"""
        snap = {
            "ddl": self.ddl,
            "ph": self.ph,
            "ph_temp": self.ph_temp,
            "pt100": self.pt100,
            "valves": self.valves.copy(),
            "is_alarming": self.is_alarming,
            "fan_speed": self.fan_speed,
            "fan_read_ok": self.fan_read_ok,
            "fan_last_error": self.fan_last_error,
            "fan_last_read_ts": self.fan_last_read_ts,
            "last_update_ts": self._last_update_ts,
            "last_error": str(self._last_error) if self._last_error else None,
            "running": self.is_running(),
            "interval": self._interval,
        }
        if self._mock_process_params:
            snap.update(self._mock_process_params)
        return snap

    def _set_values(self, ddl: float, ph: float, ph_temp: float, pt100: float) -> None:
        """批量设置传感器值 - 简单赋值，无需锁"""
        self.ddl = ddl
        self.ph = ph
        self.ph_temp = ph_temp
        self.pt100 = pt100
        self._last_update_ts = time.time()

    def get_last_error(self) -> Optional[str]:
        return str(self._last_error) if self._last_error else None

    # ------------ 与设备交互 ------------
    def update_sensor(self, ip, port):
        try:
            settings = DeviceSettings.instance()
            sensors_config = settings.get_sensors()
            # 手动线圈地址仅来自 script_define「基础点位」，与 relays 无关
            valve_map = manual_valve_address_map()
            self.sync_valves_from_script_points(valve_map)

            # Alarm & Fan config
            alarm_conf = settings.config.get("alarm", {})
            fan_conf = settings.config.get("fan", {})

            # Check mock mode
            is_mock = False
            try:
                is_mock = app_config.is_mock_mode()
            except Exception:
                pass

            # Get requests
            requests = self.get_valve_requests()

            if is_mock:
                # Mock Mode: 无 Modbus 短连接
                import random
                from .alert_and_fan import (
                    get_current_speed_with_status,
                    read_alert_message,
                    get_new_fan_speed,
                    set_new_fan_speed,
                )
                coil_ip, coil_port = settings.get_modbus_coils_endpoint()
                reg_ip, reg_port = settings.get_modbus_holding_endpoint()
                
                results = {}
                valve_results = {}
                alarm_result = False
                fan_speed_result = self.fan_speed
                fan_read_ok = False
                fan_error: Optional[str] = None
                
                # Initialize mock state if not present
                if not hasattr(self, '_mock_state'):
                    self._mock_state = {
                        "PT100": 25.0, # Start at reasonable ambient temp
                        "DDL": 5.0,
                        "PH": 7.0,
                        "PH_TEMP": 25.0
                    }

                # Mock Valve Control
                if requests:
                    LOG_SIGNAL.info(f"[Mock] 处理阀门请求: {requests}")
                    for v_name, v_state in requests.items():
                        mode_name = f"{v_name}_{'ON' if v_state else 'OFF'}"
                        segs = mode_segments_for(mode_name) or []
                        for start_addr, vals in segs:
                            log_modbus_event(
                                operation="write_coils",
                                ip=coil_ip,
                                port=coil_port,
                                unit=1,
                                address=start_addr,
                                count=len(vals),
                                data=list(vals),
                                success=True,
                                context=mock_modbus_context(
                                    source="mock_sensor_update_valve_request",
                                    request_name="update_sensor_valve_request",
                                    mode_name=mode_name,
                                    point_name=v_name,
                                    desired_state=v_state,
                                    script_command=mode_name,
                                ),
                            )
                        if not self.apply_script_mode_to_cache(mode_name):
                            self.update_valve_cache(v_name, v_state)
                        self.clear_valve_request(v_name)
                
                # 1. Mock Sensors - Update smoothly
                # Update PT100 smoothly (random walk)
                current_pt100 = self._mock_state["PT100"]
                delta = random.uniform(-0.5, 0.5) # Slow change
                new_pt100 = max(15.0, min(85.0, current_pt100 + delta))
                self._mock_state["PT100"] = round(new_pt100, 2)
                #---------------------------
                results["pt100"] = self._mock_state["PT100"]
                
                # Randomize others slightly or regenerate
                results["ddl"] = round(random.uniform(0.5, 10.0), 2)
                results["ph"] = round(random.uniform(6.0, 8.5), 2)
                results["ph_temp"] = round(random.uniform(20.0, 30.0), 2)
                #---------------------------
                for sensor_name in sensors_config:
                    #if sensor_name not in results:
                    #     results[sensor_name] = round(random.uniform(10, 100), 2)
                    key = sensor_name.lower()
                    if key not in results:
                        results[key] = round(random.uniform(10, 100), 2)
                for sensor_name, sensor_value in results.items():
                    log_modbus_event(
                        operation="read_holding_registers",
                        ip=reg_ip,
                        port=reg_port,
                        success=True,
                        result={"sensor_name": sensor_name, "value": sensor_value},
                        context=mock_modbus_context(
                            source="mock_sensor_update",
                            request_name="sensor_read",
                            sensor_name=sensor_name,
                        ),
                    )

                # 2. Mock Valve Status - return current cached state
                # valve_results is empty, we rely on cache
                
                # 3. Mock Alarm
                if alarm_conf.get("enabled", False):
                    addr = alarm_conf.get("address", 0)
                    alarm_unit = int(alarm_conf.get("unit", 1))
                    alarm_result = read_alert_message(
                        coil_ip,
                        coil_port,
                        addr,
                        mock_mode=True,
                        unit=alarm_unit,
                    )
                
                # 4. Mock Fan Speed & Auto Control
                if fan_conf.get("enabled", False):
                    unit = fan_conf.get("unit", 7)
                    (
                        fan_speed_result,
                        fan_read_ok,
                        fan_error,
                    ) = get_current_speed_with_status(
                        reg_ip, reg_port, fan_unit=unit, mock_mode=True
                    )
                    
                    # Mock Auto Control Logic
                    current_temp = 0.0
                    #-----------------------
                    if "pt100" in results:
                        current_temp = results["pt100"]
                    #-----------------------
                    else:
                        for s_name, val in results.items():
                            if "temp" in s_name.lower() or "pt100" in s_name.lower():
                                current_temp = val
                                break
                    
                    if current_temp > 0:
                        target_temp = fan_conf.get("target_temp", 25.0)
                        stop_temp = fan_conf.get("stop_temp", 20.0)
                        start_temp = fan_conf.get("start_temp", 30.0)
                        min_speed = fan_conf.get("min_speed", 50)
                        max_speed = fan_conf.get("max_speed", 100)
                        k_factor = fan_conf.get("k_factor", 5)
                        
                        if "start_temp" not in fan_conf and "target_temp" in fan_conf:
                            start_temp = target_temp
                        
                        new_speed = get_new_fan_speed(
                            current_temp, 
                            fan_speed_result,
                            start_temp=start_temp,
                            stop_temp=stop_temp,
                            k_factor=k_factor,
                            min_speed=min_speed,
                            max_speed=max_speed
                        )
                        
                        if new_speed != fan_speed_result:
                            logger.debug(
                                f"[Mock] Fan Speed: Temp={current_temp:.1f}, "
                                f"{fan_speed_result} -> {new_speed}"
                            )
                            set_new_fan_speed(reg_ip, reg_port, new_speed, fan_unit=unit, mock_mode=True)
                            fan_speed_result = new_speed
                
                sensor_vals = results
                valve_vals = valve_results
                alarm_val = alarm_result
                fan_val = fan_speed_result
                fan_read_ok_val = fan_read_ok
                fan_error_val = fan_error
                
            else:
                # Real Mode: 线圈侧一批 run_ephemeral；传感器在 driver 层每次独立短连接；双网关时线程池并行
                coil_ip, coil_port = settings.get_modbus_coils_endpoint()
                reg_ip, reg_port = settings.get_modbus_holding_endpoint()
                same_modbus_endpoint = (coil_ip.lower(), coil_port) == (
                    reg_ip.lower(),
                    reg_port,
                )

                def coil_task(client: ModbusTcpClient):
                    valve_results: Dict[str, bool] = {}
                    req_snapshot = self.get_valve_requests()
                    is_alarming_cached = self.is_alarming
                    outlet = _manual_coil_outlet_point()
                    coil_task_context = modbus_context(
                        source="sensor_update",
                        request_name="update_sensor_coils",
                    )

                    if req_snapshot:
                        pending_requests = []
                        for v_name, v_state in req_snapshot.items():
                            if is_alarming_cached and v_state:
                                if outlet is None or v_name != outlet:
                                    continue
                            pending_requests.append((v_name, v_state))
                        if pending_requests:
                            now_ts = time.time()
                            if now_ts - self._last_valve_close_ts >= self._valve_close_interval:
                                idx = self._valve_close_cursor % len(pending_requests)
                                v_name, v_state = pending_requests[idx]
                                if v_name in valve_map:
                                    mode_name = f"{v_name}_{'ON' if v_state else 'OFF'}"
                                    segs = mode_segments_for(mode_name)
                                    if not segs:
                                        logger.warning(
                                            f"script_define 缺少模式 {mode_name!r}，跳过线圈写入"
                                        )
                                    else:
                                        try:
                                            LOG_SIGNAL.info(
                                                f"线圈写入(script_define): {mode_name} "
                                                f"(write_coils, unit=1)"
                                            )
                                            write_coils_segments(
                                                client,
                                                segs,
                                                unit=1,
                                                ip=coil_ip,
                                                port=coil_port,
                                                context=merge_modbus_context(
                                                    coil_task_context,
                                                    source="sensor_update_valve_request",
                                                    request_name="update_sensor_valve_request",
                                                    mode_name=mode_name,
                                                    valve_name=v_name,
                                                    desired_state=v_state,
                                                ),
                                            )
                                            self._last_valve_close_ts = time.time()
                                            self._valve_close_cursor += 1
                                        except Exception as e:
                                            logger.error(f"Failed to set valve mode {mode_name}: {e}")

                    for name, addr in valve_map.items():
                        try:
                            started_ms = now_ms()
                            resp = client.read_coils(addr, 1, unit=1)
                            if not resp.isError():
                                valve_results[name] = resp.bits[0]
                                log_modbus_event(
                                    operation="read_coils",
                                    ip=coil_ip,
                                    port=coil_port,
                                    unit=1,
                                    address=addr,
                                    count=1,
                                    success=True,
                                    result={"bits": list(resp.bits), "value": resp.bits[0]},
                                    elapsed_ms_value=elapsed_ms(started_ms),
                                    context=merge_modbus_context(
                                        coil_task_context,
                                        source="sensor_update_valve_status",
                                        request_name="update_sensor_valve_status",
                                        point_name=name,
                                    ),
                                )
                        except Exception:
                            pass

                    return valve_results

                def run_holding_acquisition():
                    """传感器/风扇走寄存器网关；报警输入走 IO 线圈模块端点。"""
                    results: Dict[str, float] = {}
                    fan_speed_result = self.fan_speed
                    fan_read_ok = False
                    fan_error: Optional[str] = None
                    alarm_result = False
                    for sensor_name, cfg in sensors_config.items():
                        if not cfg.get("enabled", True):
                            continue
                        driver_name = cfg.get("driver")
                        params = cfg.get("params", {})
                        try:
                            driver = DriverFactory.create(driver_name)
                            values = driver.read(reg_ip, reg_port, params)
                            results.update(values)
                        except Exception as e:
                            logger.error(f"Error reading sensor {sensor_name}: {e}")

                    if fan_conf.get("enabled", False):
                        unit = fan_conf.get("unit", 7)
                        try:
                            from .alert_and_fan import (
                                get_current_speed_with_status,
                                get_new_fan_speed,
                                set_new_fan_speed,
                            )

                            read_speed, fan_read_ok, fan_error = get_current_speed_with_status(
                                reg_ip, reg_port, fan_unit=unit
                            )
                            if fan_read_ok:
                                fan_speed_result = read_speed
                            else:
                                logger.warning(
                                    f"风扇读取失败，沿用缓存速度 fan_speed={fan_speed_result} unit={unit}"
                                )
                            current_temp = 0.0
                            if "pt100" in results:
                                current_temp = results["pt100"]
                            else:
                                for s_name, val in results.items():
                                    if "pt100" in s_name.lower() or "temp" in s_name.lower():
                                        current_temp = val
                                        break
                            if current_temp > 0:
                                target_temp = fan_conf.get("target_temp", 25.0)
                                stop_temp = fan_conf.get("stop_temp", 20.0)
                                start_temp = fan_conf.get("start_temp", 30.0)
                                min_speed = fan_conf.get("min_speed", 50)
                                max_speed = fan_conf.get("max_speed", 100)
                                k_factor = fan_conf.get("k_factor", 5)
                                if "start_temp" not in fan_conf and "target_temp" in fan_conf:
                                    start_temp = target_temp
                                new_speed = get_new_fan_speed(
                                    current_temp,
                                    fan_speed_result,
                                    start_temp=start_temp,
                                    stop_temp=stop_temp,
                                    k_factor=k_factor,
                                    min_speed=min_speed,
                                    max_speed=max_speed,
                                )
                                if int(time.time()) % 5 == 0:
                                    logger.debug(
                                        f"Fan Control: Temp={current_temp:.1f}, "
                                        f"Spd {fan_speed_result} -> {new_speed}"
                                    )
                                if new_speed != fan_speed_result:
                                    logger.debug(f"Adjusting Fan Speed to {new_speed}")
                                    set_new_fan_speed(
                                        reg_ip, reg_port, new_speed, fan_unit=unit
                                    )
                                    fan_speed_result = new_speed
                        except Exception as e:
                            fan_read_ok = False
                            fan_error = str(e)
                            logger.error(f"风扇控制异常: {e}")

                    if alarm_conf.get("enabled", False):
                        a_addr = int(alarm_conf.get("address", 0))
                        a_unit = int(alarm_conf.get("unit", 1))
                        try:
                            from .alert_and_fan import read_alert_message

                            alarm_result = read_alert_message(
                                coil_ip,
                                coil_port,
                                a_addr,
                                mock_mode=False,
                                unit=a_unit,
                            )
                        except Exception:
                            pass

                    return (
                        results,
                        fan_speed_result,
                        alarm_result,
                        fan_read_ok,
                        fan_error,
                    )

                def _run_coils():
                    return run_ephemeral(coil_ip, coil_port, coil_task)

                sensor_vals: Dict[str, Any] = {}
                valve_vals: Dict[str, bool] = {}
                alarm_val = False
                fan_val = self.fan_speed
                fan_read_ok_val = self.fan_read_ok
                fan_error_val = self.fan_last_error
                req_snapshot_tick = self.get_valve_requests()
                if same_modbus_endpoint:
                    try:
                        valve_vals = _run_coils()
                        (
                            sensor_vals,
                            fan_val,
                            alarm_val,
                            fan_read_ok_val,
                            fan_error_val,
                        ) = run_holding_acquisition()
                    except Exception as e:
                        logger.error(f"Modbus 采集失败（同网关）: {e}")
                        valve_vals = {}
                        sensor_vals = {}
                        fan_val = self.fan_speed
                        alarm_val = False
                        fan_read_ok_val = False
                        fan_error_val = str(e)
                else:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        f_coil = pool.submit(_run_coils)
                        f_reg = pool.submit(run_holding_acquisition)
                        try:
                            valve_vals = f_coil.result(timeout=120.0)
                        except Exception as e:
                            logger.error(f"线圈平面更新失败: {e}")
                            valve_vals = {}
                        try:
                            (
                                sensor_vals,
                                fan_val,
                                alarm_val,
                                fan_read_ok_val,
                                fan_error_val,
                            ) = f_reg.result(timeout=120.0)
                        except Exception as e:
                            logger.error(f"寄存器/传感器采集失败: {e}")
                            sensor_vals = {}
                            fan_val = self.fan_speed
                            alarm_val = False
                            fan_read_ok_val = False
                            fan_error_val = str(e)

                # 报警为真时在线圈侧紧急关阀（除 outlet_point 配置的出水口）
                if alarm_val and alarm_conf.get("enabled", False):
                    em_outlet = _manual_coil_outlet_point()

                    def emergency_close_task(client: ModbusTcpClient):
                        em_segs = mode_segments_for(MANUAL_EMERGENCY_CLOSE_MODE)
                        if em_segs:
                            try:
                                write_coils_segments(
                                    client,
                                    em_segs,
                                    unit=1,
                                    ip=coil_ip,
                                    port=coil_port,
                                    context=modbus_context(
                                        source="alarm_emergency_close",
                                        request_name="emergency_close_mode",
                                        mode_name=MANUAL_EMERGENCY_CLOSE_MODE,
                                    ),
                                )
                            except Exception as e:
                                logger.error(f"Emergency close (mode) failed: {e}")
                        else:
                            for name, v_addr in valve_map.items():
                                if em_outlet and name == em_outlet:
                                    continue
                                try:
                                    started_ms = now_ms()
                                    client.write_coil(v_addr, False, unit=1)
                                    log_modbus_event(
                                        operation="write_coil",
                                        ip=coil_ip,
                                        port=coil_port,
                                        unit=1,
                                        address=v_addr,
                                        count=1,
                                        data=[False],
                                        success=True,
                                        elapsed_ms_value=elapsed_ms(started_ms),
                                        context=modbus_context(
                                            source="alarm_emergency_close",
                                            request_name="emergency_close_point",
                                            point_name=name,
                                        ),
                                    )
                                except Exception as e:
                                    logger.error(f"Emergency close failed for {name}: {e}")
                        for name in valve_map:
                            if em_outlet and name == em_outlet:
                                continue
                            valve_vals[name] = False
                            with self._valve_req_lock:
                                if name in self._valve_requests:
                                    self._valve_requests[name] = False
                        return None

                    try:
                        run_ephemeral(
                            coil_ip,
                            coil_port,
                            emergency_close_task,
                            context=modbus_context(
                                source="alarm_emergency_close",
                                request_name="emergency_close",
                            ),
                        )
                    except Exception as e:
                        logger.error(f"报警紧急关阀任务失败: {e}")

                if not alarm_val and req_snapshot_tick:
                    current_requests = self.get_valve_requests()
                    for name, desired in current_requests.items():
                        if name in valve_vals and valve_vals[name] == desired:
                            self.clear_valve_request(name)

            # 更新传感器值 - 简单赋值，无需锁
            for key, value in sensor_vals.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            
            # Update valves
            self.valves.update(valve_vals)
            self.is_alarming = alarm_val
            self.fan_speed = fan_val
            self.fan_read_ok = fan_read_ok_val
            self.fan_last_error = fan_error_val
            self.fan_last_read_ts = time.time()
            
            self._last_update_ts = time.time()
            self._last_error = None
            snap = self.get_snapshot()
            LOG_SENSOR.info(
                "传感器采集 "
                f"DDL={snap['ddl']:.4g} PH={snap['ph']:.4g} "
                f"PT100={snap['pt100']:.4g} PH_TEMP={snap['ph_temp']:.4g} | "
                f"阀门={snap['valves']} | 报警={snap['is_alarming']} | "
                f"风扇={snap['fan_speed']} read_ok={snap['fan_read_ok']}"
            )

        except Exception as e:
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
        logger.debug(f"请求启动自动更新线程: {ip}:{port}, interval={interval_seconds}s")
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.debug("自动更新线程已在运行，忽略重复启动。")
                return
            self._interval = max(0.1, float(interval_seconds))
            self._on_update = on_update
            self._stop_event = threading.Event()

        def _loop():
            logger.debug(
                f"自动更新线程启动: {ip}:{port}, interval={self._interval}s"
            )
            while True:
                # 检查停止
                if self._stop_event and self._stop_event.is_set():
                    logger.debug("自动更新线程收到停止信号，准备退出。")
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
                if self._stop_event and self._stop_event.wait(self._interval):
                    logger.debug("自动更新线程在等待间隔时被停止。")
                    break

            logger.debug("自动更新线程已退出。")

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
        """在下一个周期生效 - 简单赋值，无需锁"""
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

def switch_valve_by_script_mode(
    ip: str, port: int, mode_name: str, mock_mode: bool = False
) -> Optional[float]:
    """
    手动模式：按 script_define「模式定义」写线圈（write_coils），与自动控制独立。
    使用 modbus_coils 的 IP/端口，unit 固定为 1。
    mode_name 与 API device_type 一致：「基础点位名」+ _ON 或 _OFF（与 xlsx 名称列一致）。
    """
    try:
        if mock_mode:
            LOG_SIGNAL.info(f"[模拟] 手动线圈模式: {mode_name}")
            v_key, on_state = parse_manual_mode_name(mode_name)
            sdm = SensorDataManager.instance()
            st = DeviceSettings.instance()
            coil_ip, coil_port = st.get_modbus_coils_endpoint()
            segs = mode_segments_for(mode_name) or []
            for start_addr, vals in segs:
                log_modbus_event(
                    operation="write_coils",
                    ip=coil_ip,
                    port=coil_port,
                    unit=1,
                    address=start_addr,
                    count=len(vals),
                    data=list(vals),
                    success=True,
                    context=mock_modbus_context(
                        source="mock_manual_api",
                        request_name="switch_valve_by_script_mode",
                        mode_name=mode_name,
                        point_name=v_key,
                        desired_state=on_state,
                        script_command=mode_name,
                    ),
                )
            sdm.set_valve_request(v_key, on_state)
            if not sdm.apply_script_mode_to_cache(mode_name):
                sdm.update_valve_cache(v_key, on_state)
            return True

        v_key, on_state = parse_manual_mode_name(mode_name)
        try:
            SensorDataManager.instance().set_valve_request(v_key, on_state)
        except Exception:
            pass

        segs = mode_segments_for(mode_name)
        if not segs:
            raise ModbusException(
                f"script_define 中未定义模式 {mode_name!r}，无法写手动线圈"
            )

        st = DeviceSettings.instance()
        coil_ip, coil_port = st.get_modbus_coils_endpoint()

        def task(client: ModbusTcpClient) -> bool:
            write_coils_segments(
                client,
                segs,
                unit=1,
                ip=coil_ip,
                port=coil_port,
                context=modbus_context(
                    source="manual_api",
                    request_name="switch_valve_by_script_mode",
                    mode_name=mode_name,
                    point_name=v_key,
                    desired_state=on_state,
                ),
            )
            return True

        res = run_ephemeral(
            coil_ip,
            coil_port,
            task,
            context=modbus_context(
                source="manual_api",
                request_name="switch_valve_by_script_mode",
                mode_name=mode_name,
                point_name=v_key,
                desired_state=on_state,
            ),
        )
        sdm = SensorDataManager.instance()
        if not sdm.apply_script_mode_to_cache(mode_name):
            sdm.update_valve_cache(v_key, on_state)
        LOG_SIGNAL.info(f"手动线圈写入成功: {mode_name} (write_coils, unit=1)")
        return res

    except Exception as e:
        logger.error(f"手动线圈写入失败: {e}")
        raise


async def reset_devices(ip: str, port: int, reg: int, mock_mode: bool = False):
    """
    异步重置设备 - 短连接 Modbus（run_ephemeral）
    
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
            
        logger.debug(f"开始重置设备 - IP: {ip}, Port: {port}, Register: {reg}, 模拟模式: {mock_mode}")
        
        if mock_mode:
            # 模拟模式：不连接真实设备，只模拟重置过程
            logger.debug("[模拟模式] 开始模拟设备重置...")
            
            # 模拟第一步：设置重置信号
            logger.debug(f"[模拟模式] 设置重置信号 - 寄存器 {reg} 设置为 True")
            log_modbus_event(
                operation="write_coil",
                ip=ip,
                port=port,
                unit=1,
                address=reg,
                count=1,
                data=[True],
                success=True,
                context=mock_modbus_context(
                    source="mock_reset_device",
                    request_name="reset_phase_set_true",
                    register=reg,
                ),
            )
            await asyncio.sleep(1)  # 模拟网络延迟
            
            # 模拟30秒重置过程（加速到3秒用于测试）
            reset_duration = 3  # 测试时缩短到3秒
            logger.debug(f"[模拟模式] 等待设备重置完成 ({reset_duration}秒)...")
            
            # 分阶段显示进度
            for i in range(reset_duration):
                await asyncio.sleep(1)
                progress = ((i + 1) / reset_duration) * 100
                logger.debug(f"[模拟模式] 重置进度: {progress:.0f}% ({i + 1}/{reset_duration}秒)")
            
            # 模拟第二步：清除重置信号
            logger.debug(f"[模拟模式] 清除重置信号 - 寄存器 {reg} 设置为 False")
            log_modbus_event(
                operation="write_coil",
                ip=ip,
                port=port,
                unit=1,
                address=reg,
                count=1,
                data=[False],
                success=True,
                context=mock_modbus_context(
                    source="mock_reset_device",
                    request_name="reset_phase_clear_false",
                    register=reg,
                ),
            )
            await asyncio.sleep(1)  # 模拟网络延迟
            
            logger.debug("[模拟模式] 设备重置完成")
            
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
            # 真实模式：线圈平面（重置线圈）
            st = DeviceSettings.instance()
            coil_ip, coil_port = st.get_modbus_coils_endpoint()

            def reset_task(client: ModbusTcpClient):
                started_ms = now_ms()
                response1 = client.write_coil(reg, True, unit=1)
                if response1.isError():
                    log_modbus_event(
                        operation="write_coil",
                        ip=coil_ip,
                        port=coil_port,
                        unit=1,
                        address=reg,
                        count=1,
                        data=[True],
                        success=False,
                        error=str(response1),
                        elapsed_ms_value=elapsed_ms(started_ms),
                        context=modbus_context(
                            source="reset_device",
                            request_name="reset_phase_set_true",
                            register=reg,
                        ),
                    )
                    raise ModbusException(f"设置重置信号失败: {response1}")
                log_modbus_event(
                    operation="write_coil",
                    ip=coil_ip,
                    port=coil_port,
                    unit=1,
                    address=reg,
                    count=1,
                    data=[True],
                    success=True,
                    elapsed_ms_value=elapsed_ms(started_ms),
                    context=modbus_context(
                        source="reset_device",
                        request_name="reset_phase_set_true",
                        register=reg,
                    ),
                )
                return True

            def _phase1():
                run_ephemeral(
                    coil_ip,
                    coil_port,
                    reset_task,
                    context=modbus_context(
                        source="reset_device",
                        request_name="reset_phase1",
                        register=reg,
                    ),
                )

            await run_device_io(_phase1)
            logger.debug(f"[真实模式] 传感器重置开始 - 寄存器 {reg} 设置为 True")
            
            # 等待30秒重置时间
            reset_duration = 30
            logger.debug(f"[真实模式] 等待设备重置完成 ({reset_duration}秒)...")
            await asyncio.sleep(reset_duration)
            
            def clear_task(client: ModbusTcpClient):
                started_ms = now_ms()
                response2 = client.write_coil(reg, False, unit=1)
                if response2.isError():
                    log_modbus_event(
                        operation="write_coil",
                        ip=coil_ip,
                        port=coil_port,
                        unit=1,
                        address=reg,
                        count=1,
                        data=[False],
                        success=False,
                        error=str(response2),
                        elapsed_ms_value=elapsed_ms(started_ms),
                        context=modbus_context(
                            source="reset_device",
                            request_name="reset_phase_clear_false",
                            register=reg,
                        ),
                    )
                    raise ModbusException(f"清除重置信号失败: {response2}")
                log_modbus_event(
                    operation="write_coil",
                    ip=coil_ip,
                    port=coil_port,
                    unit=1,
                    address=reg,
                    count=1,
                    data=[False],
                    success=True,
                    elapsed_ms_value=elapsed_ms(started_ms),
                    context=modbus_context(
                        source="reset_device",
                        request_name="reset_phase_clear_false",
                        register=reg,
                    ),
                )
                return True

            def _phase2():
                run_ephemeral(
                    coil_ip,
                    coil_port,
                    clear_task,
                    context=modbus_context(
                        source="reset_device",
                        request_name="reset_phase2",
                        register=reg,
                    ),
                )

            await run_device_io(_phase2)
            logger.debug(f"[真实模式] 传感器重置完成 - 寄存器 {reg} 设置为 False")
            
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


def build_modbus_config_settings() -> Dict[str, Any]:
    """传感器读 + script_define 每个基础点位对应的 _ON/_OFF 手动指令。"""
    base: Dict[str, Any] = {
        "DDL": [read_ddl],
        "PT100": [read_pt100_temp],
        "PH": [read_ph_value],
        "PH_TEMP": [read_ph_temp],
    }
    eng = _get_script_engine_safe()
    if not eng or not eng.registry.points:
        return base
    for pname in eng.registry.points:
        on = f"{pname}_ON"
        off = f"{pname}_OFF"
        base[on] = [switch_valve_by_script_mode, on]
        base[off] = [switch_valve_by_script_mode, off]
    return base


class DeviceConfig:
    """设备配置类，用于管理Modbus设备连接和数据读取"""
    
    def __init__(self, mock_mode: bool = False):
        settings = DeviceSettings.instance()
        self.ip_address = settings.get_ip()
        self.port = settings.get_port()
        self.mock_mode = mock_mode  # 添加模拟模式标志

        self.modbus_config_settings = build_modbus_config_settings()
        self.sdm = SensorDataManager()
        
        # 不再在初始化时自动启动 SensorDataManager
        # 由 AutoControlManager 或其他需要的地方按需启动
        logger.debug(f"DeviceConfig initialized for {self.ip_address}:{self.port} (mock={self.mock_mode})")
        logger.debug("SensorDataManager will be started on-demand by AutoControlManager or other services")
        
    
    def set_address(self, ip: str, port: int) -> None:
        """
        设置设备地址
        
        Args:
            ip: IP地址
            port: 端口号
        """
        self.ip_address = ip
        self.port = port
        
        # Update settings
        settings = DeviceSettings.instance()
        settings.update_config({
            "ip": ip,
            "port": port
        })
        
        # Restart auto update with new address if it was running
        was_running = self.sdm.is_running()
        if was_running:
            self.sdm.stop_auto_update()
            self.sdm.start_auto_update(self.ip_address, self.port, interval_seconds=5.0, daemon=True)
        
        logger.debug(f"设备地址已更新为: {ip}:{port}")
        
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

            def _sync_inquire():
                return func(self.ip_address, self.port, *args)

            result = await run_device_io(_sync_inquire)
            logger.debug(f"成功查询设备 {device_type}, 结果: {result}")
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
        
        logger.debug(f"模拟模式 - 开始获取设备数据: {device_type}")
        
        # Try to get from SensorDataManager first if it has data (for consistency)
        sdm = SensorDataManager.instance()
        
        # Helper to get or random
        def get_or_random(current_val, min_v, max_v):
            if current_val is not None and current_val > 0:
                return current_val
            return round(random.uniform(min_v, max_v), 2)

        # 为不同类型的设备返回不同的模拟数据
        mock_data_map = {
            "DDL": lambda: get_or_random(sdm.get_ddl(), 0.5, 10.0),
            "PT100": lambda: get_or_random(sdm.get_pt100(), 15.0, 85.0),
            "PH": lambda: get_or_random(sdm.get_ph(), 6.0, 8.5),
            "PH_TEMP": lambda: get_or_random(sdm.get_ph_temp(), 20.0, 30.0),
        }

        if device_type in mock_data_map:
            logger.debug("模拟硬件延时 1 秒...")
            await asyncio.sleep(1.0)
            result = mock_data_map[device_type]()
            logger.debug(f"模拟模式 - 成功获取设备数据 [{device_type}]: {result}")
            return result

        try:
            parse_manual_mode_name(device_type)
        except ValueError:
            raise ValueError(f"模拟模式不支持的设备类型: {device_type}")

        switch_valve_by_script_mode("", 0, device_type, mock_mode=True)
        logger.debug("模拟硬件延时 1 秒...")
        await asyncio.sleep(1.0)
        logger.debug(f"模拟模式 - 成功获取设备数据 [{device_type}]: True")
        return True
    
    def get_device_types(self) -> list:
        """
        获取支持的设备类型列表
        
        Returns:
            支持的设备类型列表
        """
        return list(self.modbus_config_settings.keys())
    
    async def test_connection(self) -> bool:
        """
        测试设备连接 - 短连接探测（run_ephemeral）
        
        Returns:
            连接成功返回True，否则返回False
        """
        if self.mock_mode:
            import asyncio
            logger.debug("模拟模式 - 开始连接测试")
            logger.debug("模拟连接测试延时 1 秒...")
            await asyncio.sleep(1.0)
            logger.debug("模拟模式 - 连接测试成功")
            return True
            
        try:
            def _sync_test_connection() -> bool:
                st = DeviceSettings.instance()
                coil_ip, coil_port = st.get_modbus_coils_endpoint()
                reg_ip, reg_port = st.get_modbus_holding_endpoint()

                def test_coils(client: ModbusTcpClient) -> bool:
                    return bool(client.is_socket_open())

                def test_registers(client: ModbusTcpClient) -> bool:
                    return bool(client.is_socket_open())

                ok_coil = run_ephemeral(
                    coil_ip,
                    coil_port,
                    test_coils,
                    context=modbus_context(
                        source="manual_api",
                        request_name="test_connection_coils",
                    ),
                )
                ok_reg = run_ephemeral(
                    reg_ip,
                    reg_port,
                    test_registers,
                    context=modbus_context(
                        source="manual_api",
                        request_name="test_connection_registers",
                    ),
                )
                return bool(ok_coil and ok_reg)

            result = await run_device_io(_sync_test_connection)
            if result:
                st = DeviceSettings.instance()
                coil_ip, coil_port = st.get_modbus_coils_endpoint()
                reg_ip, reg_port = st.get_modbus_holding_endpoint()
                logger.debug(
                    f"连接测试成功 coils={coil_ip}:{coil_port} registers={reg_ip}:{reg_port}"
                )
            else:
                logger.warning("❌ 连接测试失败 coils_ok/registers_ok")
            return result
        except Exception as e:
            logger.error(f"连接测试失败: {e}")
            return False
    
    def reload_config(self):
        """重新加载配置（手动阀门仍由 script_define 决定）"""
        self.modbus_config_settings = build_modbus_config_settings()
        logger.debug("设备配置已重新加载")

    def get_connection_pool_status(self) -> Dict[str, Any]:
        """Modbus 短连接模式状态（无连接池，供调试/监控）。"""
        return get_ephemeral_status_snapshot()

    async def get_all_valve_statuses(self) -> Dict[str, bool]:
        """
        获取所有阀门和灯光的状态
        - 如果 SensorDataManager 正在运行，使用缓存数据
        - 否则，直接查询设备
        """
        if self.mock_mode:
             # Mock return cached state
             return self.sdm.get_valve_statuses()
        
        # 检查 SensorDataManager 是否正在运行
        if self.sdm.is_running():
            # 使用缓存数据，避免冲突
            return self.sdm.get_valve_statuses()
        else:
            settings = DeviceSettings.instance()
            coil_ip, coil_port = settings.get_modbus_coils_endpoint()
            valve_map = manual_valve_address_map()

            def task(client: ModbusTcpClient):
                valve_results: Dict[str, bool] = {
                    k: False for k in sorted(valve_map.keys())
                }
                for name, addr in valve_map.items():
                    try:
                        started_ms = now_ms()
                        resp = client.read_coils(addr, 1, unit=1)
                        if not resp.isError():
                            valve_results[name] = resp.bits[0]
                            log_modbus_event(
                                operation="read_coils",
                                ip=coil_ip,
                                port=coil_port,
                                unit=1,
                                address=addr,
                                count=1,
                                success=True,
                                result={"bits": list(resp.bits), "value": resp.bits[0]},
                                elapsed_ms_value=elapsed_ms(started_ms),
                                context=modbus_context(
                                    source="manual_api",
                                    request_name="get_all_valve_statuses",
                                    point_name=name,
                                ),
                            )
                        else:
                            valve_results[name] = False
                    except Exception as e:
                        logger.warning(f"Failed to read valve {name}: {e}")
                        valve_results[name] = False
                return valve_results

            def _sync_valve_statuses() -> Dict[str, bool]:
                return run_ephemeral(
                    coil_ip,
                    coil_port,
                    task,
                    context=modbus_context(
                        source="manual_api",
                        request_name="get_all_valve_statuses",
                    ),
                )

            try:
                return await run_device_io(_sync_valve_statuses)
            except Exception as e:
                logger.error(f"Failed to query valve statuses independently: {e}")
                vm = manual_valve_address_map()
                return {k: False for k in sorted(vm.keys())}



