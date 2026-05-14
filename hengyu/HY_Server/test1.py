"""
独立 HTTP 接收端：
- 接收与监控接口 `data` 快照一致（get_snapshot 形状）的设备数据，并保留 device_id。
  每条上送会追加写入 _uploaded_device_data/{安全设备ID}/{生产批次}.csv（无批次则为 _no_batch.csv）。
- 接收来自主服务转换后的 .spc 文件，统一保存到 _upload_spc/{设备}/{批次}/{raw|dark|blank}/。
- 接收来自客户端上报的暗光谱与参比光谱（blank_before / blank_after）.spc 文件。

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
# 传感器上送：按设备、生产批次各占一个 .jsonl（每行一条 JSON）
DEVICE_SENSOR_DIR = Path(__file__).resolve().parent / "_uploaded_device_data"
DEVICE_SENSOR_DIR.mkdir(parents=True, exist_ok=True)
_DEVICE_FILE_LOCK = threading.Lock()
_INVALID_BATCH_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# 工艺/批次参数：客户端只在首次上送时携带，服务端按 device_id 缓存，
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

# CSV 文件结构：
#   第 1 行 — 本批次的工艺参数，每个单元格形如 "key=value"
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
    """生产批次名用作文件名，去除 Windows / Unix 非法字符；空则写入 _no_batch.jsonl。"""
    if generation_batch is None:
        return "_no_batch"
    raw = str(generation_batch).strip()
    if not raw:
        return "_no_batch"
    s = _INVALID_BATCH_FILENAME_RE.sub("_", raw).strip(" .")
    if len(s) > 180:
        s = s[:180]
    return s if s else "_no_batch"


def _apply_process_cache(payload: dict) -> dict:
    """更新设备工艺缓存；若本次未携带则用缓存补齐。原地修改并返回 payload。"""
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return payload
    incoming = {
        k: payload[k]
        for k in _PROCESS_PARAM_KEYS
        if payload.get(k) is not None
    }
    with _process_cache_lock:
        cached = _process_cache.setdefault(device_id, {})
        if incoming:
            cached.update(incoming)
        for k, v in cached.items():
            if payload.get(k) is None:
                payload[k] = v
    return payload


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
    """将单条上送追加到 _uploaded_device_data/{safe_device}/{批次}.csv。

    文件结构：
      行 1 — 工艺参数（key=value，每字段一格）
      行 2 — 传感器表头
      行 3+ — 传感器数据（按时间追加）
    新建文件时写入 UTF-8 BOM 便于 Excel 直接打开。"""
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("payload 缺少 device_id")
    batch_key = _safe_generation_batch(payload.get("generation_batch"))
    safe_dev = _safe_device_id(device_id)
    batch_dir = DEVICE_SENSOR_DIR / safe_dev
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / f"{batch_key}.csv"
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
    """启动时从 DEVICE_SENSOR_DIR 恢复 device_store（与内存列表一致，按时间排序），
    并按设备恢复工艺参数缓存（使用每设备最新的非空字段值）。
    兼容历史 .jsonl 与当前 .csv 两种格式。"""
    if not DEVICE_SENSOR_DIR.exists():
        return
    total_lines = 0
    for device_dir in sorted(DEVICE_SENSOR_DIR.iterdir()):
        if not device_dir.is_dir():
            continue
        # 先读旧 JSONL（兼容历史数据），再读新 CSV
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
            try:
                with open(csv_path, encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.reader(f))
            except OSError as e:
                logger.warning("读取传感器 csv 文件失败，已跳过 %s：%s", csv_path, e)
                continue
            if len(rows) < 2:
                continue
            process = _parse_process_line(rows[0])
            sensor_header = rows[1]
            for raw in rows[2:]:
                if not raw:
                    continue
                row_dict = dict(zip(sensor_header, raw))
                rec = _sensor_row_to_record(row_dict)
                if rec is None:
                    continue
                # 用文件首行的工艺参数补齐传感器记录中缺失的字段
                for k, v in process.items():
                    if rec.get(k) is None:
                        rec[k] = v
                device_store.setdefault(rec["device_id"], []).append(rec)
                total_lines += 1
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

    光谱目录结构：_upload_spc/{device_id}/{batch}/{raw|dark|blank}/*.spc
    文件按修改时间升序排列，与上传顺序保持一致。
    """
    spc_count = 0
    dark_count = 0
    blank_count = 0
    if SPC_STORE_DIR.exists():
        for device_dir in sorted(SPC_STORE_DIR.iterdir()):
            if not device_dir.is_dir():
                continue
            device_id = device_dir.name
            for batch_dir in sorted(device_dir.iterdir()):
                if not batch_dir.is_dir():
                    continue
                batch = batch_dir.name
                for kind_dir in sorted(batch_dir.iterdir()):
                    if not kind_dir.is_dir():
                        continue
                    kind = kind_dir.name
                    if kind not in _ALLOWED_SPC_KINDS:
                        continue
                    files = sorted(kind_dir.glob("*.spc"), key=lambda f: f.stat().st_mtime)
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
    _rebuild_stores_from_disk()


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


