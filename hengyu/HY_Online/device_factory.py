"""
设备工厂类
用于根据配置创建相应的设备实例
"""
from config import app_config
from Devices.CDS350_API import CDS350
from Devices.CDS350_API_Mock import CDS350_Mock

class DeviceFactory:
    """设备工厂类"""
    
    @staticmethod
    def create_cds350_device():
        """根据配置创建CDS350设备实例"""
        if app_config.is_mock_mode():
            return CDS350_Mock()
        else:
            return CDS350()
    
    @staticmethod
    def get_device_mode_info():
        """获取设备模式信息"""
        return {
            "mode": app_config.device_mode.value,
            "description": app_config.get_mode_description(),
            "is_mock": app_config.is_mock_mode()
        }
