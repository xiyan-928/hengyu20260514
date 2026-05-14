"""
Mock 模式端到端测试：通过 FastAPI TestClient 调用真实路由（无独立起服务进程）。

运行（在 HY_Online 目录下，需安装 pytest、httpx）:
    conda run -n ftapi pytest tests/test_e2e_mock.py -v

或:
    pytest tests/test_e2e_mock.py -v
"""
from __future__ import annotations

import pytest


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True


def test_device_mode_info_is_mock(client):
    """确认当前为模拟设备模式（依赖 conftest 中 DEVICE_MODE=mock）。"""
    r = client.get("/device-mode")
    assert r.status_code == 200
    data = r.json().get("data") or {}
    assert data.get("is_mock") is True
    assert data.get("mode") == "mock"


@pytest.mark.usefixtures("restore_auto_control_settings")
def test_cds350_initialize_and_spectrum_mock(client):
    r = client.post("/cds350/initialize")
    assert r.status_code == 200, r.text
    r2 = client.get("/cds350/spectrum", params={"force_new": True})
    assert r2.status_code == 200, r2.text
    data = r2.json().get("data") or {}
    assert "wavelengths" in data
    assert "spectrum" in data


@pytest.mark.usefixtures("restore_auto_control_settings")
def test_manual_monitor_syncs_start_sensor_sample_flag(client):
    """
    自动控制关闭时：启动/停止传感器监控应同步 start_sensor_sample（见 main.py）。
    """
    from Devices.device_settings import DeviceSettings

    ds = DeviceSettings.instance()
    ds.update_config({"auto_control": {"enabled": False}})

    st = client.get("/auto-control/status").json().get("data") or {}
    assert st.get("start_sensor_sample") is False

    r = client.post(
        "/hy-device/monitor/control",
        json={"action": "start", "interval": 2.0},
    )
    assert r.status_code == 200, r.text
    st2 = client.get("/auto-control/status").json().get("data") or {}
    assert st2.get("start_sensor_sample") is True

    r2 = client.post(
        "/hy-device/monitor/control",
        json={"action": "stop", "interval": 2.0},
    )
    assert r2.status_code == 200
    st3 = client.get("/auto-control/status").json().get("data") or {}
    assert st3.get("start_sensor_sample") is False


@pytest.mark.usefixtures("restore_auto_control_settings")
def test_manual_spectrum_force_new_toggles_start_spec_flag(client):
    """自动控制关闭且 force_new 时，应短暂置位 start_spec_sample。"""
    from Devices.device_settings import DeviceSettings

    ds = DeviceSettings.instance()
    ds.update_config({"auto_control": {"enabled": False}})

    client.post("/cds350/initialize")
    client.get("/cds350/spectrum", params={"force_new": True})
    st = client.get("/auto-control/status").json().get("data") or {}
    assert st.get("start_spec_sample") is False


@pytest.mark.usefixtures("restore_auto_control_settings")
def test_auto_control_status_fields_when_enabled(client):
    from Devices.device_settings import DeviceSettings

    ds = DeviceSettings.instance()
    ds.update_config({"auto_control": {"enabled": True}})

    st = client.get("/auto-control/status").json().get("data") or {}
    for key in (
        "is_alarm_on",
        "is_auto_run",
        "auto_run_ready",
        "start_spec_sample",
        "start_sensor_sample",
        "has_run_alarm_on",
        "has_warmup",
        "needs_warmup",
    ):
        assert key in st, f"missing {key} in {st}"
