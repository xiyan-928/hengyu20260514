"""
FastAPI 主应用程序
提供CDS350光谱仪和HY设备的API接口
支持真实设备模式和模拟设备模式切换
"""

from fastapi import FastAPI, HTTPException, status, Request
from fastapi import File, Form, UploadFile
from fastapi_offline import FastAPIOffline
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
import logging
import traceback
import os
import sys
import asyncio
import urllib.error
import urllib.request
import urllib.parse
import datetime
import time
import json
#--------------------------------------
import threading
#--------------------------------------

from hy_logging import configure_hy_logging
#--------------------------------------
from edge_device_data import DeviceData
#--------------------------------------

configure_hy_logging()

# 添加Devices目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'Devices'))

from Devices.hy_device import DeviceConfig, reset_devices, SensorDataManager
from hy_server import BridgeDataManager
from Devices.get_spc import write_spc, convert_spectrum_to_spc
from Devices.device_settings import DeviceSettings
from Devices.drivers import DriverFactory
from config import app_config

#-------------------------------------------
from upload_relay_state import as_dict as upload_relay_as_dict
from upload_relay_state import set_both as upload_relay_set_both
from upload_relay_state import set_partial as upload_relay_set_partial
#-------------------------------------------
import order_number_state
#-------------------------------------------

from device_factory import DeviceFactory
from spectrum_manager import spectrum_manager
from pymodbus.client.sync import ModbusTcpClient

from auto_control_context import AutoControlContext
from auto_control_manager import AutoControlManager
from auto_control_script_engine import get_script_engine, load_auto_control_scripts_at_startup
from Devices.modbus_ephemeral import run_ephemeral
from hy_logging import LOG_SIGNAL
from modbus_logging import modbus_context
from light_source_service import write_coil as write_light_coil

logger = logging.getLogger(__name__)

# 与 upload_client_example 默认一致；可用 HY_SERVER_UPLOAD_BASE 或 UPLOAD_BASE 覆盖
_DEFAULT_HY_SERVER_UPLOAD_BASE = "http://127.0.0.1:8001"


def _resolve_hy_server_upload_base() -> str:
    return (
        os.getenv("HY_SERVER_UPLOAD_BASE") or os.getenv("UPLOAD_BASE") or _DEFAULT_HY_SERVER_UPLOAD_BASE
    ).strip().rstrip("/")


def _resolve_device_id_for_hy_server_sync() -> str:
    did = (order_number_state.get_device_id() or "").strip()
    if did:
        return did
    return (os.getenv("HY_ONLINE_DEVICE_ID") or "device_002").strip()


