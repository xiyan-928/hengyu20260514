"""
应用配置文件
用于控制设备模式切换和其他应用配置
"""
import os
from enum import Enum

class DeviceMode(Enum):
    """设备模式枚举"""
    REAL = "real"      # 真实设备模式
    MOCK = "mock"      # 模拟设备模式

class AppConfig:
    """应用配置类"""
    
    def __init__(self):
        # 从环境变量读取设备模式，默认为模拟模式
        mode_str = os.getenv("DEVICE_MODE", "mock").lower()
        
        if mode_str == "real":
            self.device_mode = DeviceMode.REAL
        else:
            self.device_mode = DeviceMode.MOCK
            
        # API配置
        self.host = os.getenv("API_HOST", "0.0.0.0")
        self.port = int(os.getenv("API_PORT", "8000"))
        self.reload = os.getenv("API_RELOAD", "true").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "warning")
        
    def is_mock_mode(self) -> bool:
        """判断是否为模拟模式"""
        return self.device_mode == DeviceMode.MOCK
        
    def is_real_mode(self) -> bool:
        """判断是否为真实设备模式"""
        return self.device_mode == DeviceMode.REAL
        
    def get_mode_description(self) -> str:
        """获取模式描述"""
        if self.is_mock_mode():
            return "模拟设备模式 (Mock Mode)"
        else:
            return "真实设备模式 (Real Device Mode)"

# 全局配置实例
app_config = AppConfig()
