"""
pytest 入口：必须在导入 main 之前固定为 mock 模式。
"""
from __future__ import annotations

import copy
import os

# 端到端与集成测试默认使用模拟设备（与 start.py 一致）
os.environ.setdefault("DEVICE_MODE", "mock")

import pytest


@pytest.fixture
def client():
    """FastAPI TestClient，会触发 lifespan（含 AutoControlManager.start）。"""
    from fastapi.testclient import TestClient
    from main import app

    # raise_server_exceptions=True 便于定位路由内异常
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def restore_auto_control_settings():
    """保存并恢复 auto_control 配置，避免 E2E 改写 device_config.json 后影响本地开发。"""
    from Devices.device_settings import DeviceSettings

    ds = DeviceSettings.instance()
    before = copy.deepcopy(ds.get_auto_control_settings())
    yield
    ds.update_config({"auto_control": before})