def _resolve_spc_batch(device_id: str, safe_device_id: str, batch: Optional[str]) -> str:
    """SPC 批次优先使用上传字段；缺失时使用该设备缓存的 generation_batch。"""
    if batch is not None and str(batch).strip():
        return _safe_generation_batch(batch)
    with _process_cache_lock:
        cached = _process_cache.get(device_id) or _process_cache.get(safe_device_id) or {}
        cached_batch = cached.get("generation_batch")
    return _safe_generation_batch(cached_batch)


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
    """让仅上传光谱、未上传传感器的批次也出现在批次列表中。"""
    for rec in _iter_spc_records_for_device(safe_device_id):
        batch = str(rec.get("batch") or "").strip()
        if not batch:
            continue
        server_time = str(rec.get("server_time") or "")
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
                "spc_count": 0,
                "_sort_ts": sort_ts,
            }
            batch_map[batch] = item
        item["spc_count"] = int(item.get("spc_count") or 0) + 1
        if sort_ts and sort_ts > float(item.get("_sort_ts") or 0.0):
            item["_sort_ts"] = sort_ts
        if server_time and (not item.get("first_time") or server_time < item["first_time"]):
            item["first_time"] = server_time
        if server_time and (not item.get("last_time") or server_time > item["last_time"]):
            item["last_time"] = server_time


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
    safe_batch = _resolve_spc_batch(device_id, safe_device_id, batch)
    original_name = _safe_spc_filename(
        spc_file.filename or f"{kind if kind != 'blank' else blank_type or 'blank'}.spc"
    )
    data = await spc_file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的 SPC 文件为空")

    now = datetime.now()
    server_time = now.strftime("%Y-%m-%d %H:%M:%S")
    device_dir = SPC_STORE_DIR / safe_device_id / safe_batch / kind
    device_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(original_name).stem
    saved_name = f"{stem}_{now.strftime('%Y%m%d_%H%M%S')}.spc"
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
    payload = data.model_dump()
    payload["server_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 客户端只在首次成功时携带工艺/批次参数，后续靠服务端缓存补齐
    _apply_process_cache(payload)

    try:
        _append_device_payload_to_disk(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        logger.exception("写入传感器批次文件失败 device_id=%s", data.device_id)
        raise HTTPException(
            status_code=500, detail=f"无法写入本地传感器批次文件: {e}"
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
    """列出该设备已落盘的所有生产批次。

    扫描 _uploaded_device_data/{safe_device}/*.csv，逐文件解析首行工艺参数与
    传感器记录条数；同时合并仅上传了 SPC、尚无传感器 CSV 的批次。
    结果按最新传感器/SPC 写入时间倒序排列（最近的批次在前）。
    """
    safe_dev = _safe_device_id(device_id)
    device_dir = DEVICE_SENSOR_DIR / safe_dev
    batch_map: Dict[str, dict] = {}
    if device_dir.exists():
        for csv_path in device_dir.glob("*.csv"):
            try:
                with open(csv_path, encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.reader(f))
            except OSError as e:
                logger.warning("读取批次文件失败 %s：%s", csv_path, e)
                continue
            if len(rows) < 2:
                continue
            process = _parse_process_line(rows[0])
            sensor_rows = [r for r in rows[2:] if r and any(c.strip() for c in r)]
            first_time = sensor_rows[0][0] if sensor_rows else None
            last_time = sensor_rows[-1][0] if sensor_rows else None
            batch_map[csv_path.stem] = {
                "batch": csv_path.stem,
                "filename": csv_path.name,
                "count": len(sensor_rows),
                "first_time": first_time,
                "last_time": last_time,
                "process": process,
                "spc_count": 0,
                "_sort_ts": csv_path.stat().st_mtime,
            }
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
    """读取指定批次 CSV，返回该批次的工艺参数与所有传感器记录。

    传感器记录会自动用文件首行的工艺参数补齐缺失字段，方便客户端直接绘图与展示侧栏。
    """
    safe_dev = _safe_device_id(device_id)
    safe_batch = _safe_generation_batch(batch)
    csv_path = DEVICE_SENSOR_DIR / safe_dev / f"{safe_batch}.csv"
    if not csv_path.exists():
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
        raise HTTPException(status_code=500, detail=f"读取批次文件失败：{e}") from e
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
    batch: Optional[str] = Query(None, description="生产批次，不填则返回该设备全部批次"),
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
    batch: Optional[str] = Query(None, description="生产批次，不填则取全部批次最新"),
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
    batch: Optional[str] = Query(None, description="生产批次"),
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
    batch: Optional[str] = Query(None, description="生产批次"),
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
    batch: Optional[str] = Query(None, description="生产批次，不填则返回该设备全部批次"),
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
    batch: Optional[str] = Query(None, description="生产批次，不填则取全部批次最新"),
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
    batch: Optional[str] = Query(None, description="生产批次"),
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
    batch: Optional[str] = Query(None, description="生产批次"),
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
        None, description="生产批次，不填则搜索全部批次"
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