def _sync_effective_order_to_hy_server() -> Dict[str, Any]:
    """将当前生效单号 POST 到 HY_Server，以更新工艺缓存并触发 ``_upload_spc`` 归档目录重命名。

    返回字典供接口写入 ``hy_server_sync``；未配置环境变量时使用与 upload_client 相同的默认地址。
    """
    base = _resolve_hy_server_upload_base()
    if not base:
        msg = "HY_Server 根地址为空"
        logger.warning(msg)
        return {"ok": False, "skipped": True, "message": msg}
    did = _resolve_device_id_for_hy_server_sync()
    if not did:
        msg = "device_id 为空，无法同步到 HY_Server"
        logger.warning(msg)
        return {"ok": False, "skipped": True, "message": msg}
    snap = order_number_state.snapshot()
    eff = str(snap.get("effective") or "").strip()
    url = f"{base}/device/{urllib.parse.quote(did, safe='')}/order_number"
    if eff and eff != order_number_state.PLACEHOLDER:
        body = json.dumps({"order_number": eff}, ensure_ascii=False).encode("utf-8")
    else:
        body = json.dumps({"order_number": None}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp.read()
        logger.info("已将生效单号同步到 HY_Server device=%s base=%s", did, base)
        return {"ok": True, "base": base, "device_id": did, "url": url}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        logger.warning("同步单号到 HY_Server HTTP %s: %s", e.code, detail)
        return {"ok": False, "base": base, "device_id": did, "http_status": e.code, "detail": detail}
    except urllib.error.URLError as e:
        logger.warning("同步单号到 HY_Server 失败: %s", e)
        return {"ok": False, "base": base, "device_id": did, "detail": str(e.reason or e)}


# 创建FastAPI应用
app = FastAPIOffline(
    title=f"HY Online API - {app_config.get_mode_description()}",
    description=f"恒宇在线监测系统API接口\n当前运行模式: {app_config.get_mode_description()}",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 添加请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """仅记录未捕获的请求异常（成功请求不打日志）。"""
    start_time = time.time()
    try:
        return await call_next(request)
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(
            f"请求异常 | {request.method} {request.url.path} | "
            f"耗时 {process_time:.3f}s | {e}"
        )
        raise

# 全局设备实例
# 在模拟模式下启用HY设备的模拟功能
device_config = DeviceConfig(mock_mode=app_config.is_mock_mode())
cds350_device = None

# 自动控制管理器
def get_or_init_cds350_device():
    global cds350_device
    if cds350_device is None:
        logger.debug("自动控制: CDS350设备未初始化，尝试自动初始化...")
        try:
            cds350_device = DeviceFactory.create_cds350_device()
            # 尝试初始化
            result = cds350_device.initialize_device()
            logger.debug(f"自动控制: CDS350设备自动初始化成功: {result}")
        except Exception as e:
            logger.error(f"自动控制: CDS350设备自动初始化失败: {e}")
            return None
    return cds350_device

auto_control_manager = AutoControlManager(get_or_init_cds350_device)


def _set_spectrum_light_source(enabled: bool) -> None:
    """供暗光谱采集使用：True=开光源，False=关光源。"""
    write_light_coil(enabled)


spectrum_manager.set_light_controller(_set_spectrum_light_source)
spectrum_manager.set_dark_correction(enabled=app_config.is_real_mode())


def _http_apply_script_mode(mode_name: str) -> None:
    """按 script_define 单次写线圈（独立连接，不占用自动控制线程的 client）。"""
    settings = DeviceSettings.instance()
    cfg = settings.get_auto_control_settings()
    host, port = settings.get_modbus_coils_endpoint()
    unit_id = int(cfg.get("unit_id", 1))
    monitor_register = int(cfg.get("monitor_register", 1))
    eng = get_script_engine()
    if mode_name not in eng.registry.mode_segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知模式: {mode_name!r}",
        )

    LOG_SIGNAL.info(
        f"HTTP apply-mode: 准备写模式 {mode_name!r} 到线圈端点 {host}:{port} unit={unit_id}"
    )

    def task(client: ModbusTcpClient) -> None:
        ctx = AutoControlContext(
            settings=settings,
            modbus_client=None,
            modbus_host=cfg.get("modbus_host", "localhost"),
            modbus_port=int(cfg.get("modbus_port", 5020)),
            coils_modbus_client=client,
            coils_modbus_host=host,
            coils_modbus_port=port,
            modbus_unit_id=unit_id,
            monitor_register=monitor_register,
            get_cds350_device=get_or_init_cds350_device,
        )
        eng.write_mode(mode_name, ctx)

    try:
        run_ephemeral(
            host,
            port,
            task,
            context=modbus_context(
                source="http_apply_mode",
                request_name="apply_mode",
                mode_name=mode_name,
            ),
        )
    except Exception as e:
        logger.error(
            f"HTTP apply-mode: 连接或写入失败 mode={mode_name!r} endpoint={host}:{port} unit={unit_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"无法连接线圈 Modbus {host}:{port}",
        )

    LOG_SIGNAL.info(
        f"HTTP apply-mode: 已写模式 {mode_name!r} 到线圈端点 {host}:{port} unit={unit_id}"
    )


# 后台任务管理
background_tasks = {}  # 存储后台任务的字典

#-------------------------------------------
# POST /upload 边缘数据缓冲（载荷校验同 test1.DeviceData，见 edge_device_data.py）
_upload_store_lock = threading.Lock()
_upload_store: Dict[str, List[Dict[str, Any]]] = {}
_UPLOAD_MAX_PER_DEVICE = 5000
#-------------------------------------------
#-------------------------------------------
# POST /spc/upload 接收的 SPC 元数据缓冲
_spc_upload_store_lock = threading.Lock()
_spc_upload_store: Dict[str, List[Dict[str, Any]]] = {}
_SPC_UPLOAD_MAX_PER_DEVICE = 5000
#-------------------------------------------
#-------------------------------------------
# POST /spc/blank/upload 接收的参比光谱 SPC 元数据缓冲
# 结构：{device_id: {blank_type: [record, ...]}}
_blank_spc_upload_store_lock = threading.Lock()
_blank_spc_upload_store: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_BLANK_SPC_UPLOAD_MAX_PER_DEVICE = 5000
_ALLOWED_BLANK_UPLOAD_TYPES = {"blank_before", "blank_after"}
#-------------------------------------------

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
#-------------------------------------------

# Pydantic模型定义
class DeviceAddress(BaseModel):
    """设备地址模型"""
    ip: str = Field(..., description="设备IP地址", example="192.168.1.12")
    port: int = Field(..., description="设备端口号", example=502)

class DeviceQuery(BaseModel):
    """设备查询模型"""
    device_type: str = Field(..., description="设备类型", example="PH")

class ValveControlRequest(BaseModel):
    """阀门/线圈控制：点位名称须与 script_define「基础点位配置」中的「名称」列一致"""

    point_name: str = Field(
        ...,
        min_length=1,
        description="script_define 基础点位名称（如 进水阀、光源）",
        example="进水阀",
    )
    action: str = Field(..., description="操作类型", example="ON", pattern="^(ON|OFF)$")

class MonitorControlRequest(BaseModel):
    """监控控制请求模型"""
    action: str = Field(..., description="操作类型: start/stop", pattern="^(start|stop)$")
    interval: float = Field(2.0, description="更新间隔(秒)", ge=0.1)

#-------------------------------------------
class UploadRelaySetRequest(BaseModel):
    """细粒度设置 upload_client_example 是否向上报服务推送；未传入的字段保持原样。"""

    upload_sensor: Optional[bool] = Field(
        default=None, description="是否允许上传 /hy-device/sensors 对应 JSON 到 test1 等"
    )
    upload_spc: Optional[bool] = Field(
        default=None, description="是否允许 SPC 转换并上传到 test1 等"
    )

#-------------------------------------------
class OrderNumberManualRequest(BaseModel):
    """前端 HY_APP 手动输入的单号；传 null 或空字符串等价于清除。"""

    order_number: Optional[str] = Field(
        default=None,
        description="单号文本，前端手动输入；为空字符串/null 时清除手动值",
    )

#-------------------------------------------

class WarmupChoiceRequest(BaseModel):
    """开机预热选择：是否通水冲洗"""
    with_water: bool = Field(..., description="True=通水预热 needs_warmup，False=跳过并标记已预热")

#-------------------------------------------
class BlankAcquireRequest(BaseModel):
    """手动触发参比光谱采集请求"""
    blank_type: str = Field(
        ...,
        description="参比光谱类型：blank_before（置换前）或 blank_after（清洗后）",
        pattern="^(blank_before|blank_after)$",
    )
#-------------------------------------------

class ApplyModeRequest(BaseModel):
    """按模式名写线圈（与 script_define 模式定义一致）"""
    mode: str = Field(..., description="模式名", min_length=1)

class CDS350Config(BaseModel):
    """CDS350配置模型"""
    integration_time: Optional[int] = Field(
        None, ge=60, description="积分时间(微秒)", example=10000
    )
    scans_to_average: Optional[int] = Field(
        None, ge=1, le=255, description="平均扫描次数", example=3
    )
    smoothing_enabled: Optional[bool] = Field(
        None, description="是否启用光谱 EMA 平滑", example=True
    )
    smoothing_alpha: Optional[float] = Field(
        None, gt=0.0, le=1.0, description="EMA 平滑系数，越小越平滑", example=0.25
    )

class SpectrumData(BaseModel):
    """光谱数据模型（波长可省略：缺省时按 200 nm 起、步长 1 nm 与 spectrum 对齐）。"""
    wavelengths: Optional[List[float]] = Field(
        None,
        description="波长数据；若省略则由服务端按固定网格 200..200+len(spectrum)-1 生成",
        example=[400.0, 401.0, 402.0],
    )
    spectrum: List[float] = Field(
        ...,
        description="光谱强度数据（与 wavelengths 等长；无 wavelengths 时为固定网格上的强度序列）",
        example=[1000.5, 1001.2, 999.8],
    )
    output_filename: Optional[str] = Field(
        None,
        description="输出文件名（不含扩展名）",
        example="spectrum_20250715",
    )

class DeviceResetRequest(BaseModel):
    """设备重置请求模型"""
    ip: str = Field(..., description="设备IP地址", example="192.168.1.12")
    port: int = Field(..., description="设备端口号", example=502)
    register: int = Field(..., description="重置寄存器地址", example=0, ge=0)
    mock_mode: Optional[bool] = Field(False, description="是否使用模拟模式（用于调试）", example=False)

class Response(BaseModel):
    """通用响应模型"""
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(..., description="响应消息")
    data: Optional[Any] = Field(None, description="响应数据")

# 异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器"""
    logger.error(f"全局异常: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": f"服务器内部错误: {str(exc)}",
            "data": None
        }
    )

# 根路由
@app.get("/", response_model=Response)
async def root():
    """根路由"""
    return Response(
        success=True,
        message="HY Online API 服务运行正常",
        data={"version": "1.0.0", "status": "running"}
    )

# 健康检查
@app.get("/health", response_model=Response)
async def health_check():
    """健康检查"""
    return Response(
        success=True,
        message="服务健康",
        data={"status": "healthy", "timestamp": str(datetime.datetime.now())}
    )

