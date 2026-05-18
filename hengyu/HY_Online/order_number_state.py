"""单号下发与文件夹规划：在 HY_Online 与 HY_APP 之间充当持久化状态层。

来源优先级（高 -> 低）：
1. 来自 HY_Server 的下发值（``server_value``，由 upload_client_example 轮询写入）。**只要有非空下发，即覆盖手改**
   （写入时清除 ``manual_value``；轮询结果与当前 server 相同时也会清除残留手改）。
2. 来自 HY_APP 手动输入的值（``POST /api/order-number/manual``）；仅当 **服务器尚无单号** 时作为生效单号。
   手改后会将当前生效单号同步到 HY_Server（环境变量 ``HY_SERVER_UPLOAD_BASE`` / ``UPLOAD_BASE``，
   缺省 ``http://127.0.0.1:8001``），以便 ``_upload_spc`` 归档重命名；响应含 ``hy_server_sync``。
3. 占位值「未获取」。

**生产结束**时由 HY_Online 调用 ``POST /api/order-number/production-end``，清除 server 与 manual，
前端恢复占位；HY_Server 侧 ``POST /device/{id}/production-end`` 同步清工艺缓存与下发单号。

每次「生效单号」变化时，按 `{device_id}/{YYYY}/{MM}/{DD}/{order_number}` 落盘创建空目录，
方便外部脚本/工厂在该目录下归档当日数据；目录根为 `_order_data/`，与现有
`_uploaded_spc/`、`_uploaded_device_data/` 同级。

服务端临时 SPC 落盘目录名（``HY_SPC_TEMP_DIR`` 下的一级子目录）采用
``{设备号}_{yyyy年MM月dd日}_{单号}``（各段经 `_safe_segment` 清洗），见 `spectrum_archive_folder_name()`。

状态文件 `_order_number_state.json` 在主服务重启后自动恢复。线程安全：所有公开 API
共享一把 ``threading.Lock``，写入磁盘前必须持有该锁，避免轮询线程与 FastAPI 协程竞争。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PLACEHOLDER = "未获取"

_ROOT = Path(__file__).resolve().parent
_STATE_FILE = _ROOT / "_order_number_state.json"
_ORDER_DATA_DIR = _ROOT / "_order_data"
_ORDER_DATA_DIR.mkdir(parents=True, exist_ok=True)

_INVALID_FS_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_lock = threading.Lock()
_device_id: str = ""
_server_value: Optional[str] = None
_manual_value: Optional[str] = None
_last_folder: Optional[str] = None
# 无真实单号时用于区分「又一锅」光谱临时目录；每次生产结束清除单号时刷新
_placeholder_dir_slot: Optional[str] = None


def _safe_segment(text: str, fallback: str = PLACEHOLDER) -> str:
    """将任意字符串转为可作为目录名的安全段；非法字符替换为 ``_``。"""
    raw = str(text or "").strip()
    if not raw:
        return fallback
    cleaned = _INVALID_FS_CHARS_RE.sub("_", raw).strip(" .")
    if len(cleaned) > 180:
        cleaned = cleaned[:180]
    return cleaned or fallback


def _normalize_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _effective_value_locked() -> str:
    if _server_value:
        return _server_value
    if _manual_value:
        return _manual_value
    return PLACEHOLDER


def _effective_source_locked() -> str:
    if _server_value:
        return "server"
    if _manual_value:
        return "manual"
    return "placeholder"


def _load_state_locked() -> None:
    """假定调用方已持锁。状态文件不存在或损坏时静默回退到空值。"""
    global _device_id, _server_value, _manual_value, _last_folder, _placeholder_dir_slot
    if not _STATE_FILE.exists():
        return
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取单号状态失败 %s: %s", _STATE_FILE, e)
        return
    if not isinstance(data, dict):
        return
    _device_id = str(data.get("device_id") or "")
    _server_value = _normalize_value(data.get("server_value"))
    _manual_value = _normalize_value(data.get("manual_value"))
    _last_folder = data.get("last_folder") or None
    slot = data.get("placeholder_dir_slot")
    _placeholder_dir_slot = str(slot).strip() if slot else None
    # 与「服务器覆盖手改」一致：磁盘上若两者曾并存，以服务器为准并丢掉陈旧手改
    if _server_value and _manual_value:
        _manual_value = None
        _save_state_locked()


def _save_state_locked() -> None:
    """假定调用方已持锁，原子写入以避免半文件。"""
    payload = {
        "device_id": _device_id,
        "server_value": _server_value,
        "manual_value": _manual_value,
        "last_folder": _last_folder,
        "placeholder_dir_slot": _placeholder_dir_slot,
    }
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STATE_FILE)
    except OSError as e:
        logger.warning("写入单号状态失败 %s: %s", _STATE_FILE, e)


def _order_seg_for_archive_locked() -> str:
    """光谱与 _order_data 共用末段：占位且存在 slot 时用 ``未获取_{slot}`` 区分每锅。"""
    eff = _effective_value_locked()
    if eff == PLACEHOLDER and _placeholder_dir_slot:
        return _safe_segment(f"{PLACEHOLDER}_{_placeholder_dir_slot}", PLACEHOLDER)
    return _safe_segment(eff, PLACEHOLDER)


def _spectrum_archive_folder_name_locked(
    now: Optional[datetime.datetime] = None,
) -> str:
    """光谱临时归档目录名：设备号_yyyy年MM月dd日_单号（假定已持锁）。"""
    now = now or datetime.datetime.now()
    device_seg = _safe_segment(_device_id, PLACEHOLDER)
    order_seg = _order_seg_for_archive_locked()
    date_seg = f"{now.year}年{now.month:02d}月{now.day:02d}日"
    return f"{device_seg}_{date_seg}_{order_seg}"


def spectrum_archive_folder_name(
    now: Optional[datetime.datetime] = None,
) -> str:
    """当前会话在 ``HY_SPC_TEMP_DIR`` 下的子目录名：``设备号_yyyy年MM月dd日_单号``。"""
    with _lock:
        return _spectrum_archive_folder_name_locked(now)


def _ensure_folder_locked(now: Optional[datetime.datetime] = None) -> str:
    """按当前生效单号创建 `{device}/{年}/{月}/{日}/{单号}` 目录，返回绝对路径。

    日期取系统时间；月/日补零（``05`` 而非 ``5``）。若 ``device_id`` 尚未设置，使用
    占位值，避免阻塞调用方。``_last_folder`` 用于在 ``snapshot()`` 中暴露当前目录。
    """
    global _last_folder
    now = now or datetime.datetime.now()
    device_seg = _safe_segment(_device_id, PLACEHOLDER)
    order_seg = _order_seg_for_archive_locked()
    rel = Path(device_seg) / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}" / order_seg
    folder = _ORDER_DATA_DIR / rel
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("创建单号目录失败 %s: %s", folder, e)
    _last_folder = str(folder)
    return _last_folder


# 模块加载时即恢复磁盘状态，保证主服务重启不丢失最新单号
with _lock:
    _load_state_locked()


def configure_device_id(device_id: str) -> None:
    """主服务启动时调用一次以注入设备号（来源：环境变量 / 配置 / hy 设备元数据）。"""
    global _device_id, _placeholder_dir_slot
    safe = str(device_id or "").strip()
    if not safe:
        return
    with _lock:
        if safe == _device_id:
            return
        _device_id = safe
        _placeholder_dir_slot = None
        _save_state_locked()
        _ensure_folder_locked()
    logger.info("order_number_state: device_id=%s", safe)


def get_device_id() -> str:
    with _lock:
        return _device_id


def set_server_value(value: Any) -> Dict[str, Any]:
    """轮询写入 HY_Server 下发的单号；空值视为清除。

    非空下发会 **清除手动单号**（覆盖手改）。若本次轮询值与已缓存 server 相同，仍会清除残留 ``manual_value``，
    保证与服务器对齐。
    """
    global _server_value, _manual_value, _placeholder_dir_slot
    normalized = _normalize_value(value)
    with _lock:
        if normalized == _server_value:
            if normalized and _manual_value is not None:
                _manual_value = None
                _save_state_locked()
                _ensure_folder_locked()
            return _snapshot_locked()
        _server_value = normalized
        if normalized:
            _manual_value = None
            _placeholder_dir_slot = None
        _save_state_locked()
        _ensure_folder_locked()
        return _snapshot_locked()


def set_manual_value(value: Any) -> Dict[str, Any]:
    """App 手动输入单号写入此处；为空字符串/None 时等价于清除。"""
    global _manual_value, _placeholder_dir_slot
    normalized = _normalize_value(value)
    with _lock:
        if normalized == _manual_value:
            return _snapshot_locked()
        _manual_value = normalized
        if normalized:
            _placeholder_dir_slot = None
        _save_state_locked()
        _ensure_folder_locked()
        return _snapshot_locked()


def clear_manual_value() -> Dict[str, Any]:
    return set_manual_value(None)


def clear_for_production_end() -> Dict[str, Any]:
    """生产结束：清除服务器镜像与手动单号，并刷新占位目录槽（又一锅用新临时目录）。"""
    global _server_value, _manual_value, _placeholder_dir_slot
    with _lock:
        _server_value = None
        _manual_value = None
        _placeholder_dir_slot = uuid.uuid4().hex[:12]
        _save_state_locked()
        _ensure_folder_locked()
        return _snapshot_locked()


def ensure_folder() -> str:
    """外部模块可调用以确保当日目录存在（例如日切换时主动调用）。"""
    with _lock:
        return _ensure_folder_locked()


def _snapshot_locked() -> Dict[str, Any]:
    return {
        "device_id": _device_id,
        "server_value": _server_value,
        "manual_value": _manual_value,
        "effective": _effective_value_locked(),
        "source": _effective_source_locked(),
        "placeholder": PLACEHOLDER,
        "placeholder_dir_slot": _placeholder_dir_slot,
        "folder": _last_folder,
        "spectrum_archive_folder": _spectrum_archive_folder_name_locked(),
    }


def snapshot() -> Dict[str, Any]:
    """返回当前完整状态，供 FastAPI 接口与轮询线程一并使用。"""
    with _lock:
        return _snapshot_locked()
