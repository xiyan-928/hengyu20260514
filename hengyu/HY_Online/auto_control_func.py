"""
自动控制可替换业务函数：默认实现委托现有数据源；run_on_* 由 script_define.xlsx 驱动。
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from Devices.hy_device import SensorDataManager
from auto_control_context import AutoControlContext
from auto_control_script_engine import get_script_engine
from modbus_logging import elapsed_ms, log_modbus_event, modbus_context, now_ms

logger = logging.getLogger(__name__)

_warmup_script_complete_cb: Optional[Callable[[], None]] = None


def set_warmup_script_complete_callback(cb: Optional[Callable[[], None]]) -> None:
    """由 AutoControlManager 注册：预热脚本全部执行完后调用（等效 warm_up_no_action）。"""
    global _warmup_script_complete_cb
    _warmup_script_complete_cb = cb


def get_alarm_message(ctx: AutoControlContext) -> bool:
    """
    查询当前是否处于报警状态。
    Manager 根据返回值设置 is_alarm_on / _is_alarming。
    默认：报警功能开启时读取 SensorDataManager 缓存的报警状态。
    """
    alarm_conf = ctx.settings.config.get("alarm", {})
    if not alarm_conf.get("enabled", False):
        return False
    return bool(SensorDataManager.instance().get_alarm_status())


def get_autocontrol_message(ctx: AutoControlContext) -> int:
    """
    读取自动控制信号（与原先 monitor 寄存器一致：0/1）。
    Manager 将 is_auto_run 设为 (返回值 == 1)，并传入 _process_signal(val)。
    连接失败或读失败时由调用方在 Manager 内先处理，此处假定 client 可用。
    """
    if ctx.modbus_client is None:
        return 0
    try:
        started_ms = now_ms()
        rr = ctx.modbus_client.read_holding_registers(
            ctx.monitor_register, 1, unit=ctx.modbus_unit_id
        )
        if rr.isError():
            log_modbus_event(
                operation="read_holding_registers",
                ip=ctx.modbus_host,
                port=ctx.modbus_port,
                unit=ctx.modbus_unit_id,
                address=ctx.monitor_register,
                count=1,
                success=False,
                error=str(rr),
                elapsed_ms_value=elapsed_ms(started_ms),
                context=modbus_context(
                    source="auto_control_manager",
                    request_name="get_autocontrol_message",
                ),
            )
            logger.warning(f"get_autocontrol_message: Modbus 读失败: {rr}")
            return 0
        v = rr.registers[0] if rr.registers else 0
        log_modbus_event(
            operation="read_holding_registers",
            ip=ctx.modbus_host,
            port=ctx.modbus_port,
            unit=ctx.modbus_unit_id,
            address=ctx.monitor_register,
            count=1,
            success=True,
            result={"registers": list(rr.registers), "signal": v},
            elapsed_ms_value=elapsed_ms(started_ms),
            context=modbus_context(
                source="auto_control_manager",
                request_name="get_autocontrol_message",
            ),
        )
        return 1 if int(v) == 1 else 0
    except Exception as e:
        logger.warning(f"get_autocontrol_message: {e}")
        return 0


def run_on_alarm_on(ctx: AutoControlContext) -> None:
    """
    报警从 False 变为 True 后的单次动作（与 has_run_alarm_on 配合）。
    定义见 script_define.xlsx「函数定义」sheet 中函数名 run_on_alarm_on。
    """
    get_script_engine().start("run_on_alarm_on", ctx)


def run_on_alarm_off(ctx: AutoControlContext) -> None:
    """
    报警从 True 变为 False 后的单次动作（与 has_run_alarm_off 配合）。
    定义见 script_define.xlsx「函数定义」sheet 中函数名 run_on_alarm_off。
    """
    get_script_engine().start("run_on_alarm_off", ctx)


def run_on_get_ready_for_autorun(
    ctx: AutoControlContext,
    on_complete: Optional[Callable[[], None]] = None,
) -> None:
    """
    自动运行条件满足但尚未就绪时的准备逻辑（与 auto_run_ready 配合）。
    定义见 script_define.xlsx「函数定义」中 run_on_get_ready_for_autorun。
    on_complete：脚本全部步骤执行完毕后的回调（如触发置换前参比光谱采集）。
    """
    get_script_engine().start("run_on_get_ready_for_autorun", ctx, on_complete=on_complete)


def run_on_autorun_batch_finish(
    ctx: AutoControlContext,
    on_complete: Optional[Callable[[], None]] = None,
) -> None:
    """
    自动控制监视寄存器从 1 变为 0 后的单次动作（与 _auto_run_ready 下降沿配合）。
    定义见 script_define.xlsx「函数定义」中函数名 run_on_autorun_batch_finish。
    on_complete：脚本全部步骤执行完毕后的回调（如触发清洗后参比光谱采集）。
    """
    get_script_engine().start("run_on_autorun_batch_finish", ctx, on_complete=on_complete)


def run_on_warmup(ctx: AutoControlContext) -> None:
    """
    needs_warmup 且本会话首次进入时由 Manager 调用一次；脚本结束后触发已注册的预热完成回调。
    """
    get_script_engine().start(
        "run_on_warmup", ctx, on_complete=_warmup_script_complete_cb
    )
