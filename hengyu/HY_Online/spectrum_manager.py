"""
光谱采集状态管理器
用于管理CDS350设备的光谱采集状态，避免并发采集导致的卡死问题
"""

import asyncio
import time
import threading
from typing import Tuple, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import logging

import numpy as np
import sys
import os

# 添加Devices目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'Devices'))

logger = logging.getLogger(__name__)


@dataclass
class DesiredSpectrumConfig:
    """采集前要应用到光谱仪的目标参数；None 表示沿用设备当前值。"""
    integration_time: Optional[int] = None
    scans_to_average: Optional[int] = None


@dataclass
class SpectrumSmoothingConfig:
    """光谱强度 EMA 平滑配置；alpha 越小越平滑。"""
    enabled: bool = True
    alpha: float = 0.25


def _spectrum_to_serializable_lists(
    wavelengths: Any,
    spectrum: Any,
) -> Tuple[List[float], List[float]]:
    """CDS350 驱动可返回 ndarray；API/缓存统一为 list 以便 JSON 序列化。"""
    if isinstance(wavelengths, np.ndarray):
        wavelengths = wavelengths.tolist()
    if isinstance(spectrum, np.ndarray):
        spectrum = spectrum.tolist()
    return wavelengths, spectrum


class AcquisitionStatus(Enum):
    """采集状态枚举"""
    IDLE = "idle"           # 空闲状态
    ACQUIRING = "acquiring"  # 正在采集
    COMPLETED = "completed"  # 采集完成
    ERROR = "error"         # 采集错误


@dataclass
class SpectrumData:
    """光谱数据类"""
    wavelengths: List[float]
    spectrum: List[float]
    timestamp: float
    acquisition_time: float
    integration_time: int
    scans_to_average: int
    #---------------------------------------
    spectrum_type: str = "measurement"  # "measurement" | "blank_before" | "blank_after"
    label: Optional[str] = None  # 参比光谱标签，如"置换前参比光谱"/"清洗后参比光谱"
    spc_file_path: Optional[str] = None  # 自动落盘的 SPC 文件绝对路径，None 表示未落盘
    raw_spectrum: Optional[List[float]] = None  # 扣暗前原始光谱
    dark_timestamp: Optional[float] = None  # 本次扣暗使用的暗光谱采集时间
    dark_corrected: bool = False  # spectrum 是否已扣除暗光谱
    smoothed: bool = False  # spectrum 是否已应用 EMA 平滑
    smoothing_alpha: Optional[float] = None  # 本次平滑使用的 EMA alpha
    #---------------------------------------

