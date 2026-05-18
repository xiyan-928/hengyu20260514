"""
独立 HTTP 接收端：
- 接收与监控接口 `data` 快照一致（get_snapshot 形状）的设备数据，并保留 device_id。
  每条上送追加至 _upload_spc/{设备号_yyyy年MM月dd日_单号}/SENSOR.csv（与 raw/dark/blank 同级；不再单独使用 _uploaded_device_data，旧目录仅兼容读取）。
- 接收来自主服务转换后的 .spc 文件，统一保存到 _upload_spc/{设备号_yyyy年MM月dd日_单号}/{raw|dark|blank}/。
  （兼容旧版目录 _upload_spc/{设备}/{单号}/...，启动时仍会索引。）
- 接收来自客户端上报的暗光谱与参比光谱（blank_before / blank_after）.spc 文件。

生产切换与单号缓存（避免继续写入上一生产的目录）：
- 归档目录为 ``{设备}_{yyyy年MM月dd日}_{单号}``；**单号**来自 POST /upload 补齐后的 ``generation_batch``，
  以及 SPC 上传表单 ``batch``（缺省时读该设备工艺缓存）。
- **推荐**：新生产**第一条**上送即带**新** ``generation_batch``，缓存更新后数据自动进入新单号目录。
- **本锅结束、新单号未到**：发一条 **显式**含 ``"generation_batch": ""`` 或 ``null`` 的 /upload，服务端会
  **清除**缓存中的单号，后续写入 ``…__no_batch``；新单号到达后再上送，并可触发无单号目录**重命名**。
- **边缘端「自动控制停止」**：HY_Online 可在监视寄存器 **1→0** 或 **自动控制 enabled 关闭** 时调用
  ``POST /device/{device_id}/production-end``，与上述空 ``generation_batch`` 上送等效，并**同时清除**
  该设备的 ``/order_number`` 下发映射，便于前端与边缘恢复为「未获取」。
- **目录末段单号**：已知单号则目录名为 ``…_{单号}``；未知则为 ``…__no_batch``（或带递增序号的 ``…__no_batch_{0001}``，存在
  ``_process_aux.json`` 的 ``no_batch_seq`` 中；每次 **本锅结束**或显式清空 ``generation_batch`` 后递增，避免同日下一锅仍写入上一锅无单号目录）。
- **同日且单号字符串与上一锅完全相同**仍要并列多目录：请在业务上区分单号（如 PO123-2），当前命名不含独立「锅次」段。

在 HY_Server 目录下执行: python test1.py
"""
from __future__ import annotations

import csv
from datetime import datetime, date as date_type
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

# ---- 日志配置：同时输出到终端和按日期滚动的日志文件 ----
_LOG_DIR = Path(__file__).resolve().parent / "_logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / f"test1_{time.strftime('%Y%m%d')}.log"

_LOG_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FMT,
    datefmt=_DATE_FMT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("test1")

