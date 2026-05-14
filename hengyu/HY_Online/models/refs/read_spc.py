import numpy as np
from Devices.read_spc import read_spc_xy

def read_spc_file(file_path: str) -> dict:
    """
    读取SPC文件并返回光谱数据
    
    Args:
        file_path: SPC文件的绝对路径
        
    Returns:
        dict: 包含波长和光谱强度的字典
    """
    try:
        wavelengths, spectrum = read_spc_xy(file_path)
        return {
            "wavelengths": np.array(wavelengths),
            "spectrum": np.array(spectrum)
        }
    except Exception as e:
        raise RuntimeError(f"读取SPC文件失败: {str(e)}")