#-------------------------------------------
@app.post("/upload", tags=["HY Device"])
async def edge_device_upload(data: DeviceData):
    """
    接收边缘设备上报：JSON 结构与 `edge_device_data.DeviceData`（即 test1.py 所用）一致。
    追加 `server_time` 后按 device_id 存入内存（每设备最多保留最近 5000 条）。
    """
    payload = data.model_dump()
    payload["server_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    did = str(data.device_id).strip()

    with _upload_store_lock:
        if did not in _upload_store:
            _upload_store[did] = []
        _upload_store[did].append(payload)
        n = len(_upload_store[did])
        if n > _UPLOAD_MAX_PER_DEVICE:
            _upload_store[did] = _upload_store[did][-_UPLOAD_MAX_PER_DEVICE:]
            n = len(_upload_store[did])

    return {"status": "ok", "device_id": did, "count": n}
#-------------------------------------------

#-------------------------------------------
@app.post("/spc/upload", tags=["HY Device"])
async def edge_device_spc_upload(
    device_id: str = Form(...),
    spc_file: UploadFile = File(...),
):
    """
    接收边缘设备上报的 .spc 文件。
    不落盘，仅按 device_id 将接收元数据写入内存（每设备最多保留最近 5000 条），
    用于返回类似 POST /upload 的接收确认。
    """
    did = _safe_device_id(device_id)
    original_name = _safe_spc_filename(spc_file.filename or "current_spectrum.spc")
    server_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data = await spc_file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的 SPC 文件为空")

    record = {
        "device_id": did,
        "file_name": original_name,
        "size": len(data),
        "server_time": server_time,
    }

    with _spc_upload_store_lock:
        if did not in _spc_upload_store:
            _spc_upload_store[did] = []
        _spc_upload_store[did].append(record)
        n = len(_spc_upload_store[did])
        if n > _SPC_UPLOAD_MAX_PER_DEVICE:
            _spc_upload_store[did] = _spc_upload_store[did][-_SPC_UPLOAD_MAX_PER_DEVICE:]
            n = len(_spc_upload_store[did])

    return {
        "status": "ok",
        "device_id": did,
        "count": n,
        "file_name": original_name,
        "size": len(data),
    }
#-------------------------------------------

#-------------------------------------------
@app.post("/spc/blank/upload", tags=["HY Device"])
async def edge_device_blank_spc_upload(
    device_id: str = Form(...),
    blank_type: str = Form(...),
    spc_file: UploadFile = File(...),
):
    """
    接收边缘设备上报的参比光谱 .spc 文件（blank_before / blank_after）。
    不落盘，仅按 device_id + blank_type 将接收元数据写入内存（每设备最多保留最近 5000 条），
    返回与 POST /spc/upload 一致风格的接收确认。
    """
    if blank_type not in _ALLOWED_BLANK_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 blank_type '{blank_type}'，允许值: {sorted(_ALLOWED_BLANK_UPLOAD_TYPES)}",
        )
    did = _safe_device_id(device_id)
    original_name = _safe_spc_filename(spc_file.filename or f"{blank_type}.spc")
    server_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data = await spc_file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的参比光谱 SPC 文件为空")

    record = {
        "device_id": did,
        "blank_type": blank_type,
        "file_name": original_name,
        "size": len(data),
        "server_time": server_time,
    }

    with _blank_spc_upload_store_lock:
        device_map = _blank_spc_upload_store.setdefault(did, {})
        type_list = device_map.setdefault(blank_type, [])
        type_list.append(record)
        if len(type_list) > _BLANK_SPC_UPLOAD_MAX_PER_DEVICE:
            device_map[blank_type] = type_list[-_BLANK_SPC_UPLOAD_MAX_PER_DEVICE:]
        n = len(device_map[blank_type])

    return {
        "status": "ok",
        "device_id": did,
        "blank_type": blank_type,
        "count": n,
        "file_name": original_name,
        "size": len(data),
    }
#-------------------------------------------


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.debug("应用启动，初始化自动控制服务...")
    load_auto_control_scripts_at_startup()
    device_config.reload_config()
    auto_control_manager.reset_warmup_flags()
    auto_control_manager.start()
    # HY_ONLINE_DEVICE_ID 由 upload_client_example / 启动脚本注入；缺省时使用 device_002
    order_number_state.configure_device_id(
        os.getenv("HY_ONLINE_DEVICE_ID", "device_002")
    )

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.debug("应用关闭，停止自动控制服务...")
    auto_control_manager.stop()

@app.get("/auto-control/status", response_model=Response)
async def get_auto_control_status():
    """获取自动控制服务状态"""
    try:
        status = auto_control_manager.get_status()
        return Response(
            success=True,
            message="获取自动控制状态成功",
            data=status
        )
    except Exception as e:
        logger.error(f"获取自动控制状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取自动控制状态失败: {str(e)}"
        )


@app.post("/auto-control/warmup-choice", response_model=Response)
async def post_warmup_choice(body: WarmupChoiceRequest):
    """设置开机预热：通水则 needs_warmup，否则直接 has_warmup。"""
    try:
        if body.with_water:
            auto_control_manager.warm_up_with_water()
        else:
            auto_control_manager.warm_up_no_action()
        return Response(success=True, message="预热选择已应用", data=None)
    except Exception as e:
        logger.error(f"预热选择失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/auto-control/mode-ui", response_model=Response)
