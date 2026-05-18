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

真实模式（``DEVICE_MODE=real``）：生产结束由 HY_Online **自动控制停止** 触发 HY_Server ``production-end`` 并清除本机单号显示；本脚本不因「两路关」判定结束。

模拟模式（非 real）：在本轮曾经打开过上传 relay、且**至少有一次**向 HY_Server 成功上报传感器或
SPC（含暗/参比）之后，若连续 3 轮轮询均为「两路关」，则依次 POST HY_Server ``production-end``
与主服务 ``/api/order-number/production-end``，并清空本地 ``current_batch`` 与工艺上送标志。
（打开 relay 后若仅同步了单号快照、尚未成功上报任何数据，则**不会**计为已开始采集，避免误触发结束。）

日志中「两路均为关」默认约每 20 轮全关才提示一次；触发生产结束前的若干轮会额外打出 ``已连续全关 x/3`` 便于核对计数。

断网/进程重启：本进程将 current_batch 与工艺参数是否已上送写入 _upload_client_state.json，
恢复后继续写入原单号目录（与 HY_Server 缓存一致依赖客户端重新上送工艺时可设 process_params_uploaded）。

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
from order_number_state import PLACEHOLDER as _ORDER_PLACEHOLDER

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

# 传感器每轮固定上报字段（持续上报）；含 generation_batch 以便 App 手改/下发单号后 HY_Server 能更新归档目录
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
    "generation_batch",
    # ---- 来自 hy_server.BridgeDataManager ----
    "temperature",
    "level",
    "bridge_state",
    "bridge_error",
    "bridge_last_update_ts",
)

# 工艺参数：仅在本进程首次成功上送时随载荷一并发出（单号见上列 generation_batch，每轮都带）
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

DEVICE_ID = os.getenv("HY_ONLINE_DEVICE_ID", "device_002").strip() or "device_002"
RELAY_POLL_INTERVAL_SEC = 1.0
SENSOR_UPLOAD_INTERVAL_SEC = float(os.getenv("SENSOR_UPLOAD_INTERVAL_SEC", "2"))
DEFAULT_SPC_UPLOAD_INTERVAL_SEC = float(os.getenv("SPC_UPLOAD_INTERVAL_SEC", "60"))
# 参比光谱检查间隔：每隔多少秒向主服务查询一次参比光谱状态；
# 实际上传由时间戳去重控制，只在采集到新数据后才推送。
BLANK_SPC_CHECK_INTERVAL_SEC = 30.0
HTTP_TIMEOUT_SEC = 15.0
# 软件更新检查间隔（秒）；启动时立即检查一次，之后按此间隔周期检查
UPDATE_CHECK_INTERVAL_SEC = 3600.0
# 单号拉取：每隔多少秒向 test1 查询一次该设备的当前单号，并将结果写入主服务。
ORDER_NUMBER_POLL_INTERVAL_SEC = float(
    os.getenv("ORDER_NUMBER_POLL_INTERVAL_SEC", "60")
)

# 在「全关」时每隔多少轮打印一次说明（避免刷屏）
_IDLE_LOG_EVERY = 20
_idle_streak = 0
# 模拟模式下连续多少轮「两路关」视为生产结束（通知 production-end）
_MOCK_RELAY_IDLE_END_COUNT = int(os.getenv("MOCK_RELAY_IDLE_END_COUNT", "3"))

_UPLOAD_CLIENT_STATE_PATH = Path(__file__).resolve().parent / "_upload_client_state.json"

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
    if not batch or batch == _ORDER_PLACEHOLDER:
        return None
    return batch


def ensure_current_batch(current_batch: Optional[str]) -> Optional[str]:
    """
    任一路打开时根据传感器快照同步本进程锁定的单号。
    App 手动改单号 / 服务器下发后，快照中的 generation_batch 会变，须重新拉取
    （旧逻辑在 current_batch 非空时直接返回，会导致 SPC 上传仍用旧单号、服务端目录不迁）。
    """
    try:
        snapshot = fetch_sensor_snapshot(DATA_SOURCE_BASE)
        batch = extract_batch_from_snapshot(snapshot)
        if not batch:
            if current_batch is not None:
                logger.info(
                    "单号快照已为占位/空，解除本进程锁定（曾锁定=%r）",
                    current_batch,
                )
            return None
        if batch != current_batch:
            logger.info("当前单号已同步: %r -> %r", current_batch, batch)
        return batch
    except Exception as e:
        logger.warning("读取当前单号失败，沿用本进程锁定: %s", e)
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
        if k not in snapshot:
            continue
        if k == "generation_batch":
            ts = str(snapshot[k]).strip()
            if not ts or ts == _ORDER_PLACEHOLDER:
                continue
        out[k] = snapshot[k]
    if include_process:
        for k in _PROCESS_KEYS:
            if k == "generation_batch":
                continue
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


