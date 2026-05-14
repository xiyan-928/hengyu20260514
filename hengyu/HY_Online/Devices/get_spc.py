import datetime
import logging
import os
import tempfile
import threading
import time
from typing import Sequence, Union

import numpy as np
from SPyC_Writer.SPCEnums import SPCFileType, SPCXType, SPCYType
from SPyC_Writer.SPCFileWriter import SPCFileWriter

logger = logging.getLogger(__name__)

_DEFAULT_TEMP_ROOT = os.path.join(tempfile.gettempdir(), "hy_online_spc_files")
_TEMP_ROOT = os.path.abspath(os.getenv("HY_SPC_TEMP_DIR", _DEFAULT_TEMP_ROOT))
_CLEAN_INTERVAL_SEC = max(
    60.0, float(os.getenv("HY_SPC_TEMP_CLEAN_INTERVAL_SEC", "3600"))
)
_MAX_AGE_SEC = max(60.0, float(os.getenv("HY_SPC_TEMP_MAX_AGE_SEC", "86400")))

# SPC 临时存储目录。HY_APP 会复制这些文件到 Documents/HY_Data，服务端只保留临时副本。
SPC_OUTPUT_DIR = _TEMP_ROOT
os.makedirs(SPC_OUTPUT_DIR, exist_ok=True)

# 参比光谱专用临时子目录
BLANK_SPC_OUTPUT_DIR = os.path.join(_TEMP_ROOT, "blank")
os.makedirs(BLANK_SPC_OUTPUT_DIR, exist_ok=True)

# 暗光谱专用临时子目录
DARK_SPC_OUTPUT_DIR = os.path.join(_TEMP_ROOT, "dark")
os.makedirs(DARK_SPC_OUTPUT_DIR, exist_ok=True)

NumberSeq = Union[Sequence[float], Sequence[int], np.ndarray]

_cleanup_thread_started = False
_cleanup_thread_lock = threading.Lock()


def cleanup_old_spc_files(max_age_sec: float = _MAX_AGE_SEC) -> int:
    """删除 HY_Online 临时 SPC 目录中过期的 .spc 文件，返回删除数量。"""
    cutoff = time.time() - max_age_sec
    deleted = 0
    for root, _, files in os.walk(_TEMP_ROOT):
        for name in files:
            if not name.lower().endswith(".spc"):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    deleted += 1
            except FileNotFoundError:
                continue
            except OSError as e:
                logger.warning("删除过期临时 SPC 文件失败 %s: %s", path, e)
    return deleted


def _cleanup_loop() -> None:
    while True:
        try:
            deleted = cleanup_old_spc_files()
            if deleted:
                logger.info("已清理 %s 个过期临时 SPC 文件", deleted)
        except Exception as e:
            logger.warning("临时 SPC 文件清理任务异常: %s", e)
        time.sleep(_CLEAN_INTERVAL_SEC)


def start_spc_temp_cleanup_thread() -> None:
    """启动一次后台清理线程；模块可能被重复导入，需保证幂等。"""
    global _cleanup_thread_started
    with _cleanup_thread_lock:
        if _cleanup_thread_started:
            return
        thread = threading.Thread(
            target=_cleanup_loop,
            name="SpcTempCleanup",
            daemon=True,
        )
        thread.start()
        _cleanup_thread_started = True


start_spc_temp_cleanup_thread()


def _is_evenly_spaced(x_array: np.ndarray, rtol: float = 1e-5, atol: float = 1e-6) -> bool:
    if x_array.size < 3:
        return True
    diffs = np.diff(np.asarray(x_array, dtype=np.float64))
    return bool(np.allclose(diffs, diffs[0], rtol=rtol, atol=atol))

def write_spc(x_values: NumberSeq, y_values: NumberSeq, spc_name: str = None) -> str:
    """
    将光谱数据写入SPC文件
    
    Args:
        x_values: X轴数据（波长）
        y_values: Y轴数据（光谱强度）
        spc_name: SPC文件名，如果为None则自动生成
    
    Returns:
        str: 生成的SPC文件的绝对路径
    
    Raises:
        RuntimeError: 写入SPC文件失败时抛出异常
    """
    try:
        x_array = np.asarray(x_values, dtype=np.float64)
        y_array = np.asarray(y_values, dtype=np.float64)
        if x_array.size == 0 or y_array.size == 0:
            raise ValueError("X轴和Y轴数据不能为空")
        if x_array.shape != y_array.shape:
            raise ValueError("X轴和Y轴数据长度必须相同")
        
        # 生成文件名
        if spc_name is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            spc_name = f"spectrum_{timestamp}.spc"
        elif not spc_name.endswith('.spc'):
            spc_name += '.spc'
        
        # 确保文件路径是绝对路径
        if not os.path.isabs(spc_name):
            spc_name = os.path.join(SPC_OUTPUT_DIR, spc_name)

        # 目录不存在时自动创建
        os.makedirs(os.path.dirname(spc_name), exist_ok=True)
        
        file_type = SPCFileType(0) if _is_evenly_spaced(x_array) else SPCFileType.TXVALS
        writer = SPCFileWriter(
            file_type,
            compress_date=datetime.datetime.now(),
            x_units=SPCXType.SPCXNMetr,
            y_units=SPCYType.SPCYCount,
        )
        success = writer.write_spc_file(
            spc_name,
            y_values=np.asarray(y_array, dtype=np.float32),
            x_values=np.asarray(x_array, dtype=np.float32),
        )
        if not success:
            raise RuntimeError("SPC文件写入失败，writer.write_spc_file返回False")
        
        # 验证文件是否成功创建
        if not os.path.exists(spc_name):
            raise RuntimeError(f"SPC文件创建失败，文件不存在: {spc_name}")
        
        return spc_name
        
    except Exception as e:
        raise RuntimeError(f"写入SPC文件失败: {str(e)}")
        
def convert_spectrum_to_spc(
    wavelengths: NumberSeq,
    spectrum: NumberSeq,
    output_path: str = None,
) -> dict:
    """
    将光谱数据转换为SPC文件并返回结果信息
    
    Args:
        wavelengths: 波长数据
        spectrum: 光谱强度数据
        output_path: 输出文件路径，如果为None则自动生成
    
    Returns:
        dict: 包含转换结果信息的字典
    """
    try:
        file_path = write_spc(wavelengths, spectrum, output_path)
        file_size = os.path.getsize(file_path)
        wl = np.asarray(wavelengths)
        n = int(wl.size)
        return {
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "file_size": file_size,
            "data_points": n,
            "wavelength_range": {
                "min": float(wl.min()) if n else 0,
                "max": float(wl.max()) if n else 0,
            },
            "created_at": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        raise RuntimeError(f"光谱数据转换为SPC文件失败: {str(e)}")
            
