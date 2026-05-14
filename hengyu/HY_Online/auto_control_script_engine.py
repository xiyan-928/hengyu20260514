"""
自动控制脚本引擎：按 xlsx 定义执行模式序列（write_coils），非阻塞 tick。
"""
from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional, Tuple

from Devices.modbus_ephemeral import run_ephemeral
from auto_control_context import AutoControlContext
from script_define_loader import ScriptRegistry, load_script_registry, resolve_script_define_path
from config import app_config
from hy_logging import LOG_SIGNAL
from modbus_logging import elapsed_ms, log_modbus_event, mock_modbus_context, modbus_context, now_ms

logger = logging.getLogger(__name__)

OnComplete = Optional[Callable[[], None]]


class AutoControlScriptEngine:
    def __init__(self) -> None:
        self._registry = ScriptRegistry()
        self._active_hook: Optional[str] = None
        self._steps: List[Tuple[str, float]] = []
        self._applied_count: int = 0
        self._next_deadline: Optional[float] = None
        self._on_complete: OnComplete = None

    def set_registry(self, reg: ScriptRegistry) -> None:
        self._registry = reg

    @property
    def registry(self) -> ScriptRegistry:
        return self._registry

    def start(self, hook_name: str, ctx: AutoControlContext, on_complete: OnComplete = None) -> None:
        """启动某 hook 的脚本；若已有运行中的脚本则打断并重置。"""
        if self._active_hook is not None:
            LOG_SIGNAL.info(
                f"自动控制脚本: 打断 {self._active_hook!r}，启动 {hook_name!r}"
            )
        self._active_hook = hook_name
        self._on_complete = on_complete
        self._steps = []
        self._applied_count = 0
        self._next_deadline = None

        steps = self._registry.hook_steps.get(hook_name)
        if not steps:
            self._active_hook = None
            self._on_complete = None
            if on_complete:
                try:
                    on_complete()
                except Exception as e:
                    logger.error(f"自动控制脚本空定义回调异常: {e}")
            return

        self._steps = list(steps)
        ctx.current_hook_name = hook_name
        ctx.current_script_command = self._registry.hook_raw_commands.get(hook_name)
        ctx.current_mode_name = None
        self._apply_mode_for_index(ctx, 0)
        delay = self._steps[0][1]
        self._applied_count = 1
        self._next_deadline = time.monotonic() + float(delay)

    def tick(self, ctx: AutoControlContext) -> None:
        """主循环每轮调用，推进等待后的步骤。"""
        if self._active_hook is None or not self._steps:
            return
        if self._next_deadline is None:
            return
        if time.monotonic() < self._next_deadline:
            return
        if self._applied_count >= len(self._steps):
            self._finish()
            return
        self._apply_mode_for_index(ctx, self._applied_count)
        delay = self._steps[self._applied_count][1]
        self._applied_count += 1
        self._next_deadline = time.monotonic() + float(delay)

    def _apply_mode_for_index(self, ctx: AutoControlContext, idx: int) -> None:
        mode_name = self._steps[idx][0]
        ctx.current_mode_name = mode_name
        self._write_mode(mode_name, ctx)

    def _write_mode(self, mode_name: str, ctx: AutoControlContext) -> None:
        segs = self._registry.mode_segments.get(mode_name)
        if not segs:
            logger.warning(f"自动控制脚本: 未知模式 {mode_name!r}，跳过写线圈")
            return
        coil_host = ctx.coils_modbus_host or ctx.modbus_host
        coil_port = ctx.coils_modbus_port or ctx.modbus_port
        client = ctx.coils_modbus_client
        is_mock = app_config.is_mock_mode()
        if coil_host is None or coil_port is None:
            logger.warning("自动控制脚本: 未配置 modbus_coils 端点，跳过 write_coils")
            return
        if client is None:
            if is_mock:
                for start_addr, vals in segs:
                    log_modbus_event(
                        operation="write_coils",
                        ip=coil_host,
                        port=coil_port,
                        unit=int(ctx.modbus_unit_id),
                        address=start_addr,
                        count=len(vals),
                        data=list(vals),
                        success=True,
                        context=mock_modbus_context(
                            source="mock_auto_control_script_engine",
                            request_name="script_write_mode",
                            hook_name=ctx.current_hook_name,
                            mode_name=mode_name,
                            script_command=ctx.current_script_command,
                        ),
                    )
                    LOG_SIGNAL.info(
                        f"自动控制脚本[模拟]: 写模式 {mode_name!r} 到线圈端点 {coil_host}:{coil_port} @{start_addr} 位={len(vals)}"
                    )
                return
            def task(ephemeral_client):
                return self._write_mode_segments(ephemeral_client, mode_name, segs, ctx, coil_host, int(coil_port), is_mock)

            run_ephemeral(
                coil_host,
                int(coil_port),
                task,
                context=modbus_context(
                    source="auto_control_script_engine",
                    request_name="script_write_mode",
                    hook_name=ctx.current_hook_name,
                    mode_name=mode_name,
                    script_command=ctx.current_script_command,
                ),
            )
            return
        self._write_mode_segments(client, mode_name, segs, ctx, coil_host, int(coil_port), is_mock)

    def _write_mode_segments(
        self,
        client,
        mode_name: str,
        segs,
        ctx: AutoControlContext,
        coil_host: str,
        coil_port: int,
        is_mock: bool,
    ) -> None:
        unit = int(ctx.modbus_unit_id)
        base_context = (
            mock_modbus_context(
                source="mock_auto_control_script_engine",
                request_name="script_write_mode",
                hook_name=ctx.current_hook_name,
                mode_name=mode_name,
                script_command=ctx.current_script_command,
            )
            if is_mock
            else modbus_context(
                source="auto_control_script_engine",
                request_name="script_write_mode",
                hook_name=ctx.current_hook_name,
                mode_name=mode_name,
                script_command=ctx.current_script_command,
            )
        )
        for start_addr, vals in segs:
            try:
                started_ms = now_ms()
                rr = client.write_coils(start_addr, vals, unit=unit)
                if hasattr(rr, "isError") and rr.isError():
                    log_modbus_event(
                        operation="write_coils",
                        ip=coil_host,
                        port=coil_port,
                        unit=unit,
                        address=start_addr,
                        count=len(vals),
                        data=list(vals),
                        success=False,
                        error=str(rr),
                        elapsed_ms_value=elapsed_ms(started_ms),
                        context=base_context,
                    )
                    logger.warning(
                        f"write_coils 失败 mode={mode_name!r} addr={start_addr} unit={unit}: {rr}"
                    )
                else:
                    log_modbus_event(
                        operation="write_coils",
                        ip=coil_host,
                        port=coil_port,
                        unit=unit,
                        address=start_addr,
                        count=len(vals),
                        data=list(vals),
                        success=True,
                        elapsed_ms_value=elapsed_ms(started_ms),
                        context=base_context,
                    )
                    LOG_SIGNAL.info(
                        f"自动控制脚本: 写模式 {mode_name!r} 到线圈端点 {coil_host}:{coil_port} @{start_addr} 位={len(vals)}"
                    )
            except Exception as e:
                logger.warning(
                    f"write_coils 异常 mode={mode_name!r} addr={start_addr}: {e}"
                )

    def write_mode(self, mode_name: str, ctx: AutoControlContext) -> None:
        """单次按模式名写线圈（供 HTTP 手动触发，不经脚本步骤队列）。"""
        ctx.current_hook_name = "manual_apply_mode"
        ctx.current_script_command = mode_name
        ctx.current_mode_name = mode_name
        self._write_mode(mode_name, ctx)

    def _finish(self) -> None:
        cb = self._on_complete
        self._active_hook = None
        self._steps = []
        self._applied_count = 0
        self._next_deadline = None
        self._on_complete = None
        if cb:
            try:
                cb()
            except Exception as e:
                logger.error(f"自动控制脚本完成回调异常: {e}")


_engine: Optional[AutoControlScriptEngine] = None


def get_script_engine() -> AutoControlScriptEngine:
    global _engine
    if _engine is None:
        _engine = AutoControlScriptEngine()
    return _engine


def load_auto_control_scripts_at_startup() -> ScriptRegistry:
    """从 device_settings 解析路径并加载 registry，写入全局 engine。"""
    from Devices.device_settings import DeviceSettings

    cfg = DeviceSettings.instance().get_auto_control_settings()
    rel = cfg.get("script_define_path", "define/script_define.xlsx")
    path = resolve_script_define_path(str(rel))
    reg = load_script_registry(path)
    get_script_engine().set_registry(reg)
    if reg.load_errors:
        for err in reg.load_errors:
            logger.warning(f"script_define: {err}")
    return reg


def reload_auto_control_scripts() -> ScriptRegistry:
    """与 load_auto_control_scripts_at_startup 相同，供配置热重载语义使用。"""
    return load_auto_control_scripts_at_startup()
