from __future__ import annotations

import logging
import os
import sys
import ctypes
import threading
import time
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


class _CDS350SingletonBase:
    """线程安全的类级单例基类（每子类各自一份 _instance）。"""

    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = object.__new__(cls)
        return cls._instance


def _ctypes_spectrum_to_numpy(
    wl_buf: ctypes.Array,
    sp_buf: ctypes.Array,
) -> Tuple[np.ndarray, np.ndarray]:
    """将 ctypes 波长/强度缓冲区转为 float64 ndarray（独立副本，可安全长期保存）。"""
    wl = np.array(wl_buf, dtype=np.float64, copy=True)
    sp = np.array(sp_buf, dtype=np.float64, copy=True)
    return wl, sp


class _CDS350Windows(_CDS350SingletonBase):
    """CDS350 光谱仪控制类（Windows，cms_driver_x64_usb.dll）。进程内单例。"""

    _instance = None

    def __init__(self):
        if getattr(self, "_cds350_singleton_ready", False):
            return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        dll_path = os.path.join(base_dir, "cms_driver_x64_usb.dll")
        try:
            self.wrapper = ctypes.CDLL(dll_path)
            self._setup_function_prototypes()
            self.handle = ctypes.c_int(-1)
            self.wavelengths = None
            self.spectrum = None
        except OSError as e:
            raise RuntimeError(f"加载DLL失败: {e}")
        self._cds350_singleton_ready = True

    def _setup_function_prototypes(self):
        self.wrapper.getUSBDeviceCount.restype = ctypes.c_int
        self.wrapper.getUSBDeviceName.argtypes = [ctypes.c_int]
        self.wrapper.getUSBDeviceName.restype = ctypes.c_char_p
        self.wrapper.openUSB.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        self.wrapper.closeUSB.argtypes = [ctypes.c_int]
        self.wrapper.setIntegrationTime.argtypes = [ctypes.c_int, ctypes.c_int]
        self.wrapper.getIntegrationTime.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.wrapper.setScansToAverage.argtypes = [ctypes.c_int, ctypes.c_ubyte]
        self.wrapper.getScansToAverage.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte)]
        self.wrapper.getWavelengths.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
        self.wrapper.getSpectrum.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ushort)]

    def initialize_device(self):
        # 真实 USB 设备已打开时幂等返回，避免重复 openUSB 导致第二次初始化失败
        if self.handle.value != -1:
            return {
                "integration_time": self.get_integration_time(),
                "scans_to_average": self.get_scans_to_average(),
                "device_type": "CDS350_Real",
                "status": "initialized",
                "already_initialized": True,
            }

        device_count = self.wrapper.getUSBDeviceCount()
        if device_count == 0:
            raise RuntimeError("未找到USB设备。")

        device_name_ptr = self.wrapper.getUSBDeviceName(0)
        if not device_name_ptr:
            raise RuntimeError("获取设备名称失败。")

        ret_open = self.wrapper.openUSB(device_name_ptr, ctypes.byref(self.handle))
        if ret_open != 0:
            raise RuntimeError("打开USB设备失败。")

        integration_time = self.get_integration_time()
        scans_to_average = self.get_scans_to_average()

        return {
            "integration_time": integration_time,
            "scans_to_average": scans_to_average,
            "device_type": "CDS350_Real",
            "status": "initialized",
        }

    def get_device_status(self):
        status = {
            "device_type": "CDS350_Real",
            "platform": "windows",
            "initialized": self.handle.value != -1,
            "connected": False,
            "handle": self.handle.value,
            "usb_device_count": None,
            "error_message": None,
        }
        try:
            status["usb_device_count"] = self.wrapper.getUSBDeviceCount()
            status["connected"] = (
                status["initialized"] and status["usb_device_count"] > 0
            )
            if status["initialized"]:
                status["integration_time"] = self.get_integration_time()
                status["scans_to_average"] = self.get_scans_to_average()
        except Exception as e:
            status["connected"] = False
            status["error_message"] = str(e)
        return status

    def restart_device(self):
        close_error = None
        try:
            self.close_device()
        except Exception as e:
            close_error = str(e)
            self.handle = ctypes.c_int(-1)
        time.sleep(0.5)
        result = self.initialize_device()
        return {
            "status": "restarted",
            "close_error": close_error,
            **result,
        }

    def close_device(self):
        if self.handle.value != -1:
            try:
                self.wrapper.closeUSB(self.handle)
            finally:
                self.handle = ctypes.c_int(-1)

    def set_integration_time(self, time):
        if not isinstance(time, int) or time < 60:
            raise ValueError("积分时间必须为整数且至少为60微秒。")
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        ret = self.wrapper.setIntegrationTime(self.handle, time)
        if ret != 0:
            raise RuntimeError(f"设置积分时间失败，返回码: {ret}")

    def get_integration_time(self):
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        integration_time = ctypes.c_int()
        ret = self.wrapper.getIntegrationTime(self.handle, ctypes.byref(integration_time))
        if ret != 0:
            raise RuntimeError(f"获取积分时间失败，返回码: {ret}")
        return integration_time.value

    def set_scans_to_average(self, scans):
        if not isinstance(scans, int) or scans < 1 or scans > 255:
            raise ValueError("平均次数必须为1到255之间的整数。")
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        ret = self.wrapper.setScansToAverage(self.handle, ctypes.c_ubyte(scans))
        if ret != 0:
            raise RuntimeError(f"设置平均次数失败，返回码: {ret}")

    def get_scans_to_average(self):
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        scans_to_average = ctypes.c_ubyte()
        ret = self.wrapper.getScansToAverage(self.handle, ctypes.byref(scans_to_average))
        if ret != 0:
            raise RuntimeError(f"获取平均次数失败，返回码: {ret}")
        return scans_to_average.value

    def read_spectrum(self):
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        self.wavelengths = (ctypes.c_float * 2048)()
        self.spectrum = (ctypes.c_ushort * 2048)()
        ret_wl = self.wrapper.getWavelengths(self.handle, self.wavelengths)
        ret_sp = self.wrapper.getSpectrum(self.handle, self.spectrum)
        if ret_wl != 0 or ret_sp != 0:
            raise RuntimeError(
                f"读取光谱数据失败，波长返回码: {ret_wl}, 光谱返回码: {ret_sp}"
            )
        return _ctypes_spectrum_to_numpy(self.wavelengths, self.spectrum)

    def get_spectrum_data(self):
        return self.read_spectrum()

    def __del__(self):
        self.close_device()


