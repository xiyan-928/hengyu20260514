from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
from SPyC_Writer.SPCEnums import SPCFileType

HEADER_SIZE = 512
SUBHEADER_SIZE = 32
FLOAT32_EXPONENT = -128


def _is_monotonic(values: np.ndarray) -> bool:
    if values.size < 2:
        return True
    diffs = np.diff(values)
    return bool(np.all(diffs >= 0) or np.all(diffs <= 0))


def _parse_single_trace_txvals(
    data: bytes,
    num_points: int,
    subheader_offset: int,
    x_offset: int,
    y_offset: int,
) -> Tuple[np.ndarray, np.ndarray]:
    expected_size = y_offset + num_points * 4
    if len(data) < expected_size:
        raise ValueError("SPC 文件长度不足")

    exponent = int.from_bytes(data[subheader_offset + 1 : subheader_offset + 2], "little", signed=True)
    if exponent != FLOAT32_EXPONENT:
        raise ValueError(f"暂不支持的 Y 数据指数格式: {exponent}")

    x_values = np.frombuffer(data[x_offset : x_offset + num_points * 4], dtype="<f4").astype(np.float64)
    y_values = np.frombuffer(data[y_offset : y_offset + num_points * 4], dtype="<f4").astype(np.float64)
    if not _is_monotonic(x_values):
        raise ValueError("X 轴数据不是单调序列")
    return x_values, y_values


def _parse_single_trace_even(data: bytes, num_points: int) -> Tuple[np.ndarray, np.ndarray]:
    y_offset = HEADER_SIZE + SUBHEADER_SIZE
    expected_size = y_offset + num_points * 4
    if len(data) < expected_size:
        raise ValueError("SPC 文件长度不足")

    exponent = int.from_bytes(data[HEADER_SIZE + 1 : HEADER_SIZE + 2], "little", signed=True)
    if exponent != FLOAT32_EXPONENT:
        raise ValueError(f"暂不支持的 Y 数据指数格式: {exponent}")

    first_x = np.frombuffer(data[8:16], dtype="<f8", count=1)[0]
    last_x = np.frombuffer(data[16:24], dtype="<f8", count=1)[0]
    if num_points == 1:
        x_values = np.array([first_x], dtype=np.float64)
    else:
        x_values = np.linspace(first_x, last_x, num_points, dtype=np.float64)
    y_values = np.frombuffer(data[y_offset : y_offset + num_points * 4], dtype="<f4").astype(np.float64)
    return x_values, y_values


def read_spc_xy(file_path: str | Path) -> Tuple[np.ndarray, np.ndarray]:
    path = Path(file_path)
    data = path.read_bytes()
    if len(data) < HEADER_SIZE + SUBHEADER_SIZE:
        raise ValueError("SPC 文件太短")

    file_type = data[0]
    num_points = int.from_bytes(data[4:8], "little", signed=False)
    is_single_txvals = (
        (file_type & int(SPCFileType.TXVALS))
        and not (file_type & int(SPCFileType.TMULTI))
        and not (file_type & int(SPCFileType.TXYXYS))
    )
    if num_points <= 0:
        raise ValueError("SPC 点数无效")
    if file_type == 0:
        return _parse_single_trace_even(data, num_points)
    if not is_single_txvals:
        raise ValueError(f"暂不支持的 SPC 文件类型: {file_type}")

    try:
        return _parse_single_trace_txvals(
            data,
            num_points,
            subheader_offset=HEADER_SIZE,
            x_offset=HEADER_SIZE + SUBHEADER_SIZE,
            y_offset=HEADER_SIZE + SUBHEADER_SIZE + num_points * 4,
        )
    except ValueError:
        # 兼容旧版错误布局：header -> x -> subheader -> y
        legacy_subheader_offset = HEADER_SIZE + num_points * 4
        return _parse_single_trace_txvals(
            data,
            num_points,
            subheader_offset=legacy_subheader_offset,
            x_offset=HEADER_SIZE,
            y_offset=legacy_subheader_offset + SUBHEADER_SIZE,
        )