async def get_mode_ui():
    """script_define 中 Visible 为真的模式列表（供硬件按钮）。"""
    try:
        reg = get_script_engine().registry
        data = reg.list_visible_mode_buttons()
        return Response(success=True, message="ok", data=data)
    except Exception as e:
        logger.error(f"获取模式 UI 列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post("/auto-control/apply-mode", response_model=Response)
async def post_apply_mode(body: ApplyModeRequest):
    """单次写入某模式对应线圈。"""
    try:
        _http_apply_script_mode(body.mode.strip())
        return Response(success=True, message=f"已应用模式 {body.mode!r}", data=None)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"应用模式失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# 设备模式信息
@app.get("/device-mode", response_model=Response)
async def get_device_mode():
    """获取当前设备模式信息"""
    return Response(
        success=True,
        message="获取设备模式信息成功",
        data=DeviceFactory.get_device_mode_info()
    )

# ==================== Settings API ====================

@app.get("/api/settings/device", tags=["Settings"])
async def get_device_settings():
    """获取当前设备配置"""
    return DeviceSettings.instance().config

@app.post("/api/settings/device", tags=["Settings"])
async def update_device_settings(config: Dict[str, Any]):
    """更新设备配置"""
    try:
        DeviceSettings.instance().update_config(config)
        # 更新运行时配置
        ip = config.get('ip')
        port = config.get('port')
        if ip and port:
            device_config.set_address(ip, port)
            
        # 更新自动控制配置
        auto_control_manager.reload_settings()
        
        return {"status": "success", "config": DeviceSettings.instance().config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#-------------------------------------------
#========= Upload relay（供 upload_client_example 轮询 + 前端启停） ===========


@app.get("/api/upload-relay/status", response_model=Response, tags=["Settings"])
async def get_upload_relay_status():
    """返回当前是否允许向外部上报传感器快照与 SPC（被 upload_client_example 每轮 GET 调用）。"""
    data = upload_relay_as_dict()
    data["spc_upload_interval_sec"] = (
        DeviceSettings.instance().get_spectrum_query_interval_sec()
    )
    return Response(
        success=True,
        message="ok",
        data=data,
    )


@app.post("/api/upload-relay/start", response_model=Response, tags=["Settings"])
async def post_upload_relay_start():
    """开始上报：打开传感器与 SPC 两路开关，供独立客户端 upload_client_example 开始实际上传。"""
    d = upload_relay_set_both(True, True)
    return Response(
        success=True,
        message="upload relay 已开启（传感器+SPC）",
        data=d,
    )


@app.post("/api/upload-relay/stop", response_model=Response, tags=["Settings"])
async def post_upload_relay_stop():
    """停止上报：关闭两路，upload_client_example 将仅轮询不 POST。"""
    d = upload_relay_set_both(False, False)
    return Response(
        success=True,
        message="upload relay 已停止",
        data=d,
    )


@app.post("/api/upload-relay/set", response_model=Response, tags=["Settings"])
async def post_upload_relay_set(body: UploadRelaySetRequest):
    """单独设置某一路；两字段均可为 null 表示不修改（若均为 null 则 400）。"""
    if body.upload_sensor is None and body.upload_spc is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少提供 upload_sensor 或 upload_spc 之一",
        )
    d = upload_relay_set_partial(
        upload_sensor=body.upload_sensor, upload_spc=body.upload_spc
    )
    return Response(
        success=True,
        message="upload relay 已更新",
        data=d,
    )


#-------------------------------------------
@app.get("/api/order-number", response_model=Response, tags=["OrderNumber"])
async def get_order_number_state():
    """返回当前生效单号、来源、设备号与对应文件夹路径。

    生效优先级：**server > manual > 占位「未获取」**。服务器一旦有非空下发即覆盖手改；
    upload_client_example 轮询写入 server；App 仅在本机 **尚无服务器单号** 时手改才生效。
    """
    return Response(
        success=True,
        message="ok",
        data=order_number_state.snapshot(),
    )


@app.post("/api/order-number/manual", response_model=Response, tags=["OrderNumber"])
async def post_order_number_manual(body: OrderNumberManualRequest):
    """前端 App 提交手动输入的单号；为空字符串/null 时清除手动值。"""
    data = order_number_state.set_manual_value(body.order_number)
    hy_sync = await asyncio.to_thread(_sync_effective_order_to_hy_server)
    payload = dict(data)
    payload["hy_server_sync"] = hy_sync
    return Response(
        success=True,
        message="手动单号已更新",
        data=payload,
    )


@app.delete("/api/order-number/manual", response_model=Response, tags=["OrderNumber"])
async def delete_order_number_manual():
    """显式清除手动输入的单号；服务端下发的 server_value 不受影响。"""
    data = order_number_state.clear_manual_value()
    hy_sync = await asyncio.to_thread(_sync_effective_order_to_hy_server)
    payload = dict(data)
    payload["hy_server_sync"] = hy_sync
    return Response(
        success=True,
        message="手动单号已清除",
        data=payload,
    )


@app.post("/api/order-number/server", response_model=Response, tags=["OrderNumber"])
async def post_order_number_server(body: OrderNumberManualRequest):
    """upload_client_example 轮询 HY_Server 后调用本端点写入 server_value。

    主服务与上报客户端是独立进程，故走 HTTP 而非内存写入；空值/null 视为清除。
    **生效单号**在存在非空 ``server_value`` 时以服务器为准（轮询会清除手改）；否则采用 ``manual_value``。
    """
    data = order_number_state.set_server_value(body.order_number)
    return Response(
        success=True,
        message="server 单号已更新",
        data=data,
    )


@app.post("/api/order-number/production-end", response_model=Response, tags=["OrderNumber"])
async def post_order_number_production_end():
    """生产结束：清除 server / manual 单号，App 轮询后将显示「未获取」。

    由 HY_Online 内部（自动控制 production-end 回调或 upload_client 模拟结束）调用；
    与 HY_Server ``/device/{id}/production-end`` 配合使用。"""
    data = order_number_state.clear_for_production_end()
    return Response(
        success=True,
        message="生产已结束，单号显示已清除",
        data=data,
    )


@app.post("/api/order-number/refresh", response_model=Response, tags=["OrderNumber"])
async def post_order_number_refresh():
    """按当前时间和生效单号重新创建/对齐目录（日切换或修复缺失目录用）。"""
    folder = order_number_state.ensure_folder()
    return Response(
        success=True,
        message="目录已对齐",
        data={"folder": folder, **order_number_state.snapshot()},
    )

#-------------------------------------------

@app.get("/api/settings/drivers", tags=["Settings"])
async def get_available_drivers():
    """获取可用的传感器驱动程序列表"""
    return {"drivers": DriverFactory.get_available_drivers()}


@app.get("/api/settings/script-define-files", tags=["Settings"])
async def list_script_define_files():
    """列出 HY_Online/define 下可用的 xlsx（相对 HY_Online 根的路径）。"""
    root = os.path.dirname(os.path.abspath(__file__))
    define_dir = os.path.join(root, "define")
    files: List[str] = []
    if os.path.isdir(define_dir):
        for name in sorted(os.listdir(define_dir)):
            if name.lower().endswith(".xlsx"):
                files.append(f"define/{name}")
    if not files:
        files = ["define/script_define.xlsx"]
    return {"files": files}


# ==================== HY Device API ====================

@app.post("/hy-device/set-address", response_model=Response)
async def set_device_address(address: DeviceAddress):
    """设置HY设备地址"""
    try:
        device_config.set_address(address.ip, address.port)
        return Response(
            success=True,
            message="设备地址设置成功",
            data={"ip": address.ip, "port": address.port}
        )
    except Exception as e:
        logger.error(f"设置设备地址失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"设置设备地址失败: {str(e)}"
        )

@app.get("/hy-device/address", response_model=Response)
async def get_device_address():
    """获取当前HY设备地址"""
    return Response(
        success=True,
        message="获取设备地址成功",
        data={"ip": device_config.ip_address, "port": device_config.port}
    )

@app.get("/hy-device/types", response_model=Response)
async def get_device_types():
    """获取支持的设备类型"""
    return Response(
        success=True,
        message="获取设备类型成功",
        data={"types": device_config.get_device_types()}
    )

@app.post("/hy-device/query", response_model=Response)
async def query_device(query: DeviceQuery):
    """查询HY设备数据"""
    try:
        logger.debug(f"开始查询HY设备数据: {query.device_type}")
        result = await device_config.run_modbus_inquire(query.device_type)
        logger.debug(f"设备查询成功 [{query.device_type}]: {result}")
        return Response(
            success=True,
            message=f"查询{query.device_type}成功",
            data={"device_type": query.device_type, "value": result}
        )
    except Exception as e:
        logger.error(f"❌ 查询HY设备数据失败 [{query.device_type}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"查询设备数据失败: {str(e)}"
        )

#---------------------------------------------------
@app.get("/hy-device/sensors", response_model=Response, tags=["HY Device"])
async def get_sensors_snapshot():
    """
    获取当前传感器缓存（DDL/PH/PH_TEMP/PT100、阀门缓存、报警与风扇等），
    并合并 hy_server.BridgeDataManager 的温度、液位、状态切换与异常信息。
    数据来自最近一次监控轮询或 POST /hy-device/query；本接口不主动读 Modbus。
    """
    snapshot = SensorDataManager.instance().get_snapshot()
    snapshot.update(BridgeDataManager.instance().get_snapshot())
    return Response(
        success=True,
        message="ok",
        data=snapshot,
    )
#---------------------------------------------------

@app.get("/hy-device/test-connection", response_model=Response)
async def test_device_connection():
    """测试HY设备连接"""
    try:
        logger.debug(f"开始测试HY设备连接: {device_config.ip_address}:{device_config.port}")
        is_connected = await device_config.test_connection()
        logger.debug(f"连接测试完成: {'成功' if is_connected else '失败'}")
        return Response(
            success=True,
            message="连接测试完成",
            data={
                "connected": is_connected,
                "ip": device_config.ip_address,
                "port": device_config.port
            }
        )
    except Exception as e:
        logger.error(f"❌ HY设备连接测试异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"连接测试失败: {str(e)}"
        )

@app.post("/hy-device/valve-control", response_model=Response)
async def control_valve(request: ValveControlRequest):
    """控制阀门/线圈（按 script_define 基础点位名称）"""
    try:
        reg = get_script_engine().registry
        if request.point_name not in reg.points:
            known = sorted(reg.points.keys())
            raise ValueError(
                f"未知点位 {request.point_name!r}，当前 script_define 基础点位: {known}"
            )

        device_type = f"{request.point_name}_{request.action}"

        if device_type not in device_config.get_device_types():
            raise ValueError(
                f"未注册指令 {device_type!r}（请检查 xlsx「模式定义」是否包含对应 _ON/_OFF 模式）"
            )

        action_desc = "打开" if request.action == "ON" else "关闭"
        label = request.point_name

        logger.debug(f"开始控制操作: {label} {action_desc} ({device_type})")

        result = await device_config.run_modbus_inquire(device_type)

        logger.debug(f"控制操作成功: {label}{action_desc}, 结果: {result}")

        return Response(
            success=True,
            message=f"{label}{action_desc}成功",
            data={
                "point_name": request.point_name,
                "action": request.action,
                "device_type": device_type,
                "result": result,
                "description": f"{label}{action_desc}",
            },
        )
    except Exception as e:
        logger.error(f"❌ 阀门控制失败 [{request.point_name}_{request.action}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"阀门控制失败: {str(e)}",
        )


@app.get("/hy-device/coil-point-names", response_model=Response)
async def list_coil_point_names():
    """script_define「基础点位配置」中的名称列表（供前端动态渲染）。"""
    names = DeviceSettings.instance().list_script_define_point_names()
    return Response(
        success=True,
        message="ok",
        data={"points": names},
    )

@app.get("/hy-device/valve-status", response_model=Response)
async def get_valve_status():
    """获取阀门和灯光的当前状态"""
    try:
        # 获取实际状态
        statuses = await device_config.get_all_valve_statuses()
        
        return Response(
            success=True,
            message="获取阀门状态成功",
            data=statuses
        )
    except Exception as e:
        logger.error(f"获取阀门状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取阀门状态失败: {str(e)}"
        )

@app.post("/hy-device/monitor/control", response_model=Response)
async def control_monitor(request: MonitorControlRequest):
    """
    控制传感器实时监控（手动模式）
    
    Start: 启动后台自动更新线程
    Stop: 停止后台自动更新线程
    """
    try:
        sdm = SensorDataManager.instance()
        settings = DeviceSettings.instance()
        ip = settings.get_ip()
        port = settings.get_port()
        
        if request.action == "start":
            if not sdm.is_running():
                # 手动模式下先做一次即时采样，避免 status 初始读到陈旧 fan_speed=0
                try:
                    sdm.update_sensor(ip, port)
                except Exception as prime_e:
                    logger.warning(f"监控启动前即时采样失败，将继续启动后台监控: {prime_e}")
                sdm.start_auto_update(ip, port, interval_seconds=request.interval, daemon=True)
                msg = "监控已启动"
            else:
                msg = "监控已在运行中"
                # 更新间隔
                sdm.set_interval(request.interval)

        elif request.action == "stop":
            if sdm.is_running():
                sdm.stop_auto_update()
                msg = "监控已停止"
            else:
                msg = "监控未运行"

        ac_cfg = settings.get_auto_control_settings()
        if not ac_cfg.get("enabled", False):
            if request.action == "start":
                auto_control_manager.set_manual_sample_flags(start_sensor=True)
            else:
                auto_control_manager.set_manual_sample_flags(start_sensor=False)
                
        return Response(
            success=True,
            message=msg,
            data={"running": sdm.is_running()}
        )
    except Exception as e:
        logger.error(f"控制监控失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"控制监控失败: {str(e)}"
        )

@app.get("/hy-device/connection-pool", response_model=Response)
async def get_connection_pool_status():
    """获取Modbus连接池状态"""
    try:
        status = device_config.get_connection_pool_status()
        logger.debug(f"连接池状态查询: {status['total_connections']} 个活跃连接")
        return Response(
            success=True,
            message="获取连接池状态成功",
            data=status
        )
    except Exception as e:
        logger.error(f"❌ 获取连接池状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取连接池状态失败: {str(e)}"
        )

@app.post("/hy-device/reset", response_model=Response)
async def reset_device(request: DeviceResetRequest):
    """
    重置设备（异步执行，立即返回）
    
    该接口会启动一个后台任务来执行设备重置操作，立即返回任务ID。
    重置过程包括：设置重置信号 -> 等待30秒 -> 清除重置信号
    """
    try:
        import uuid
        import asyncio
        
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())[:8]
        
        # 创建后台任务
        async def reset_task():
            try:
                logger.debug(f"开始执行设备重置任务 {task_id}")
                result = await reset_devices(request.ip, request.port, request.register, request.mock_mode)
                background_tasks[task_id] = {
                    "status": "completed",
                    "result": result,
                    "error": None,
                    "completed_at": time.time()
                }
                logger.debug(f"设备重置任务 {task_id} 完成")
            except Exception as e:
                background_tasks[task_id] = {
                    "status": "failed",
                    "result": None,
                    "error": str(e),
                    "completed_at": time.time()
                }
                logger.error(f"❌ 设备重置任务 {task_id} 失败: {e}")
        
        # 初始化任务状态
        background_tasks[task_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "started_at": time.time()
        }
        
        # 启动后台任务
        asyncio.create_task(reset_task())
        
        logger.debug(
            f"设备重置任务已启动 - 任务ID: {task_id}, IP: {request.ip}, Port: {request.port}"
        )
        
        # 根据模拟模式设置预计时长
        estimated_duration = "5秒 (模拟模式)" if request.mock_mode else "32秒 (真实模式)"
        
        return Response(
            success=True,
            message="设备重置任务已启动",
            data={
                "task_id": task_id,
                "ip": request.ip,
                "port": request.port,
                "register": request.register,
                "mock_mode": request.mock_mode,
                "estimated_duration": estimated_duration,
                "status": "running"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ 启动设备重置任务失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"启动设备重置任务失败: {str(e)}"
        )

@app.get("/hy-device/reset-status/{task_id}", response_model=Response)
async def get_reset_status(task_id: str):
    """
    查询设备重置任务状态
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务状态信息
    """
    try:
        if task_id not in background_tasks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务ID不存在"
            )
        
        task_info = background_tasks[task_id]
        
        # 计算运行时间
        current_time = time.time()
        if task_info["status"] == "running":
            duration = current_time - task_info["started_at"]
        else:
            duration = task_info["completed_at"] - task_info["started_at"]
        
        response_data = {
            "task_id": task_id,
            "status": task_info["status"],
            "duration_seconds": round(duration, 2),
            "result": task_info["result"],
            "error": task_info["error"]
        }
        
        # 根据任务结果判断模式和剩余时间
        if task_info["status"] == "running":
            # 从结果中判断是否为模拟模式，如果没有结果则默认真实模式
            estimated_total = 5 if (task_info.get("result") and task_info["result"].get("mode") == "mock") else 32
            response_data["estimated_remaining"] = max(0, estimated_total - duration)
            response_data["estimated_total"] = estimated_total
        
        return Response(
            success=True,
            message=f"任务状态: {task_info['status']}",
            data=response_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询任务状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"查询任务状态失败: {str(e)}"
        )