class _CDS350Linux(_CDS350SingletonBase):
    """CDS350 光谱仪控制类（Linux，libwrapper.so；积分时间/平均次数 get 为缓存值）。进程内单例。"""

    _instance = None

    _COMM_USB = 0
    _DEFAULT_INTEGRATION_US = 100_000
    _DEFAULT_SCANS = 1
    # 与固件/实测一致：GetWavelengths / GetScopes 缓冲区均为 2048 点
    _PIXEL_COUNT = 2048

    def __init__(self):
        if getattr(self, "_cds350_singleton_ready", False):
            return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "lib", "CDS350", "libwrapper.so"),
            "/usr/local/lib/libwrapper.so",
        ]
        last_err = None
        self.wrapper = None
        for so_path in candidates:
            if not os.path.isfile(so_path):
                continue
            try:
                self.wrapper = ctypes.CDLL(so_path, mode=ctypes.RTLD_GLOBAL)
                break
            except OSError as e:
                last_err = e
        if self.wrapper is None:
            msg = "未找到或无法加载 libwrapper.so（请将库置于 Devices/lib/CDS350/ 或 /usr/local/lib/）"
            if last_err:
                msg += f": {last_err}"
            raise RuntimeError(msg)

        self._setup_function_prototypes()
        self.handle = ctypes.c_int(-1)
        self.wavelengths = None
        self.spectrum = None
        self._cached_integration_us = self._DEFAULT_INTEGRATION_US
        self._cached_scans = self._DEFAULT_SCANS
        self._cds350_singleton_ready = True

    def _setup_function_prototypes(self):
        w = self.wrapper
        w.Init.argtypes = [ctypes.c_int]
        w.Init.restype = ctypes.c_int
        w.Open.argtypes = [ctypes.c_int]
        w.Open.restype = ctypes.c_int
        w.SetIntegrationTime.argtypes = [ctypes.c_int, ctypes.c_double]
        w.SetIntegrationTime.restype = ctypes.c_int
        w.SetAverageTime.argtypes = [ctypes.c_int, ctypes.c_int]
        w.SetAverageTime.restype = ctypes.c_int
        w.GetWavelengthsNumber.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        w.GetWavelengthsNumber.restype = ctypes.c_int
        w.GetWavelengths.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
        w.GetWavelengths.restype = ctypes.c_int
        w.GetScopes.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ushort)]
        w.GetScopes.restype = ctypes.c_int

    def _device_index(self):
        return self.handle.value

    def initialize_device(self):
        # 已 Open 成功时幂等返回，避免重复 Init+Open
        if self.handle.value != -1:
            return {
                "integration_time": self.get_integration_time(),
                "scans_to_average": self.get_scans_to_average(),
                "device_type": "CDS350_Real",
                "status": "initialized",
                "already_initialized": True,
            }

        ret = self.wrapper.Init(self._COMM_USB)
        if ret <= 0:
            raise RuntimeError(f"Linux光谱仪初始化失败（Init 返回 {ret}），请检查USB连接与驱动。")

        idx = 0
        ret_open = self.wrapper.Open(idx)
        if ret_open < 0:
            raise RuntimeError(f"打开光谱仪失败（Open 返回 {ret_open}）。")

        self.handle = ctypes.c_int(idx)
        self._cached_integration_us = self._DEFAULT_INTEGRATION_US
        self._cached_scans = self._DEFAULT_SCANS

        return {
            "integration_time": self._cached_integration_us,
            "scans_to_average": self._cached_scans,
            "device_type": "CDS350_Real",
            "status": "initialized",
        }

    def get_device_status(self):
        status = {
            "device_type": "CDS350_Real",
            "platform": "linux",
            "initialized": self.handle.value != -1,
            "connected": self.handle.value != -1,
            "handle": self.handle.value,
            "error_message": None,
        }
        try:
            if status["initialized"]:
                status["integration_time"] = self.get_integration_time()
                status["scans_to_average"] = self.get_scans_to_average()
                status["reported_pixel_count"] = self._pixel_count_reported()
        except Exception as e:
            status["connected"] = False
            status["error_message"] = str(e)
        return status

    def restart_device(self):
        close_error = None
        try:
            self.close_device()
        except Exception as e:
            close_error = str(e)
            self.handle = ctypes.c_int(-1)
        time.sleep(0.5)
        result = self.initialize_device()
        return {
            "status": "restarted",
            "close_error": close_error,
            **result,
        }

    def close_device(self):
        self.handle = ctypes.c_int(-1)

    def set_integration_time(self, time):
        if not isinstance(time, int) or time < 60:
            raise ValueError("积分时间必须为整数且至少为60微秒。")
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        ms = time / 1000.0
        ret = self.wrapper.SetIntegrationTime(self._device_index(), ms)
        if ret < 0:
            raise RuntimeError(f"设置积分时间失败，返回码: {ret}")
        self._cached_integration_us = time

    def get_integration_time(self):
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        return self._cached_integration_us

    def set_scans_to_average(self, scans):
        if not isinstance(scans, int) or scans < 1 or scans > 255:
            raise ValueError("平均次数必须为1到255之间的整数。")
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        ret = self.wrapper.SetAverageTime(self._device_index(), scans)
        if ret < 0:
            raise RuntimeError(f"设置平均次数失败，返回码: {ret}")
        self._cached_scans = scans

    def get_scans_to_average(self):
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        return self._cached_scans

    def _pixel_count_reported(self) -> int:
        """查询设备报告的像素数（仅用于与固定缓冲区交叉校验）。"""
        n = ctypes.c_int()
        ret = self.wrapper.GetWavelengthsNumber(self._device_index(), ctypes.byref(n))
        if ret < 0 or n.value <= 0:
            return self._PIXEL_COUNT
        return n.value

    def read_spectrum(self):
        if self.handle.value == -1:
            raise RuntimeError("设备尚未初始化。")
        n = self._PIXEL_COUNT
        reported = self._pixel_count_reported()
        if reported != n:
            logger.warning(
                "GetWavelengthsNumber 返回 %s，与固定缓冲区长度 %s 不一致（按实测使用 %s）",
                reported,
                n,
                n,
            )
        self.wavelengths = (ctypes.c_float * n)()
        self.spectrum = (ctypes.c_ushort * n)()
        ret_wl = self.wrapper.GetWavelengths(self._device_index(), self.wavelengths)
        ret_sp = self.wrapper.GetScopes(self._device_index(), self.spectrum)
        if ret_wl < 0 or ret_sp < 0:
            raise RuntimeError(
                f"读取光谱数据失败，波长返回码: {ret_wl}, 光谱返回码: {ret_sp}"
            )
        return _ctypes_spectrum_to_numpy(self.wavelengths, self.spectrum)

    def get_spectrum_data(self):
        return self.read_spectrum()

    def __del__(self):
        self.close_device()


class _CDS350Unsupported:
    """非 Windows/Linux 平台占位，避免误用。"""

    def __init__(self):
        raise RuntimeError(
            "CDS350 硬件驱动仅支持 Windows (win32) 与 Linux；当前平台: "
            f"{sys.platform}"
        )


if sys.platform == "win32":
    CDS350 = _CDS350Windows
elif sys.platform.startswith("linux"):
    CDS350 = _CDS350Linux
else:
    CDS350 = _CDS350Unsupported


if __name__ == "__main__":
    dev = None
    try:
        dev = CDS350()
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if dev is not None:
            del dev
