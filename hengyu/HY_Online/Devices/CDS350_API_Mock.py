import os
import ctypes
import time
import numpy as np
import random
from typing import Tuple, List

from .CDS350_API import _CDS350SingletonBase


class CDS350_Mock(_CDS350SingletonBase):
    """CDS350光谱仪模拟类 - 用于无硬件环境下的调试。进程内单例。"""

    _instance = None

    def __init__(self):
        """初始化模拟CDS350设备"""
        if getattr(self, "_cds350_singleton_ready", False):
            return
        print("🔧 初始化CDS350模拟设备...")
        
        # 模拟设备句柄
        self.handle = ctypes.c_int(-1)
        
        # 模拟设备参数
        self.integration_time = 10000  # 默认积分时间 10ms
        self.scans_to_average = 3      # 默认平均次数
        
        # 预生成的模拟光谱数据
        self.wavelengths = None
        self.spectrum = None
        
        # 设备状态
        self.is_initialized = False

        print("✅ CDS350模拟设备初始化完成")
        self._cds350_singleton_ready = True

    def _generate_mock_spectrum(self) -> Tuple[List[float], List[int]]:
        """生成模拟光谱数据"""
        # 生成波长范围 200-1100nm (CDS350典型范围)
        wavelengths = np.linspace(200, 1100, 2048).tolist()
        
        # 生成模拟光谱强度
        # 使用多个高斯峰来模拟真实光谱
        x = np.array(wavelengths)
        intensity = np.zeros_like(x)
        
        # 添加几个特征峰
        peaks = [
            (350, 2000, 50),   # 峰位置, 强度, 宽度
            (450, 3500, 30),
            (550, 4000, 40),
            (650, 2800, 35),
            (750, 3200, 45),
            (850, 1800, 60)
        ]
        
        for peak_pos, peak_intensity, peak_width in peaks:
            intensity += peak_intensity * np.exp(-(x - peak_pos)**2 / (2 * peak_width**2))
        
        # 添加基线和噪声
        baseline = 500 + 200 * np.sin(x / 100)
        noise = np.random.normal(0, 50, len(x))
        
        intensity = intensity + baseline + noise
        
        # 确保强度为正值且在合理范围内
        intensity = np.clip(intensity, 100, 65000).astype(int).tolist()
        
        return wavelengths, intensity

    def initialize_device(self) -> dict:
        """模拟初始化设备并打开第一个USB设备"""
        print("🔌 模拟CDS350设备初始化...")
        
        # 模拟初始化延时
        time.sleep(0.5)
        
        # 模拟设备连接成功
        self.handle = ctypes.c_int(1)  # 设置为有效句柄
        self.is_initialized = True
        
        print(f"✅ CDS350模拟设备初始化成功")
        print(f"   - 积分时间: {self.integration_time}μs")
        print(f"   - 平均次数: {self.scans_to_average}")
        
        return {
            "integration_time": self.integration_time,
            "scans_to_average": self.scans_to_average,
            "device_type": "CDS350_Mock",
            "status": "initialized"
        }

    def get_device_status(self) -> dict:
        """返回模拟设备连接状态，接口与真机保持一致。"""
        return {
            "device_type": "CDS350_Mock",
            "platform": "mock",
            "initialized": self.handle.value != -1 and self.is_initialized,
            "connected": self.handle.value != -1 and self.is_initialized,
            "handle": self.handle.value,
            "integration_time": self.integration_time if self.is_initialized else None,
            "scans_to_average": self.scans_to_average if self.is_initialized else None,
            "error_message": None,
        }

    def restart_device(self) -> dict:
        """模拟设备重启：关闭后重新初始化。"""
        self.close_device()
        result = self.initialize_device()
        return {
            "status": "restarted",
            "close_error": None,
            **result,
        }

    def close_device(self):
        """模拟关闭设备"""
        print("🔒 关闭CDS350模拟设备...")
        if self.handle.value != -1:
            self.handle = ctypes.c_int(-1)
            self.is_initialized = False
            print("✅ CDS350模拟设备已关闭")

    def set_integration_time(self, time: int):
        """模拟设置积分时间（微秒）"""
        if not isinstance(time, int) or time < 60:
            raise ValueError("积分时间必须为整数且至少为60微秒。")
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        
        self.integration_time = time
        print(f"📊 CDS350积分时间设置为: {time}μs")

    def get_integration_time(self) -> int:
        """模拟获取当前积分时间（微秒）"""
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        return self.integration_time

    def set_scans_to_average(self, scans: int):
        """模拟设置平均次数"""
        if not isinstance(scans, int) or scans < 1 or scans > 255:
            raise ValueError("平均次数必须为1到255之间的整数。")
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        
        self.scans_to_average = scans
        print(f"📊 CDS350平均次数设置为: {scans}")

    def get_scans_to_average(self) -> int:
        """模拟获取当前平均次数"""
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        return self.scans_to_average

    def read_spectrum(self) -> Tuple[np.ndarray, np.ndarray]:
        """模拟读取波长和光谱数据（与真机一致返回 float64 ndarray）"""
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        
        print("📡 CDS350正在采集光谱数据...")
        
        # 模拟采集时间（基于积分时间和平均次数）
        acquisition_time = (self.integration_time / 1000000) * self.scans_to_average
        acquisition_time = max(0.1, min(acquisition_time, 2.0))  # 限制在0.1-2秒
        
        # 添加一些随机延时模拟真实采集
        actual_time = acquisition_time + random.uniform(0.05, 0.2)
        time.sleep(actual_time)
        
        # 生成模拟光谱数据
        wavelengths, spectrum = self._generate_mock_spectrum()
        
        # 根据设备参数调整数据质量
        # 积分时间越长，信噪比越好
        snr_factor = min(self.integration_time / 50000, 2.0)  # 归一化SNR因子
        noise_level = max(10, 100 / snr_factor)
        
        # 添加设备参数相关的噪声
        noise = np.random.normal(0, noise_level, len(spectrum))
        spectrum = np.array(spectrum) + noise
        spectrum = np.clip(spectrum, 50, 65000).astype(np.float64)

        print(f"✅ CDS350光谱采集完成 - 数据点数: {len(wavelengths)}, 采集时间: {actual_time:.2f}s")

        return np.asarray(wavelengths, dtype=np.float64), spectrum

    def get_spectrum_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """获取光谱数据，返回波长和强度数组"""
        return self.read_spectrum()
    
    def __del__(self):
        """析构函数，确保设备关闭"""
        self.close_device()


# 为了保持兼容性，创建别名
CDS350 = CDS350_Mock


if __name__ == "__main__":
    # 测试模拟CDS350设备
    print("🧪 测试CDS350模拟设备")
    print("=" * 50)
    
    try:
        # 创建设备实例
        cds350 = CDS350_Mock()
        
        # 初始化设备
        integration_time, scans_to_average = cds350.initialize_device()
        
        # 测试参数设置
        cds350.set_integration_time(30000)
        cds350.set_scans_to_average(5)
        
        print(f"\n当前设备参数:")
        print(f"积分时间: {cds350.get_integration_time()}μs")
        print(f"平均次数: {cds350.get_scans_to_average()}")
        
        # 测试光谱采集
        print(f"\n开始光谱采集测试...")
        wavelengths, spectrum = cds350.read_spectrum()
        
        print(f"光谱数据统计:")
        print(f"- 波长范围: {min(wavelengths):.1f} - {max(wavelengths):.1f} nm")
        print(f"- 强度范围: {min(spectrum)} - {max(spectrum)}")
        print(f"- 平均强度: {np.mean(spectrum):.1f}")
        
        # 关闭设备
        cds350.close_device()
        
        print("\n✅ CDS350模拟设备测试完成")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
    finally:
        del cds350