# ==================== CDS350 API (统一路由，自动选择设备模式) ====================

@app.post("/cds350/initialize", response_model=Response)
async def initialize_cds350():
    """初始化CDS350设备（根据配置选择真实设备或模拟设备）"""
    global cds350_device
    try:
        cds350_device = DeviceFactory.create_cds350_device()
        result = cds350_device.initialize_device()
        device_status = spectrum_manager.check_device_status(cds350_device)
        
        mode_info = DeviceFactory.get_device_mode_info()
        return Response(
            success=True,
            message=f"CDS350设备初始化成功 ({mode_info['description']})",
            data={
                **result,
                "device_mode": mode_info,
                "device_status": device_status,
            }
        )
    except Exception as e:
        logger.error(f"CDS350设备初始化失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CDS350设备初始化失败: {str(e)}"
        )

@app.get("/cds350/device-status", response_model=Response)
async def get_cds350_device_status():
    """检测CDS350设备连接状态。"""
    try:
        if cds350_device is None:
            return Response(
                success=True,
                message="CDS350设备未初始化",
                data={
                    "connected": False,
                    "initialized": False,
                    "error_message": "设备未初始化",
                },
            )
        device_status = spectrum_manager.check_device_status(cds350_device)
        return Response(
            success=True,
            message="获取CDS350设备状态成功",
            data=device_status,
        )
    except Exception as e:
        logger.error(f"获取CDS350设备状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取CDS350设备状态失败: {str(e)}",
        )

