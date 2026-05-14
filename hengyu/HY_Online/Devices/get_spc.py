import datetime
import os
from typing import Sequence, Union

import numpy as np
from SPyC_Writer.SPCEnums import SPCFileType, SPCXType, SPCYType
from SPyC_Writer.SPCFileWriter import SPCFileWriter

# SPC 文件持久化存储目录（~/spc_files/），进程启动时自动创建
SPC_OUTPUT_DIR = os.path.expanduser("~/spc_files")
os.makedirs(SPC_OUTPUT_DIR, exist_ok=True)

# 参比光谱专用子目录（~/spc_files/blank/）
BLANK_SPC_OUTPUT_DIR = os.path.expanduser("~/spc_files/blank")
os.makedirs(BLANK_SPC_OUTPUT_DIR, exist_ok=True)

# 暗光谱专用子目录（~/spc_files/dark/）
DARK_SPC_OUTPUT_DIR = os.path.expanduser("~/spc_files/dark")
os.makedirs(DARK_SPC_OUTPUT_DIR, exist_ok=True)

NumberSeq = Union[Sequence[float], Sequence[int], np.ndarray]


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
            