def fetch_server_order_number(upload_base: str, device_id: str) -> Optional[str]:
    """从 HY_Server 拉取该设备当前单号；服务端不可达或字段缺失时返回 None。"""
    url = upload_base.rstrip("/") + "/device/" + parse.quote(device_id, safe="") + "/order_number"
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urlerror.URLError, OSError, json.JSONDecodeError) as e:
        logger.warning("拉取单号失败 device=%s: %s", device_id, e)
        return None
    if not isinstance(body, dict):
        return None
    raw = body.get("order_number")
    if raw is None:
        return ""  # 服务端显式无值；返回空串以便区分「拉取失败」与「确认清除」
    text = str(raw).strip()
    return text


def push_server_order_number_to_local(data_source_base: str, value: Optional[str]) -> None:
    """将 server 下发的单号写入主服务（HY_Online），由其更新 order_number_state。

    value=None 表示本轮拉取失败，跳过；空串表示服务端确认清除。
    """
    if value is None:
        return
    url = data_source_base.rstrip("/") + "/api/order-number/server"
    payload = json.dumps({"order_number": value or None}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            resp.read()
    except (urlerror.URLError, OSError) as e:
        logger.warning("写入本地单号状态失败: %s", e)


def load_upload_client_state() -> tuple[Optional[str], bool]:
    """恢复上次锁定的单号与工艺上送标志，便于中断后续传同一单号。"""
    if not _UPLOAD_CLIENT_STATE_PATH.is_file():
        return None, False
    try:
        with open(_UPLOAD_CLIENT_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取 upload_client 状态失败 %s: %s", _UPLOAD_CLIENT_STATE_PATH, e)
        return None, False
    if not isinstance(data, dict):
        return None, False
    b = data.get("current_batch")
    batch = str(b).strip() if b is not None and str(b).strip() else None
    proc = bool(data.get("process_params_uploaded"))
    return batch, proc


def save_upload_client_state(current_batch: Optional[str], process_params_uploaded: bool) -> None:
    tmp = _UPLOAD_CLIENT_STATE_PATH.with_suffix(".json.tmp")
    payload = {
        "current_batch": current_batch,
        "process_params_uploaded": process_params_uploaded,
    }
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _UPLOAD_CLIENT_STATE_PATH)
    except OSError as e:
        logger.warning("写入 upload_client 状态失败 %s: %s", _UPLOAD_CLIENT_STATE_PATH, e)


def post_local_production_end(data_source_base: str) -> bool:
    """通知主服务清除 App 侧单号显示（与 HY_Server production-end 配套）。"""
    url = data_source_base.rstrip("/") + "/api/order-number/production-end"
    req = request.Request(url, data=b"", method="POST")
    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            if resp.status != 200:
                logger.warning("production-end 本机单号清除 HTTP %s", resp.status)
                return False
            return True
    except (urlerror.URLError, OSError) as e:
        logger.warning("production-end 本机单号清除失败: %s", e)
        return False


def post_production_end(upload_base: str, device_id: str) -> bool:
    """通知 HY_Server 清除工艺缓存中的单号（本锅结束）。"""
    url = (
        upload_base.rstrip("/")
        + "/device/"
        + parse.quote(device_id, safe="")
        + "/production-end"
    )
    req = request.Request(url, data=b"", method="POST")
    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            if resp.status != 200:
                logger.warning("production-end HTTP %s", resp.status)
                return False
            return True
    except (urlerror.URLError, OSError) as e:
        logger.warning("production-end 请求失败: %s", e)
        return False


def send_sensor_once(include_process: bool = False) -> tuple[bool, Optional[str]]:
    """发送一次传感器载荷。返回 (是否携带工艺参数, 当前单号)。"""
    snapshot = fetch_sensor_snapshot(DATA_SOURCE_BASE)
    payload = build_device_payload(
        DEVICE_ID, snapshot, include_process=include_process
    )
    sensor_raw = post_upload(UPLOAD_URL, payload)
    sent_process = include_process and any(k in payload for k in _PROCESS_KEYS)
    raw_batch = extract_batch_from_snapshot(snapshot) or str(
        payload.get("generation_batch") or ""
    ).strip()
    if raw_batch and raw_batch != _ORDER_PLACEHOLDER:
        batch: Optional[str] = raw_batch
    else:
        batch = None
    logger.info(
        "sensor 上传响应: %s%s",
        sensor_raw,
        "（含工艺参数，本进程仅此一次）" if sent_process else "",
    )
    return sent_process, batch


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
    loaded_batch, loaded_proc = load_upload_client_state()
    process_params_uploaded: bool = loaded_proc
    current_batch: Optional[str] = loaded_batch
    if current_batch is not None:
        logger.info("已从状态文件恢复生产单号锁定: %s", current_batch)
    spc_upload_interval_sec: float = DEFAULT_SPC_UPLOAD_INTERVAL_SEC
    # 参比光谱：记录上次检查时刻（wall clock）与上次已上传的 source_timestamp（去重）
    last_blank_check_at: Optional[float] = None
    last_blank_spc_ts: Dict[str, float] = {bt: 0.0 for bt in _BLANK_TYPES}
    last_dark_spc_ts: float = 0.0
    # 上次软件更新检查时刻（monotonic）；启动时已检查过，故初始化为当前时刻
    last_update_check_at: float = time.monotonic()
    # 单号轮询：与上传开关无关，独立按间隔从 HY_Server 拉取；
    # 仅在变化时同步到主服务，避免在 _logs 中刷屏。
    last_order_poll_at: float = 0.0
    last_pushed_order_value: Optional[str] = None  # None=尚未推送任何值；"" 与具体单号都属于已知状态
    # 本轮是否曾打开过上传 relay（模拟模式下「两路关×3」结束需曾进入过上传过程）
    relay_ever_active_this_session = False
    # 本轮是否已向 HY_Server 成功上报过传感器/SPC 等数据（仅凭 relay 曾开不足以触发 production-end）
    mock_had_server_upload_this_session = False

    while True:
        try:
            now = time.monotonic()
            device_mode = os.getenv("DEVICE_MODE", "mock").lower()

            # ---- 定期单号拉取（与上传开关无关，始终执行）----
            if now - last_order_poll_at >= ORDER_NUMBER_POLL_INTERVAL_SEC:
                last_order_poll_at = now
                order_val = fetch_server_order_number(UPLOAD_BASE, DEVICE_ID)
                if order_val is not None and order_val != last_pushed_order_value:
                    push_server_order_number_to_local(DATA_SOURCE_BASE, order_val)
                    last_pushed_order_value = order_val
                    logger.info(
                        "server 单号已同步到本地: %r",
                        order_val if order_val else "(空，清除)",
                    )

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

            if us or up:
                relay_ever_active_this_session = True

            if not us:
                last_sensor_upload_at = None
            if not up:
                last_spc_upload_at = None
                last_blank_check_at = None

            if not us and not up:
                _idle_streak += 1
                if _idle_streak % _IDLE_LOG_EVERY == 1:
                    logger.info(
                        "两路均为关（请 POST 主服务 /api/upload-relay/start），不向上报…"
                        "  （约每 %s 轮提示一次；触发生产结束前会另行打印全关计数）",
                        _IDLE_LOG_EVERY,
                    )
                if (
                    device_mode != "real"
                    and relay_ever_active_this_session
                    and mock_had_server_upload_this_session
                    and _idle_streak <= _MOCK_RELAY_IDLE_END_COUNT
                ):
                    logger.info(
                        "模拟模式：两路均为关，已连续全关 %s/%s 轮（仅统计「已成功上报」之后的全关轮次）",
                        _idle_streak,
                        _MOCK_RELAY_IDLE_END_COUNT,
                    )
                if (
                    device_mode != "real"
                    and relay_ever_active_this_session
                    and mock_had_server_upload_this_session
                    and _idle_streak >= _MOCK_RELAY_IDLE_END_COUNT
                ):
                    if post_production_end(UPLOAD_BASE, DEVICE_ID):
                        post_local_production_end(DATA_SOURCE_BASE)
                        logger.info(
                            "模拟模式：已连续 %s 轮两路关（先成功上报再计数），已通知服务端与主服务生产结束并清除本地单号锁定",
                            _MOCK_RELAY_IDLE_END_COUNT,
                        )
                        current_batch = None
                        process_params_uploaded = False
                        save_upload_client_state(None, False)
                        _idle_streak = 0
                        relay_ever_active_this_session = False
                        mock_had_server_upload_this_session = False
                    else:
                        logger.warning(
                            "模拟模式：已连续 %s 轮两路关，但 production-end 通知失败，保留本地单号锁定",
                            _MOCK_RELAY_IDLE_END_COUNT,
                        )
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
                if device_mode != "real":
                    mock_had_server_upload_this_session = True
                save_upload_client_state(current_batch, process_params_uploaded)

            if up and (
                last_spc_upload_at is None
                or now - last_spc_upload_at >= spc_upload_interval_sec
            ):
                try:
                    send_spc_once(batch=current_batch)
                    last_spc_upload_at = time.monotonic()
                    if device_mode != "real":
                        mock_had_server_upload_this_session = True
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
                        if device_mode != "real":
                            mock_had_server_upload_this_session = True
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
                            if device_mode != "real":
                                mock_had_server_upload_this_session = True
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