@app.post("/cds350/restart", response_model=Response)
async def restart_cds350():
    """重启CDS350设备，用于断连后的手动恢复。"""
    global cds350_device
    try:
        if cds350_device is None:
            cds350_device = DeviceFactory.create_cds350_device()
            result = cds350_device.initialize_device()
            device_status = spectrum_manager.check_device_status(cds350_device)
            return Response(
                success=True,
                message="CDS350设备未初始化，已完成初始化",
                data={
                    **result,
                    "device_status": device_status,
                },
            )

        restart_result = spectrum_manager.restart_device(
            cds350_device,
            reason="手动调用 /cds350/restart",
        )
        return Response(
            success=True,
            message="CDS350设备重启成功",
            data={
                "restart_result": restart_result,
                "device_status": spectrum_manager.check_device_status(cds350_device),
            },
        )
    except Exception as e:
        logger.error(f"重启CDS350设备失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"重启CDS350设备失败: {str(e)}",
        )

@app.post("/cds350/configure", response_model=Response)
async def configure_cds350(config: CDS350Config):
    """记录CDS350目标参数；实际设备写入在采集前按需执行。"""
    try:
        results = spectrum_manager.set_desired_config(
            integration_time=config.integration_time,
            scans_to_average=config.scans_to_average,
        )
        smoothing = spectrum_manager.set_smoothing_config(
            enabled=config.smoothing_enabled,
            alpha=config.smoothing_alpha,
        )
        results["smoothing"] = smoothing
            
        return Response(
            success=True,
            message="CDS350目标参数和平滑配置已记录，将在采集前按需应用",
            data=results
        )
    except Exception as e:
        logger.error(f"CDS350设备配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CDS350设备配置失败: {str(e)}"
        )

@app.get("/cds350/spectrum", response_model=Response)
async def get_cds350_spectrum(force_new: bool = False):
    """
    获取CDS350光谱数据
    
    Args:
        force_new: 是否强制获取新数据（默认False，会使用缓存数据避免并发采集）
    """
    global cds350_device
    try:
        if cds350_device is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="设备未初始化，请先调用初始化接口"
            )

        ac_cfg = DeviceSettings.instance().get_auto_control_settings()
        auto_enabled = ac_cfg.get("enabled", False)
        if not auto_enabled and force_new:
            auto_control_manager.set_manual_sample_flags(start_spec=True)
        try:
            # 使用光谱采集管理器获取数据
            wavelengths, spectrum = await spectrum_manager.get_spectrum_data(
                device=cds350_device,
                force_new=force_new,
            )
        finally:
            if not auto_enabled and force_new:
                auto_control_manager.set_manual_sample_flags(start_spec=False)
        
        # 获取状态信息
        status_info = spectrum_manager.get_status()
        cached_data = spectrum_manager.get_cached_data()
        data_timestamp = cached_data.timestamp if cached_data else None

        # 模拟模式：与 HY_APP 一致，仅返回固定网格上的强度（整数），不传 wavelengths
        if app_config.is_mock_mode():
            sp_list = [int(round(float(x))) for x in spectrum]
            data = {
                "spectrum": sp_list,
                "length": len(sp_list),
                "timestamp": (
                    datetime.datetime.fromtimestamp(data_timestamp).isoformat()
                    if data_timestamp
                    else None
                ),
                "integration_time": cached_data.integration_time if cached_data else None,
                "scans_to_average": cached_data.scans_to_average if cached_data else None,
                "last_acquisition_time": (
                    cached_data.acquisition_time if cached_data else None
                ),
                "dark_corrected": cached_data.dark_corrected if cached_data else False,
                "dark_timestamp": cached_data.dark_timestamp if cached_data else None,
                "smoothed": cached_data.smoothed if cached_data else False,
                "smoothing_alpha": cached_data.smoothing_alpha if cached_data else None,
                "dark_status": spectrum_manager.get_dark_status(),
                "acquisition_status": status_info,
            }
        else:
            data = {
                "wavelengths": wavelengths,
                "spectrum": spectrum,
                "length": len(wavelengths) if wavelengths else 0,
                "timestamp": (
                    datetime.datetime.fromtimestamp(data_timestamp).isoformat()
                    if data_timestamp
                    else None
                ),
                "integration_time": cached_data.integration_time if cached_data else None,
                "scans_to_average": cached_data.scans_to_average if cached_data else None,
                "last_acquisition_time": (
                    cached_data.acquisition_time if cached_data else None
                ),
                "dark_corrected": cached_data.dark_corrected if cached_data else False,
                "dark_timestamp": cached_data.dark_timestamp if cached_data else None,
                "smoothed": cached_data.smoothed if cached_data else False,
                "smoothing_alpha": cached_data.smoothing_alpha if cached_data else None,
                "dark_status": spectrum_manager.get_dark_status(),
                "acquisition_status": status_info,
            }

        return Response(
            success=True,
            message="获取光谱数据成功",
            data=data,
        )
    except Exception as e:
        logger.error(f"获取光谱数据失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取光谱数据失败: {str(e)}"
        )

