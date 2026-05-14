"""
自动控制脚本化逻辑单元测试：报警边沿、自动状态机、手动标志。

运行（在 HY_Online 目录下）:
    conda run -n ftapi python -m unittest discover -s tests -p "test_auto_control_scripting.py" -v
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 保证从 HY_Online 根目录导入
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auto_control_context import AutoControlContext
from auto_control_manager import AutoControlManager


class TestAlarmEdgeAndRunOn(unittest.TestCase):
    """1. 报警：run_on_alarm_on 仅在报警上升沿调用一次"""

    @patch("auto_control_manager.run_on_alarm_off")
    @patch("auto_control_manager.run_on_alarm_on")
    def test_run_on_alarm_on_called_once_per_edge(self, mock_run_on, mock_run_off):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})

        mgr._is_alarming = True
        mgr._has_run_alarm_on = False
        mgr._apply_state_machine(ctx, 0)
        mock_run_on.assert_called_once()
        mock_run_off.assert_not_called()

        mgr._apply_state_machine(ctx, 0)
        mock_run_on.assert_called_once()
        mock_run_off.assert_not_called()

    @patch("auto_control_manager.run_on_alarm_off")
    @patch("auto_control_manager.run_on_alarm_on")
    def test_alarm_clear_allows_next_edge(self, mock_run_on, mock_run_off):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})

        mgr._is_alarming = True
        mgr._has_run_alarm_on = False
        mgr._apply_state_machine(ctx, 0)
        self.assertTrue(mgr._has_run_alarm_on)
        mock_run_on.assert_called_once()
        mock_run_off.assert_not_called()

        mgr._is_alarming = False
        mgr._apply_state_machine(ctx, 0)
        self.assertFalse(mgr._has_run_alarm_on)
        self.assertTrue(mgr._has_run_alarm_off)
        mock_run_off.assert_called_once()

        mgr._is_alarming = True
        mgr._apply_state_machine(ctx, 0)
        self.assertEqual(mock_run_on.call_count, 2)

    @patch("auto_control_manager.run_on_alarm_off")
    @patch("auto_control_manager.run_on_alarm_on")
    def test_run_on_alarm_off_called_once_per_falling_edge(self, mock_run_on, mock_run_off):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})

        mgr._is_alarming = True
        mgr._apply_state_machine(ctx, 0)
        mock_run_on.assert_called_once()

        mgr._is_alarming = False
        mgr._apply_state_machine(ctx, 0)
        mock_run_off.assert_called_once()

        mgr._apply_state_machine(ctx, 0)
        mock_run_off.assert_called_once()


class TestAutoControlStateMachine(unittest.TestCase):
    """2. 自动控制：is_auto_run、就绪与 _is_action_active 门控"""

    @patch("auto_control_manager.run_on_autorun_batch_finish")
    @patch("auto_control_manager.run_on_get_ready_for_autorun")
    def test_batch_finish_called_once_on_falling_edge(self, mock_ready, mock_finish):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._is_alarming = False
        mgr._auto_run_ready = False

        mgr._apply_state_machine(ctx, 1)
        mock_ready.assert_called_once()
        mock_finish.assert_not_called()

        mgr._apply_state_machine(ctx, 0)
        mock_finish.assert_called_once()
        mgr._apply_state_machine(ctx, 0)
        mock_finish.assert_called_once()

    @patch("auto_control_manager.run_on_get_ready_for_autorun")
    def test_get_ready_called_when_auto_run_and_not_ready(self, mock_ready):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._is_alarming = False
        mgr._auto_run_ready = False
        mgr._is_action_active = False

        mgr._apply_state_machine(ctx, 1)
        mock_ready.assert_called_once()
        self.assertTrue(mgr._auto_run_ready)

    def test_auto_sample_flags_when_action_active_and_no_alarm(self):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._is_alarming = False
        mgr._is_action_active = True
        mgr._auto_run_ready = True

        mgr._apply_state_machine(ctx, 1)
        with mgr._state_lock:
            self.assertTrue(mgr._start_spec_sample)
            self.assertTrue(mgr._start_sensor_sample)

    def test_alarm_blocks_auto_sample_flags_even_if_action_active(self):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._is_alarming = True
        mgr._is_action_active = True
        mgr._auto_run_ready = True

        mgr._apply_state_machine(ctx, 1)
        with mgr._state_lock:
            self.assertFalse(mgr._start_spec_sample)
            self.assertFalse(mgr._start_sensor_sample)

    @patch("auto_control_manager.run_on_autorun_batch_finish")
    def test_val_zero_clears_auto_ready_and_samples(self, mock_finish):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._is_alarming = False
        mgr._auto_run_ready = True
        mgr._is_action_active = True
        mgr._apply_state_machine(ctx, 1)
        with mgr._state_lock:
            self.assertTrue(mgr._start_spec_sample)

        mgr._apply_state_machine(ctx, 0)
        mock_finish.assert_called_once()
        self.assertFalse(mgr._auto_run_ready)
        with mgr._state_lock:
            self.assertFalse(mgr._start_spec_sample)
            self.assertFalse(mgr._start_sensor_sample)


class TestManualSampleFlags(unittest.TestCase):
    """3. 手动：仅 auto_control.enabled=False 时 set_manual_sample_flags 生效"""

    def test_manual_sets_flags_when_auto_disabled(self):
        mgr = AutoControlManager(lambda: None)
        with patch.object(
            mgr._settings,
            "get_auto_control_settings",
            return_value={"enabled": False},
        ):
            mgr.set_manual_sample_flags(start_spec=True, start_sensor=True)
        with mgr._state_lock:
            self.assertTrue(mgr._start_spec_sample)
            self.assertTrue(mgr._start_sensor_sample)

    def test_manual_ignored_when_auto_enabled(self):
        mgr = AutoControlManager(lambda: None)
        mgr._start_spec_sample = False
        mgr._start_sensor_sample = False
        with patch.object(
            mgr._settings,
            "get_auto_control_settings",
            return_value={"enabled": True},
        ):
            mgr.set_manual_sample_flags(start_spec=True, start_sensor=True)
        with mgr._state_lock:
            self.assertFalse(mgr._start_spec_sample)
            self.assertFalse(mgr._start_sensor_sample)

    def test_manual_stop_sensor_sets_fan_speed_zero(self):
        mgr = AutoControlManager(lambda: None)
        fake_sdm = MagicMock()
        fake_sdm.get_fan_speed.return_value = 0
        with patch.object(
            mgr._settings,
            "get_auto_control_settings",
            return_value={"enabled": False},
        ), patch("auto_control_manager.SensorDataManager.instance", return_value=fake_sdm):
            mgr.set_manual_sample_flags(start_sensor=False)
        fake_sdm.set_fan_speed_to_zero.assert_called_once_with(reason="manual_sensor_stop")


class TestWarmupPhase(unittest.TestCase):
    """预热：_warmup_phase 在自动控制信号查询前"""

    @patch("auto_control_manager.run_on_warmup")
    def test_has_warmup_clears_needs_no_run(self, mock_run):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._has_warmup = True
        mgr._needs_warmup = True
        mgr._warmup_phase(ctx)
        mock_run.assert_not_called()
        with mgr._state_lock:
            self.assertFalse(mgr._needs_warmup)

    @patch("auto_control_manager.run_on_warmup")
    def test_needs_warmup_calls_run_on_warmup(self, mock_run):
        mgr = AutoControlManager(lambda: None)
        ctx = mgr._build_context(None, {"unit_id": 1, "monitor_register": 1})
        mgr._has_warmup = False
        mgr._needs_warmup = True
        mgr._warmup_phase(ctx)
        mock_run.assert_called_once()

    def test_warm_up_with_water_and_no_action(self):
        mgr = AutoControlManager(lambda: None)
        mgr.reset_warmup_flags()
        mgr.warm_up_with_water()
        with mgr._state_lock:
            self.assertTrue(mgr._needs_warmup)
            self.assertFalse(mgr._has_warmup)
        mgr.warm_up_no_action()
        with mgr._state_lock:
            self.assertTrue(mgr._has_warmup)


class TestConnectionSelection(unittest.TestCase):
    def test_build_context_exposes_separate_coils_endpoint(self):
        mgr = AutoControlManager(lambda: None)
        with patch.object(
            mgr._settings,
            "get_modbus_coils_endpoint",
            return_value=("192.168.1.10", 502),
        ):
            ctx = mgr._build_context(None, {"modbus_host": "localhost", "modbus_port": 5020})

        self.assertEqual(ctx.modbus_host, "localhost")
        self.assertEqual(ctx.modbus_port, 5020)
        self.assertEqual(ctx.coils_modbus_host, "192.168.1.10")
        self.assertEqual(ctx.coils_modbus_port, 502)

    @patch("auto_control_manager.time.sleep", side_effect=lambda _: None)
    @patch("auto_control_manager.ModbusTcpClient")
    def test_run_does_not_connect_signal_source_when_auto_control_disabled(self, mock_client_cls, _mock_sleep):
        mgr = AutoControlManager(lambda: None)
        mgr._running = True

        def stop_after_tick(ctx):
            mgr._running = False

        with patch.object(
            mgr._settings,
            "get_auto_control_settings",
            return_value={"enabled": False, "modbus_host": "localhost", "modbus_port": 5020, "poll_interval": 0.0},
        ), patch.object(mgr, "_refresh_alarm_state"), patch.object(mgr, "_warmup_phase"), patch.object(
            mgr, "_tick_script_engine", side_effect=stop_after_tick
        ), patch.object(mgr, "_update_fan_from_sdm"):
            mgr._run()

        mock_client_cls.assert_not_called()

    @patch("auto_control_manager.time.sleep", side_effect=lambda _: None)
    @patch("auto_control_manager.ModbusTcpClient")
    def test_run_connects_signal_source_when_auto_control_enabled(self, mock_client_cls, _mock_sleep):
        mgr = AutoControlManager(lambda: None)
        mgr._running = True
        client = MagicMock()
        client.connect.return_value = True
        mock_client_cls.return_value = client

        def stop_after_tick(ctx):
            mgr._running = False

        with patch.object(
            mgr._settings,
            "get_auto_control_settings",
            return_value={"enabled": True, "modbus_host": "localhost", "modbus_port": 5020, "poll_interval": 0.0},
        ), patch("auto_control_manager.get_autocontrol_message", return_value=0), patch.object(
            mgr, "_refresh_alarm_state"
        ), patch.object(mgr, "_warmup_phase"), patch.object(
            mgr, "_apply_state_machine"
        ), patch.object(
            mgr, "_process_signal"
        ), patch.object(
            mgr, "_data_acquisition_phase"
        ), patch.object(
            mgr, "_update_fan_from_sdm"
        ), patch.object(
            mgr, "_tick_script_engine", side_effect=stop_after_tick
        ):
            mgr._run()

        mock_client_cls.assert_called_once_with("localhost", port=5020, timeout=2.0)
        client.connect.assert_called()


class TestGetAutocontrolMessage(unittest.TestCase):
    """Modbus 读 0/1"""

    def test_returns_one_when_register_is_one(self):
        from auto_control_func import get_autocontrol_message
        from Devices.device_settings import DeviceSettings

        client = MagicMock()
        rr = MagicMock()
        rr.isError.return_value = False
        rr.registers = [1]
        client.read_holding_registers.return_value = rr

        ctx = AutoControlContext(
            settings=DeviceSettings.instance(),
            modbus_client=client,
            modbus_unit_id=1,
            monitor_register=1,
        )
        self.assertEqual(get_autocontrol_message(ctx), 1)

    def test_returns_zero_when_client_none(self):
        from auto_control_func import get_autocontrol_message
        from Devices.device_settings import DeviceSettings

        ctx = AutoControlContext(
            settings=DeviceSettings.instance(),
            modbus_client=None,
        )
        self.assertEqual(get_autocontrol_message(ctx), 0)


if __name__ == "__main__":
    unittest.main()
