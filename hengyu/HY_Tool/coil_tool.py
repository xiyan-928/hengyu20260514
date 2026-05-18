#!/usr/bin/env python3
"""
简单 Modbus 线圈读写程序

使用方法：
1. 修改下面的 IP、PORT、UNIT、COIL_ADDRESS、WRITE_VALUES 等参数
2. Linux 中运行：python3 coil_tool.py

也可以被 coil_web_app.py 导入，在浏览器页面中控制 6 个线圈。
"""

from pymodbus.client.sync import ModbusTcpClient


# ===================== 在这里填写现场参数 =====================
IP = "192.168.1.10"
PORT = 502
UNIT = 1

# 线圈起始地址和读取数量
COIL_ADDRESS = 0
COIL_COUNT = 6
COIL_NAMES = ["光源", "进液阀", "进水阀", "置换阀", "出液阀", "水泵"]

# 是否写线圈；只想读取时改为 False
WRITE_ENABLE = False
WRITE_ADDRESS = 0

# 从 WRITE_ADDRESS 开始一次写入 6 个线圈
# True 表示吸合/打开，False 表示断开/关闭
WRITE_VALUES = [True, False, False, False, False, False]
# =============================================================


def _check_response(result, action):
    if result is None:
        raise RuntimeError(f"{action}失败：无响应")
    if hasattr(result, "isError") and result.isError():
        raise RuntimeError(f"{action}失败：{result}")


def read_coils(address=COIL_ADDRESS, count=COIL_COUNT):
    """读取线圈，返回 bool 列表。"""
    client = ModbusTcpClient(IP, port=PORT, timeout=2)

    if not client.connect():
        raise ConnectionError(f"连接失败：{IP}:{PORT}")

    try:
        result = client.read_coils(address, count, unit=UNIT)
        _check_response(result, "读线圈")
        return [bool(value) for value in result.bits[:count]]

    finally:
        client.close()


def write_coils(address=WRITE_ADDRESS, values=None):
    """从 address 开始一次写入多个线圈。"""
    values = WRITE_VALUES if values is None else values
    values = [bool(value) for value in values]
    client = ModbusTcpClient(IP, port=PORT, timeout=2)

    if not client.connect():
        raise ConnectionError(f"连接失败：{IP}:{PORT}")

    try:
        result = client.write_coils(address, values, unit=UNIT)
        _check_response(result, "写线圈")
        return values
    finally:
        client.close()


def write_one_coil(index, value):
    """写入 6 个线圈中的某一个，index 从 0 开始。"""
    if index < 0 or index >= COIL_COUNT:
        raise ValueError(f"线圈序号超出范围：{index}")
    address = COIL_ADDRESS + index
    client = ModbusTcpClient(IP, port=PORT, timeout=2)

    if not client.connect():
        raise ConnectionError(f"连接失败：{IP}:{PORT}")

    try:
        result = client.write_coil(address, bool(value), unit=UNIT)
        _check_response(result, "写单个线圈")
        return bool(value)
    finally:
        client.close()


def main():
    try:
        if WRITE_ENABLE:
            values = write_coils(WRITE_ADDRESS, WRITE_VALUES)
            print(f"写线圈成功：address={WRITE_ADDRESS}, count={len(values)}, values={values}")

        values = read_coils(COIL_ADDRESS, COIL_COUNT)
        print(f"读线圈成功：address={COIL_ADDRESS}, count={COIL_COUNT}")
        print(f"线圈值：{values}")
    except Exception as exc:
        print(exc)


if __name__ == "__main__":
    main()
