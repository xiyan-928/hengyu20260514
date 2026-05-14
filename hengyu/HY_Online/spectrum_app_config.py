"""
光谱应用独立配置：项目根目录、光源 Modbus（含 mock/real）。
持久化文件：HY_Online/spectrum_app_config.json
环境变量可覆盖：SPECTRUM_PROJECT_ROOT、LIGHT_SOURCE_MODE（mock|real）
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

_CONFIG_PATH = Path(__file__).resolve().parent / "spectrum_app_config.json"
_lock = threading.Lock()

_DEFAULT: Dict[str, Any] = {
    "project_root": "",
    "light_source": {
        "mode": "mock",
        "host": "127.0.0.1",
        "port": 502,
        "unit": 1,
        "address": 0,
    },
}


def _deep_merge_light(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        out[k] = v
    return out


def _load_raw_file() -> Dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {}
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _merge_with_env(data: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**_DEFAULT, **{k: v for k, v in data.items() if k != "light_source"}}
    merged["light_source"] = _deep_merge_light(
        _DEFAULT["light_source"], data.get("light_source") or {}
    )
    if os.getenv("SPECTRUM_PROJECT_ROOT") is not None:
        merged["project_root"] = os.environ["SPECTRUM_PROJECT_ROOT"].strip()
    mode = os.getenv("LIGHT_SOURCE_MODE", "").strip().lower()
    if mode in ("mock", "real"):
        merged["light_source"]["mode"] = mode
    return merged


def load_config() -> Dict[str, Any]:
    with _lock:
        data = _load_raw_file()
        return _merge_with_env(data)


def save_config(update: Dict[str, Any]) -> Dict[str, Any]:
    """合并写入磁盘后返回最新配置（含环境变量覆盖后的视图）。仅把用户数据写入 JSON，不写 env 覆盖。"""
    with _lock:
        data = _load_raw_file()
        stored = {**_DEFAULT, **{k: v for k, v in data.items() if k != "light_source"}}
        stored["light_source"] = _deep_merge_light(
            _DEFAULT["light_source"], data.get("light_source") or {}
        )
        for k, v in update.items():
            if k == "light_source" and isinstance(v, dict):
                stored["light_source"] = _deep_merge_light(stored["light_source"], v)
            elif k == "project_root":
                stored["project_root"] = v
            else:
                stored[k] = v
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"project_root": stored["project_root"], "light_source": stored["light_source"]},
                f,
                ensure_ascii=False,
                indent=2,
            )
        return _merge_with_env(_load_raw_file())
