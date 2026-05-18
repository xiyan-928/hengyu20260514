#!/usr/bin/env python3
"""
读取各个 Modbus 模块数据
========================

默认读取同目录下的 ``my.json``，按配置中的 ``modules -> devices`` 依次读取
EC、PH、PT100、风机、IO 线圈等模块数据。

用法示例：

    python3 read_modbus_modules.py
    python3 read_modbus_modules.py -c my.json --repeat 10 --interval 2
    python3 read_modbus_modules.py -m PH_TRANSMITTER -m PT100_PLC --json
    python3 read_modbus_modules.py --use-current -o read_result.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from modbus_setup_tool import Config, Module, POST_CLOSE_DELAY_SEC, _connect, read_device


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


DEFAULT_CONFIG = "my.json"


def _module_endpoint(module: Module, use_target: bool) -> str:
    ip, port = module.test_endpoint(use_target)
    return f"{ip}:{port}"


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _select_modules(config: Config, names: Optional[List[str]]) -> List[Module]:
    if not names:
        return list(config.modules)
    return [config.find_module(name) for name in names]


def read_module(module: Module, *, use_target: bool, timeout: float) -> List[Dict[str, Any]]:
    """读取一个模块下配置的全部设备。"""
    ip, port = module.test_endpoint(use_target)
    now = datetime.now().isoformat(timespec="seconds")
    results: List[Dict[str, Any]] = []

    if not module.devices:
        return results

    try:
        client = _connect(ip, port, timeout=timeout)
    except Exception as exc:
        for dev in module.devices:
            results.append(
                {
                    "time": now,
                    "module": module.name,
                    "endpoint": f"{ip}:{port}",
                    "device": dev.name,
                    "unit": dev.unit,
                    "fc": dev.fc,
                    "address": dev.address,
                    "count": dev.count,
                    "decode": dev.decode,
                    "ok": False,
                    "error": f"连接失败：{exc}",
                    "elapsed_ms": 0,
                }
            )
        return results

    try:
        for dev in module.devices:
            read_result = read_device(client, dev)
            results.append(
                {
                    "time": now,
                    "module": module.name,
                    "endpoint": f"{ip}:{port}",
                    "device": dev.name,
                    "unit": dev.unit,
                    "fc": dev.fc,
                    "address": dev.address,
                    "count": dev.count,
                    "decode": dev.decode,
                    "ok": bool(read_result.get("ok")),
                    "value": read_result.get("value"),
                    "registers": read_result.get("registers"),
                    "bits": read_result.get("bits"),
                    "error": read_result.get("error"),
                    "elapsed_ms": read_result.get("elapsed_ms"),
                }
            )
            time.sleep(0.05)
    finally:
        try:
            client.close()
        except Exception:
            pass
        time.sleep(POST_CLOSE_DELAY_SEC)

    return results


def read_all(
    modules: Iterable[Module],
    *,
    use_target: bool,
    timeout: float,
) -> List[Dict[str, Any]]:
    all_results: List[Dict[str, Any]] = []
    for module in modules:
        all_results.extend(read_module(module, use_target=use_target, timeout=timeout))
    return all_results


def print_table(results: List[Dict[str, Any]], *, round_index: int, round_count: int) -> None:
    if round_count > 1:
        print(f"\n# 第 {round_index}/{round_count} 轮")

    if not results:
        print("没有可读取的设备。")
        return

    current_module = None
    for item in results:
        module = item["module"]
        if module != current_module:
            current_module = module
            print(f"\n[{module}] @ {item['endpoint']}")

        prefix = (
            f"  {item['device']:<16} unit={item['unit']:<3} fc={item['fc']} "
            f"addr={item['address']:<5} count={item['count']:<3}"
        )
        if item["ok"]:
            raw = item.get("registers")
            if raw is None:
                raw = item.get("bits")
            print(
                f"{prefix} OK   value={_format_value(item.get('value')):<18} "
                f"raw={_format_value(raw)} ({item.get('elapsed_ms')}ms)"
            )
        else:
            print(f"{prefix} FAIL {item.get('error')} ({item.get('elapsed_ms')}ms)")


def write_output(path: Path, results: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已导出结果：{path.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="读取各个 Modbus 模块数据")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help=f"配置文件（默认 {DEFAULT_CONFIG}）")
    parser.add_argument("-m", "--module", action="append", help="只读取指定模块；可重复传入多个")
    parser.add_argument("--use-current", action="store_true", help="使用 current_ip:port，而不是 target_ip:port")
    parser.add_argument("--repeat", type=int, default=1, help="读取轮数（默认 1）")
    parser.add_argument("--interval", type=float, default=1.0, help="多轮读取间隔秒数（默认 1.0）")
    parser.add_argument("--timeout", type=float, default=2.0, help="TCP 连接/请求超时秒数（默认 2.0）")
    parser.add_argument("--json", action="store_true", help="按 JSON 输出到控制台")
    parser.add_argument("-o", "--output", default=None, help="导出读取结果到 JSON 文件")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load(Path(args.config))
    modules = _select_modules(config, args.module)
    use_target = not args.use_current
    repeat = max(1, int(args.repeat))

    print(
        f"配置文件：{Path(args.config).resolve()}\n"
        f"读取模块：{', '.join(m.name for m in modules)}\n"
        f"连接地址：{'target_ip:target_port' if use_target else 'current_ip:current_port'}"
    )
    for module in modules:
        print(f"  - {module.name}: {_module_endpoint(module, use_target)} devices={len(module.devices)}")

    all_results: List[Dict[str, Any]] = []
    for index in range(1, repeat + 1):
        round_results = read_all(modules, use_target=use_target, timeout=float(args.timeout))
        all_results.extend(round_results)
        if args.json:
            print(json.dumps(round_results, ensure_ascii=False, indent=2))
        else:
            print_table(round_results, round_index=index, round_count=repeat)

        if index < repeat:
            time.sleep(max(0.0, float(args.interval)))

    success = sum(1 for item in all_results if item.get("ok"))
    print(f"\n汇总：成功 {success}/{len(all_results)}")

    if args.output:
        write_output(Path(args.output), all_results)

    return 0 if all_results and success == len(all_results) else 2


if __name__ == "__main__":
    sys.exit(main())
