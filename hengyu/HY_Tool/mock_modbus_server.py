"""
mock_modbus_server.py —— 用于测试 ``modbus_setup_tool.py`` 的 Modbus TCP 模拟器
==============================================================================

用途
----
* 在没有真实 PLC / 网关的情况下，本地启动若干 Modbus TCP 从站
* 自动从 ``setup.json`` 提取需要模拟的端口 / unit / 设备
* 对每个已知 ``decode`` 类型预填合理的测试值
  （DDL ≈ 500.00 µS/cm、PH 25.5 ℃/7.00、PT100 25.5 ℃、风扇 50、报警 0、光源 1 …）
* ``--animate`` 时让传感器值随时间小幅波动，模拟"在线"
* 实时打印每一次 **写入**（用于验证 ``configure_writes`` 序列是否正确发送）

工作方式
--------
* 按 setup.json 中各 module 的 ``current_port`` 启动 TCP 服务，
  同一端口下多个 module 的 unit 会合并到一个 ServerContext（同 unit 同地址会被
  后写入的 preset 覆盖；启动日志会列出合并后的 unit 列表，方便人工核对）。
* **<1024 的端口在 Windows 下需要管理员、Linux 下需要 root/sudo**。
  若想避免提权，使用 ``--remap-port 502:5502`` 把实际监听端口换成 5502，
  并相应把 setup.json 中的 ``current_port`` 改成 5502 即可（或加
  ``--write-localhost-setup`` 让本脚本自动生成一份指向 127.0.0.1 的副本）。
* 跨平台：纯 Python（pymodbus），Linux / macOS / Windows 都能跑；
  Linux 上若想用 GUI（``modbus_setup_gui.py``），需要先安装 Tk
  （Debian/Ubuntu: ``sudo apt install python3-tk``；Fedora: ``sudo dnf install python3-tkinter``；
  Arch: ``sudo pacman -S tk``）。

依赖
----
``pymodbus==2.5``（与 modbus_setup_tool.py 一致）

典型用法
--------
::

    # 1) 启动模拟器（端口 502 重映射到 5502, 5020 不变；同时生成本机用的 setup 副本）
    python mock_modbus_server.py --setup setup.json \
        --remap-port 502:5502 \
        --write-localhost-setup setup_localhost.json \
        --animate

    # 2) 另一个终端，用工具针对本机模拟器跑测试
    python modbus_setup_tool.py -c setup_localhost.json test --use-current

    # 3) 同样可以验证 configure_writes 是否正确（模拟器会打印每一次写入）
    python modbus_setup_tool.py -c setup_localhost.json write-ip --all -y
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

try:
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusSlaveContext,
    )
    from pymodbus.device import ModbusDeviceIdentification
    from pymodbus.server.sync import ModbusTcpServer
except ImportError:
    print("错误：未找到 pymodbus，请先安装：pip install pymodbus==2.5", file=sys.stderr)
    sys.exit(1)


log = logging.getLogger("mock_modbus")

# 各数据块大小，足以覆盖 setup.json 中常见地址（PT100 在 500）
DI_SIZE = 1024
CO_SIZE = 1024
HR_SIZE = 2048
IR_SIZE = 1024

# 读功能码 -> 数据块代号
FC_KIND = {1: "co", 2: "di", 3: "hr", 4: "ir"}


# ---------------------------------------------------------------------------
# 带日志的数据块：每次客户端写入都打印一行
# ---------------------------------------------------------------------------


_LOG_STATE = threading.local()


def _suppressed() -> bool:
    return bool(getattr(_LOG_STATE, "suppress", False))


class _Suppress:
    """``with _Suppress(): ...`` 期间，当前线程内的写入不再触发日志。

    用于把脚本启动期 / 动画刷新期等"内部写"和客户端真实写入区分开。
    线程局部变量保证：动画线程在静默写自身值的同时，主线程上的客户端写入仍会打印。
    """

    def __enter__(self):
        self._prev = bool(getattr(_LOG_STATE, "suppress", False))
        _LOG_STATE.suppress = True
        return self

    def __exit__(self, exc_type, exc, tb):
        _LOG_STATE.suppress = self._prev
        return False


class LoggedBlock(ModbusSequentialDataBlock):
    """ModbusSequentialDataBlock 的子类，写入时打印日志。

    内部写（启动预设、动画刷新）通过 ``_Suppress`` 临时静默，
    客户端 TCP 写则始终打印。
    """

    def __init__(self, address, values, *, unit_id: int, kind: str):
        super().__init__(address, values)
        self.unit_id = unit_id
        self.kind = kind

    def setValues(self, address, values):  # type: ignore[override]
        super().setValues(address, values)
        if _suppressed():
            return
        log.info(
            "[unit=%d] WRITE %-2s @ %-5d <- %s",
            self.unit_id, self.kind, address, list(values),
        )


def make_slave_context(unit_id: int) -> ModbusSlaveContext:
    """构造一个空的、零起始的 ModbusSlaveContext。"""
    return ModbusSlaveContext(
        di=LoggedBlock(0, [0] * DI_SIZE, unit_id=unit_id, kind="di"),
        co=LoggedBlock(0, [0] * CO_SIZE, unit_id=unit_id, kind="co"),
        hr=LoggedBlock(0, [0] * HR_SIZE, unit_id=unit_id, kind="hr"),
        ir=LoggedBlock(0, [0] * IR_SIZE, unit_id=unit_id, kind="ir"),
        zero_mode=True,
    )


# ---------------------------------------------------------------------------
# 描述一个待模拟的设备
# ---------------------------------------------------------------------------


@dataclass
class DeviceSpec:
    module: str
    bind_port: int   # 实际监听端口（经过 remap 之后）
    src_port: int    # setup.json 中原始 port
    unit: int
    fc: int          # 读功能码：1/2/3/4
    address: int
    count: int
    decode: str
    name: str
    comment: str = ""


def parse_remap(items: List[str]) -> Dict[int, int]:
    """解析 ``--remap-port 502:5502`` 这种重映射，返回 {原端口: 新端口}。"""
    remap: Dict[int, int] = {}
    for item in items or []:
        if ":" not in item:
            raise SystemExit(f"--remap-port 格式错误：{item!r}，应为 OLD:NEW")
        old_s, new_s = item.split(":", 1)
        try:
            remap[int(old_s)] = int(new_s)
        except ValueError as ex:
            raise SystemExit(f"--remap-port 端口必须是整数：{item!r}（{ex}）") from ex
    return remap


def load_specs(setup_path: Path, port_remap: Dict[int, int]) -> Tuple[List[DeviceSpec], dict]:
    """从 setup.json 抽取 DeviceSpec 列表，并返回原始 JSON 用于生成 localhost 副本。"""
    if not setup_path.exists():
        raise SystemExit(f"找不到 setup 文件：{setup_path.resolve()}")
    data = json.loads(setup_path.read_text(encoding="utf-8"))
    specs: List[DeviceSpec] = []
    for module in data.get("modules", []):
        src_port = int(module.get("current_port", 502))
        bind_port = port_remap.get(src_port, src_port)
        for dev in module.get("devices", []):
            specs.append(DeviceSpec(
                module=str(module.get("name", "?")),
                bind_port=bind_port,
                src_port=src_port,
                unit=int(dev["unit"]),
                fc=int(dev["fc"]),
                address=int(dev["address"]),
                count=int(dev.get("count", 1)),
                decode=str(dev.get("decode", "raw")),
                name=str(dev["name"]),
                comment=str(dev.get("comment", "")),
            ))
    return specs, data


# ---------------------------------------------------------------------------
# 预填值
# ---------------------------------------------------------------------------


def _u32_be_pair(value: float, scale: float) -> Tuple[int, int]:
    v = int(round(value * scale)) & 0xFFFFFFFF
    return (v >> 16) & 0xFFFF, v & 0xFFFF


def preset_for(spec: DeviceSpec) -> List[int]:
    """根据 (name, decode) 返回该设备的初始寄存器/线圈数值列表。

    若长度小于 count，会被补 0。返回值都按 spec.count 截断。
    """
    name = spec.name.upper()
    decode = spec.decode

    # 电导率 DDL：(reg0<<16 | reg1)/100，目标值 500.00 µS/cm
    if decode == "u32_div100":
        hi, lo = _u32_be_pair(500.0, 100.0)
        values: List[int] = [hi, lo]

    # u32_div1000：示例 1.234
    elif decode == "u32_div1000":
        hi, lo = _u32_be_pair(1.234, 1000.0)
        values = [hi, lo]

    # 大端 32 位整数 (无除法)
    elif decode in ("u32_be", "u32_le"):
        hi, lo = _u32_be_pair(12345, 1.0)
        values = [hi, lo] if decode == "u32_be" else [lo, hi]

    # PH 传感器：reg0=温度*10, reg1=pH*100 -> 25.5 ℃ / 7.00
    elif decode == "raw" and "PH" in name:
        values = [255, 700]

    # PT100：reg0/10 -> 25.5 ℃
    elif decode == "r0_div10":
        values = [255]

    # 单寄存器除以 100：示例 1.23
    elif decode == "r0_div100":
        values = [123]

    # 16 位无符号 / 有符号
    elif decode == "u16":
        if "FAN" in name:
            values = [50]                # 风扇 50%
        elif "AUTORUN" in name or "SIGNAL" in name:
            values = [0]                 # 自动运行信号默认未触发
        else:
            values = [0]
    elif decode == "s16":
        values = [0]

    # 线圈 / 离散量
    elif decode == "bits":
        if "ALARM" in name:
            values = [0]                                          # 报警清零
        elif "LIGHT" in name and "VALVE" not in name:
            # 光源默认亮（光谱仪 / 照明）；ALL_RELAYS 等多位读时下面再覆盖
            values = [1]
        elif "VALVE" in name or "PUMP" in name:
            values = [0]                                          # 阀门 / 水泵默认关
        elif "ALL_RELAYS" in name or name.endswith("RELAYS"):
            # [LIGHT, VALVE_INLET, VALVE_IN, VALVE_REPLACE, VALVE_OUT, PUMP]
            values = [1, 0, 0, 0, 0, 0]
        else:
            values = [0]

    # 其他 raw 默认全 0
    else:
        values = [0] * max(1, spec.count)

    if len(values) < spec.count:
        values = list(values) + [0] * (spec.count - len(values))
    return values[: spec.count]


# ---------------------------------------------------------------------------
# 构建并启动服务
# ---------------------------------------------------------------------------


def build_contexts(specs: List[DeviceSpec]) -> Dict[int, ModbusServerContext]:
    """按 bind_port 分组，每个端口下汇总所有 unit，返回 {port: ServerContext}。"""
    slaves_by_port: Dict[int, Dict[int, ModbusSlaveContext]] = {}
    for s in specs:
        slaves = slaves_by_port.setdefault(s.bind_port, {})
        if s.unit not in slaves:
            slaves[s.unit] = make_slave_context(s.unit)
    return {
        port: ModbusServerContext(slaves=slaves, single=False)
        for port, slaves in slaves_by_port.items()
    }


def apply_presets(specs: List[DeviceSpec], contexts: Dict[int, ModbusServerContext]) -> None:
    """把 preset_for(spec) 写入到对应 unit 的数据块上。"""
    with _Suppress():
        for s in specs:
            if s.fc not in FC_KIND:
                log.warning("[%s/%s] 跳过未知读功能码 fc=%s", s.module, s.name, s.fc)
                continue
            slave: ModbusSlaveContext = contexts[s.bind_port][s.unit]
            values = preset_for(s)
            slave.setValues(s.fc, s.address, values)


def print_summary(specs: List[DeviceSpec], contexts: Dict[int, ModbusServerContext], host: str) -> None:
    print("=" * 78)
    print(f"模拟器监听 {len(contexts)} 个端口（bind host = {host}）:")
    # 按 (bind_port, unit) 收集设备
    grouped: Dict[Tuple[int, int], List[DeviceSpec]] = {}
    for s in specs:
        grouped.setdefault((s.bind_port, s.unit), []).append(s)
    for port in sorted(contexts.keys()):
        units = sorted(contexts[port].slaves())
        print(f"  - {host}:{port}  units={units}")
        for unit in units:
            devs = grouped.get((port, unit), [])
            for d in devs:
                init = preset_for(d)
                kind = FC_KIND.get(d.fc, "?")
                print(
                    f"      [{d.module:<16}] {d.name:<16} unit={d.unit:<3} fc={d.fc} "
                    f"{kind} @ {d.address:<5} count={d.count} decode={d.decode:<14} init={init}"
                )
    print("=" * 78)


# ---------------------------------------------------------------------------
# 动态数值（--animate）
# ---------------------------------------------------------------------------


def _animate_value(spec: DeviceSpec, t: float) -> Optional[List[int]]:
    """根据当前时间 t（秒）返回该设备的最新寄存器/线圈值。返回 None 则不更新。"""
    name = spec.name.upper()
    decode = spec.decode

    if decode == "u32_div100":            # DDL 480~520 µS/cm
        v = 500.0 + 20.0 * math.sin(2 * math.pi * t / 30.0)
        hi, lo = _u32_be_pair(v, 100.0)
        return [hi, lo]

    if decode == "raw" and "PH" in name:  # PH：温度 24~26 ℃，pH 6.8~7.2
        temp = 25.0 + 1.0 * math.sin(2 * math.pi * t / 60.0)
        ph = 7.0 + 0.2 * math.sin(2 * math.pi * t / 45.0)
        return [int(round(temp * 10)) & 0xFFFF, int(round(ph * 100)) & 0xFFFF]

    if decode == "r0_div10":              # PT100：24~26 ℃
        temp = 25.0 + 1.0 * math.sin(2 * math.pi * t / 60.0)
        return [int(round(temp * 10)) & 0xFFFF]

    if decode == "u16" and "FAN" in name: # 风扇 40~60%
        spd = 50 + int(round(10 * math.sin(2 * math.pi * t / 20.0)))
        return [max(0, min(100, spd))]

    return None  # 其他设备（线圈、信号等）保持手动 / 上次写入的值


def animate_loop(
    specs: List[DeviceSpec],
    contexts: Dict[int, ModbusServerContext],
    stop_evt: threading.Event,
    interval: float = 1.0,
) -> None:
    t0 = time.time()
    while not stop_evt.is_set():
        t = time.time() - t0
        with _Suppress():  # 仅动画线程自身的写入静默，客户端写仍打印
            for s in specs:
                if s.fc not in FC_KIND:
                    continue
                new_values = _animate_value(s, t)
                if not new_values:
                    continue
                slave: ModbusSlaveContext = contexts[s.bind_port][s.unit]
                slave.setValues(s.fc, s.address, new_values[: s.count])
        stop_evt.wait(interval)


# ---------------------------------------------------------------------------
# 生成指向 127.0.0.1 的 setup 副本
# ---------------------------------------------------------------------------


def write_localhost_setup(
    data: dict,
    port_remap: Dict[int, int],
    out_path: Path,
    bind_host: str,
) -> None:
    """把原始 setup.json 改写为指向本机 + 重映射端口，方便直接用工具测试。

    * current_ip / target_ip 全部替换成 ``bind_host``
      （若 bind_host 为 0.0.0.0，则改写成 127.0.0.1）。
    * current_port / target_port 经 port_remap 替换。
    """
    host = "127.0.0.1" if bind_host in ("0.0.0.0", "::") else bind_host
    new = json.loads(json.dumps(data))  # deepcopy via JSON
    for m in new.get("modules", []):
        if "current_ip" in m:
            m["current_ip"] = host
        if "target_ip" in m and m["target_ip"]:
            m["target_ip"] = host
        if "current_port" in m:
            cp = int(m["current_port"])
            m["current_port"] = port_remap.get(cp, cp)
        if m.get("target_port") is not None:
            tp = int(m["target_port"])
            m["target_port"] = port_remap.get(tp, tp)
    out_path.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[i] 已生成本机版配置：{out_path.resolve()}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mock_modbus_server",
        description="用于测试 modbus_setup_tool.py 的本地 Modbus TCP 模拟器",
    )
    p.add_argument("--setup", default="setup.json",
                   help="读取的 setup.json 路径（默认 setup.json）")
    p.add_argument("--host", default="0.0.0.0",
                   help="服务绑定 IP（默认 0.0.0.0；Windows 上若想只对本机暴露可用 127.0.0.1）")
    p.add_argument("--remap-port", action="append", default=[],
                   metavar="OLD:NEW",
                   help="把 setup.json 中的某个端口映射到另一个监听端口（可重复）"
                        "，例：--remap-port 502:5502")
    p.add_argument("--animate", action="store_true",
                   help="让传感器值随时间小幅波动（DDL/PH/PT100/FAN）")
    p.add_argument("--animate-interval", type=float, default=1.0,
                   help="动画刷新周期秒（默认 1.0）")
    p.add_argument("--write-localhost-setup", default=None, metavar="PATH",
                   help="另存一份把 IP/端口改写成 127.0.0.1 + 重映射后的 setup 副本")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="日志级别（默认 INFO）")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pymodbus").setLevel(logging.WARNING)

    port_remap = parse_remap(args.remap_port)
    specs, raw_data = load_specs(Path(args.setup), port_remap)
    if not specs:
        log.error("setup.json 中没有任何 devices，模拟器无事可做。")
        return 1

    contexts = build_contexts(specs)
    apply_presets(specs, contexts)
    print_summary(specs, contexts, args.host)

    if args.write_localhost_setup:
        write_localhost_setup(raw_data, port_remap, Path(args.write_localhost_setup), args.host)

    identity = ModbusDeviceIdentification()
    identity.VendorName = "HY-Mock"
    identity.ProductCode = "HYMOCK"
    identity.ProductName = "HY Modbus Simulator"
    identity.ModelName = "mock_modbus_server.py"
    identity.MajorMinorRevision = "1.0"

    servers: List[ModbusTcpServer] = []
    threads: List[threading.Thread] = []
    for port, ctx in sorted(contexts.items()):
        try:
            srv = ModbusTcpServer(
                ctx, identity=identity, address=(args.host, port),
                allow_reuse_address=True,
            )
        except PermissionError as ex:
            log.error("绑定 %s:%d 失败（%s）。Windows/Linux 上 <1024 端口需要管理员；"
                      "可用 --remap-port %d:NEW 改成 ≥1024 的端口。",
                      args.host, port, ex, port)
            return 2
        except OSError as ex:
            log.error("绑定 %s:%d 失败：%s", args.host, port, ex)
            return 2
        servers.append(srv)
        th = threading.Thread(target=srv.serve_forever, name=f"mb-{port}", daemon=True)
        th.start()
        threads.append(th)
        log.info("已启动 Modbus TCP -> %s:%d  units=%s",
                 args.host, port, sorted(ctx.slaves()))

    stop_evt = threading.Event()
    if args.animate:
        anim = threading.Thread(
            target=animate_loop,
            args=(specs, contexts, stop_evt, args.animate_interval),
            name="animator", daemon=True,
        )
        anim.start()
        log.info("数值动画已开启（周期 %.1fs）", args.animate_interval)

    log.info("就绪。按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C，正在停止 ...")
    finally:
        stop_evt.set()
        for srv in servers:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
