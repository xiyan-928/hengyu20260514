"""
Modbus 模块初次搭建系统的测试程序
================================

用途
----
1. 一次性配置（修改）多个 Modbus 模块/网关的 IP、端口
   —— 不同模块的寄存器布局不同，用户在 JSON 中以 ``configure_writes``
   形式手动列出每条 ``{fc, address, value}`` 写入，工具按顺序逐条执行。
2. 配置每个模块下的设备（unit、读取地址、寄存器数量、解码方式）。
3. 配置完成后对所有模块/设备进行统一读取测试，验证联通与数值。

使用流程
--------
::

    # 1) 生成示例配置
    python modbus_setup_tool.py init -o setup.json

    # 2) 用任意文本编辑器编辑 setup.json，按实际填写各模块的
    #    current_ip / current_port / configure_writes / target_ip
    #    以及 devices 列表。

    # 3) 查看配置摘要（可选）
    python modbus_setup_tool.py -c setup.json show -v

    # 4) 对模块写入 IP/端口等配置寄存器（先 dry-run 预览，再正式执行）
    python modbus_setup_tool.py -c setup.json write-ip -m GW1 --dry-run
    python modbus_setup_tool.py -c setup.json write-ip -m GW1
    # 或一次性对所有模块执行：
    python modbus_setup_tool.py -c setup.json write-ip --all -y

    # 5) 统一测试（默认使用 target_ip:target_port，若未填则回退到 current）
    python modbus_setup_tool.py -c setup.json test
    python modbus_setup_tool.py -c setup.json test -m GW1 --repeat 3 -o result.json

依赖：``pymodbus==2.5``
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

# Windows 控制台默认 GBK，统一切到 UTF-8，避免中文/特殊字符报错
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

try:
    from pymodbus.client.sync import ModbusTcpClient
except ImportError:
    print("错误：未找到 pymodbus，请先安装：pip install pymodbus==2.5", file=sys.stderr)
    sys.exit(1)


DEFAULT_CONFIG_FILENAME = "modbus_setup_config.json"
POST_CLOSE_DELAY_SEC = 0.3


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class WriteOp:
    """一条 Modbus 写入操作。

    - ``fc=6`` : write_register（value 为 int）
    - ``fc=16``: write_registers（value 为 int 数组，从 address 起依次写入）
    - ``fc=5`` : write_coil（value 为 0/1 或 bool）
    - ``fc=15``: write_coils（value 为 0/1 数组或 bool 数组）
    """

    fc: int
    address: int
    value: Any
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WriteOp":
        return cls(
            fc=int(d["fc"]),
            address=int(d["address"]),
            value=d["value"],
            comment=str(d.get("comment", "")),
        )


@dataclass
class Device:
    """一个挂在模块下的 Modbus 从站（unit）以及一段读取范围。

    - ``fc``: 1=read_coils, 2=read_discrete_inputs, 3=read_holding_registers, 4=read_input_registers
    - ``decode``: 见 :func:`decode_registers`
    """

    name: str
    unit: int
    fc: int
    address: int
    count: int = 2
    decode: str = "raw"
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Device":
        return cls(
            name=str(d["name"]),
            unit=int(d["unit"]),
            fc=int(d["fc"]),
            address=int(d["address"]),
            count=int(d.get("count", 2)),
            decode=str(d.get("decode", "raw")),
            comment=str(d.get("comment", "")),
        )


@dataclass
class Module:
    """一个 Modbus 网关/模块。

    ``current_*``: 模块当前真实地址（出厂或现网络中实际地址），用于连接执行
    ``configure_writes``；写入完成、模块切换到新地址后再使用 ``target_*``
    进行后续设备读取测试。
    """

    name: str
    current_ip: str
    current_port: int = 502
    current_unit: int = 1
    target_ip: Optional[str] = None
    target_port: Optional[int] = None
    target_unit: Optional[int] = None
    configure_writes: List[WriteOp] = field(default_factory=list)
    devices: List[Device] = field(default_factory=list)
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Module":
        return cls(
            name=str(d["name"]),
            current_ip=str(d["current_ip"]),
            current_port=int(d.get("current_port", 502)),
            current_unit=int(d.get("current_unit", 1)),
            target_ip=(str(d["target_ip"]) if d.get("target_ip") else None),
            target_port=(int(d["target_port"]) if d.get("target_port") is not None else None),
            target_unit=(int(d["target_unit"]) if d.get("target_unit") is not None else None),
            configure_writes=[WriteOp.from_dict(x) for x in d.get("configure_writes", [])],
            devices=[Device.from_dict(x) for x in d.get("devices", [])],
            comment=str(d.get("comment", "")),
        )

    def test_endpoint(self, use_target: bool) -> Tuple[str, int]:
        if use_target and self.target_ip:
            return self.target_ip, int(self.target_port or self.current_port)
        return self.current_ip, int(self.current_port)


@dataclass
class Config:
    modules: List[Module] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            raise SystemExit(
                f"找不到配置文件：{path.resolve()}\n请先运行 `init` 生成示例，或使用 -c 指定文件。"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(modules=[Module.from_dict(x) for x in data.get("modules", [])])

    def find_module(self, name: str) -> Module:
        for m in self.modules:
            if m.name == name:
                return m
        names = [m.name for m in self.modules]
        raise SystemExit(f"未找到模块：{name!r}。已知模块：{names}")


# ---------------------------------------------------------------------------
# 示例配置（init 子命令写出的模板）
# ---------------------------------------------------------------------------


EXAMPLE_CONFIG: dict = {
    "_comment": (
        "Modbus 模块初次搭建配置。每个模块独立配置：current_* 为当前真实地址，"
        "configure_writes 列出修改 IP/端口/保存重启等寄存器的写入序列（不同品牌差别很大，"
        "请查模块手册并按需修改）。devices 用于配置完成后的统一读取测试。"
    ),
    "modules": [
        {
            "name": "GW1",
            "comment": "示例：将出厂 IP 192.168.1.10 改成 192.168.1.12；寄存器地址/编码方式请按实际模块手册替换。",
            "current_ip": "192.168.1.10",
            "current_port": 502,
            "current_unit": 1,
            "target_ip": "192.168.1.12",
            "target_port": 502,
            "configure_writes": [
                {"fc": 6, "address": 100, "value": 192, "comment": "IP byte 1"},
                {"fc": 6, "address": 101, "value": 168, "comment": "IP byte 2"},
                {"fc": 6, "address": 102, "value": 1,   "comment": "IP byte 3"},
                {"fc": 6, "address": 103, "value": 12,  "comment": "IP byte 4"},
                {"fc": 6, "address": 110, "value": 502, "comment": "TCP 端口"},
                {"fc": 16, "address": 200, "value": [1], "comment": "示例：写 1 触发保存/重启（请按手册）"}
            ],
            "devices": [
                {"name": "DDL",   "unit": 8,  "fc": 3, "address": 3,   "count": 2, "decode": "u32_div100", "comment": "电导率"},
                {"name": "PH",    "unit": 9,  "fc": 3, "address": 6,   "count": 2, "decode": "raw",        "comment": "[温度*10, pH*100]"},
                {"name": "PT100", "unit": 20, "fc": 3, "address": 500, "count": 2, "decode": "r0_div10",   "comment": "温度 /10 ℃"}
            ]
        },
        {
            "name": "GW2",
            "comment": "第二个模块示例（线圈网关）。",
            "current_ip": "192.168.1.11",
            "current_port": 502,
            "current_unit": 1,
            "target_ip": "192.168.1.10",
            "target_port": 502,
            "configure_writes": [],
            "devices": [
                {"name": "LIGHT_COIL",  "unit": 1, "fc": 1, "address": 0, "count": 1, "decode": "bits", "comment": "LIGHT"},
                {"name": "VALVE_COILS", "unit": 1, "fc": 1, "address": 0, "count": 4, "decode": "bits", "comment": "LIGHT/CLEAN/IN/OUT"}
            ]
        }
    ]
}


# ---------------------------------------------------------------------------
# 解码方案
# ---------------------------------------------------------------------------


def decode_registers(registers: List[int], scheme: str) -> Any:
    """将寄存器数组按 ``scheme`` 解码成可读值。

    支持：

    - ``raw``         : 原样返回数组
    - ``u16`` / ``s16``: 取第 0 个寄存器为 16 位无符号 / 有符号
    - ``u32_be``      : (reg0<<16)|reg1
    - ``u32_le``      : (reg1<<16)|reg0
    - ``u32_div100``  : u32_be / 100
    - ``u32_div1000`` : u32_be / 1000
    - ``r0_div10``    : reg0 / 10
    - ``r0_div100``   : reg0 / 100
    - ``bits``        : 每个寄存器最低位取布尔
    """
    if scheme == "raw":
        return list(registers)
    if not registers:
        return None
    if scheme == "u16":
        return int(registers[0]) & 0xFFFF
    if scheme == "s16":
        v = int(registers[0]) & 0xFFFF
        return v - 0x10000 if v >= 0x8000 else v
    if scheme in ("u32_be", "u32_div100", "u32_div1000"):
        if len(registers) < 2:
            return None
        v = (int(registers[0]) << 16) | int(registers[1])
        if scheme == "u32_div100":
            return v / 100.0
        if scheme == "u32_div1000":
            return v / 1000.0
        return v
    if scheme == "u32_le":
        if len(registers) < 2:
            return None
        return (int(registers[1]) << 16) | int(registers[0])
    if scheme == "r0_div10":
        return int(registers[0]) / 10.0
    if scheme == "r0_div100":
        return int(registers[0]) / 100.0
    if scheme == "bits":
        return [bool(int(r) & 1) for r in registers]
    return list(registers)


# ---------------------------------------------------------------------------
# Modbus 通讯
# ---------------------------------------------------------------------------


def _connect(ip: str, port: int, timeout: float = 2.0) -> ModbusTcpClient:
    client = ModbusTcpClient(ip, port=int(port), timeout=timeout)
    if not client.connect():
        try:
            client.close()
        except Exception:
            pass
        raise ConnectionError(f"无法连接 {ip}:{port}")
    return client


def execute_write(client: ModbusTcpClient, op: WriteOp, unit: int) -> Tuple[bool, str]:
    """执行一条写入。返回 (success, message)。"""
    try:
        if op.fc == 6:
            value = int(op.value)
            resp = client.write_register(int(op.address), value, unit=unit)
        elif op.fc == 16:
            values = list(op.value) if isinstance(op.value, (list, tuple)) else [op.value]
            values = [int(v) & 0xFFFF for v in values]
            resp = client.write_registers(int(op.address), values, unit=unit)
        elif op.fc == 5:
            value = bool(op.value) if not isinstance(op.value, (int, float)) else bool(int(op.value))
            resp = client.write_coil(int(op.address), value, unit=unit)
        elif op.fc == 15:
            values = list(op.value) if isinstance(op.value, (list, tuple)) else [op.value]
            values = [bool(int(v)) if isinstance(v, (int, float)) else bool(v) for v in values]
            resp = client.write_coils(int(op.address), values, unit=unit)
        else:
            return False, f"不支持的写功能码：{op.fc}（支持 5/6/15/16）"
    except Exception as ex:
        return False, f"异常：{ex}"

    if resp is None:
        return False, "无响应（可能模块已重启/换 IP）"
    if hasattr(resp, "isError") and resp.isError():
        return False, f"Modbus 错误：{resp}"
    return True, "OK"


def read_device(client: ModbusTcpClient, dev: Device) -> dict:
    """读取一个设备。返回包含 ok / value / registers|bits / error / elapsed_ms 的字典。"""
    started = time.time()
    try:
        if dev.fc == 1:
            resp = client.read_coils(dev.address, dev.count, unit=dev.unit)
        elif dev.fc == 2:
            resp = client.read_discrete_inputs(dev.address, dev.count, unit=dev.unit)
        elif dev.fc == 3:
            resp = client.read_holding_registers(dev.address, dev.count, unit=dev.unit)
        elif dev.fc == 4:
            resp = client.read_input_registers(dev.address, dev.count, unit=dev.unit)
        else:
            return {
                "ok": False,
                "error": f"不支持的读功能码：{dev.fc}（支持 1/2/3/4）",
                "elapsed_ms": int((time.time() - started) * 1000),
            }
    except Exception as ex:
        return {
            "ok": False,
            "error": f"异常：{ex}",
            "elapsed_ms": int((time.time() - started) * 1000),
        }

    elapsed = int((time.time() - started) * 1000)
    if resp is None or (hasattr(resp, "isError") and resp.isError()):
        return {"ok": False, "error": f"Modbus 错误：{resp}", "elapsed_ms": elapsed}

    if dev.fc in (1, 2):
        bits_all = list(getattr(resp, "bits", []) or [])
        bits = [bool(b) for b in bits_all[: dev.count]]
        return {"ok": True, "bits": bits, "value": bits, "elapsed_ms": elapsed}

    registers = list(getattr(resp, "registers", []) or [])
    value = decode_registers(registers, dev.decode)
    return {"ok": True, "registers": registers, "value": value, "elapsed_ms": elapsed}


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    out_path = Path(args.output or args.config or DEFAULT_CONFIG_FILENAME)
    if out_path.exists() and not args.force:
        print(f"文件已存在：{out_path}（使用 --force 覆盖）")
        return 1
    out_path.write_text(
        json.dumps(EXAMPLE_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已生成示例配置：{out_path.resolve()}")
    print("请编辑后再运行 `show` / `write-ip` / `test` 等子命令。")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cfg = Config.load(Path(args.config))
    print(f"配置文件：{Path(args.config).resolve()}")
    print(f"共 {len(cfg.modules)} 个模块：")
    for m in cfg.modules:
        tgt = f"{m.target_ip}:{m.target_port}" if m.target_ip else "(未设定)"
        print(
            f"  - [{m.name}] current={m.current_ip}:{m.current_port} unit={m.current_unit}"
            f"  target={tgt}  writes={len(m.configure_writes)}  devices={len(m.devices)}"
        )
        if m.comment:
            print(f"      // {m.comment}")
        if args.verbose:
            for i, w in enumerate(m.configure_writes, 1):
                print(
                    f"      WRITE[{i}]  fc={w.fc:<2} addr={w.address:<5} value={w.value}"
                    f"   // {w.comment}"
                )
            for d in m.devices:
                print(
                    f"      DEV       {d.name:<12} unit={d.unit:<3} fc={d.fc} "
                    f"addr={d.address:<5} count={d.count} decode={d.decode}"
                    + (f"   // {d.comment}" if d.comment else "")
                )
    return 0


def cmd_write_ip(args: argparse.Namespace) -> int:
    cfg = Config.load(Path(args.config))
    targets = cfg.modules if args.all else [cfg.find_module(args.module)]

    overall_ok = True
    for m in targets:
        print("=" * 72)
        print(f"模块 [{m.name}]  当前 {m.current_ip}:{m.current_port}  unit={m.current_unit}")
        if m.target_ip:
            print(f"  目标 {m.target_ip}:{m.target_port}")
        if not m.configure_writes:
            print("  (无 configure_writes，跳过)")
            continue

        print(f"  待执行写入 {len(m.configure_writes)} 条：")
        for i, w in enumerate(m.configure_writes, 1):
            print(
                f"    [{i}] fc={w.fc:<2} addr={w.address:<5} value={w.value}"
                + (f"   // {w.comment}" if w.comment else "")
            )
        if args.dry_run:
            print("  (--dry-run，仅预览，不执行)")
            continue
        if not args.yes:
            ans = input(f"  确认写入到 {m.current_ip}:{m.current_port}? [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("  已取消。")
                continue

        try:
            client = _connect(m.current_ip, m.current_port, timeout=args.timeout)
        except Exception as ex:
            print(f"  连接失败：{ex}")
            overall_ok = False
            continue

        try:
            for i, w in enumerate(m.configure_writes, 1):
                ok, msg = execute_write(client, w, m.current_unit)
                tag = "OK  " if ok else "FAIL"
                print(
                    f"    [{i}] {tag} fc={w.fc:<2} addr={w.address:<5} value={w.value}  -> {msg}"
                )
                if not ok:
                    overall_ok = False
                    if args.stop_on_error:
                        print("    (--stop-on-error，终止该模块剩余写入)")
                        break
                time.sleep(args.delay)
        finally:
            try:
                client.close()
            except Exception:
                pass
            time.sleep(POST_CLOSE_DELAY_SEC)

    print("=" * 72)
    print("全部完成。" if overall_ok else "存在失败项，请检查上方日志。")
    return 0 if overall_ok else 2


def _run_module_tests(m: Module, use_target: bool, timeout: float) -> List[dict]:
    ip, port = m.test_endpoint(use_target)
    print("-" * 72)
    print(f"测试模块 [{m.name}] @ {ip}:{port}  设备数={len(m.devices)}")
    results: List[dict] = []
    if not m.devices:
        return results

    try:
        client = _connect(ip, port, timeout=timeout)
    except Exception as ex:
        print(f"  连接失败：{ex}")
        for d in m.devices:
            results.append({
                "module": m.name, "device": d.name, "unit": d.unit, "fc": d.fc,
                "address": d.address, "count": d.count, "decode": d.decode,
                "ok": False, "error": f"连接失败：{ex}", "elapsed_ms": 0,
            })
        return results

    try:
        for d in m.devices:
            r = read_device(client, d)
            line = (
                f"  {d.name:<14} unit={d.unit:<3} fc={d.fc} addr={d.address:<5} "
                f"count={d.count} decode={d.decode:<12}"
            )
            if r.get("ok"):
                raw = r.get("registers", r.get("bits"))
                print(
                    f"{line} OK   raw={raw}  value={r.get('value')}  "
                    f"({r.get('elapsed_ms')}ms)"
                )
            else:
                print(f"{line} FAIL {r.get('error')}  ({r.get('elapsed_ms')}ms)")
            results.append({
                "module": m.name, "device": d.name, "unit": d.unit, "fc": d.fc,
                "address": d.address, "count": d.count, "decode": d.decode,
                "ok": r.get("ok"),
                "registers": r.get("registers"),
                "bits": r.get("bits"),
                "value": r.get("value"),
                "error": r.get("error"),
                "elapsed_ms": r.get("elapsed_ms"),
            })
            time.sleep(0.05)
    finally:
        try:
            client.close()
        except Exception:
            pass
        time.sleep(POST_CLOSE_DELAY_SEC)

    return results


def cmd_test(args: argparse.Namespace) -> int:
    cfg = Config.load(Path(args.config))
    targets = cfg.modules if args.module is None else [cfg.find_module(args.module)]
    use_target = not args.use_current

    all_results: List[dict] = []
    repeat = max(1, args.repeat)
    for round_idx in range(repeat):
        if repeat > 1:
            print("#" * 72)
            print(f"# 第 {round_idx + 1}/{repeat} 轮")
        for m in targets:
            all_results.extend(_run_module_tests(m, use_target, args.timeout))
        if round_idx < repeat - 1:
            time.sleep(max(0.0, args.interval))

    ok_count = sum(1 for r in all_results if r.get("ok"))
    print("=" * 72)
    print(f"汇总：成功 {ok_count}/{len(all_results)}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已导出结果：{Path(args.output).resolve()}")

    return 0 if all_results and ok_count == len(all_results) else 2


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="modbus_setup_tool",
        description="Modbus 模块初次搭建系统的测试程序（JSON 配置 + CLI）",
    )
    p.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG_FILENAME,
        help=f"配置文件路径（默认 {DEFAULT_CONFIG_FILENAME}）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="生成示例配置文件")
    p_init.add_argument("-o", "--output", default=None, help="输出文件名（默认沿用 -c）")
    p_init.add_argument("--force", action="store_true", help="若已存在则覆盖")
    p_init.set_defaults(func=cmd_init)

    p_show = sub.add_parser("show", help="打印当前配置摘要")
    p_show.add_argument("-v", "--verbose", action="store_true", help="显示每条写入/设备明细")
    p_show.set_defaults(func=cmd_show)

    p_wip = sub.add_parser("write-ip", help="对模块执行 configure_writes 中的所有写入")
    g = p_wip.add_mutually_exclusive_group(required=True)
    g.add_argument("-m", "--module", help="模块名")
    g.add_argument("--all", action="store_true", help="对所有模块依次执行")
    p_wip.add_argument("--dry-run", action="store_true", help="仅预览将要写入的内容")
    p_wip.add_argument("-y", "--yes", action="store_true", help="跳过交互确认")
    p_wip.add_argument("--timeout", type=float, default=2.0, help="TCP 连接/请求超时秒（默认 2.0）")
    p_wip.add_argument("--delay", type=float, default=0.1, help="相邻写入之间的延时秒（默认 0.1）")
    p_wip.add_argument("--stop-on-error", action="store_true", help="某条失败时停止该模块剩余写入")
    p_wip.set_defaults(func=cmd_write_ip)

    p_test = sub.add_parser("test", help="读取所有设备进行统一测试")
    p_test.add_argument("-m", "--module", default=None, help="只测试指定模块；不指定则测全部")
    p_test.add_argument("--use-current", action="store_true",
                        help="使用 current_ip:port 而非 target_ip:port 进行测试")
    p_test.add_argument("--repeat", type=int, default=1, help="重复读取轮数（默认 1）")
    p_test.add_argument("--interval", type=float, default=1.0,
                        help="重复轮之间的间隔秒（默认 1.0）")
    p_test.add_argument("--timeout", type=float, default=2.0, help="TCP 连接/请求超时秒（默认 2.0）")
    p_test.add_argument("-o", "--output", default=None, help="导出结果到 JSON 文件")
    p_test.set_defaults(func=cmd_test)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
