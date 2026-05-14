#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单独测试 DDL、PT100、PH 传感器：读数逻辑与 Devices/drivers.py 一致（每次读数独立短连接）。

配置**仅**从 device_config.json 读取（不经过 DeviceSettings 与代码内 DEFAULT_CONFIG 合并）。
请在 HY_Online 目录下执行：
  python test_sensors_ddl_pt100_ph.py
  python test_sensors_ddl_pt100_ph.py --host 192.168.1.12 --port 502
  python test_sensors_ddl_pt100_ph.py --config D:\\path\\device_config.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Devices.drivers import DriverFactory

SENSOR_ORDER = ("DDL", "PT100", "PH")


def _load_device_config(config_path: str) -> Dict[str, Any]:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"找不到配置文件: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _holding_endpoint_from_file(cfg: Dict[str, Any]) -> Tuple[str, int]:
    """与 DeviceSettings.get_modbus_holding_endpoint 规则一致，但数据全部来自已加载的 JSON。"""
    m = cfg.get("modbus_holding") or {}
    host = m.get("host")
    if host is None or (isinstance(host, str) and host.strip() == ""):
        host = cfg.get("ip")
    port = m.get("port")
    if port is None:
        port = cfg.get("port")
    if host is None or (isinstance(host, str) and host.strip() == ""):
        raise ValueError("device_config.json 中未设置可连接的寄存器主机（需顶层 ip 或 modbus_holding.host）")
    if port is None:
        raise ValueError("device_config.json 中未设置端口（需顶层 port 或 modbus_holding.port）")
    return str(host).strip(), int(port)


def main() -> int:
    default_config = os.path.join(_ROOT, "device_config.json")
    parser = argparse.ArgumentParser(description="一次性读取 DDL / PT100 / PH（配置来自 JSON 文件）")
    parser.add_argument(
        "--config",
        default=default_config,
        help=f"device_config.json 路径（默认: {default_config}）",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="仅覆盖 JSON 中的寄存器网关主机（调试用途）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="仅覆盖 JSON 中的寄存器网关端口（调试用途）",
    )
    parser.add_argument("--timeout", type=float, default=3.0, help="（保留参数，超时由驱动内 Modbus 客户端使用）")
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    try:
        raw = _load_device_config(config_path)
    except (OSError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"读取配置失败: {e}")
        return 1

    try:
        ip, port = _holding_endpoint_from_file(raw)
    except ValueError as e:
        print(e)
        return 1

    if args.host is not None:
        ip = args.host.strip()
    if args.port is not None:
        port = int(args.port)

    sensors_root = raw.get("sensors")
    if not isinstance(sensors_root, dict):
        print("device_config.json 中缺少 sensors 对象")
        return 1

    print(f"已加载配置: {config_path}")
    print(f"Modbus 寄存器网关: {ip}:{port}\n")

    for name in SENSOR_ORDER:
        cfg = sensors_root.get(name)
        if not isinstance(cfg, dict):
            print(f"[{name}] JSON 中无此项或类型非对象，跳过")
            continue
        if cfg.get("enabled") is False:
            print(f"[{name}] enabled=false，跳过")
            continue

        driver_name = cfg.get("driver")
        if not driver_name:
            print(f"[{name}] JSON 中缺少 driver，跳过")
            continue

        params = cfg.get("params")
        if not isinstance(params, dict):
            print(f"[{name}] JSON 中缺少 params 对象，跳过")
            continue
        if "unit" not in params or "address" not in params:
            print(f"[{name}] params 须同时包含 JSON 键 unit 与 address，跳过")
            continue

        try:
            driver = DriverFactory.create(driver_name)
        except ValueError as e:
            print(f"[{name}] 驱动不可用: {e}")
            continue

        try:
            data = driver.read(ip, port, params)
        except Exception as e:
            print(f"[{name}] 通讯异常: {e}")
            continue

        unit = params["unit"]
        addr = params["address"]

        if not data:
            print(
                f"[{name}] 读失败或空结果 (unit={unit}, address={addr})，"
                "请核对从站与寄存器地址。"
            )
            continue

        if name == "DDL":
            print(f"[{name}] ddl = {data.get('ddl')}  (unit={unit}, address={addr})")
        elif name == "PT100":
            print(f"[{name}] pt100 = {data.get('pt100')} ℃  (unit={unit}, address={addr})")
        elif name == "PH":
            print(
                f"[{name}] ph = {data.get('ph')}, "
                f"ph_temp = {data.get('ph_temp')} ℃  (unit={unit}, address={addr})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
