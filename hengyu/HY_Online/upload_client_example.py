"""
独立上报客户端（与主服务分离进程）：

1. 每轮先 GET 主服务 /api/upload-relay/status，根据 upload_sensor / upload_spc 决定是否
   - 拉 /hy-device/sensors 并 POST 到 test1
   - 拉 /spc/convert-current-spectrum 并上传 SPC
2. 两路开关由主服务暴露，**前端**可调用：
   - POST /api/upload-relay/start  — 两路开
   - POST /api/upload-relay/stop   — 两路关
   - POST /api/upload-relay/set   — 单独设某路
3. 默认主服务上两开关为**关**；本脚本在「全关」时只睡眠，不向上游 test1 推数据。

环境：DATA_SOURCE_BASE 为主服务，UPLOAD_BASE 为 test1 根地址。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib import error as urlerror
from urllib import parse
from urllib import request

from version import APP_VERSION
import update_manager

# ---- 日志配置：同时输出到终端和按日期滚动的日志文件 ----
_LOG_DIR = Path(__file__).resolve().parent / "_logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / f"upload_client_{time.strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("upload_client")

# 主服务（与 start.py 端口一致，含 upload-relay 与传感器/SPC 接口）
DATA_SOURCE_BASE = "http://127.0.0.1:8000"
# 上报服务根地址（如 test1.py:8001，实际 POST 到 /upload 与 /spc/upload）
#UPLOAD_BASE = "http://192.168.0.103:5000"
UPLOAD_BASE = "http://127.0.0.1:8001"
UPLOAD_URL = UPLOAD_BASE.rstrip("/") + "/upload"
SPC_UPLOAD_URL = UPLOAD_BASE.rstrip("/") + "/spc/upload"
DARK_SPC_UPLOAD_URL = UPLOAD_BASE.rstrip("/") + "/spc/dark/upload"
BLANK_SPC_UPLOAD_URL = UPLOAD_BASE.rstrip("/") + "/spc/blank/upload"

_RELAY_STATUS_PATH = "/api/upload-relay/status"

# 传感器每轮固定上报字段（持续上报）
_SNAPSHOT_KEYS = (
    "ddl",
    "ph",
    "ph_temp",
    "pt100",
    "valves",
    "is_alarming",
    "fan_speed",
    "fan_read_ok",
    "fan_last_error",
    "fan_last_read_ts",
    "last_update_ts",
    "last_error",
    "running",
    "interval",
    # ---- 来自 hy_server.BridgeDataManager ----
    "temperature",
    "level",
    "bridge_state",
    "bridge_error",
    "bridge_last_update_ts",
)

# 工艺/批次参数：仅在本进程首次成功上送时随载荷一并发出，之后由服务端按设备缓存补齐
_PROCESS_KEYS = (
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

DEVICE_ID = "device_002"
RELAY_POLL_INTERVAL_SEC = 1.0
SENSOR_UPLOAD_INTERVAL_SEC = float(os.getenv("SENSOR_UPLOAD_INTERVAL_SEC", "2"))
DEFAULT_SPC_UPLOAD_INTERVAL_SEC = float(os.getenv("SPC_UPLOAD_INTERVAL_SEC", "5"))
# 参比光谱检查间隔：每隔多少秒向主服务查询一次参比光谱状态；
# 实际上传由时间戳去重控制，只在采集到新数据后才推送。
BLANK_SPC_CHECK_INTERVAL_SEC = 30.0
HTTP_TIMEOUT_SEC = 15.0
# 软件更新检查间隔（秒）；启动时立即检查一次，之后按此间隔周期检查
UPDATE_CHECK_INTERVAL_SEC = 3600.0

# 在「全关」时每隔多少轮打印一次说明（避免刷屏）
_IDLE_LOG_EVERY = 20
_idle_streak = 0

_BLANK_TYPES = ("blank_before", "blank_after")


def fetch_relay_flags(base: str) -> Optional[Tuple[bool, bool, float]]:
    """
    返回 (upload_sensor, upload_spc, spc_upload_interval_sec)；
    若主服务不可达或 JSON 异常则 None（本轮回避上传）。
    """
    url = base.rstrip("/") + _RELAY_STATUS_PATH
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urlerror.URLError, OSError, json.JSONDecodeError) as e:
        logger.error("无法读取 upload-relay 状态，本轮回避上传: %s", e)
        return None
    if not body.get("success"):
        logger.warning("upload-relay 响应 success=false: %s", body)
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        logger.warning("upload-relay 缺少 data 对象")
        return None
    try:
        spc_interval = float(
            data.get("spc_upload_interval_sec", DEFAULT_SPC_UPLOAD_INTERVAL_SEC)
        )
    except (TypeError, ValueError):
        spc_interval = DEFAULT_SPC_UPLOAD_INTERVAL_SEC
    return bool(data.get("upload_sensor")), bool(data.get("upload_spc")), max(1.0, spc_interval)


def fetch_sensor_snapshot(base: str) -> Dict[str, Any]:
    url = base.rstrip("/") + "/hy-device/sensors"
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"/hy-device/sensors 失败: {body}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("响应缺少 data 对象")
    return data


def extract_batch_from_snapshot(snapshot: Dict[str, Any]) -> Optional[str]:
    batch = str(snapshot.get("generation_batch") or "").strip()
    return batch or None


def ensure_current_batch(current_batch: Optional[str]) -> Optional[str]:
    """
    任一上传通道打开时都先读取一次传感器快照。
    模拟模式下这会触发/读取进程内唯一的 generation_batch；
    后打开的通道复用 current_batch，不再重新生成。
    """
    if current_batch:
        return current_batch
    try:
        snapshot = fetch_sensor_snapshot(DATA_SOURCE_BASE)
        batch = extract_batch_from_snapshot(snapshot)
        if batch:
            logger.info("当前批次已锁定: %s", batch)
            return batch
    except Exception as e:
        logger.warning("读取当前批次失败，后续由服务端兜底: %s", e)
    return current_batch


def fetch_current_spc(base: str) -> tuple[str, bytes]:
    convert_url = base.rstrip("/") + "/spc/convert-current-spectrum"
    convert_req = request.Request(convert_url, method="GET")
    with request.urlopen(convert_req, timeout=HTTP_TIMEOUT_SEC) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if not body.get("success"):
        raise RuntimeError(f"/spc/convert-current-spectrum 失败: {body}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("SPC 转换响应缺少 data 对象")

    file_name = str(data.get("file_name") or "").strip()
    if not file_name:
        raise RuntimeError("SPC 转换响应缺少 file_name")

    download_url = base.rstrip("/") + "/spc/download/" + parse.quote(file_name)
    download_req = request.Request(download_url, method="GET")
    with request.urlopen(download_req, timeout=HTTP_TIMEOUT_SEC) as resp:
        spc_bytes = resp.read()

    if not spc_bytes:
        raise RuntimeError(f"下载到的 SPC 文件为空: {file_name}")

    return file_name, spc_bytes


def build_device_payload(
    device_id: str,
    snapshot: Dict[str, Any],
    include_process: bool = False,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"device_id": device_id}
    for k in _SNAPSHOT_KEYS:
        if k in snapshot:
            out[k] = snapshot[k]
    if include_process:
        for k in _PROCESS_KEYS:
            v = snapshot.get(k)
            if v is not None:
                out[k] = v
    return out


def post_upload(upload_url: str, payload: Dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        upload_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
        return response.read().decode("utf-8")


def _multipart_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def post_spc_upload(
    upload_url: str,
    device_id: str,
    file_name: str,
    spc_bytes: bytes,
    batch: Optional[str] = None,
) -> str:
    boundary = "----HYBoundary" + uuid.uuid4().hex
    filename = file_name if file_name.lower().endswith(".spc") else f"{file_name}.spc"
    payload = _multipart_field(boundary, "device_id", device_id)
    if batch:
        payload += _multipart_field(boundary, "batch", batch)
    payload += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="spc_file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + spc_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = request.Request(
        upload_url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
        return response.read().decode("utf-8")


def post_blank_spc_upload(
    upload_url: str,
    device_id: str,
    blank_type: str,
    file_name: str,
    spc_bytes: bytes,
    batch: Optional[str] = None,
) -> str:
    """将参比光谱 SPC 文件上报到 /spc/blank/upload，携带 blank_type 字段。"""
    boundary = "----HYBoundary" + uuid.uuid4().hex
    filename = file_name if file_name.lower().endswith(".spc") else f"{file_name}.spc"
    payload = _multipart_field(boundary, "device_id", device_id)
    payload += _multipart_field(boundary, "blank_type", blank_type)
    if batch:
        payload += _multipart_field(boundary, "batch", batch)
    payload += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="spc_file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + spc_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = request.Request(
        upload_url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
        return response.read().decode("utf-8")


def fetch_blank_spc(base: str, blank_type: str) -> tuple[str, bytes, float]:
    """
    获取指定类型最新参比光谱对应的 SPC 文件。
    返回 (file_name, spc_bytes, source_timestamp)。
    若尚无该类型参比光谱，抛 RuntimeError（消息含 "404"）。
    """
    convert_url = (
        base.rstrip("/")
        + "/spc/blank/convert-latest"
        + f"?blank_type={parse.quote(blank_type)}"
    )
    req = request.Request(convert_url, method="GET")
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if not body.get("success"):
        raise RuntimeError(f"/spc/blank/convert-latest [{blank_type}] 失败: {body}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"参比光谱 SPC 转换响应缺少 data 对象 [{blank_type}]")

    file_name = str(data.get("file_name") or "").strip()
    if not file_name:
        raise RuntimeError(f"参比光谱 SPC 转换响应缺少 file_name [{blank_type}]")

    source_timestamp = float(data.get("source_timestamp") or 0)

    download_url = base.rstrip("/") + "/spc/download/" + parse.quote(file_name)
    dl_req = request.Request(download_url, method="GET")
    with request.urlopen(dl_req, timeout=HTTP_TIMEOUT_SEC) as resp:
        spc_bytes = resp.read()

    if not spc_bytes:
        raise RuntimeError(f"下载到的参比光谱 SPC 文件为空: {file_name}")

    return file_name, spc_bytes, source_timestamp


def fetch_dark_spc(base: str) -> tuple[str, bytes, float]:
    """获取最新暗光谱对应的 SPC 文件，返回 (file_name, spc_bytes, source_timestamp)。"""
    convert_url = base.rstrip("/") + "/spc/dark/convert-latest"
    req = request.Request(convert_url, method="GET")
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if not body.get("success"):
        raise RuntimeError(f"/spc/dark/convert-latest 失败: {body}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("暗光谱 SPC 转换响应缺少 data 对象")
    file_name = str(data.get("file_name") or "").strip()
    if not file_name:
        raise RuntimeError("暗光谱 SPC 转换响应缺少 file_name")
    source_timestamp = float(data.get("source_timestamp") or 0)

    download_url = base.rstrip("/") + "/spc/download/" + parse.quote(file_name)
    dl_req = request.Request(download_url, method="GET")
    with request.urlopen(dl_req, timeout=HTTP_TIMEOUT_SEC) as resp:
        spc_bytes = resp.read()
    if not spc_bytes:
        raise RuntimeError(f"下载到的暗光谱 SPC 文件为空: {file_name}")
    return file_name, spc_bytes, source_timestamp


def send_sensor_once(include_process: bool = False) -> tuple[bool, Optional[str]]:
    """发送一次传感器载荷。返回 (是否携带工艺参数, 当前批次)。"""
    snapshot = fetch_sensor_snapshot(DATA_SOURCE_BASE)
    payload = build_device_payload(
        DEVICE_ID, snapshot, include_process=include_process
    )
    sensor_raw = post_upload(UPLOAD_URL, payload)
    sent_process = include_process and any(k in payload for k in _PROCESS_KEYS)
    batch = extract_batch_from_snapshot(snapshot) or str(
        payload.get("generation_batch") or ""
    ).strip()
    logger.info(
        "sensor 上传响应: %s%s",
        sensor_raw,
        "（含工艺参数，本进程仅此一次）" if sent_process else "",
    )
    return sent_process, (batch or None)


def send_spc_once(batch: Optional[str] = None) -> None:
    spc_name, spc_bytes = fetch_current_spc(DATA_SOURCE_BASE)
    spc_raw = post_spc_upload(SPC_UPLOAD_URL, DEVICE_ID, spc_name, spc_bytes, batch=batch)
    logger.info("spc 上传响应: %s", spc_raw)


if __name__ == "__main__":
    logger.info("upload_client 启动  版本: %s  日志文件: %s", APP_VERSION, _LOG_FILE)
    logger.info(
        "DEVICE_MODE=%s  传感器上传间隔=%s 秒（工艺参数仅首次上送），采样 SPC 上传间隔跟随 App 光谱查询间隔（默认 %s 秒）",
        os.getenv("DEVICE_MODE", "mock"),
        SENSOR_UPLOAD_INTERVAL_SEC,
        DEFAULT_SPC_UPLOAD_INTERVAL_SEC,
    )

    # ---- 启动时立即检查软件更新（有更新则仅下载，不自动应用）----
    try:
        update_manager.check_and_download(UPLOAD_BASE, APP_VERSION)
    except Exception as _ue:
        logger.error("更新检查异常，继续正常运行: %s", _ue)

    last_sensor_upload_at: Optional[float] = None
    last_spc_upload_at: Optional[float] = None
    process_params_uploaded: bool = False
    current_batch: Optional[str] = None
    spc_upload_interval_sec: float = DEFAULT_SPC_UPLOAD_INTERVAL_SEC
    # 参比光谱：记录上次检查时刻（wall clock）与上次已上传的 source_timestamp（去重）
    last_blank_check_at: Optional[float] = None
    last_blank_spc_ts: Dict[str, float] = {bt: 0.0 for bt in _BLANK_TYPES}
    last_dark_spc_ts: float = 0.0
    # 上次软件更新检查时刻（monotonic）；启动时已检查过，故初始化为当前时刻
    last_update_check_at: float = time.monotonic()

    while True:
        try:
            now = time.monotonic()

            # ---- 定期软件更新检查（与上传开关状态无关，始终执行）----
            if now - last_update_check_at >= UPDATE_CHECK_INTERVAL_SEC:
                last_update_check_at = now
                try:
                    update_manager.check_and_download(UPLOAD_BASE, APP_VERSION)
                except Exception as _ue:
                    logger.error("定期更新检查异常: %s", _ue)

            flags = fetch_relay_flags(DATA_SOURCE_BASE)
            if flags is None:
                time.sleep(RELAY_POLL_INTERVAL_SEC)
                continue
            us, up, spc_upload_interval_sec = flags

            if not us:
                last_sensor_upload_at = None
            if not up:
                last_spc_upload_at = None
                last_blank_check_at = None

            if not us and not up:
                _idle_streak += 1
                if _idle_streak % _IDLE_LOG_EVERY == 1:
                    logger.info("两路均为关（请 POST 主服务 /api/upload-relay/start），不向上报…")
                time.sleep(RELAY_POLL_INTERVAL_SEC)
                continue

            _idle_streak = 0
            if us or up:
                current_batch = ensure_current_batch(current_batch)

            if us and (
                last_sensor_upload_at is None
                or now - last_sensor_upload_at >= SENSOR_UPLOAD_INTERVAL_SEC
            ):
                sent_process, batch = send_sensor_once(
                    include_process=not process_params_uploaded
                )
                if batch:
                    current_batch = batch
                last_sensor_upload_at = time.monotonic()
                if sent_process:
                    process_params_uploaded = True

            if up and (
                last_spc_upload_at is None
                or now - last_spc_upload_at >= spc_upload_interval_sec
            ):
                try:
                    send_spc_once(batch=current_batch)
                    last_spc_upload_at = time.monotonic()
                except Exception as e:
                    logger.error("SPC 步骤失败（传感器可能已上传）: %s", e)

            # ---- 参比光谱上传（复用 upload_spc 开关，按时间戳去重，仅在新数据到达时上传）----
            if up and (
                last_blank_check_at is None
                or now - last_blank_check_at >= BLANK_SPC_CHECK_INTERVAL_SEC
            ):
                last_blank_check_at = time.monotonic()
                try:
                    dfile_name, dspc_bytes, dts = fetch_dark_spc(DATA_SOURCE_BASE)
                    if dts > last_dark_spc_ts:
                        dspc_raw = post_spc_upload(
                            DARK_SPC_UPLOAD_URL,
                            DEVICE_ID,
                            dfile_name,
                            dspc_bytes,
                            batch=current_batch,
                        )
                        last_dark_spc_ts = dts
                        logger.info("dark_spc 上传响应: %s", dspc_raw)
                except urlerror.HTTPError as e:
                    if e.code != 404:
                        logger.error(
                            "暗光谱 HTTP %s: %s",
                            e.code,
                            e.read().decode("utf-8", errors="replace"),
                        )
                except Exception as e:
                    logger.error("暗光谱步骤失败: %s", e)

                for blank_type in _BLANK_TYPES:
                    try:
                        bfile_name, bspc_bytes, bts = fetch_blank_spc(
                            DATA_SOURCE_BASE, blank_type
                        )
                        if bts > last_blank_spc_ts[blank_type]:
                            bspc_raw = post_blank_spc_upload(
                                BLANK_SPC_UPLOAD_URL,
                                DEVICE_ID,
                                blank_type,
                                bfile_name,
                                bspc_bytes,
                                batch=current_batch,
                            )
                            last_blank_spc_ts[blank_type] = bts
                            logger.info("blank_spc [%s] 上传响应: %s", blank_type, bspc_raw)
                    except urlerror.HTTPError as e:
                        if e.code != 404:
                            logger.error(
                                "参比光谱 [%s] HTTP %s: %s",
                                blank_type,
                                e.code,
                                e.read().decode("utf-8", errors="replace"),
                            )
                    except Exception as e:
                        logger.error("参比光谱 [%s] 步骤失败: %s", blank_type, e)

        except urlerror.HTTPError as e:
            logger.error("HTTP %s: %s", e.code, e.read().decode("utf-8", errors="replace"))
        except urlerror.URLError as e:
            logger.error("网络错误: %s", e.reason)
        except Exception as e:
            logger.error("未预期错误: %s", e)
        time.sleep(RELAY_POLL_INTERVAL_SEC)