@app.get("/cds350/spectrum-status", response_model=Response)
async def get_spectrum_status():
    """获取光谱采集状态"""
    try:
        status_info = spectrum_manager.get_status()
        return Response(
            success=True,
            message="获取光谱采集状态成功",
            data=status_info
        )
    except Exception as e:
        logger.error(f"获取光谱采集状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取光谱采集状态失败: {str(e)}"
        )

@app.post("/cds350/spectrum-reset", response_model=Response)
async def reset_spectrum_status():
    """重置光谱采集状态"""
    try:
        spectrum_manager.reset_to_idle()
        return Response(
            success=True,
            message="光谱采集状态重置成功",
            data=spectrum_manager.get_status()
        )
    except Exception as e:
        logger.error(f"重置光谱采集状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"重置光谱采集状态失败: {str(e)}"
        )

@app.post("/cds350/close", response_model=Response)
async def close_cds350():
    """关闭CDS350设备"""
    global cds350_device
    try:
        if cds350_device is None:
            return Response(
                success=True,
                message="设备未初始化，无需关闭",
                data=None
            )
        
        cds350_device.close_device()
        cds350_device = None
        return Response(
            success=True,
            message="CDS350设备关闭成功",
            data=None
        )
    except Exception as e:
        logger.error(f"关闭CDS350设备失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"关闭CDS350设备失败: {str(e)}"
        )

# ==================== SPC转化 API ====================

@app.post("/spc/convert", response_model=Response)
async def convert_to_spc(spectrum_data: SpectrumData):
    """
    将光谱数据转换为SPC文件
    
    接收光谱数据（波长和强度），转换为SPC格式文件并返回文件信息
    """
    try:
        sp_len = len(spectrum_data.spectrum)
        if sp_len == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="光谱数据不能为空"
            )
        if spectrum_data.wavelengths is not None:
            if len(spectrum_data.wavelengths) != sp_len:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="波长数据和光谱数据长度不一致"
                )
            wl = spectrum_data.wavelengths
        else:
            wl = [200.0 + i for i in range(sp_len)]
        
        # 转换为SPC文件
        result = convert_spectrum_to_spc(
            wavelengths=wl,
            spectrum=spectrum_data.spectrum,
            output_path=spectrum_data.output_filename
        )
        
        return Response(
            success=True,
            message="光谱数据转换为SPC文件成功",
            data=result
        )
        
    except Exception as e:
        logger.error(f"SPC转换失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SPC转换失败: {str(e)}"
        )

@app.get("/spc/convert-current-spectrum", response_model=Response)
async def convert_current_spectrum_to_spc(output_filename: Optional[str] = None):
    """
    获取当前CDS350光谱数据并转换为SPC文件
    
    Args:
        output_filename: 输出文件名（可选）
    """
    global cds350_device
    try:
        if cds350_device is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CDS350设备未初始化，请先调用初始化接口"
            )
        
        # 获取光谱数据
        wavelengths, spectrum = await spectrum_manager.get_spectrum_data(
            device=cds350_device, 
            force_new=False  # 使用缓存数据以避免重复采集
        )
        cached_data = spectrum_manager.get_cached_data()
        
        if not wavelengths or not spectrum:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="未能获取到光谱数据"
            )
        
        # 转换为SPC文件
        result = convert_spectrum_to_spc(
            wavelengths=wavelengths,
            spectrum=spectrum,
            output_path=output_filename
        )
        
        # 添加光谱数据信息
        result["spectrum_info"] = {
            "data_points": len(wavelengths),
            "wavelength_range": {
                "min": min(wavelengths),
                "max": max(wavelengths)
            },
            "intensity_range": {
                "min": min(spectrum),
                "max": max(spectrum)
            },
            "dark_corrected": cached_data.dark_corrected if cached_data else False,
            "dark_timestamp": cached_data.dark_timestamp if cached_data else None,
        }
        
        return Response(
            success=True,
            message="当前光谱数据转换为SPC文件成功",
            data=result
        )
        
    except Exception as e:
        logger.error(f"当前光谱SPC转换失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前光谱SPC转换失败: {str(e)}"
        )

@app.get("/spc/download/{filename}")
async def download_spc_file(filename: str):
    """
    下载SPC文件
    
    根据文件名下载对应的SPC文件
    """
    try:
        # 安全检查：确保文件名只包含安全字符
        if not filename.endswith('.spc'):
            filename += '.spc'
        
        # 检查文件名是否安全（防止路径穿越攻击）
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的文件名"
            )
        
        from Devices.get_spc import find_spc_file_for_download

        file_path = find_spc_file_for_download(filename)

        if not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"文件未找到: {filename}"
            )
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type='application/octet-stream'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载SPC文件失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"下载文件失败: {str(e)}"
        )
        
#-------------------------------------------
# ==================== 参比光谱（参比光谱）API ====================
# blank_before：置换之前采集的参比光谱
# blank_after ：清洗之后采集的参比光谱
# 后台自动触发路径：
#   run_on_get_ready_for_autorun 脚本完成 → blank_before
#   run_on_autorun_batch_finish  脚本完成 → blank_after
# 以下接口提供手动触发与数据查询能力

@app.get("/spc/blank/list", response_model=Response, tags=["SPC"])
async def get_blank_list(blank_type: Optional[str] = None):
    """
    查询参比光谱摘要列表（不含波长/强度数组）。
    blank_type 可选值：blank_before（置换前）、blank_after（清洗后），不传则返回全部。
    """
    valid = {"blank_before", "blank_after"}
    if blank_type is not None and blank_type not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"blank_type 须为 blank_before 或 blank_after，收到: {blank_type!r}",
        )
    items = spectrum_manager.get_blank_list(blank_type)
    return Response(
        success=True,
        message="ok",
        data={"count": len(items), "items": items},
    )