class SpectrumAcquisitionManager:
    """光谱采集管理器"""
    
    #---------------------------------------
    _BLANK_MAX = 100  # 每个标签类型最多保留的条数上限（全局）
    _DARK_INTERVAL_SEC = 30 * 60
    #---------------------------------------

    def __init__(self):
        self.status = AcquisitionStatus.IDLE
        self.current_data: Optional[SpectrumData] = None
        self.last_data: Optional[SpectrumData] = None
        self.acquisition_lock = threading.Lock()  # 仅用于采集操作的锁
        self.data_lock = threading.RLock()  # 用于保护数据读写的锁
        self.acquisition_thread: Optional[threading.Thread] = None
        self.error_message: Optional[str] = None
        self.acquisition_start_time: Optional[float] = None
        #-----------------------------------
        # 设备级串行锁：常规采集与参比光谱采集共享同一物理设备，
        # 若底层驱动非线程安全则必须串行化所有 get_spectrum_data 调用。
        self._device_lock = threading.Lock()
        #参比光谱独立存储（置换前 / 清洗后）
        self.blank_spectra: List[SpectrumData] = []
        self._blank_lock = threading.Lock()
        # 正在进行中的参比光谱采集类型集合，防止同类型重复触发
        self._blank_acquiring: set = set()
        self._config_lock = threading.RLock()
        self._desired_config = DesiredSpectrumConfig()
        self._smoothing_config = SpectrumSmoothingConfig()
        self.dark_spectrum: Optional[SpectrumData] = None
        self._dark_enabled = True
        self._dark_interval_sec = self._DARK_INTERVAL_SEC
        self._dark_off_settle_sec = 1.0
        self._dark_on_settle_sec = 1.0
        self._light_controller: Optional[Callable[[bool], None]] = None
        self.last_device_status: Optional[dict] = None
        self.last_device_error: Optional[str] = None
        self.last_recovery_result: Optional[dict] = None
        #-----------------------------------

    def set_light_controller(
        self,
        controller: Optional[Callable[[bool], None]],
        off_settle_sec: Optional[float] = None,
        on_settle_sec: Optional[float] = None,
    ) -> None:
        """设置光源控制回调。参数 True=开光源，False=关光源。"""
        self._light_controller = controller
        if off_settle_sec is not None:
            self._dark_off_settle_sec = max(0.0, float(off_settle_sec))
        if on_settle_sec is not None:
            self._dark_on_settle_sec = max(0.0, float(on_settle_sec))

    def set_dark_correction(
        self,
        enabled: bool = True,
        interval_sec: Optional[float] = None,
    ) -> None:
        """配置暗光谱扣除；默认每 30 分钟更新一次暗光谱。"""
        self._dark_enabled = bool(enabled)
        if interval_sec is not None:
            self._dark_interval_sec = max(1.0, float(interval_sec))

    def get_dark_status(self) -> dict:
        """返回暗光谱缓存状态，供 API/前端展示。"""
        with self.data_lock:
            dark = self.dark_spectrum
            now = time.time()
            age = (now - dark.timestamp) if dark else None
            return {
                "enabled": self._dark_enabled,
                "has_dark": dark is not None,
                "dark_timestamp": dark.timestamp if dark else None,
                "dark_age_sec": age,
                "interval_sec": self._dark_interval_sec,
                "next_due_in_sec": (
                    max(0.0, self._dark_interval_sec - age)
                    if age is not None
                    else 0.0
                ),
                "data_points": len(dark.wavelengths) if dark else 0,
            }

    def set_desired_config(
        self,
        integration_time: Optional[int] = None,
        scans_to_average: Optional[int] = None,
    ) -> dict:
        """只记录目标参数，不直接访问设备 API；采集前再按需应用。"""
        with self._config_lock:
            if integration_time is not None:
                self._desired_config.integration_time = integration_time
            if scans_to_average is not None:
                self._desired_config.scans_to_average = scans_to_average
            return self.get_desired_config()

    def get_desired_config(self) -> dict:
        with self._config_lock:
            return {
                "integration_time": self._desired_config.integration_time,
                "scans_to_average": self._desired_config.scans_to_average,
            }

    def set_smoothing_config(
        self,
        enabled: Optional[bool] = None,
        alpha: Optional[float] = None,
    ) -> dict:
        """配置光谱 EMA 平滑；alpha 必须在 (0, 1]，越小越平滑。"""
        with self._config_lock:
            if enabled is not None:
                self._smoothing_config.enabled = bool(enabled)
            if alpha is not None:
                alpha_value = float(alpha)
                if not 0.0 < alpha_value <= 1.0:
                    raise ValueError("EMA alpha 必须在 (0, 1] 范围内")
                self._smoothing_config.alpha = alpha_value
            return self.get_smoothing_config()

    def get_smoothing_config(self) -> dict:
        with self._config_lock:
            return {
                "enabled": self._smoothing_config.enabled,
                "alpha": self._smoothing_config.alpha,
            }

    def _apply_desired_config_locked(self, device) -> Tuple[int, int]:
        """
        在持有 _device_lock 时调用：先读取设备当前参数，只有目标值不同才写设备。
        这样配置请求本身不会碰硬件，且重复采集不会反复 set 积分时间。
        """
        with self._config_lock:
            desired_integration_time = self._desired_config.integration_time
            desired_scans_to_average = self._desired_config.scans_to_average

        integration_time = device.get_integration_time()
        if (
            desired_integration_time is not None
            and integration_time != desired_integration_time
        ):
            logger.info(
                "采集前更新积分时间: 当前=%s, 目标=%s",
                integration_time,
                desired_integration_time,
            )
            device.set_integration_time(desired_integration_time)
            integration_time = desired_integration_time

        scans_to_average = device.get_scans_to_average()
        if (
            desired_scans_to_average is not None
            and scans_to_average != desired_scans_to_average
        ):
            logger.info(
                "采集前更新平均扫描次数: 当前=%s, 目标=%s",
                scans_to_average,
                desired_scans_to_average,
            )
            device.set_scans_to_average(desired_scans_to_average)
            scans_to_average = desired_scans_to_average

        return integration_time, scans_to_average

    def get_status(self) -> dict:
        """获取当前状态信息 - 使用数据锁保护读取"""
        with self.data_lock:
            current_status = self.status
            current_data = self.current_data
            current_error = self.error_message
            current_start_time = self.acquisition_start_time
            
            status_info = {
                "status": current_status.value,
                "has_data": current_data is not None,
                "last_acquisition_time": current_data.timestamp if current_data else None,
                "error_message": current_error,
                "device_status": self.last_device_status,
                "last_device_error": self.last_device_error,
                "last_recovery_result": self.last_recovery_result,
                "dark_status": self.get_dark_status(),
                "smoothing": self.get_smoothing_config(),
            }
            
            if current_status == AcquisitionStatus.ACQUIRING and current_start_time:
                status_info["acquisition_duration"] = time.time() - current_start_time
            
            if current_data:
                status_info["data_info"] = {
                    "data_points": len(current_data.wavelengths),
                    "integration_time": current_data.integration_time,
                    "scans_to_average": current_data.scans_to_average,
                    "acquisition_time": current_data.acquisition_time,
                    "dark_corrected": current_data.dark_corrected,
                    "dark_timestamp": current_data.dark_timestamp,
                    "smoothed": current_data.smoothed,
                    "smoothing_alpha": current_data.smoothing_alpha,
                }
            
            return status_info

    def _is_likely_spectrometer_error(self, error: Exception) -> bool:
        msg = str(error)
        markers = (
            "CDS350",
            "USB",
            "光谱",
            "设备",
            "初始化",
            "打开",
            "返回码",
            "handle",
            "Integration",
            "Spectrum",
            "Wavelength",
        )
        return isinstance(error, RuntimeError) and any(marker in msg for marker in markers)

    def _query_device_status_locked(self, device) -> dict:
        """在持有 _device_lock 时调用，检测并缓存光谱仪状态。"""
        if device is None:
            status_info = {
                "connected": False,
                "initialized": False,
                "error_message": "设备实例为空",
            }
        else:
            try:
                if hasattr(device, "get_device_status"):
                    status_info = device.get_device_status()
                else:
                    handle = getattr(device, "handle", None)
                    handle_value = getattr(handle, "value", None)
                    status_info = {
                        "connected": handle_value not in (None, -1),
                        "initialized": handle_value not in (None, -1),
                        "handle": handle_value,
                        "error_message": None,
                    }
            except Exception as e:
                status_info = {
                    "connected": False,
                    "initialized": False,
                    "error_message": str(e),
                }
        status_info["checked_at"] = time.time()
        with self.data_lock:
            self.last_device_status = status_info
        return status_info

    def check_device_status(self, device) -> dict:
        """公开状态检测入口，供 API 调用。"""
        with self._device_lock:
            return self._query_device_status_locked(device)

    def _restart_device_locked(self, device, reason: str) -> dict:
        """在持有 _device_lock 时调用，重启光谱仪并缓存重启结果。"""
        if device is None:
            raise RuntimeError("设备实例为空，无法重启")
        started_at = time.time()
        try:
            if hasattr(device, "restart_device"):
                restart_detail = device.restart_device()
            else:
                close_error = None
                if hasattr(device, "close_device"):
                    try:
                        device.close_device()
                    except Exception as e:
                        close_error = str(e)
                restart_detail = device.initialize_device()
                restart_detail = {
                    "status": "restarted",
                    "close_error": close_error,
                    **restart_detail,
                }
            result = {
                "success": True,
                "reason": reason,
                "started_at": started_at,
                "finished_at": time.time(),
                "detail": restart_detail,
            }
        except Exception as e:
            result = {
                "success": False,
                "reason": reason,
                "started_at": started_at,
                "finished_at": time.time(),
                "error_message": str(e),
            }
            with self.data_lock:
                self.last_recovery_result = result
            raise RuntimeError(f"光谱仪重启失败: {e}") from e

        with self.data_lock:
            self.last_recovery_result = result
        self._query_device_status_locked(device)
        return result

    def restart_device(self, device, reason: str = "手动重启") -> dict:
        """公开重启入口，供 API 调用。"""
        with self._device_lock:
            return self._restart_device_locked(device, reason)

    def _run_device_operation_with_recovery_locked(
        self,
        device,
        operation_name: str,
        operation: Callable[[], Any],
    ) -> Any:
        """
        在持有 _device_lock 时调用：设备操作失败后检测状态、重启设备并重试一次。
        非光谱仪类错误直接抛出，避免把光源/业务错误误判为设备断连。
        """
        try:
            return operation()
        except Exception as first_error:
            with self.data_lock:
                self.last_device_error = str(first_error)
            if not self._is_likely_spectrometer_error(first_error):
                raise

            before_status = self._query_device_status_locked(device)
            logger.warning(
                "%s失败，准备检测并重启光谱仪: error=%s, status=%s",
                operation_name,
                first_error,
                before_status,
            )
            try:
                recovery_result = self._restart_device_locked(
                    device,
                    reason=f"{operation_name}失败: {first_error}",
                )
            except Exception as restart_error:
                raise RuntimeError(
                    f"{operation_name}失败；设备状态: {before_status}；"
                    f"重启失败: {restart_error}；原始错误: {first_error}"
                ) from restart_error

            try:
                result = operation()
                logger.info("%s在光谱仪重启后重试成功", operation_name)
                return result
            except Exception as retry_error:
                after_status = self._query_device_status_locked(device)
                with self.data_lock:
                    self.last_device_error = str(retry_error)
                raise RuntimeError(
                    f"{operation_name}失败；已尝试重启光谱仪但重试仍失败。"
                    f"原始错误: {first_error}；重试错误: {retry_error}；"
                    f"重启结果: {recovery_result}；当前设备状态: {after_status}"
                ) from retry_error
    
    def get_cached_data(self) -> Optional[SpectrumData]:
        """获取缓存的光谱数据 - 使用数据锁保护读取"""
        with self.data_lock:
            return self.current_data

    def get_dark_latest(self) -> Optional[SpectrumData]:
        """返回最新暗光谱，无则返回 None。"""
        with self.data_lock:
            return self.dark_spectrum
    
    def is_acquiring(self) -> bool:
        """检查是否正在采集 - 使用数据锁保护读取"""
        with self.data_lock:
            return self.status == AcquisitionStatus.ACQUIRING

    def _dark_is_due_locked(self, now: Optional[float] = None) -> bool:
        if not self._dark_enabled:
            return False
        if self._light_controller is None:
            return False
        dark = self.dark_spectrum
        if dark is None:
            return True
        return ((now or time.time()) - dark.timestamp) >= self._dark_interval_sec

    def _set_light_source(self, enabled: bool) -> None:
        if self._light_controller is None:
            raise RuntimeError("未配置光源控制器，无法采集暗光谱")
        action = "打开" if enabled else "关闭"
        logger.info("%s光源用于暗光谱采集", action)
        self._light_controller(enabled)

    def _capture_dark_spectrum_locked(self, device) -> SpectrumData:
        """
        在持有 _device_lock 时调用：关闭光源采集暗光谱，finally 中保证光源重新打开。
        """
        logger.info("开始采集暗光谱")
        t0 = time.time()
        light_on_restored = False
        try:
            self._set_light_source(False)
            if self._dark_off_settle_sec > 0:
                time.sleep(self._dark_off_settle_sec)
            integration_time, scans_to_average = self._apply_desired_config_locked(device)
            wavelengths, spectrum = device.get_spectrum_data()
            wavelengths, spectrum = _spectrum_to_serializable_lists(wavelengths, spectrum)
            ts_now = time.time()
            data = SpectrumData(
                wavelengths=wavelengths,
                spectrum=spectrum,
                timestamp=ts_now,
                acquisition_time=ts_now - t0,
                integration_time=integration_time,
                scans_to_average=scans_to_average,
                spectrum_type="dark",
                label="暗光谱",
            )
            with self.data_lock:
                self.dark_spectrum = data
            logger.info("暗光谱采集完成，耗时 %.2fs", data.acquisition_time)
            return data
        finally:
            try:
                self._set_light_source(True)
                light_on_restored = True
                if self._dark_on_settle_sec > 0:
                    time.sleep(self._dark_on_settle_sec)
            except Exception as e:
                logger.error("暗光谱采集后重新打开光源失败: %s", e)
                if not light_on_restored:
                    raise

    def _ensure_dark_spectrum_locked(self, device) -> Optional[SpectrumData]:
        """在持有 _device_lock 时调用，必要时刷新暗光谱。"""
        if not self._dark_is_due_locked():
            with self.data_lock:
                return self.dark_spectrum
        return self._capture_dark_spectrum_locked(device)

    def _apply_dark_correction(
        self,
        wavelengths: List[float],
        spectrum: List[float],
    ) -> Tuple[List[float], bool, Optional[float]]:
        with self.data_lock:
            dark = self.dark_spectrum
        if not self._dark_enabled or dark is None:
            return spectrum, False, None
        if len(dark.spectrum) != len(spectrum) or len(dark.wavelengths) != len(wavelengths):
            logger.warning(
                "暗光谱长度不匹配，跳过扣暗: measurement=%s, dark=%s",
                len(spectrum),
                len(dark.spectrum),
            )
            return spectrum, False, None
        corrected = [
            float(signal) - float(dark_value)
            for signal, dark_value in zip(spectrum, dark.spectrum)
        ]
        return corrected, True, dark.timestamp

    @staticmethod
    def _ema_once(values: List[float], alpha: float) -> List[float]:
        if not values:
            return []
        prev = float(values[0])
        smoothed = [prev]
        keep = 1.0 - alpha
        for value in values[1:]:
            prev = alpha * float(value) + keep * prev
            smoothed.append(prev)
        return smoothed

    def _apply_ema_smoothing(
        self,
        spectrum: List[float],
    ) -> Tuple[List[float], bool, Optional[float]]:
        with self._config_lock:
            enabled = self._smoothing_config.enabled
            alpha = self._smoothing_config.alpha
        if not enabled or len(spectrum) < 2 or alpha >= 1.0:
            return spectrum, False, None

        # 前后各做一次 EMA，减小单向 EMA 对峰位的滞后影响。
        forward = self._ema_once(spectrum, alpha)
        backward = self._ema_once(list(reversed(forward)), alpha)
        return list(reversed(backward)), True, alpha
    
    def start_acquisition(self, device, timeout: float = 30.0) -> bool:
        """
        启动光谱采集
        
        Args:
            device: CDS350设备实例
            timeout: 采集超时时间（秒）
            
        Returns:
            bool: 如果成功启动采集返回True，如果已在采集中返回False
        """
        with self.acquisition_lock:
            # 使用数据锁检查状态
            with self.data_lock:
                if self.status == AcquisitionStatus.ACQUIRING:
                    logger.debug("采集已在进行中，忽略新的采集请求")
                    return False
                
                self.status = AcquisitionStatus.ACQUIRING
                self.error_message = None
                self.acquisition_start_time = time.time()
                
                # 将当前数据移到历史数据
                if self.current_data:
                    self.last_data = self.current_data
            
            # 启动采集线程
            self.acquisition_thread = threading.Thread(
                target=self._acquisition_worker,
                args=(device, timeout),
                daemon=True
            )
            self.acquisition_thread.start()
            
            logger.debug("光谱采集已启动")
            return True
    
    def _acquisition_worker(self, device, timeout: float):
        """采集工作线程"""
        try:
            logger.debug("开始光谱数据采集")
            start_time = time.time()

            # 持设备锁后再访问硬件，防止与参比光谱采集线程并发冲突
            with self._device_lock:
                def _capture_measurement():
                    self._ensure_dark_spectrum_locked(device)
                    cfg = self._apply_desired_config_locked(device)
                    data = device.get_spectrum_data()
                    return cfg, data

                (integration_time, scans_to_average), (wavelengths, spectrum) = (
                    self._run_device_operation_with_recovery_locked(
                        device,
                        "光谱采集",
                        _capture_measurement,
                    )
                )
            wavelengths, spectrum = _spectrum_to_serializable_lists(wavelengths, spectrum)
            raw_spectrum = list(spectrum)
            spectrum, dark_corrected, dark_timestamp = self._apply_dark_correction(
                wavelengths,
                spectrum,
            )
            spectrum, smoothed, smoothing_alpha = self._apply_ema_smoothing(spectrum)

            acquisition_time = time.time() - start_time

            # 创建光谱数据对象
            spectrum_data = SpectrumData(
                wavelengths=wavelengths,
                spectrum=spectrum,
                timestamp=time.time(),
                acquisition_time=acquisition_time,
                integration_time=integration_time,
                scans_to_average=scans_to_average,
                #---------------------------
                spectrum_type="measurement",
                raw_spectrum=raw_spectrum if dark_corrected else None,
                dark_timestamp=dark_timestamp,
                dark_corrected=dark_corrected,
                smoothed=smoothed,
                smoothing_alpha=smoothing_alpha,
                #---------------------------
            )
            
            # 仅在更新共享数据时使用数据锁
            with self.data_lock:
                self.current_data = spectrum_data
                self.status = AcquisitionStatus.COMPLETED
                self.error_message = None
                self.acquisition_start_time = None
                
            logger.debug(f"光谱采集完成，耗时: {acquisition_time:.2f}s")
            
        except Exception as e:
            logger.error(f"光谱采集失败: {e}")
            # 仅在更新错误状态时使用数据锁
            with self.data_lock:
                self.status = AcquisitionStatus.ERROR
                self.error_message = str(e)
                self.last_device_error = str(e)
                self.acquisition_start_time = None
    
    async def wait_for_completion(self, timeout: float = 30.0) -> bool:
        """
        等待采集完成 - 异步版本，使用数据锁保护状态读取
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            bool: 成功完成返回True，超时或出错返回False
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # 使用数据锁快速检查状态
            with self.data_lock:
                current_status = self.status
                if current_status == AcquisitionStatus.COMPLETED:
                    return True
                elif current_status == AcquisitionStatus.ERROR:
                    return False
            
            # 使用异步睡眠，不阻塞事件循环
            await asyncio.sleep(0.1)
        
        logger.debug("等待光谱采集完成超时")
        return False
    
    def reset_to_idle(self):
        """重置状态为空闲 - 使用数据锁保护状态检查和修改"""
        # 先检查当前状态，避免不必要的锁获取
        with self.data_lock:
            if self.status == AcquisitionStatus.ACQUIRING:
                logger.debug("正在采集中，无法重置状态")
                return
                
            # 在同一个锁保护下修改状态
            self.status = AcquisitionStatus.IDLE
            self.error_message = None
            logger.debug("光谱采集管理器状态重置为空闲")
    
    async def get_spectrum_data(
        self, device, force_new: bool = False
    ) -> Tuple[List[float], List[float]]:
        """
        获取光谱数据 - 异步版本
        
        Args:
            device: CDS350设备实例
            force_new: 是否强制获取新数据
            
        Returns:
            Tuple[List[float], List[int]]: (波长数组, 光谱强度数组)
        """
        # 如果正在采集，返回缓存数据
        if self.is_acquiring():
            logger.debug("检测到正在采集，返回缓存数据")
            cached_data = self.get_cached_data()
            if cached_data:
                return cached_data.wavelengths, cached_data.spectrum
            else:
                # 如果没有缓存数据，等待当前采集完成
                logger.debug("等待当前采集完成...")
                if await self.wait_for_completion(timeout=60.0):
                    cached_data = self.get_cached_data()
                    if cached_data:
                        return cached_data.wavelengths, cached_data.spectrum
                with self.data_lock:
                    detail = self.error_message
                raise RuntimeError(detail or "等待光谱采集完成超时")
        
        # 如果不是强制获取新数据，且有最近的数据，检查是否可以复用
        if not force_new:
            with self.data_lock:
                current_data = self.current_data
                if current_data and time.time() - current_data.timestamp < 30.0:
                    logger.debug("返回缓存的光谱数据")
                    return current_data.wavelengths, current_data.spectrum
        
        # 启动新的采集
        logger.debug("启动新的光谱采集")
        if self.start_acquisition(device):
            # 等待采集完成
            if await self.wait_for_completion(timeout=60.0):
                cached_data = self.get_cached_data()
                if cached_data:
                    return cached_data.wavelengths, cached_data.spectrum
                else:
                    raise RuntimeError("采集完成但无法获取数据")
            else:
                with self.data_lock:
                    detail = self.error_message
                raise RuntimeError(detail or "光谱采集失败或超时")
        else:
            # 如果无法启动新采集（已在采集中），返回现有数据
            logger.debug("无法启动新采集，返回现有数据")
            cached_data = self.get_cached_data()
            if cached_data:
                return cached_data.wavelengths, cached_data.spectrum
            else:
                raise RuntimeError("无法获取光谱数据")

    #---------------------------------------
    # ------------------------------------------------------------------
    # 参比光谱：独立于常规采集，存入 blank_spectra 列表
    # blank_type: "blank_before"（置换前）| "blank_after"（清洗后）
    # ------------------------------------------------------------------

    _BLANK_LABELS = {
        "blank_before": "置换前参比光谱",
        "blank_after":  "清洗后参比光谱",
    }

    def start_blank_acquisition(self, device, blank_type: str) -> bool:
        """
        在独立后台线程中采集参比光谱，不干扰常规采集状态机。
        结果追加到 blank_spectra；每种类型最多保留 _BLANK_MAX 条。
        blank_type: "blank_before" 或 "blank_after"
        返回 True 表示线程已启动，False 表示参数非法、设备为 None 或同类型采集已在进行中。
        """
        if blank_type not in self._BLANK_LABELS:
            logger.warning(f"start_blank_acquisition: 未知 blank_type={blank_type!r}")
            return False
        if device is None:
            logger.warning(f"start_blank_acquisition [{blank_type}]: device 为 None，跳过")
            return False

        # 去重：同类型参比光谱采集只允许一条线程同时运行
        with self._blank_lock:
            if blank_type in self._blank_acquiring:
                logger.warning(
                    f"start_blank_acquisition [{blank_type}]: 同类型参比光谱采集已在进行中，忽略重复触发"
                )
                return False
            self._blank_acquiring.add(blank_type)

        label = self._BLANK_LABELS[blank_type]

        def _worker():
            try:
                logger.info(f"开始采集参比光谱 [{label}]")
                t0 = time.time()
                # 持设备锁后再访问硬件，与常规采集线程串行化
                with self._device_lock:
                    def _capture_blank():
                        self._ensure_dark_spectrum_locked(device)
                        cfg = self._apply_desired_config_locked(device)
                        data = device.get_spectrum_data()
                        return cfg, data

                    (integration_time, scans_to_average), (wavelengths, spectrum) = (
                        self._run_device_operation_with_recovery_locked(
                            device,
                            f"参比光谱采集[{label}]",
                            _capture_blank,
                        )
                    )
                wavelengths, spectrum = _spectrum_to_serializable_lists(wavelengths, spectrum)
                raw_spectrum = list(spectrum)
                spectrum, dark_corrected, dark_timestamp = self._apply_dark_correction(
                    wavelengths,
                    spectrum,
                )
                spectrum, smoothed, smoothing_alpha = self._apply_ema_smoothing(spectrum)
                acq_time = time.time() - t0
                ts_now = time.time()
                data = SpectrumData(
                    wavelengths=wavelengths,
                    spectrum=spectrum,
                    timestamp=ts_now,
                    acquisition_time=acq_time,
                    integration_time=integration_time,
                    scans_to_average=scans_to_average,
                    spectrum_type=blank_type,
                    label=label,
                    raw_spectrum=raw_spectrum if dark_corrected else None,
                    dark_timestamp=dark_timestamp,
                    dark_corrected=dark_corrected,
                    smoothed=smoothed,
                    smoothing_alpha=smoothing_alpha,
                )

                # 自动落盘为 SPC 文件（IO 在锁外执行，避免长时间持锁）
                try:
                    from Devices.get_spc import convert_spectrum_to_spc, BLANK_SPC_OUTPUT_DIR
                    ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts_now))
                    auto_filename = os.path.join(BLANK_SPC_OUTPUT_DIR, f"{blank_type}_{ts_str}")
                    spc_result = convert_spectrum_to_spc(wavelengths, spectrum, auto_filename)
                    data.spc_file_path = spc_result["file_path"]
                    logger.info(f"参比光谱已落盘 [{label}]: {data.spc_file_path}")
                except Exception as spc_e:
                    logger.error(f"参比光谱落盘失败 [{label}]: {spc_e}")

                with self._blank_lock:
                    self.blank_spectra.append(data)
                    # 超出上限时循环丢弃最旧的同类条目（while 应对历史积压场景）
                    same_type = [d for d in self.blank_spectra if d.spectrum_type == blank_type]
                    while len(same_type) > self._BLANK_MAX:
                        oldest = same_type.pop(0)
                        self.blank_spectra.remove(oldest)
                    count = len(same_type)
                logger.info(
                    f"参比光谱采集完成 [{label}]，耗时 {acq_time:.2f}s，当前共 {count} 条"
                )
            except Exception as e:
                logger.error(f"参比光谱采集失败 [{label}]: {e}")
            finally:
                # 无论成功/失败都清除进行中标记，允许后续重新触发
                with self._blank_lock:
                    self._blank_acquiring.discard(blank_type)

        t = threading.Thread(target=_worker, name=f"BlankAcq_{blank_type}", daemon=True)
        t.start()
        return True

    def get_blank_latest(self, blank_type: str) -> Optional[SpectrumData]:
        """返回指定类型的最新一条参比光谱，无则返回 None。"""
        with self._blank_lock:
            same = [d for d in self.blank_spectra if d.spectrum_type == blank_type]
            return same[-1] if same else None

    def get_blank_list(self, blank_type: Optional[str] = None) -> List[dict]:
        """
        返回参比光谱摘要列表（不含波长/光谱数组）。
        blank_type=None 时返回全部类型。
        """
        with self._blank_lock:
            items = (
                [d for d in self.blank_spectra if d.spectrum_type == blank_type]
                if blank_type
                else list(self.blank_spectra)
            )
        return [
            {
                "spectrum_type": d.spectrum_type,
                "label": d.label,
                "timestamp": d.timestamp,
                "acquisition_time": d.acquisition_time,
                "integration_time": d.integration_time,
                "scans_to_average": d.scans_to_average,
                "data_points": len(d.wavelengths),
                "dark_corrected": d.dark_corrected,
                "dark_timestamp": d.dark_timestamp,
                "smoothed": d.smoothed,
                "smoothing_alpha": d.smoothing_alpha,
            }
            for d in items
        ]
        #-----------------------------------

# 全局光谱采集管理器实例
spectrum_manager = SpectrumAcquisitionManager()