# uvicorn 专属日志配置（同样写入同一文件）
_UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": _LOG_FMT, "datefmt": _DATE_FMT},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
        "file": {
            "class": "logging.FileHandler",
            "filename": str(_LOG_FILE),
            "encoding": "utf-8",
            "formatter": "default",
        },
    },
    "loggers": {
        "uvicorn":        {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "uvicorn.error":  {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
    },
}

from edge_device_data import DeviceData
from read_spc_plot import read_spc_file

device_store: Dict[str, List[dict]] = {}
spc_store: Dict[str, List[dict]] = {}
# blank_spc_store[device_id][blank_type] = list of record dicts
blank_spc_store: Dict[str, Dict[str, List[dict]]] = {}
dark_spc_store: Dict[str, List[dict]] = {}

SPC_STORE_DIR = Path(__file__).resolve().parent / "_upload_spc"
SPC_STORE_DIR.mkdir(parents=True, exist_ok=True)
BLANK_SPC_STORE_DIR = SPC_STORE_DIR
UPDATE_STORE_DIR = Path(__file__).resolve().parent / "_updates"
UPDATE_STORE_DIR.mkdir(parents=True, exist_ok=True)
# 传感器 CSV 与光谱共用 _upload_spc/{设备_yyyy年MM月dd日_单号}/；历史数据可读 _uploaded_device_data（不再自动创建）。
LEGACY_SENSOR_DATA_DIR = Path(__file__).resolve().parent / "_uploaded_device_data"
# 归档目录根部单一传感器文件（与 raw/dark/blank 子目录并列）
_SENSOR_ARCHIVE_CSV = "SENSOR.csv"
_DEVICE_FILE_LOCK = threading.Lock()
_ARCHIVE_RENAME_LOCK = threading.Lock()
_INVALID_BATCH_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# 单号下发：服务端按 device_id 维护当前生效单号，客户端通过 GET 拉取。
# 数据落盘到 _order_numbers.json，重启后保留；空字符串/None 视为清除。
_ORDER_NUMBER_FILE = Path(__file__).resolve().parent / "_order_numbers.json"
_order_numbers: Dict[str, str] = {}
_order_numbers_lock = threading.Lock()

# 工艺/单号参数：客户端只在首次上送时携带，服务端按 device_id 缓存，
# 后续每条 /upload 写盘前自动用缓存补齐缺失字段。
_PROCESS_PARAM_KEYS: Tuple[str, ...] = (
    "generation_batch",
    "fabric_weight_g",
    "fabric_length",
    "fabric_width",
    "fabric_height",
    "fabric_thickness",
    "fabric_density",
    "fabric_material",
    "bath_ratio",
)
_process_cache: Dict[str, Dict[str, Any]] = {}
_process_cache_lock = threading.Lock()
# 持久化：无单号目录槽 + 一锅结束后抑制从 SENSOR CSV 回放 generation_batch（避免重启后旧单号又回到缓存、同日 __no_batch 目录复用）
_PROCESS_AUX_FILE = Path(__file__).resolve().parent / "_process_aux.json"
_process_aux_lock = threading.Lock()

# CSV 文件结构：
#   第 1 行 — 本单号的工艺参数，每个单元格形如 "key=value"
#   第 2 行 — 传感器表头（_SENSOR_CSV_FIELDS）
#   第 3 行起 — 传感器数据
_SENSOR_CSV_FIELDS: Tuple[str, ...] = (
    "server_time",
    "device_id",
    "ddl",
    "ph",
    "ph_temp",
    "pt100",
    "valves",
    "is_alarming",
    "fan_speed",
    "fan_read_ok",
    "running",
    "interval",
    "temperature",
    "level",
    "bridge_state",
)
_SENSOR_CSV_BOOL_FIELDS = {"is_alarming", "fan_read_ok", "running"}
_SENSOR_CSV_INT_FIELDS = {"fan_speed"}
_SENSOR_CSV_FLOAT_FIELDS = {
    "ddl", "ph", "ph_temp", "pt100",
    "interval", "temperature", "level",
}
_PROCESS_FLOAT_FIELDS = {
    "fabric_weight_g", "fabric_length", "fabric_width", "fabric_height",
    "fabric_thickness", "fabric_density", "bath_ratio",
}

_ALLOWED_BLANK_TYPES = {"blank_before", "blank_after"}
_ALLOWED_SPC_KINDS = {"raw", "dark", "blank"}

# 新版归档目录名中的日期段：中文「yyyy年MM月dd日」；兼容历史 ``_YYYYMMDD_`` 纯数字目录
_SPC_ARCHIVE_DATE_RE = re.compile(
    r"_((?:\d{4}年\d{2}月\d{2}日|\d{8}))_"
)


def _spc_date_segment_cn(when: datetime) -> str:
    """用于目录名、文件名中的日期段：yyyy年MM月dd日（固定两位月日）。"""
    return f"{when.year}年{when.month:02d}月{when.day:02d}日"


def _spc_upload_archive_folder_name(
    safe_device_id: str, safe_batch: str, when: datetime
) -> str:
    """上传 SPC 归档目录名：设备号_yyyy年MM月dd日_单号。"""
    return f"{safe_device_id}_{_spc_date_segment_cn(when)}_{safe_batch}"


def _parse_spc_archive_folder_name(folder_name: str) -> Optional[Tuple[str, str]]:
    """从归档目录名解析 (device_id, batch)；失败返回 None。"""
    m = _SPC_ARCHIVE_DATE_RE.search(folder_name)
    if not m:
        return None
    device_id = folder_name[: m.start()].strip("_") or ""
    batch = folder_name[m.end() :].lstrip("_") or ""
    if not device_id or not batch:
        return None
    return device_id, batch


def _rewrite_stored_paths_after_archive_rename(
    old_root: Path, new_root: Path, new_batch: str
) -> None:
    """SPC 内存索引中路径与 batch 随归档根目录重命名而更新。"""
    try:
        old_r = old_root.resolve()
        new_r = new_root.resolve()
    except OSError:
        return
    old_base = str(old_r)
    old_prefix = old_base + os.sep

    def touch(rec: dict) -> None:
        p = rec.get("path")
        if not isinstance(p, str):
            return
        try:
            resolved = Path(p).resolve()
        except (OSError, RuntimeError):
            return
        s = str(resolved)
        if s == old_base or s.startswith(old_prefix):
            rel = s[len(old_base) :].lstrip(r"\/")
            rec["path"] = str(new_r / rel) if rel else str(new_r)
            rec["batch"] = new_batch

    for lst in spc_store.values():
        for rec in lst:
            touch(rec)
    for lst in dark_spc_store.values():
        for rec in lst:
            touch(rec)
    for bmap in blank_spc_store.values():
        for lst in bmap.values():
            for rec in lst:
                touch(rec)


def _try_rename_no_batch_archive_folder(safe_device_id: str, new_batch: str) -> None:
    """无单号占位目录（``no_batch`` / ``no_batch_*`` 段）在首次收到真实单号时重命名为新末段。

    多目录并存时：若存在当日 ``…__no_batch``（无后缀），仍优先该目录；否则选 **末段序号最小**
    的占位目录（纯 ``no_batch`` 优先于 ``no_batch_0001``，再优于 ``0002``…）；序号相同再按 mtime。
    """
    if (
        not new_batch
        or new_batch == "_no_batch"
        or str(new_batch).startswith("_no_batch_")
    ):
        return
    prefix = f"{safe_device_id}_"
    with _ARCHIVE_RENAME_LOCK:
        if not SPC_STORE_DIR.is_dir():
            return
        candidates: List[Path] = []
        for p in SPC_STORE_DIR.iterdir():
            if not p.is_dir() or not p.name.startswith(prefix):
                continue
            parsed = _parse_spc_archive_folder_name(p.name)
            if not parsed:
                continue
            dev, seg = parsed
            if dev != safe_device_id:
                continue
            if not _folder_batch_segment_is_placeholder(seg):
                continue
            candidates.append(p)
        if not candidates:
            return
        now = datetime.now()
        preferred_plain = SPC_STORE_DIR / _spc_upload_archive_folder_name(
            safe_device_id, "_no_batch", now
        )
        if preferred_plain.is_dir():
            src = preferred_plain
        else:
            # 多锅无单号目录并存时优先末段序号更小的（如 0001 先于 0002），避免误迁最新一锅。
            src = min(candidates, key=_no_batch_placeholder_pick_key)
        m = _SPC_ARCHIVE_DATE_RE.search(src.name)
        if not m:
            return
        head = src.name[: m.end()]
        dest_name = head + new_batch
        dest = SPC_STORE_DIR / dest_name
        if dest.exists():
            logger.warning(
                "无单号目录未重命名：目标归档已存在 device=%s dest=%s",
                safe_device_id,
                dest_name,
            )
            return
        try:
            old_r = src.resolve()
            src.rename(dest)
            new_r = dest.resolve()
            _rewrite_stored_paths_after_archive_rename(old_r, new_r, new_batch)
            logger.info(
                "无单号归档已重命名为新单号: %s -> %s",
                src.name,
                dest_name,
            )
        except OSError as e:
            logger.warning("归档重命名失败 %s -> %s: %s", src, dest, e)


def _try_rename_batch_archive_folder(
    safe_device_id: str,
    old_batch_key: str,
    new_batch_key: str,
    when: datetime,
) -> None:
    """同日、同设备下将归档根目录末段由 old_batch_key 改为 new_batch_key（如手动单号 → 服务器单号）。

    ``_no_batch`` 占位目录仍由 ``_try_rename_no_batch_archive_folder`` 处理；此处跳过。"""
    if not old_batch_key or not new_batch_key or old_batch_key == new_batch_key:
        return
    if old_batch_key == "_no_batch" or new_batch_key == "_no_batch":
        return
    if str(old_batch_key).startswith("_no_batch_") or str(new_batch_key).startswith(
        "_no_batch_"
    ):
        return
    with _ARCHIVE_RENAME_LOCK:
        if not SPC_STORE_DIR.is_dir():
            return
        src = SPC_STORE_DIR / _spc_upload_archive_folder_name(
            safe_device_id, old_batch_key, when
        )
        dest = SPC_STORE_DIR / _spc_upload_archive_folder_name(
            safe_device_id, new_batch_key, when
        )
        if not src.is_dir():
            return
        if dest.exists():
            logger.warning(
                "单号目录迁移跳过：目标已存在 device=%s %s -> %s",
                safe_device_id,
                src.name,
                dest.name,
            )
            return
        try:
            old_r = src.resolve()
            src.rename(dest)
            new_r = dest.resolve()
            _rewrite_stored_paths_after_archive_rename(old_r, new_r, new_batch_key)
            logger.info(
                "归档目录已随单号更新重命名: %s -> %s",
                old_r.name,
                new_r.name,
            )
        except OSError as e:
            logger.warning("归档目录迁移失败 %s -> %s: %s", src, dest, e)


def _peek_cached_generation_batch_raw(device_id: str) -> Any:
    """读取工艺缓存中的 generation_batch（上传处理前快照），缺失则返回 None。"""
    did = str(device_id or "").strip()
    if not did:
        return None
    safe = _safe_device_id(did)
    with _process_cache_lock:
        cached = _process_cache.get(did) or _process_cache.get(safe) or {}
        if "generation_batch" not in cached:
            return None
        return cached.get("generation_batch")


def _spc_top_dir_has_kind_children(path: Path) -> bool:
    try:
        for ch in path.iterdir():
            if ch.is_dir() and ch.name in _ALLOWED_SPC_KINDS:
                return True
    except OSError:
        return False
    return False


def _collect_sensor_csv_paths_for_device(safe_dev: str) -> List[Path]:
    """旧版 _uploaded_device_data 与新版 _upload_spc 下归档目录中的 SENSOR.csv（及历史 {单号}.csv）。"""
    paths: List[Path] = []
    for root in (LEGACY_SENSOR_DATA_DIR, SPC_STORE_DIR):
        if not root.is_dir():
            continue
        legacy = root / safe_dev
        if legacy.is_dir():
            paths.extend(sorted(legacy.glob("*.csv")))
        for top in root.iterdir():
            if not top.is_dir():
                continue
            parsed = _parse_spc_archive_folder_name(top.name)
            if not parsed:
                continue
            if parsed[0] != safe_dev:
                continue
            preferred = top / _SENSOR_ARCHIVE_CSV
            if preferred.is_file():
                paths.append(preferred)
                continue
            paths.extend(sorted(top.glob("*.csv")))
    return paths


def _find_sensor_batch_csv_path(safe_dev: str, safe_batch: str) -> Optional[Path]:
    """定位传感器 CSV：新版在 _upload_spc 归档目录；旧版可在 _uploaded_device_data。多日同单号取最新修改时间。"""
    candidates: List[Path] = []
    for root in (LEGACY_SENSOR_DATA_DIR, SPC_STORE_DIR):
        if not root.is_dir():
            continue
        legacy_flat = root / safe_dev / f"{safe_batch}.csv"
        if legacy_flat.is_file():
            candidates.append(legacy_flat)
        for top in root.iterdir():
            if not top.is_dir():
                continue
            parsed = _parse_spc_archive_folder_name(top.name)
            if not parsed or parsed[0] != safe_dev or parsed[1] != safe_batch:
                continue
            p_new = top / _SENSOR_ARCHIVE_CSV
            p_old = top / f"{safe_batch}.csv"
            if p_new.is_file():
                candidates.append(p_new)
            elif p_old.is_file():
                candidates.append(p_old)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _add_sensor_csv_to_batch_map(batch_map: Dict[str, dict], csv_path: Path) -> None:
    """将单个传感器 CSV 摘要合并进 batch_map（同单号多文件时合并条数与时间范围）。"""
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        logger.warning("读取单号文件失败 %s：%s", csv_path, e)
        return
    if len(rows) < 2:
        return
    process = _parse_process_line(rows[0])
    sensor_rows = [r for r in rows[2:] if r and any(c.strip() for c in r)]
    first_time = sensor_rows[0][0] if sensor_rows else None
    last_time = sensor_rows[-1][0] if sensor_rows else None
    mtime = csv_path.stat().st_mtime
    parent_parsed = _parse_spc_archive_folder_name(csv_path.parent.name)
    batch_key = parent_parsed[1] if parent_parsed else csv_path.stem
    new_item = {
        "batch": batch_key,
        "filename": csv_path.name,
        "count": len(sensor_rows),
        "first_time": first_time,
        "last_time": last_time,
        "process": process,
        "spectrum_file_count": 0,
        "blank_spc_file_count": 0,
        "_sort_ts": mtime,
    }
    prev = batch_map.get(batch_key)
    if prev is None:
        batch_map[batch_key] = new_item
        return
    prev_mtime = float(prev.get("_sort_ts", 0))
    prev.setdefault("spectrum_file_count", 0)
    prev.setdefault("blank_spc_file_count", 0)
    prev["count"] = int(prev.get("count", 0)) + len(sensor_rows)
    if first_time and (
        not prev.get("first_time") or first_time < prev["first_time"]
    ):
        prev["first_time"] = first_time
    if last_time and (not prev.get("last_time") or last_time > prev["last_time"]):
        prev["last_time"] = last_time
    if mtime >= prev_mtime:
        prev["process"] = process
        prev["filename"] = csv_path.name
    prev["_sort_ts"] = max(prev_mtime, mtime)


# 支持的软件包后缀
_ALLOWED_UPDATE_SUFFIXES = {".zip", ".tar.gz", ".apk", ".exe", ".dmg", ".deb", ".rpm"}
# 从文件名解析版本号：匹配 _vX.Y.Z 或 _vX.Y 格式
_VERSION_RE = re.compile(r"_v(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)


def _parse_version(filename: str) -> Tuple[int, int, int]:
    """从文件名中提取版本号三元组，无法解析时返回 (0, 0, 0)。
    支持 AppName_v1.2.3.zip 或 AppName_v1.2.zip 格式。
    """
    m = _VERSION_RE.search(filename)
    if not m:
        return (0, 0, 0)
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) is not None else 0
    return (major, minor, patch)


def _version_str(v: Tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def _scan_update_packages() -> List[dict]:
    """扫描 _updates/ 目录，返回按版本号升序排列的软件包列表。"""
    packages = []
    if not UPDATE_STORE_DIR.exists():
        return packages
    for f in UPDATE_STORE_DIR.iterdir():
        if not f.is_file():
            continue
        name_lower = f.name.lower()
        if not any(name_lower.endswith(ext) for ext in _ALLOWED_UPDATE_SUFFIXES):
            continue
        stat = f.stat()
        ver = _parse_version(f.name)
        packages.append({
            "filename": f.name,
            "version": _version_str(ver),
            "version_tuple": ver,
            "size": stat.st_size,
            "upload_time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "path": str(f),
        })
    packages.sort(key=lambda p: p["version_tuple"])
    return packages


def _safe_generation_batch(generation_batch: Any) -> str:
    """单号用作文件名，去除 Windows / Unix 非法字符；空则写入 _no_batch.jsonl。"""
    if generation_batch is None:
        return "_no_batch"
    raw = str(generation_batch).strip()
    if not raw:
        return "_no_batch"
    s = _INVALID_BATCH_FILENAME_RE.sub("_", raw).strip(" .")
    if len(s) > 180:
        s = s[:180]
    return s if s else "_no_batch"


def _effective_archive_batch_key(
    device_id: str, safe_device_id: str, generation_batch: Any
) -> str:
    """落盘用归档末段：真实单号用清洗后值；无单号时使用 ``_no_batch`` 或 ``_no_batch_{0001}`` 递增槽。"""
    base = _safe_generation_batch(generation_batch)
    if base != "_no_batch":
        return base
    did = str(device_id or "").strip()
    if not did:
        return "_no_batch"
    safe = safe_device_id or _safe_device_id(did)
    with _process_cache_lock:
        c = _process_cache.get(did) or _process_cache.get(safe) or {}
        slot = c.get("no_batch_dir_slot")
    if isinstance(slot, str) and slot.strip():
        suf = _INVALID_BATCH_FILENAME_RE.sub("_", slot.strip()).strip(" .")[:32]
        if suf:
            return f"_no_batch_{suf}"
    return "_no_batch"


def _folder_batch_segment_is_placeholder(seg: str) -> bool:
    """解析自归档文件夹名的 batch 段是否为无单号占位（含 ``no_batch`` / ``no_batch_slot``）。"""
    s = (seg or "").strip()
    if s == "no_batch":
        return True
    return s.startswith("no_batch_")


def _no_batch_placeholder_pick_key(path: Path) -> Tuple[int, int, float, str]:
    """多占位目录时排序键：`min` = 优先末段序号更小的，其次更早 mtime。

    - 纯 ``no_batch`` 视为序号 -1，优先于 ``no_batch_0001`` 等。
    - ``no_batch_0007`` 等为数字后缀按其整数值排序。
    - 非数字后缀（历史 hex 等）排在数字槽之后，同类再按 mtime、目录名稳定排序。
    """
    parsed = _parse_spc_archive_folder_name(path.name)
    if not parsed:
        return (2, 0, 0.0, path.name)
    _, seg = parsed
    s = (seg or "").strip()
    try:
        mt = path.stat().st_mtime
    except OSError:
        mt = 0.0
    name = path.name
    if s == "no_batch":
        return (0, -1, mt, name)
    if s.startswith("no_batch_"):
        suf = s[len("no_batch_") :]
        if suf.isdigit():
            return (0, int(suf), mt, name)
        return (1, 0, mt, name)
    return (2, 0, mt, name)


def _load_process_aux_disk() -> Dict[str, Any]:
    if not _PROCESS_AUX_FILE.exists():
        return {}
    try:
        with open(_PROCESS_AUX_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取工艺辅助状态失败 %s: %s", _PROCESS_AUX_FILE, e)
        return {}
    return data if isinstance(data, dict) else {}


def _save_process_aux_disk(root: Dict[str, Any]) -> None:
    tmp = _PROCESS_AUX_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(root, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _PROCESS_AUX_FILE)
    except OSError as e:
        logger.warning("写入工艺辅助状态失败 %s: %s", _PROCESS_AUX_FILE, e)


def _alloc_no_batch_dir_slot(safe_id: str) -> str:
    """为新的一锅无单号归档分配递增槽（0001、0002…），写入 ``_process_aux`` 并 ``batch_cleared=True``。"""
    safe = str(safe_id or "").strip()
    if not safe:
        return "0001"
    with _process_aux_lock:
        root = _load_process_aux_disk()
        cur = dict(root.get(safe) or {})
        try:
            n = int(cur.get("no_batch_seq", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        n += 1
        slot = f"{n:04d}"
        cur["no_batch_seq"] = n
        cur["no_batch_dir_slot"] = slot
        cur["batch_cleared"] = True
        root[safe] = cur
        _save_process_aux_disk(root)
        return slot


def _persist_process_aux_cleared(safe_id: str, slot: str) -> None:
    """一锅结束或清空单号：记下新 slot，并标记须忽略 CSV 回放的 generation_batch。"""
    suf = str(slot or "").strip()[:32]
    if not suf:
        return
    with _process_aux_lock:
        root = _load_process_aux_disk()
        cur = dict(root.get(safe_id) or {})
        cur["no_batch_dir_slot"] = suf
        cur["batch_cleared"] = True
        root[safe_id] = cur
        _save_process_aux_disk(root)


def _apply_process_cache(
    payload: dict, *, generation_batch_was_provided: bool = False
) -> dict:
    """更新设备工艺缓存；若本次未携带则用缓存补齐。原地修改并返回 payload。

    当请求体中**显式**带有 ``generation_batch`` 且值为空/null 时，会清除该设备缓存里的单号，
    后续归档使用占位 ``_no_batch`` 目录，便于「一锅结束 → 清空单号 → 再下发新单号」开始新文件夹。"""
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return payload
    did = device_id.strip()
    new_slot: Optional[str] = None
    if generation_batch_was_provided:
        gb = payload.get("generation_batch")
        if gb is None or (isinstance(gb, str) and not str(gb).strip()):
            try:
                new_slot = _alloc_no_batch_dir_slot(_safe_device_id(did))
            except HTTPException:
                new_slot = None
    with _process_cache_lock:
        cached = _process_cache.setdefault(did, {})
        if new_slot is not None:
            cached.pop("generation_batch", None)
            cached["no_batch_dir_slot"] = new_slot
        incoming = {
            k: payload[k]
            for k in _PROCESS_PARAM_KEYS
            if payload.get(k) is not None
        }
        if incoming:
            cached.update(incoming)
        for k in _PROCESS_PARAM_KEYS:
            v = cached.get(k)
            if v is not None and payload.get(k) is None:
                payload[k] = v
    return payload


def _clear_generation_batch_cache(device_id: str) -> tuple[str, str, bool]:
    """清除该设备工艺缓存中的 generation_batch，并刷新无单号归档槽（新的一锅使用新目录）。"""
    raw = str(device_id or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="缺少 device_id")
    safe = _safe_device_id(raw)
    slot = _alloc_no_batch_dir_slot(safe)
    cleared = False
    with _process_cache_lock:
        for key in {raw, safe}:
            c = _process_cache.setdefault(key, {})
            c["no_batch_dir_slot"] = slot
            if c.pop("generation_batch", None) is not None:
                cleared = True
    return raw, safe, cleared


def _persist_process_aux_has_batch(safe_id: str) -> None:
    """已有有效 generation_batch 写入缓存后，允许 CSV 回放中的单号参与合并。"""
    with _process_aux_lock:
        root = _load_process_aux_disk()
        cur = dict(root.get(safe_id) or {})
        cur["batch_cleared"] = False
        root[safe_id] = cur
        _save_process_aux_disk(root)


def _apply_process_aux_after_rebuild() -> None:
    """启动重建 device_store 工艺缓存后应用磁盘辅助状态（优先于 CSV 中的旧单号）。"""
    root = _load_process_aux_disk()
    if not root:
        return

    def _apply_aux_to_entry(did_key: str, aux: Dict[str, Any]) -> None:
        c = _process_cache.setdefault(did_key, {})
        slot = aux.get("no_batch_dir_slot")
        if isinstance(slot, str) and slot.strip():
            c["no_batch_dir_slot"] = str(slot).strip()[:32]
        if aux.get("batch_cleared"):
            c.pop("generation_batch", None)

    with _process_cache_lock:
        seen: set[str] = set()
        for did in list(_process_cache.keys()):
            try:
                s = _safe_device_id(did)
            except HTTPException:
                continue
            aux = root.get(s)
            if not isinstance(aux, dict):
                continue
            _apply_aux_to_entry(did, aux)
            seen.add(s)
        for s, aux in root.items():
            if not isinstance(s, str) or not isinstance(aux, dict):
                continue
            if s in seen:
                continue
            _apply_aux_to_entry(s, aux)
    logger.info("已合并工艺辅助状态（一锅结束/slot）设备: %s", sorted(root.keys()))


def _generation_batch_explicitly_in_request(data: DeviceData) -> bool:
    """判断请求体是否显式携带 generation_batch（兼容 Pydantic v1 __fields_set__）。"""
    fs = getattr(data, "model_fields_set", None)
    if fs is not None and "generation_batch" in fs:
        return True
    fsv1 = getattr(data, "__fields_set__", None)
    return bool(fsv1 and "generation_batch" in fsv1)


def _sync_process_cache_from_dispatch_and_rename_archives(
    path_device_id: str, new_order_text: Optional[str]
) -> None:
    """HTTP 下发/清除单号后同步 ``_process_cache.generation_batch`` 并重命名 ``_upload_spc`` 归档目录。

    否则仅有 ``_order_numbers`` 更新时，工艺缓存与磁盘目录末段仍停留在旧单号。"""
    raw_param = str(path_device_id or "").strip()
    if not raw_param:
        return
    safe_dev = _safe_device_id(path_device_id)
    peeked_gb = _peek_cached_generation_batch_raw(raw_param)
    old_simple = _safe_generation_batch(peeked_gb)
    norm = str(new_order_text).strip() if new_order_text else ""
    new_slot: Optional[str] = None
    if not norm:
        new_slot = _alloc_no_batch_dir_slot(safe_dev)
    now = datetime.now()
    with _process_cache_lock:
        for key in {raw_param, safe_dev}:
            c = _process_cache.setdefault(key, {})
            if norm:
                c["generation_batch"] = norm
            else:
                c.pop("generation_batch", None)
                if new_slot is not None:
                    c["no_batch_dir_slot"] = new_slot
    new_simple = _safe_generation_batch(norm if norm else None)
    _try_rename_no_batch_archive_folder(safe_dev, new_simple)
    _try_rename_batch_archive_folder(safe_dev, old_simple, new_simple, now)
    logger.info(
        "单号下发已同步工艺缓存并尝试归档重命名 device=%s old=%s new=%s",
        safe_dev,
        old_simple,
        new_simple,
    )
    if norm:
        _persist_process_aux_has_batch(safe_dev)


def _device_record_sort_ts(rec: dict) -> float:
    st = rec.get("server_time")
    if isinstance(st, str) and len(st) >= 19:
        try:
            return datetime.strptime(st[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    ts = rec.get("last_update_ts")
    if isinstance(ts, (int, float)):
        return float(ts)
    return 0.0


def _csv_cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _process_params_line(payload: dict) -> List[str]:
    """工艺参数行：每个工艺字段一格 'key=value'，缺失值仍写出 'key=' 占位。"""
    return [f"{k}={_csv_cell_str(payload.get(k))}" for k in _PROCESS_PARAM_KEYS]


def _parse_process_line(cells: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for cell in cells:
        if not isinstance(cell, str) or "=" not in cell:
            continue
        k, _, raw = cell.partition("=")
        k = k.strip()
        raw = raw.strip()
        if not k or k not in _PROCESS_PARAM_KEYS or raw == "":
            continue
        if k in _PROCESS_FLOAT_FIELDS:
            try:
                out[k] = float(raw)
            except ValueError:
                pass
        else:
            out[k] = raw
    return out


def _sensor_row_values(payload: dict) -> List[str]:
    out: List[str] = []
    for k in _SENSOR_CSV_FIELDS:
        v = payload.get(k)
        if k == "valves":
            if isinstance(v, dict):
                out.append(json.dumps(v, ensure_ascii=False, separators=(",", ":")))
            else:
                out.append("" if v is None else str(v))
        else:
            out.append(_csv_cell_str(v))
    return out


def _sensor_row_to_record(row: Dict[str, str]) -> Optional[dict]:
    """读取 CSV 第 3+ 行恢复为传感器 dict；缺失字段为 None。"""
    rec: Dict[str, Any] = {}
    for k in _SENSOR_CSV_FIELDS:
        v = row.get(k, "")
        if v is None or v == "":
            rec[k] = None
            continue
        if k == "valves":
            try:
                rec[k] = json.loads(v)
            except (TypeError, json.JSONDecodeError):
                rec[k] = {}
            continue
        if k in _SENSOR_CSV_BOOL_FIELDS:
            rec[k] = v.strip().lower() in ("true", "1", "yes")
            continue
        if k in _SENSOR_CSV_INT_FIELDS:
            try:
                rec[k] = int(v)
            except ValueError:
                try:
                    rec[k] = int(float(v))
                except ValueError:
                    rec[k] = None
            continue
        if k in _SENSOR_CSV_FLOAT_FIELDS:
            try:
                rec[k] = float(v)
            except ValueError:
                rec[k] = None
            continue
        rec[k] = v
    if not isinstance(rec.get("device_id"), str) or not rec["device_id"]:
        return None
    return rec


def _append_device_payload_to_disk(payload: dict) -> None:
    """将单条上送追加到 _upload_spc/{设备_yyyy年MM月dd日_单号}/SENSOR.csv（与光谱同目录）。

    兼容读取旧版 _uploaded_device_data/… 下的 CSV。

    文件结构：
      行 1 — 工艺参数（key=value，每字段一格）
      行 2 — 传感器表头
      行 3+ — 传感器数据（按时间追加）
    新建文件时写入 UTF-8 BOM 便于 Excel 直接打开。"""
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("payload 缺少 device_id")
    did = device_id.strip()
    safe_dev = _safe_device_id(device_id)
    batch_key = _effective_archive_batch_key(did, safe_dev, payload.get("generation_batch"))
    now = datetime.now()
    archive_name = _spc_upload_archive_folder_name(safe_dev, batch_key, now)
    batch_dir = SPC_STORE_DIR / archive_name
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / _SENSOR_ARCHIVE_CSV
    sensor_row = _sensor_row_values(payload)
    with _DEVICE_FILE_LOCK:
        new_file = not path.exists() or path.stat().st_size == 0
        with open(path, "a", encoding="utf-8", newline="") as f:
            if new_file:
                f.write("\ufeff")
            writer = csv.writer(f)
            if new_file:
                writer.writerow(_process_params_line(payload))
                writer.writerow(list(_SENSOR_CSV_FIELDS))
            writer.writerow(sensor_row)


def _rebuild_device_store_from_disk() -> None:
    """启动时恢复 sensor 历史：先扫旧目录 _uploaded_device_data，再扫 _upload_spc 下各归档目录的 SENSOR.csv。

    兼容历史 .jsonl 与 .csv；jsonl 仅在旧目录中查找。
    """
    total_lines = 0

    def _ingest_sensor_csv_file(csv_path: Path) -> None:
        nonlocal total_lines
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        except OSError as e:
            logger.warning("读取传感器 csv 文件失败，已跳过 %s：%s", csv_path, e)
            return
        if len(rows) < 2:
            return
        process = _parse_process_line(rows[0])
        sensor_header = rows[1]
        for raw in rows[2:]:
            if not raw:
                continue
            row_dict = dict(zip(sensor_header, raw))
            rec = _sensor_row_to_record(row_dict)
            if rec is None:
                continue
            for k, v in process.items():
                if rec.get(k) is None:
                    rec[k] = v
            device_store.setdefault(rec["device_id"], []).append(rec)
            total_lines += 1

    if LEGACY_SENSOR_DATA_DIR.exists():
        for device_dir in sorted(LEGACY_SENSOR_DATA_DIR.iterdir()):
            if not device_dir.is_dir():
                continue
            for jsonl_path in sorted(device_dir.glob("*.jsonl")):
                try:
                    with open(jsonl_path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            rec = json.loads(line)
                            did = rec.get("device_id")
                            if not isinstance(did, str) or not did:
                                continue
                            device_store.setdefault(did, []).append(rec)
                            total_lines += 1
                except (OSError, json.JSONDecodeError) as e:
                    logger.warning("读取传感器 jsonl 文件失败，已跳过 %s：%s", jsonl_path, e)
            for csv_path in sorted(device_dir.glob("*.csv")):
                _ingest_sensor_csv_file(csv_path)

    if SPC_STORE_DIR.exists():
        for top in sorted(SPC_STORE_DIR.iterdir()):
            if not top.is_dir():
                continue
            sp = top / _SENSOR_ARCHIVE_CSV
            if sp.is_file():
                _ingest_sensor_csv_file(sp)
    for rows in device_store.values():
        rows.sort(key=_device_record_sort_ts)
    # 用每设备最新的非空字段重建工艺缓存（按时间正序遍历，后者覆盖前者）
    with _process_cache_lock:
        for did, rows in device_store.items():
            cached: Dict[str, Any] = {}
            for rec in rows:
                for k in _PROCESS_PARAM_KEYS:
                    v = rec.get(k)
                    if v is not None:
                        cached[k] = v
            if cached:
                _process_cache[did] = cached
    logger.info(
        "传感器历史已从磁盘恢复：共 %d 条，设备 %s；工艺缓存设备 %s",
        total_lines,
        sorted(device_store.keys()),
        sorted(_process_cache.keys()),
    )


def _rebuild_stores_from_disk() -> None:
    """服务器启动时扫描磁盘，重建 spc_store 和 blank_spc_store 索引。

    新版：_upload_spc/{设备号_yyyy年MM月dd日_单号}/{raw|dark|blank}/*.spc
    旧版：_upload_spc/{device_id}/{batch}/{raw|dark|blank}/*.spc
    文件按修改时间升序排列，与上传顺序保持一致。
    """
    spc_count = 0
    dark_count = 0
    blank_count = 0

    def _ingest(device_id: str, batch: str, kind_root: Path) -> None:
        nonlocal spc_count, dark_count, blank_count
        for kind_dir in sorted(kind_root.iterdir()):
            if not kind_dir.is_dir():
                continue
            kind = kind_dir.name
            if kind not in _ALLOWED_SPC_KINDS:
                continue
            files = sorted(
                kind_dir.glob("*.spc"), key=lambda f: f.stat().st_mtime
            )
            for spc_file in files:
                rec = _spc_record_from_file(
                    device_id=device_id,
                    batch=batch,
                    kind=kind,
                    spc_file=spc_file,
                    blank_type=_blank_type_from_filename(spc_file.name)
                    if kind == "blank"
                    else None,
                )
                if kind == "raw":
                    spc_store.setdefault(device_id, []).append(rec)
                    spc_count += 1
                elif kind == "dark":
                    dark_spc_store.setdefault(device_id, []).append(rec)
                    dark_count += 1
                elif kind == "blank":
                    blank_type = rec.get("blank_type") or "blank"
                    blank_spc_store.setdefault(device_id, {}).setdefault(
                        blank_type, []
                    ).append(rec)
                    blank_count += 1

    if SPC_STORE_DIR.exists():
        for top_dir in sorted(SPC_STORE_DIR.iterdir()):
            if not top_dir.is_dir():
                continue

            if _spc_top_dir_has_kind_children(top_dir):
                parsed = _parse_spc_archive_folder_name(top_dir.name)
                if not parsed:
                    logger.warning(
                        "无法解析 SPC 归档目录名（跳过索引）: %s", top_dir.name
                    )
                    continue
                dev, bat = parsed
                _ingest(dev, bat, top_dir)
            else:
                device_id = top_dir.name
                for batch_dir in sorted(top_dir.iterdir()):
                    if not batch_dir.is_dir():
                        continue
                    batch = batch_dir.name
                    _ingest(device_id, batch, batch_dir)

    logger.info(
        "磁盘索引重建完成：采样光谱 %d 条，暗光谱 %d 条，参比光谱 %d 条，涉及设备 %s",
        spc_count,
        dark_count,
        blank_count,
        sorted(set(spc_store) | set(dark_spc_store) | set(blank_spc_store)),
    )


app = FastAPI(
    title=f"HY Monitor API",
    description=f"恒宇在线监测系统服务器端API接口\n",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


@app.on_event("startup")
async def startup_event() -> None:
    _rebuild_device_store_from_disk()
    _apply_process_aux_after_rebuild()
    _rebuild_stores_from_disk()
    _load_order_numbers_from_disk()


def _safe_spc_filename(filename: str) -> str:
    name = os.path.basename(str(filename or "").strip())
    if not name:
        raise HTTPException(status_code=400, detail="缺少文件名")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="无效的文件名")
    if not name.lower().endswith(".spc"):
        name += ".spc"
    return name


def _safe_device_id(device_id: str) -> str:
    safe = str(device_id or "").strip()
    if not safe:
        raise HTTPException(status_code=400, detail="缺少 device_id")
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in safe)


def _load_order_numbers_from_disk() -> None:
    """启动时从 _ORDER_NUMBER_FILE 恢复 device_id -> order_number 映射。"""
    if not _ORDER_NUMBER_FILE.exists():
        return
    try:
        with open(_ORDER_NUMBER_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取单号映射文件失败 %s: %s", _ORDER_NUMBER_FILE, e)
        return
    if not isinstance(data, dict):
        return
    with _order_numbers_lock:
        _order_numbers.clear()
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if v is None:
                continue
            text = str(v).strip()
            if not text:
                continue
            _order_numbers[k] = text
    logger.info("已加载 %d 个设备的单号映射", len(_order_numbers))


def _save_order_numbers_to_disk_locked() -> None:
    """假定调用方已持 _order_numbers_lock，将当前映射原子写入磁盘。"""
    tmp_path = _ORDER_NUMBER_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_order_numbers, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _ORDER_NUMBER_FILE)
    except OSError as e:
        logger.warning("写入单号映射文件失败 %s: %s", _ORDER_NUMBER_FILE, e)


class OrderNumberRequest(BaseModel):
    """设置/清除单号请求体。order_number 为 null 或空字符串视为清除。"""

    order_number: Optional[str] = Field(
        default=None,
        description="要下发给该设备的单号；传 null 或空字符串等价于清除",
    )


def _resolve_spc_batch(device_id: str, safe_device_id: str, batch: Optional[str]) -> str:
    """SPC 单号优先使用上传字段；缺失时使用该设备缓存的 generation_batch（含无单号 slot）。"""
    if batch is not None and str(batch).strip():
        return _safe_generation_batch(batch)
    did = str(device_id or "").strip()
    with _process_cache_lock:
        cached = _process_cache.get(did) or _process_cache.get(safe_device_id) or {}
        cached_batch = cached.get("generation_batch")
    return _effective_archive_batch_key(did, safe_device_id, cached_batch)


def _blank_type_from_filename(filename: str) -> Optional[str]:
    for blank_type in sorted(_ALLOWED_BLANK_TYPES):
        if filename.startswith(blank_type):
            return blank_type
    return None


def _spc_record_from_file(
    device_id: str,
    batch: str,
    kind: str,
    spc_file: Path,
    blank_type: Optional[str] = None,
) -> dict:
    stat = spc_file.stat()
    rec = {
        "device_id": device_id,
        "batch": batch,
        "kind": kind,
        "original_filename": spc_file.name,
        "stored_filename": spc_file.name,
        "path": str(spc_file),
        "size": stat.st_size,
        "server_time": datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }
    if blank_type:
        rec["blank_type"] = blank_type
    return rec


def _spc_file_summary(rec: dict) -> dict:
    out = {
        "original_filename": rec["original_filename"],
        "stored_filename": rec["stored_filename"],
        "size": rec["size"],
        "server_time": rec["server_time"],
        "batch": rec.get("batch"),
        "kind": rec.get("kind"),
    }
    if rec.get("blank_type"):
        out["blank_type"] = rec["blank_type"]
    return out


def _filter_by_batch(records: List[dict], batch: Optional[str]) -> List[dict]:
    if batch is None or str(batch).strip() == "":
        return records
    safe_batch = _safe_generation_batch(batch)
    return [rec for rec in records if rec.get("batch") == safe_batch]


def _filter_by_date(
    records: List[dict],
    date_from: Optional[str],
    date_to: Optional[str],
) -> List[dict]:
    """按 server_time 字段（格式 YYYY-MM-DD HH:MM:SS）筛选记录。

    date_from / date_to 均为可选的 YYYY-MM-DD 字符串，表示闭区间起止日期。
    """
    if not date_from and not date_to:
        return records

    def _parse_date(s: str) -> Optional[date_type]:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None

    from_date = _parse_date(date_from) if date_from else None
    to_date = _parse_date(date_to) if date_to else None

    if (date_from and from_date is None) or (date_to and to_date is None):
        raise HTTPException(
            status_code=400,
            detail="日期格式无效，请使用 YYYY-MM-DD（如 2025-01-01）",
        )
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="date_from 不能晚于 date_to")

    filtered = []
    for rec in records:
        st = rec.get("server_time", "")
        try:
            rec_date = datetime.strptime(st, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            filtered.append(rec)
            continue
        if from_date and rec_date < from_date:
            continue
        if to_date and rec_date > to_date:
            continue
        filtered.append(rec)
    return filtered


def _parse_server_time(value: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _iter_spc_records_for_device(safe_device_id: str) -> List[dict]:
    records: List[dict] = []
    records.extend(spc_store.get(safe_device_id) or [])
    records.extend(dark_spc_store.get(safe_device_id) or [])
    for type_records in (blank_spc_store.get(safe_device_id) or {}).values():
        records.extend(type_records)
    return records


def _device_has_spc_batch(safe_device_id: str, safe_batch: str) -> bool:
    return any(
        rec.get("batch") == safe_batch
        for rec in _iter_spc_records_for_device(safe_device_id)
    )


def _merge_spc_batches(batch_map: Dict[str, dict], safe_device_id: str) -> None:
    """让仅上传光谱、未上传传感器的单号也出现在单号列表中；并分别累计采样光谱条数与参比条数。"""
    def upsert(
        batch: str,
        server_time: str,
        *,
        spectrum_delta: int = 0,
        blank_delta: int = 0,
    ) -> None:
        if not batch:
            return
        ts = _parse_server_time(server_time)
        sort_ts = ts.timestamp() if ts else 0.0
        item = batch_map.get(batch)
        if item is None:
            item = {
                "batch": batch,
                "filename": None,
                "count": 0,
                "first_time": server_time or None,
                "last_time": server_time or None,
                "process": {},
                "spectrum_file_count": 0,
                "blank_spc_file_count": 0,
                "_sort_ts": sort_ts,
            }
            batch_map[batch] = item
        else:
            item.setdefault("spectrum_file_count", 0)
            item.setdefault("blank_spc_file_count", 0)
        item["spectrum_file_count"] = int(item.get("spectrum_file_count") or 0) + spectrum_delta
        item["blank_spc_file_count"] = int(item.get("blank_spc_file_count") or 0) + blank_delta
        if sort_ts and sort_ts > float(item.get("_sort_ts") or 0.0):
            item["_sort_ts"] = sort_ts
        if server_time and (not item.get("first_time") or server_time < item["first_time"]):
            item["first_time"] = server_time
        if server_time and (not item.get("last_time") or server_time > item["last_time"]):
            item["last_time"] = server_time

    for rec in spc_store.get(safe_device_id) or []:
        upsert(
            str(rec.get("batch") or "").strip(),
            str(rec.get("server_time") or ""),
            spectrum_delta=1,
        )
    for rec in dark_spc_store.get(safe_device_id) or []:
        # 暗光谱参与单号归档与时间排序，不计入「采样光谱」条数（与 /spc/device 列表一致）。
        upsert(
            str(rec.get("batch") or "").strip(),
            str(rec.get("server_time") or ""),
        )
    for type_records in (blank_spc_store.get(safe_device_id) or {}).values():
        for rec in type_records:
            upsert(
                str(rec.get("batch") or "").strip(),
                str(rec.get("server_time") or ""),
                blank_delta=1,
            )


def _read_spc_spectrum_data(path: str, title: str) -> dict[str, Any]:
    """Read an SPC file and return x/y coordinate data for client-side plotting."""
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="SPC file not found on disk")
    try:
        x, y = read_spc_file(Path(path))
        count = min(len(x), len(y))
        x = x[:count]
        y = y[:count]
        mask = (x == x) & (y == y)
        x = x[mask]
        y = y[mask]
        finite_mask = [math.isfinite(float(xv)) and math.isfinite(float(yv)) for xv, yv in zip(x, y)]
        x_values = [float(v) for v, keep in zip(x, finite_mask) if keep]
        y_values = [float(v) for v, keep in zip(y, finite_mask) if keep]
    except Exception as exc:
        logger.exception("SPC 数据读取失败: %s", path)
        raise HTTPException(status_code=422, detail=f"SPC 数据读取失败: {exc}") from exc
    return {
        "title": title,
        "xlabel": "波长(nm)",
        "ylabel": "强度",
        "point_count": len(x_values),
        "x": x_values,
        "y": y_values,
    }


async def _save_uploaded_spc(
    *,
    device_id: str,
    spc_file: UploadFile,
    kind: str,
    batch: Optional[str] = None,
    blank_type: Optional[str] = None,
) -> dict:
    if kind not in _ALLOWED_SPC_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 kind '{kind}'，允许值: {sorted(_ALLOWED_SPC_KINDS)}",
        )
    if blank_type is not None and blank_type not in _ALLOWED_BLANK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 blank_type '{blank_type}'，允许值: {sorted(_ALLOWED_BLANK_TYPES)}",
        )
    safe_device_id = _safe_device_id(device_id)
    peeked_gb = _peek_cached_generation_batch_raw(device_id)
    did = device_id.strip()
    with _process_cache_lock:
        c = _process_cache.get(did) or _process_cache.get(safe_device_id) or {}
        cached_gb = c.get("generation_batch")
    new_simple = (
        _safe_generation_batch(batch)
        if batch is not None and str(batch).strip()
        else _safe_generation_batch(cached_gb)
    )
    safe_batch = _resolve_spc_batch(device_id, safe_device_id, batch)
    now = datetime.now()
    _try_rename_no_batch_archive_folder(safe_device_id, new_simple)
    _try_rename_batch_archive_folder(
        safe_device_id, _safe_generation_batch(peeked_gb), new_simple, now
    )
    original_name = _safe_spc_filename(
        spc_file.filename or f"{kind if kind != 'blank' else blank_type or 'blank'}.spc"
    )
    data = await spc_file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的 SPC 文件为空")

    server_time = now.strftime("%Y-%m-%d %H:%M:%S")
    archive_name = _spc_upload_archive_folder_name(safe_device_id, safe_batch, now)
    device_dir = SPC_STORE_DIR / archive_name / kind
    device_dir.mkdir(parents=True, exist_ok=True)

    # 文件名：类型前缀 + YYYYMMDD + HHMMSS
    if kind == "blank" and blank_type:
        label = str(blank_type)
    else:
        label = kind
    date_seg = now.strftime("%Y%m%d")
    base_t = now.strftime("%H%M%S")
    saved_name = f"{label}_{date_seg}_{base_t}.spc"
    saved_path = device_dir / saved_name
    if saved_path.exists():
        saved_name = f"{label}_{date_seg}_{base_t}_{now.microsecond // 1000:03d}.spc"
        saved_path = device_dir / saved_name
    with open(saved_path, "wb") as f:
        f.write(data)

    rec = {
        "device_id": safe_device_id,
        "batch": safe_batch,
        "kind": kind,
        "original_filename": original_name,
        "stored_filename": saved_name,
        "path": str(saved_path),
        "size": len(data),
        "server_time": server_time,
    }
    if blank_type:
        rec["blank_type"] = blank_type

    if kind == "raw":
        spc_store.setdefault(safe_device_id, []).append(rec)
        count = len(spc_store[safe_device_id])
    elif kind == "dark":
        dark_spc_store.setdefault(safe_device_id, []).append(rec)
        count = len(dark_spc_store[safe_device_id])
    else:
        bt = blank_type or "blank"
        blank_spc_store.setdefault(safe_device_id, {}).setdefault(bt, []).append(rec)
        count = len(blank_spc_store[safe_device_id][bt])

    return {
        "status": "ok",
        "device_id": safe_device_id,
        "batch": safe_batch,
        "kind": kind,
        "blank_type": blank_type,
        "count": count,
        "file_name": saved_name,
        "original_file_name": original_name,
        "size": len(data),
    }


@app.get("/")
def home():
    return {
        "message": "HTTP server is running.",
        "endpoints": [
            "POST /upload",
            "POST /spc/upload",
            "POST /spc/dark/upload",
            "POST /spc/blank/upload",
            "GET /devices",
            "GET /device/{device_id}",
            "GET /device/{device_id}/latest",
            "GET /spc/device/{device_id}",
            "GET /spc/device/{device_id}?batch=xxx&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD",
            "GET /spc/device/{device_id}/latest",
            "GET /spc/device/{device_id}/files/{filename}",
            "GET /spc/device/{device_id}/files/{filename}/data",
            "GET /spc/blank/device/{device_id}",
            "GET /spc/blank/device/{device_id}?batch=xxx&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD",
            "GET /spc/blank/device/{device_id}/{blank_type}/latest",
            "GET /spc/blank/device/{device_id}/{blank_type}/files/{filename}",
            "GET /spc/blank/device/{device_id}/{blank_type}/files/{filename}/data",
            "GET /spc/search",
            "GET /spc/search?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&device_id=xxx&spc_type=sample|blank_before|blank_after",
            "--- 单号下发 ---",
            "GET /order_numbers",
            "GET /device/{device_id}/order_number",
            "POST /device/{device_id}/order_number  body: {\"order_number\": \"XYZ\"}",
            "DELETE /device/{device_id}/order_number",
            "POST /device/{device_id}/production-end  （清除工艺缓存单号，等同显式空 generation_batch）",
            "--- 软件更新 ---",
            "POST /update/upload",
            "GET /update/list",
            "GET /update/latest",
            "GET /update/check?current_version=X.Y.Z",
            "GET /update/download/{filename}",
        ],
        "fields": list(DeviceData.model_fields.keys()),
    }


@app.post("/upload")
def upload_device_data(data: DeviceData) -> dict[str, Any]:
    peeked_gb = _peek_cached_generation_batch_raw(data.device_id)
    payload = data.model_dump()
    payload["server_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 客户端只在首次成功时携带工艺/单号参数，后续靠服务端缓存补齐
    _apply_process_cache(
        payload,
        generation_batch_was_provided=_generation_batch_explicitly_in_request(data),
    )
    safe_dev = _safe_device_id(data.device_id)
    gb_live = payload.get("generation_batch")
    if gb_live is not None and str(gb_live).strip():
        _persist_process_aux_has_batch(safe_dev)
    now = datetime.now()
    old_simple = _safe_generation_batch(peeked_gb)
    new_simple = _safe_generation_batch(payload.get("generation_batch"))
    _try_rename_no_batch_archive_folder(safe_dev, new_simple)
    _try_rename_batch_archive_folder(safe_dev, old_simple, new_simple, now)

    try:
        _append_device_payload_to_disk(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        logger.exception("写入传感器单号文件失败 device_id=%s", data.device_id)
        raise HTTPException(
            status_code=500, detail=f"无法写入本地传感器单号文件: {e}"
        ) from e

    if data.device_id not in device_store:
        device_store[data.device_id] = []

    device_store[data.device_id].append(payload)

    return {
        "status": "ok",
        "device_id": data.device_id,
        "count": len(device_store[data.device_id]),
    }


@app.post("/spc/upload")
async def upload_spc_file(
    device_id: str = Form(...),
    batch: Optional[str] = Form(None),
    spc_file: UploadFile = File(...),
) -> dict[str, Any]:
    return await _save_uploaded_spc(
        device_id=device_id,
        batch=batch,
        spc_file=spc_file,
        kind="raw",
    )


@app.post("/spc/dark/upload")
async def upload_dark_spc_file(
    device_id: str = Form(...),
    batch: Optional[str] = Form(None),
    spc_file: UploadFile = File(...),
) -> dict[str, Any]:
    return await _save_uploaded_spc(
        device_id=device_id,
        batch=batch,
        spc_file=spc_file,
        kind="dark",
    )


@app.get("/devices")
def get_all_devices():
    all_ids = sorted(
        set(device_store.keys())
        | set(spc_store.keys())
        | set(dark_spc_store.keys())
        | set(blank_spc_store.keys())
    )
    return {
        "device_count": len(all_ids),
        "devices": all_ids,
    }


@app.get("/order_numbers")
def list_order_numbers() -> dict[str, Any]:
    """列出当前所有设备的单号映射；客户端无需鉴权即可查阅，便于运维核对。"""
    with _order_numbers_lock:
        snapshot = dict(_order_numbers)
    return {
        "count": len(snapshot),
        "order_numbers": snapshot,
    }


@app.get("/device/{device_id}/order_number")
def get_device_order_number(device_id: str) -> dict[str, Any]:
    """读取该设备当前的单号；客户端按固定间隔轮询此接口拉取最新单号。"""
    safe_dev = _safe_device_id(device_id)
    with _order_numbers_lock:
        current = _order_numbers.get(safe_dev)
    return {
        "device_id": safe_dev,
        "order_number": current,
    }


@app.post("/device/{device_id}/order_number")
def set_device_order_number(device_id: str, body: OrderNumberRequest) -> dict[str, Any]:
    """设置/清除该设备的单号；传 null 或空字符串等价于 DELETE，立即落盘以便重启后保留。"""
    safe_dev = _safe_device_id(device_id)
    raw_param = str(device_id or "").strip()
    raw = (body.order_number or "").strip()
    with _order_numbers_lock:
        if raw:
            _order_numbers[safe_dev] = raw
            if raw_param != safe_dev:
                _order_numbers[raw_param] = raw
            action = "set"
        else:
            _order_numbers.pop(safe_dev, None)
            if raw_param != safe_dev:
                _order_numbers.pop(raw_param, None)
            action = "cleared"
        _save_order_numbers_to_disk_locked()
        current = _order_numbers.get(safe_dev)
    logger.info("单号已 %s device=%s order_number=%s", action, safe_dev, current)
    _sync_process_cache_from_dispatch_and_rename_archives(device_id, raw if raw else None)
    return {
        "status": "ok",
        "action": action,
        "device_id": safe_dev,
        "order_number": current,
    }


@app.post("/device/{device_id}/production-end")
def production_end(device_id: str) -> dict[str, Any]:
    """本锅结束：清除工艺缓存中的 generation_batch，并清除该设备的 /order_number 下发映射（与 DELETE 一致）。"""
    raw, safe, cleared = _clear_generation_batch_cache(device_id)
    removed_order = False
    with _order_numbers_lock:
        if _order_numbers.pop(safe, None) is not None:
            removed_order = True
        if raw != safe and _order_numbers.pop(raw, None) is not None:
            removed_order = True
        if removed_order:
            _save_order_numbers_to_disk_locked()
    logger.info(
        "production-end: device_id=%s (safe=%s) cleared_generation_batch=%s removed_order_number=%s",
        raw,
        safe,
        cleared,
        removed_order,
    )
    return {
        "status": "ok",
        "device_id": raw,
        "cleared_generation_batch": cleared,
        "removed_order_number": removed_order,
    }


@app.delete("/device/{device_id}/order_number")
def delete_device_order_number(device_id: str) -> dict[str, Any]:
    """显式清除该设备的单号映射，客户端轮询将拿到 order_number=null。"""
    raw_param = str(device_id or "").strip()
    safe_dev = _safe_device_id(device_id)
    with _order_numbers_lock:
        existed = _order_numbers.pop(safe_dev, None) is not None
        if raw_param != safe_dev:
            existed = _order_numbers.pop(raw_param, None) is not None or existed
        if existed:
            _save_order_numbers_to_disk_locked()
    if existed:
        logger.info("单号已 removed device=%s", safe_dev)
    _sync_process_cache_from_dispatch_and_rename_archives(raw_param, None)
    return {
        "status": "ok",
        "device_id": safe_dev,
        "removed": existed,
    }


@app.get("/device/{device_id}")
def get_device_data(device_id: str):
    known = (
        device_id in device_store
        or device_id in spc_store
        or device_id in dark_spc_store
        or device_id in blank_spc_store
    )
    if not known:
        raise HTTPException(status_code=404, detail="Device not found")

    records = device_store.get(device_id) or []
    return {
        "device_id": device_id,
        "count": len(records),
        "data": records,
    }


@app.get("/device/{device_id}/latest")
def get_latest_device_data(device_id: str):
    known = (
        device_id in device_store
        or device_id in spc_store
        or device_id in dark_spc_store
        or device_id in blank_spc_store
    )
    if not known:
        raise HTTPException(status_code=404, detail="Device not found")

    records = device_store.get(device_id) or []
    if records:
        return records[-1]
    # 设备仅有 SPC 数据，尚无传感器快照：返回只含 device_id 的占位响应
    return {"device_id": device_id}


@app.get("/device/{device_id}/batches")
def list_device_batches(device_id: str):
    """列出该设备已落盘的所有生产单号。

    扫描 _uploaded_device_data（旧）与 _upload_spc 归档目录中的 SENSOR.csv，
    逐文件解析首行工艺参数与传感器记录条数（字段 ``count``）；同时合并仅上传了光谱、尚无传感器 CSV 的单号。
    对每个单号另行统计：``spectrum_file_count``（采样光谱 raw，与 ``GET /spc/device`` 一致）、
    ``blank_spc_file_count``（全部参比类型合计）。
    暗光谱仅参与时间排序与单号出现，不计入 ``spectrum_file_count``。
    结果按最新传感器/光谱写入时间倒序排列（最近的单号在前）。
    """
    safe_dev = _safe_device_id(device_id)
    batch_map: Dict[str, dict] = {}
    for csv_path in _collect_sensor_csv_paths_for_device(safe_dev):
        _add_sensor_csv_to_batch_map(batch_map, csv_path)
    _merge_spc_batches(batch_map, safe_dev)
    batches = sorted(
        batch_map.values(),
        key=lambda item: float(item.get("_sort_ts") or 0.0),
        reverse=True,
    )
    for item in batches:
        item.pop("_sort_ts", None)
    return {
        "device_id": safe_dev,
        "count": len(batches),
        "batches": batches,
    }


@app.get("/device/{device_id}/batch/{batch}")
def get_device_batch(device_id: str, batch: str):
    """读取指定单号 CSV，返回该单号的工艺参数与所有传感器记录。

    传感器记录会自动用文件首行的工艺参数补齐缺失字段，方便客户端直接绘图与展示侧栏。
    """
    safe_dev = _safe_device_id(device_id)
    safe_batch = _safe_generation_batch(batch)
    csv_path = _find_sensor_batch_csv_path(safe_dev, safe_batch)
    if csv_path is None:
        if _device_has_spc_batch(safe_dev, safe_batch):
            return {
                "device_id": safe_dev,
                "batch": safe_batch,
                "process": {},
                "count": 0,
                "data": [],
            }
        raise HTTPException(status_code=404, detail="batch not found")
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取单号文件失败：{e}") from e
    if len(rows) < 2:
        return {
            "device_id": safe_dev,
            "batch": safe_batch,
            "process": {},
            "count": 0,
            "data": [],
        }

    process = _parse_process_line(rows[0])
    sensor_header = rows[1]
    records: List[dict] = []
    for raw in rows[2:]:
        if not raw or not any(c.strip() for c in raw):
            continue
        rec = _sensor_row_to_record(dict(zip(sensor_header, raw)))
        if rec is None:
            continue
        for k, v in process.items():
            if rec.get(k) is None:
                rec[k] = v
        records.append(rec)
    return {
        "device_id": safe_dev,
        "batch": safe_batch,
        "process": process,
        "count": len(records),
        "data": records,
    }


@app.get("/spc/device/{device_id}")
def get_spc_file_list(
    device_id: str,
    batch: Optional[str] = Query(None, description="生产单号，不填则返回该设备全部单号"),
    date_from: Optional[str] = Query(
        None, description="起始日期（含），格式 YYYY-MM-DD，如 2025-01-01"
    ),
    date_to: Optional[str] = Query(
        None, description="截止日期（含），格式 YYYY-MM-DD，如 2025-12-31"
    ),
):
    """列出设备的采样光谱 SPC 文件。可通过 batch / date_from / date_to 筛选。"""
    safe_device_id = _safe_device_id(device_id)
    all_records = spc_store.get(safe_device_id) or []
    if not all_records:
        raise HTTPException(status_code=404, detail="SPC file not found")

    records = _filter_by_date(_filter_by_batch(all_records, batch), date_from, date_to)

    return {
        "device_id": safe_device_id,
        "total": len(all_records),
        "count": len(records),
        "batch": _safe_generation_batch(batch) if batch else None,
        "date_from": date_from,
        "date_to": date_to,
        "files": [_spc_file_summary(rec) for rec in records],
    }


@app.get("/spc/device/{device_id}/latest")
def get_latest_spc_file(
    device_id: str,
    batch: Optional[str] = Query(None, description="生产单号，不填则取全部单号最新"),
):
    safe_device_id = _safe_device_id(device_id)
    records = _filter_by_batch(spc_store.get(safe_device_id) or [], batch)
    if not records:
        raise HTTPException(status_code=404, detail="SPC file not found")

    latest = records[-1]
    path = latest["path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="SPC file not found on disk")

    return FileResponse(
        path=path,
        filename=latest["stored_filename"],
        media_type="application/octet-stream",
    )


@app.get("/spc/device/{device_id}/files/{filename}")
def get_spc_file_by_name(
    device_id: str,
    filename: str,
    batch: Optional[str] = Query(None, description="生产单号"),
):
    safe_device_id = _safe_device_id(device_id)
    safe_filename = _safe_spc_filename(filename)
    records = _filter_by_batch(spc_store.get(safe_device_id) or [], batch)
    if not records:
        raise HTTPException(status_code=404, detail="SPC file not found")

    target = next((rec for rec in records if rec["stored_filename"] == safe_filename), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Specified SPC file not found")

    path = target["path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="SPC file not found on disk")

    return FileResponse(
        path=path,
        filename=target["stored_filename"],
        media_type="application/octet-stream",
    )


@app.get("/spc/device/{device_id}/files/{filename}/data")
def get_spc_file_data(
    device_id: str,
    filename: str,
    batch: Optional[str] = Query(None, description="生产单号"),
):
    """按文件名读取采样光谱 SPC，并返回横纵坐标数据。"""
    safe_device_id = _safe_device_id(device_id)
    safe_filename = _safe_spc_filename(filename)
    records = _filter_by_batch(spc_store.get(safe_device_id) or [], batch)
    if not records:
        raise HTTPException(status_code=404, detail="SPC file not found")

    target = next((rec for rec in records if rec["stored_filename"] == safe_filename), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Specified SPC file not found")

    return _read_spc_spectrum_data(
        target["path"],
        title=f"{safe_device_id} - {target['stored_filename']}",
    )


@app.post("/spc/blank/upload")
async def upload_blank_spc_file(
    device_id: str = Form(...),
    blank_type: str = Form(...),
    batch: Optional[str] = Form(None),
    spc_file: UploadFile = File(...),
) -> dict[str, Any]:
    """接收来自客户端的参比光谱 SPC 文件（blank_before / blank_after）。"""
    if blank_type not in _ALLOWED_BLANK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 blank_type '{blank_type}'，允许值: {sorted(_ALLOWED_BLANK_TYPES)}",
        )
    return await _save_uploaded_spc(
        device_id=device_id,
        batch=batch,
        spc_file=spc_file,
        kind="blank",
        blank_type=blank_type,
    )


@app.get("/spc/blank/device/{device_id}")
def get_blank_spc_overview(
    device_id: str,
    batch: Optional[str] = Query(None, description="生产单号，不填则返回该设备全部单号"),
    date_from: Optional[str] = Query(
        None, description="起始日期（含），格式 YYYY-MM-DD，如 2025-01-01"
    ),
    date_to: Optional[str] = Query(
        None, description="截止日期（含），格式 YYYY-MM-DD，如 2025-12-31"
    ),
):
    """列出该设备下所有参比光谱类型及文件。可通过 batch / date_from / date_to 筛选。"""
    safe_device_id = _safe_device_id(device_id)
    type_map = blank_spc_store.get(safe_device_id) or {}
    if not type_map:
        raise HTTPException(status_code=404, detail="未找到该设备的参比光谱记录")

    return {
        "device_id": safe_device_id,
        "batch": _safe_generation_batch(batch) if batch else None,
        "date_from": date_from,
        "date_to": date_to,
        "blank_types": {
            bt: {
                "total": len(all_recs),
                "count": len(
                    _filter_by_date(_filter_by_batch(all_recs, batch), date_from, date_to)
                ),
                "files": [
                    _spc_file_summary(rec)
                    for rec in _filter_by_date(
                        _filter_by_batch(all_recs, batch), date_from, date_to
                    )
                ],
            }
            for bt, all_recs in type_map.items()
        },
    }


@app.get("/spc/blank/device/{device_id}/{blank_type}/latest")
def get_latest_blank_spc_file(
    device_id: str,
    blank_type: str,
    batch: Optional[str] = Query(None, description="生产单号，不填则取全部单号最新"),
):
    """下载指定设备、指定类型的最新参比光谱 SPC 文件。"""
    safe_device_id = _safe_device_id(device_id)
    if blank_type not in _ALLOWED_BLANK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 blank_type '{blank_type}'，允许值: {sorted(_ALLOWED_BLANK_TYPES)}",
        )
    records = _filter_by_batch(
        (blank_spc_store.get(safe_device_id) or {}).get(blank_type) or [],
        batch,
    )
    if not records:
        raise HTTPException(status_code=404, detail="未找到该类型参比光谱文件")

    latest = records[-1]
    if not os.path.exists(latest["path"]):
        raise HTTPException(status_code=404, detail="参比光谱 SPC 文件在磁盘上不存在")

    return FileResponse(
        path=latest["path"],
        filename=latest["stored_filename"],
        media_type="application/octet-stream",
    )


@app.get("/spc/blank/device/{device_id}/{blank_type}/files/{filename}")
def get_blank_spc_file_by_name(
    device_id: str,
    blank_type: str,
    filename: str,
    batch: Optional[str] = Query(None, description="生产单号"),
):
    """按文件名下载指定设备、指定类型的参比光谱 SPC 文件。"""
    safe_device_id = _safe_device_id(device_id)
    if blank_type not in _ALLOWED_BLANK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 blank_type '{blank_type}'，允许值: {sorted(_ALLOWED_BLANK_TYPES)}",
        )
    safe_filename = _safe_spc_filename(filename)
    records = _filter_by_batch(
        (blank_spc_store.get(safe_device_id) or {}).get(blank_type) or [],
        batch,
    )
    if not records:
        raise HTTPException(status_code=404, detail="未找到该类型参比光谱文件")

    target = next((rec for rec in records if rec["stored_filename"] == safe_filename), None)
    if target is None:
        raise HTTPException(status_code=404, detail="指定参比光谱 SPC 文件未找到")

    if not os.path.exists(target["path"]):
        raise HTTPException(status_code=404, detail="参比光谱 SPC 文件在磁盘上不存在")

    return FileResponse(
        path=target["path"],
        filename=target["stored_filename"],
        media_type="application/octet-stream",
    )


@app.get("/spc/blank/device/{device_id}/{blank_type}/files/{filename}/data")
def get_blank_spc_file_data(
    device_id: str,
    blank_type: str,
    filename: str,
    batch: Optional[str] = Query(None, description="生产单号"),
):
    """按文件名读取参比光谱 SPC，并返回横纵坐标数据。"""
    safe_device_id = _safe_device_id(device_id)
    if blank_type not in _ALLOWED_BLANK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 blank_type '{blank_type}'，允许值: {sorted(_ALLOWED_BLANK_TYPES)}",
        )
    safe_filename = _safe_spc_filename(filename)
    records = _filter_by_batch(
        (blank_spc_store.get(safe_device_id) or {}).get(blank_type) or [],
        batch,
    )
    if not records:
        raise HTTPException(status_code=404, detail="未找到该类型参比光谱文件")

    target = next((rec for rec in records if rec["stored_filename"] == safe_filename), None)
    if target is None:
        raise HTTPException(status_code=404, detail="指定参比光谱 SPC 文件未找到")

    return _read_spc_spectrum_data(
        target["path"],
        title=f"{safe_device_id} - {blank_type} - {target['stored_filename']}",
    )


@app.get("/spc/search")
def search_spc(
    date_from: Optional[str] = Query(
        None, description="起始日期（含），格式 YYYY-MM-DD，如 2025-01-01"
    ),
    date_to: Optional[str] = Query(
        None, description="截止日期（含），格式 YYYY-MM-DD，如 2025-12-31"
    ),
    device_id: Optional[str] = Query(
        None, description="设备 ID，不填则搜索所有设备"
    ),
    batch: Optional[str] = Query(
        None, description="生产单号，不填则搜索全部单号"
    ),
    spc_type: Optional[str] = Query(
        None,
        description="光谱类型：sample（采样光谱）| dark（暗光谱）| blank_before（置换前参比）| blank_after（清洗后参比），不填则搜索全部类型",
    ),
):
    """跨设备光谱检索：按日期范围、设备 ID、光谱类型搜索 SPC 文件，结果按上传时间降序排列。"""
    if spc_type is not None and spc_type not in ("sample", "dark", *_ALLOWED_BLANK_TYPES):
        raise HTTPException(
            status_code=400,
            detail=f"无效的 spc_type '{spc_type}'，允许值: sample, dark, blank_before, blank_after",
        )

    if device_id:
        safe_id = _safe_device_id(device_id)
        device_ids_to_search: List[str] = [safe_id]
    else:
        all_ids = set(spc_store.keys()) | set(dark_spc_store.keys()) | set(blank_spc_store.keys())
        device_ids_to_search = sorted(all_ids)

    results: List[dict] = []

    # 采样光谱
    if spc_type in (None, "sample"):
        for did in device_ids_to_search:
            for rec in _filter_by_date(
                _filter_by_batch(spc_store.get(did) or [], batch), date_from, date_to
            ):
                results.append(
                    {
                        "device_id": did,
                        "spc_type": "sample",
                        **_spc_file_summary(rec),
                    }
                )

    if spc_type in (None, "dark"):
        for did in device_ids_to_search:
            for rec in _filter_by_date(
                _filter_by_batch(dark_spc_store.get(did) or [], batch), date_from, date_to
            ):
                results.append(
                    {
                        "device_id": did,
                        "spc_type": "dark",
                        **_spc_file_summary(rec),
                    }
                )

    # 参比光谱
    for blank_type in sorted(_ALLOWED_BLANK_TYPES):
        if spc_type in (None, blank_type):
            for did in device_ids_to_search:
                type_recs = (blank_spc_store.get(did) or {}).get(blank_type) or []
                for rec in _filter_by_date(_filter_by_batch(type_recs, batch), date_from, date_to):
                    results.append(
                        {
                            "device_id": did,
                            "spc_type": blank_type,
                            **_spc_file_summary(rec),
                        }
                    )

    results.sort(key=lambda r: r.get("server_time", ""), reverse=True)

    return {
        "total": len(results),
        "date_from": date_from,
        "date_to": date_to,
        "device_id": device_id,
        "batch": _safe_generation_batch(batch) if batch else None,
        "spc_type": spc_type,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 软件版本更新接口
# ---------------------------------------------------------------------------

@app.post("/update/upload")
async def upload_update_package(
    package: UploadFile = File(..., description="软件更新压缩包，文件名须含版本号，如 HY_Monitor_v1.2.3.zip"),
) -> dict[str, Any]:
    """上传新版本软件压缩包到服务器 _updates/ 目录。

    文件命名规范：``<应用名>_v<主>.<次>.<修>.<后缀>``，例如 ``HY_Monitor_v1.2.3.zip``。
    支持后缀：.zip / .tar.gz / .apk / .exe / .dmg / .deb / .rpm。
    """
    original_name = (package.filename or "").strip()
    if not original_name:
        raise HTTPException(status_code=400, detail="缺少文件名")
    name_lower = original_name.lower()
    if not any(name_lower.endswith(ext) for ext in _ALLOWED_UPDATE_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，允许后缀: {sorted(_ALLOWED_UPDATE_SUFFIXES)}",
        )
    if os.path.sep in original_name or "/" in original_name or "\\" in original_name:
        raise HTTPException(status_code=400, detail="无效的文件名")

    ver = _parse_version(original_name)
    if ver == (0, 0, 0):
        raise HTTPException(
            status_code=400,
            detail="文件名中未找到版本号，请使用 AppName_v1.2.3.zip 格式",
        )

    dest_path = UPDATE_STORE_DIR / original_name
    data = await package.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    with open(dest_path, "wb") as f:
        f.write(data)

    logger.info("软件包上传成功: %s  版本: %s  大小: %d bytes", original_name, _version_str(ver), len(data))
    return {
        "status": "ok",
        "filename": original_name,
        "version": _version_str(ver),
        "size": len(data),
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/update/list")
def list_update_packages() -> dict[str, Any]:
    """列出服务器上所有可用的软件更新包（按版本号升序排列）。"""
    packages = _scan_update_packages()
    return {
        "total": len(packages),
        "packages": [
            {
                "filename": p["filename"],
                "version": p["version"],
                "size": p["size"],
                "upload_time": p["upload_time"],
            }
            for p in packages
        ],
    }


@app.get("/update/latest")
def get_latest_update() -> dict[str, Any]:
    """返回最新版本软件包的元信息（不下载文件）。

    客户端可将本地版本与返回的 ``version`` 字段做比较，决定是否需要更新。
    若服务器尚无任何软件包，返回 ``{"available": false}``。
    """
    packages = _scan_update_packages()
    if not packages:
        return {"available": False}
    latest = packages[-1]
    return {
        "available": True,
        "filename": latest["filename"],
        "version": latest["version"],
        "size": latest["size"],
        "upload_time": latest["upload_time"],
        "download_url": f"/update/download/{latest['filename']}",
    }


@app.get("/update/check")
def check_update(
    current_version: str = Query(..., description="客户端当前版本号，格式 X.Y.Z，如 1.0.0"),
) -> dict[str, Any]:
    """检查是否有新版本可用。

    客户端传入当前版本号（如 ``1.0.0``），服务器返回是否需要更新及最新包信息。
    """
    def _parse_ver_str(s: str) -> Tuple[int, int, int]:
        parts = s.strip().lstrip("vV").split(".")
        try:
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return (major, minor, patch)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"无效的版本号格式 '{current_version}'，请使用 X.Y.Z（如 1.0.0）",
            )

    client_ver = _parse_ver_str(current_version)
    packages = _scan_update_packages()
    if not packages:
        return {
            "needs_update": False,
            "current_version": _version_str(client_ver),
            "message": "服务器暂无可用更新包",
        }

    latest = packages[-1]
    server_ver = latest["version_tuple"]
    needs_update = server_ver > client_ver

    resp: dict[str, Any] = {
        "needs_update": needs_update,
        "current_version": _version_str(client_ver),
        "latest_version": latest["version"],
    }
    if needs_update:
        resp.update({
            "filename": latest["filename"],
            "size": latest["size"],
            "upload_time": latest["upload_time"],
            "download_url": f"/update/download/{latest['filename']}",
        })
    return resp


@app.get("/update/download/{filename}")
def download_update_package(filename: str):
    """按文件名下载指定版本的软件更新包。"""
    safe_name = os.path.basename(filename.strip())
    if not safe_name or safe_name in {".", ".."} or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(status_code=400, detail="无效的文件名")

    dest_path = UPDATE_STORE_DIR / safe_name
    if not dest_path.exists() or not dest_path.is_file():
        raise HTTPException(status_code=404, detail=f"软件包 '{safe_name}' 不存在")

    logger.info("软件包下载: %s", safe_name)
    return FileResponse(
        path=str(dest_path),
        filename=safe_name,
        media_type="application/octet-stream",
    )


if __name__ == "__main__":
    logger.info("test1 启动，日志文件: %s", _LOG_FILE)
    uvicorn.run(
        "test1:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_config=_UVICORN_LOG_CONFIG,
    )