@app.get("/spc/blank/latest", response_model=Response, tags=["SPC"])
async def get_blank_latest(blank_type: str = "blank_before"):
    """
    获取指定类型最新一条参比光谱的完整数据（含波长与强度数组）。
    blank_type：blank_before（置换前，默认）或 blank_after（清洗后）。
    """
    valid = {"blank_before", "blank_after"}
    if blank_type not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"blank_type 须为 blank_before 或 blank_after，收到: {blank_type!r}",
        )
    data = spectrum_manager.get_blank_latest(blank_type)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"尚无 {blank_type} 参比光谱，请先触发采集",
        )
    label_map = {"blank_before": "置换前参比光谱", "blank_after": "清洗后参比光谱"}
    return Response(
        success=True,
        message=f"获取{label_map[blank_type]}成功",
        data={
            "spectrum_type": data.spectrum_type,
            "label": data.label,
            "timestamp": data.timestamp,
            "acquisition_time": data.acquisition_time,
            "integration_time": data.integration_time,
            "scans_to_average": data.scans_to_average,
            "dark_corrected": data.dark_corrected,
            "dark_timestamp": data.dark_timestamp,
            "data_points": len(data.wavelengths),
            "wavelengths": data.wavelengths,
            "spectrum": data.spectrum,
        },
    )


@app.post("/spc/blank/acquire", response_model=Response, tags=["SPC"])
async def acquire_blank_spectrum(body: BlankAcquireRequest):
    """
    手动触发参比光谱采集（在独立后台线程中执行，不阻塞当前请求）。
    适用于自动控制未运行时，由前端/操作人员手动触发置换前或清洗后参比光谱。
    需要 CDS350 设备已初始化。
    """
    global cds350_device
    device = cds350_device or get_or_init_cds350_device()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CDS350 设备未初始化，请先调用 /cds350/initialize",
        )
    label_map = {"blank_before": "置换前参比光谱", "blank_after": "清洗后参比光谱"}
    started = spectrum_manager.start_blank_acquisition(device, body.blank_type)
    if not started:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启动 {label_map[body.blank_type]} 采集失败",
        )
    return Response(
        success=True,
        message=f"{label_map[body.blank_type]}采集已在后台启动",
        data={"blank_type": body.blank_type, "label": label_map[body.blank_type]},
    )


@app.get("/spc/dark/convert-latest", response_model=Response, tags=["SPC"])
async def convert_dark_to_spc(output_filename: Optional[str] = None):
    """将最新暗光谱转换为 SPC 文件并返回下载信息。"""
    data = spectrum_manager.get_dark_latest()
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="尚无暗光谱，请等待真实模式下暗光谱采集完成",
        )

    if output_filename is None and data.spc_file_path and os.path.exists(data.spc_file_path):
        fp = data.spc_file_path
        result = {
            "file_path": fp,
            "file_name": os.path.basename(fp),
            "file_size": os.path.getsize(fp),
            "data_points": len(data.wavelengths),
            "created_at": datetime.datetime.fromtimestamp(data.timestamp).isoformat(),
        }
    else:
        try:
            from Devices.get_spc import get_dark_spc_dir
            output_path = output_filename
            if output_path is None:
                ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(data.timestamp))
                output_path = os.path.join(get_dark_spc_dir(), f"dark_{ts_str}")
            result = convert_spectrum_to_spc(
                wavelengths=data.wavelengths,
                spectrum=data.spectrum,
                output_path=output_path,
            )
            data.spc_file_path = result["file_path"]
        except Exception as e:
            logger.error(f"暗光谱 SPC 转换失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SPC 转换失败: {e}",
            )

    wl, sp = data.wavelengths, data.spectrum
    result["spectrum_type"] = "dark"
    result["label"] = data.label or "暗光谱"
    result["source_timestamp"] = data.timestamp
    result["spectrum_info"] = {
        "data_points": len(wl),
        "wavelength_range": {
            "min": min(wl) if wl else None,
            "max": max(wl) if wl else None,
        },
        "intensity_range": {
            "min": min(sp) if sp else None,
            "max": max(sp) if sp else None,
        },
    }
    return Response(
        success=True,
        message="暗光谱已转换为 SPC 文件",
        data=result,
    )


@app.get("/spc/blank/convert-latest", response_model=Response, tags=["SPC"])
async def convert_blank_to_spc(
    blank_type: str = "blank_before",
    output_filename: Optional[str] = None,
):
    """
    将指定类型最新参比光谱转换为 SPC 文件并返回下载信息。
    之后可调用 GET /spc/download/{filename} 下载该文件。
    blank_type：blank_before（置换前，默认）或 blank_after（清洗后）。
    """
    valid = {"blank_before", "blank_after"}
    if blank_type not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"blank_type 须为 blank_before 或 blank_after，收到: {blank_type!r}",
        )
    data = spectrum_manager.get_blank_latest(blank_type)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"尚无 {blank_type} 参比光谱，请先触发采集",
        )
    label_map = {"blank_before": "置换前参比光谱", "blank_after": "清洗后参比光谱"}

    # 优先复用采集时自动落盘的 SPC 文件，避免重复 IO 转换
    if data.spc_file_path and os.path.exists(data.spc_file_path):
        fp = data.spc_file_path
        result = {
            "file_path": fp,
            "file_name": os.path.basename(fp),
            "file_size": os.path.getsize(fp),
            "data_points": len(data.wavelengths),
            "created_at": datetime.datetime.fromtimestamp(data.timestamp).isoformat(),
        }
    else:
        # 降级：实时转换（落盘失败或文件被外部删除时的保底路径）
        try:
            result = convert_spectrum_to_spc(
                wavelengths=data.wavelengths,
                spectrum=data.spectrum,
                output_path=output_filename,
            )
        except Exception as e:
            logger.error(f"参比光谱 SPC 转换失败 [{blank_type}]: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SPC 转换失败: {e}",
            )

    result["blank_type"] = blank_type
    result["label"] = label_map[blank_type]
    result["source_timestamp"] = data.timestamp
    wl, sp = data.wavelengths, data.spectrum
    result["spectrum_info"] = {
        "data_points": len(wl),
        "wavelength_range": {
            "min": min(wl) if wl else None,
            "max": max(wl) if wl else None,
        },
        "intensity_range": {
            "min": min(sp) if sp else None,
            "max": max(sp) if sp else None,
        },
    }
    return Response(
        success=True,
        message=f"{label_map[blank_type]}已转换为 SPC 文件",
        data=result,
    )
#-------------------------------------------
    
# ==================== 启动应用 ====================

if __name__ == "__main__":
    import uvicorn
    print(f"🚀 启动 {app_config.get_mode_description()}")
    print(f"📡 API地址: http://{app_config.host}:{app_config.port}")
    print(f"📖 API文档: http://{app_config.host}:{app_config.port}/docs")
    
    uvicorn.run(
        "main:app",
        host=app_config.host,
        port=app_config.port,
        reload=app_config.reload,
        log_level=app_config.log_level
    )
