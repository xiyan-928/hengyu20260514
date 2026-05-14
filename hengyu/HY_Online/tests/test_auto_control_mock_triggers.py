"""
模拟模式下验证自动控制各触发条件是否执行对应脚本（write_coils / 预热完成）。

依赖 conftest 中 DEVICE_MODE=mock；不启动真实 Modbus，使用 MagicMock 记录指令。

运行（HY_Online 目录）:
    pytest tests/test_auto_control_mock_triggers.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _build_ctx_with_coils_client(mgr, mock_client):
    from auto_control_context import AutoControlContext

    return AutoControlContext(
        settings=mgr._settings,
        modbus_client=mock_client,
        coils_modbus_client=mock_client,
        modbus_host="localhost",
        modbus_port=5020,
        coils_modbus_host="192.168.1.10",
        coils_modbus_port=502,
        modbus_unit_id=1,
        monitor_register=1,
        get_cds350_device=mgr._get_cds350_device,
    )


@pytest.fixture
def script_registry_and_engine():
    """注入可预测的脚本定义，与现场 xlsx 解耦。"""
    from auto_control_script_engine import get_script_engine
    from script_define_loader import ScriptRegistry

    reg = ScriptRegistry()
    reg.points = {"P0": 0, "P1": 1}
    reg.mode_segments = {
        "MODE_ALARM": [(0, [True, False])],
        "MODE_ALARM_OFF": [(0, [False, False])],
        "MODE_READY": [(0, [False, True])],
        "MODE_BATCH_END": [(0, [True, False])],
        "MODE_WARM": [(0, [True, True])],
    }
    reg.hook_steps = {
        "run_on_alarm_on": [("MODE_ALARM", 0.0)],
        "run_on_alarm_off": [("MODE_ALARM_OFF", 0.0)],
        "run_on_get_ready_for_autorun": [("MODE_READY", 0.0)],
        "run_on_autorun_batch_finish": [("MODE_BATCH_END", 0.0)],
        "run_on_warmup": [("MODE_WARM", 0.0)],
    }
    eng = get_script_engine()
    eng.set_registry(reg)
    yield eng, reg
    empty = ScriptRegistry()
    eng.set_registry(empty)
    eng._active_hook = None
    eng._steps = []
    eng._applied_count = 0
    eng._next_deadline = None
    eng._on_complete = None


@pytest.fixture
def mock_client():
    client = MagicMock()
    rr = MagicMock()
    rr.isError.return_value = False
    rr.registers = [0]
    client.read_holding_registers.return_value = rr
    client.write_coils.return_value = rr
    return client


@pytest.fixture
def mgr():
    from auto_control_manager import AutoControlManager

    return AutoControlManager(lambda: None)


def test_environment_is_mock_mode():
    """与 start.py / conftest 一致：默认模拟设备模式。"""
    from config import app_config

    assert os.environ.get("DEVICE_MODE", "").lower() in ("", "mock")
    assert app_config.is_mock_mode() is True


@pytest.mark.usefixtures("script_registry_and_engine")
def test_alarm_rising_edge_triggers_alarm_mode_write_coils(mgr, mock_client):
    """报警为 True 且尚未执行过 run_on_alarm_on：应 write_coils 写入 MODE_ALARM。"""
    ctx = _build_ctx_with_coils_client(mgr, mock_client)
    mock_client.reset_mock()

    with patch("auto_control_manager.get_alarm_message", return_value=True):
        mgr._refresh_alarm_state(ctx)
    assert mgr._is_alarming is True
    mgr._has_run_alarm_on = False

    mgr._apply_state_machine(ctx, 0)

    mock_client.write_coils.assert_called()
    args, kwargs = mock_client.write_coils.call_args
    assert args[0] == 0
    assert list(args[1]) == [True, False]
    assert kwargs.get("unit") == 1


@pytest.mark.usefixtures("script_registry_and_engine")
def test_alarm_falling_edge_triggers_alarm_off_mode_write_coils(mgr, mock_client):
    """报警由 True→False：应 write_coils 写入 MODE_ALARM_OFF。"""
    ctx = _build_ctx_with_coils_client(mgr, mock_client)
    mock_client.reset_mock()

    # 先制造一次报警上升沿，确保后续下降沿可触发 run_on_alarm_off
    with patch("auto_control_manager.get_alarm_message", return_value=True):
        mgr._refresh_alarm_state(ctx)
    mgr._has_run_alarm_on = False
    mgr._apply_state_machine(ctx, 0)

    # 再切为报警解除，触发下降沿脚本
    with patch("auto_control_manager.get_alarm_message", return_value=False):
        mgr._refresh_alarm_state(ctx)
    mock_client.reset_mock()
    mgr._apply_state_machine(ctx, 0)

    mock_client.write_coils.assert_called()
    args, kwargs = mock_client.write_coils.call_args
    assert args[0] == 0
    assert list(args[1]) == [False, False]
    assert kwargs.get("unit") == 1


@pytest.mark.usefixtures("script_registry_and_engine")
def test_auto_run_signal_triggers_ready_mode_write_coils(mgr, mock_client):
    """自动控制信号为 1 且尚未就绪：应 write_coils 写入 MODE_READY。"""
    from auto_control_func import get_autocontrol_message

    rr = mock_client.read_holding_registers.return_value
    rr.registers = [1]

    ctx = _build_ctx_with_coils_client(mgr, mock_client)
    mock_client.reset_mock()

    mgr._is_alarming = False
    mgr._has_run_alarm_on = False
    mgr._auto_run_ready = False

    val = get_autocontrol_message(_build_ctx_with_coils_client(mgr, mock_client))
    assert val == 1
    mgr._apply_state_machine(ctx, val)

    mock_client.write_coils.assert_called()
    args, kwargs = mock_client.write_coils.call_args
    assert list(args[1]) == [False, True]
    assert kwargs.get("unit") == 1


@pytest.mark.usefixtures("script_registry_and_engine")
def test_auto_run_falling_edge_triggers_batch_finish_write_coils(mgr, mock_client):
    """自动控制信号 1→0：应 write_coils 写入 MODE_BATCH_END（在 READY 之后）。"""
    from auto_control_func import get_autocontrol_message

    rr = mock_client.read_holding_registers.return_value

    ctx = _build_ctx_with_coils_client(mgr, mock_client)

    mgr._is_alarming = False
    mgr._has_run_alarm_on = False
    mgr._auto_run_ready = False

    rr.registers = [1]
    val = get_autocontrol_message(_build_ctx_with_coils_client(mgr, mock_client))
    assert val == 1
    mock_client.reset_mock()
    mgr._apply_state_machine(ctx, val)
    mock_client.write_coils.assert_called()
    args_ready, _ = mock_client.write_coils.call_args
    assert list(args_ready[1]) == [False, True]

    rr.registers = [0]
    val0 = get_autocontrol_message(_build_ctx_with_coils_client(mgr, mock_client))
    assert val0 == 0
    mock_client.reset_mock()
    mgr._apply_state_machine(ctx, val0)

    mock_client.write_coils.assert_called()
    args_end, kwargs = mock_client.write_coils.call_args
    assert list(args_end[1]) == [True, False]
    assert kwargs.get("unit") == 1


@pytest.mark.usefixtures("script_registry_and_engine")
def test_warmup_session_triggers_warm_mode_and_completion_callback(mgr, mock_client):
    """needs_warmup 首次进入：启动预热脚本，tick 后应完成并 has_warmup=True。"""
    from auto_control_script_engine import get_script_engine
    import auto_control_script_engine as ace_mod

    ctx = _build_ctx_with_coils_client(mgr, mock_client)
    mock_client.reset_mock()

    mgr.reset_warmup_flags()
    mgr.warm_up_with_water()

    clock = [0.0]

    def fake_mono():
        return clock[0]

    with patch.object(ace_mod.time, "monotonic", side_effect=fake_mono):
        mgr._warmup_phase(ctx)
        mock_client.write_coils.assert_called()
        args, _ = mock_client.write_coils.call_args
        assert list(args[1]) == [True, True]

        clock[0] = 1.0
        mgr._tick_script_engine(ctx)

    with mgr._state_lock:
        assert mgr._has_warmup is True

    eng = get_script_engine()
    assert eng._active_hook is None


@pytest.mark.usefixtures("script_registry_and_engine")
def test_new_alarm_interrupts_previous_script(mgr, mock_client, script_registry_and_engine):
    """状态机再次触发 run_on_alarm_on 时应打断引擎中未跑完的长脚本并重新从 MODE_ALARM 开始。"""
    from auto_control_script_engine import get_script_engine
    from auto_control_context import AutoControlContext

    eng, reg = script_registry_and_engine
    prev = list(reg.hook_steps.get("run_on_alarm_on", []))
    reg.hook_steps["run_on_alarm_on"] = [
        ("MODE_ALARM", 3600.0),
        ("MODE_READY", 1.0),
    ]
    try:
        ctx = AutoControlContext(
            settings=mgr._settings,
            modbus_client=mock_client,
                coils_modbus_client=mock_client,
                modbus_host="localhost",
                modbus_port=5020,
                coils_modbus_host="192.168.1.10",
                coils_modbus_port=502,
            modbus_unit_id=1,
            monitor_register=1,
            get_cds350_device=mgr._get_cds350_device,
        )
        mock_client.reset_mock()
        eng.start("run_on_alarm_on", ctx)
        assert mock_client.write_coils.call_count >= 1

        mock_client.reset_mock()
        mgr._is_alarming = True
        mgr._has_run_alarm_on = False
        mgr._apply_state_machine(ctx, 0)

        mock_client.write_coils.assert_called()
        args, kwargs = mock_client.write_coils.call_args
        assert list(args[1]) == [True, False]
        assert eng._active_hook == "run_on_alarm_on"
        assert eng._applied_count == 1
    finally:
        reg.hook_steps["run_on_alarm_on"] = prev
