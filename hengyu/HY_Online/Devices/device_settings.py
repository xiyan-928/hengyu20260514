import json
import os
import logging
from typing import Dict, Any, Tuple, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "ip": "192.168.1.12",
    "port": 502,
    "sensors": {
        "DDL": {
            "driver": "DefaultDDL",
            "enabled": True,
            "params": {
                "unit": 8,
                "address": 3
            }
        },
        "PH": {
            "driver": "DefaultPH",
            "enabled": True,
            "params": {
                "unit": 9,
                "address": 6
            }
        },
        "PT100": {
            "driver": "DefaultPT100",
            "enabled": True,
            "params": {
                "unit": 20,
                "address": 0
            }
        }
    },
    "relays": {
        "LIGHT": {"address": 0},
        "VALVE_OUT": {"address": 2},
        "VALVE_IN": {"address": 1},
        "VALVE_CLEAN": {"address": 3}
    },
    "alarm": {
        "enabled": True,
        "address": 0,
        "fc": 2,
        "unit": 1
    },
    "fan": {
        "enabled": True,
        "unit": 7,
        "target_temp": 25.0, # 保留以兼容旧代码，但主要逻辑将迁移到 start_temp
        "stop_temp": 20.0,   # 新增：停止温度
        "start_temp": 30.0,  # 新增：启动温度
        "min_speed": 50,
        "max_speed": 100,
        "k_factor": 5
    },
    "auto_control": {
        "enabled": True,
        "modbus_host": "localhost",
        "modbus_port": 5020,
        "unit_id": 1,
        "monitor_register": 1,
        "wait_time": 300,
        "script_define_path": "define/script_define.xlsx"
    },
    # 线圈侧（阀、线圈状态、离散量报警等）；空对象表示沿用顶层 ip/port
    "modbus_coils": {},
    # 寄存器侧（holding/input 传感器读、风扇 holding 等）；空对象表示沿用顶层 ip/port
    "modbus_holding": {},
    "manual_coil": {
        "outlet_point": None,
        "signal_zero_close_points": [],
        "autorun_open_points": [],
    },
    "spectrum": {
        "query_interval_sec": 60,
    },
}

class DeviceSettings:
    _instance = None
    _config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'device_config.json')
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DeviceSettings, cls).__new__(cls)
            cls._instance._config = DEFAULT_CONFIG.copy()
            cls._instance.load()
        return cls._instance
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def load(self):
        """Load configuration from JSON file"""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    # Merge with default to ensure all keys exist
                    self._merge_config(self._config, saved_config)
                logger.debug(f"Loaded device configuration from {self._config_file}")
            else:
                logger.debug("No device configuration file found, using defaults")
                self.save() # Save defaults
        except Exception as e:
            logger.error(f"Error loading device configuration: {e}")
            
    def save(self):
        """Save configuration to JSON file"""
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=4)
            logger.debug(f"Saved device configuration to {self._config_file}")
        except Exception as e:
            logger.error(f"Error saving device configuration: {e}")
            
    def _merge_config(self, default: Dict, saved: Dict):
        """Recursively merge saved config into default config"""
        for key, value in saved.items():
            if key in default and isinstance(default[key], dict) and isinstance(value, dict):
                self._merge_config(default[key], value)
            else:
                default[key] = value
                
    @property
    def config(self) -> Dict[str, Any]:
        return self._config
        
    def update_config(self, new_config: Dict[str, Any]):
        """Update configuration and save"""
        logger.debug(f"Updating config: {new_config.keys()}")
        if 'auto_control' in new_config:
            logger.debug(f"Updating auto_control: {new_config['auto_control']}")
        self._merge_config(self._config, new_config)
        self.save()
        
    def get_ip(self) -> str:
        return self._config.get('ip', '192.168.1.12')
        
    def get_port(self) -> int:
        return self._config.get('port', 502)
        
    def get_sensors(self) -> Dict[str, Any]:
        return self._config.get('sensors', {})
        
    def get_relays(self) -> Dict[str, Any]:
        return self._config.get('relays', {})

    def get_auto_control_settings(self) -> Dict[str, Any]:
        return self._config.get('auto_control', {})

    def get_spectrum_query_interval_sec(self) -> float:
        """光谱查询间隔；上传客户端使用同一值作为采样 SPC 上传间隔。"""
        spectrum = self._config.get("spectrum") or {}
        try:
            value = float(spectrum.get("query_interval_sec", 60))
        except (TypeError, ValueError):
            value = 60.0
        return max(1.0, value)

    def get_modbus_coils_endpoint(self) -> Tuple[str, int]:
        """线圈/离散量网关；未配置 host/port 时回退到设备 ip/port。"""
        m = self._config.get("modbus_coils") or {}
        host = m.get("host")
        if host is None or host == "":
            host = self.get_ip()
        port = m.get("port")
        if port is None:
            port = self.get_port()
        return str(host).strip(), int(port)

    def get_modbus_holding_endpoint(self) -> Tuple[str, int]:
        """寄存器网关（holding + input register 等）；未配置时回退到设备 ip/port。"""
        m = self._config.get("modbus_holding") or {}
        host = m.get("host")
        if host is None or host == "":
            host = self.get_ip()
        port = m.get("port")
        if port is None:
            port = self.get_port()
        return str(host).strip(), int(port)

    def get_manual_coil_settings(self) -> Dict[str, Any]:
        return self._config.get("manual_coil") or {}

    def get_manual_coil_outlet_point(self) -> Optional[str]:
        v = self.get_manual_coil_settings().get("outlet_point")
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    def list_script_define_point_names(self) -> List[str]:
        """script_define 基础点位名称（与 xlsx「名称」列一致）。"""
        try:
            from auto_control_script_engine import get_script_engine

            reg = get_script_engine().registry
            return sorted(reg.points.keys())
        except Exception:
            return []

    def get_manual_coil_signal_zero_points(self) -> List[str]:
        """控制信号为 0 时需关闭的点位；空列表表示全部基础点位。"""
        pts = self.get_manual_coil_settings().get("signal_zero_close_points")
        if isinstance(pts, list) and len(pts) > 0:
            return [str(p) for p in pts]
        return self.list_script_define_point_names()

    def get_manual_coil_autorun_open_points(self) -> List[str]:
        """计时结束后需打开的点位；空列表表示全部基础点位。"""
        pts = self.get_manual_coil_settings().get("autorun_open_points")
        if isinstance(pts, list) and len(pts) > 0:
            return [str(p) for p in pts]
        return self.list_script_define_point_names()
