"""
软件自动更新管理器

工作流程：
1. 调用 check_for_update() 向服务器查询是否有新版本
2. 若有更新，调用 download_update() 将压缩包流式下载到本地 _updates/ 目录

压缩包约定：服务器文件名格式 HY_Online_v<X>.<Y>.<Z>.zip
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request

logger = logging.getLogger("update_manager")

# 本地缓存下载包的目录
_UPDATE_CACHE_DIR = Path(__file__).resolve().parent / "_updates"
_UPDATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CHECK_TIMEOUT_SEC = 15.0    # 版本查询超时（秒）
DOWNLOAD_TIMEOUT_SEC = 300.0  # 文件下载超时（秒），支持较大安装包
_CHUNK_SIZE = 64 * 1024       # 流式下载块大小（64 KB）


def check_for_update(server_base: str, current_version: str) -> Optional[dict]:
    """向服务器查询是否有新版本。

    返回值：
    - None：网络不可达或解析失败
    - dict with needs_update=False：已是最新
    - dict with needs_update=True + filename / version / size：有更新

    示例返回（有更新时）：
    {
        "needs_update": True,
        "current_version": "1.0.0",
        "latest_version": "1.2.3",
        "filename": "HY_Online_v1.2.3.zip",
        "download_url": "/update/download/HY_Online_v1.2.3.zip",
        "size": 10240000,
    }
    """
    params = urlparse.urlencode({"current_version": current_version})
    url = server_base.rstrip("/") + "/update/check?" + params
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=CHECK_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body
    except urlerror.HTTPError as e:
        logger.error("更新检查失败 HTTP %s: %s", e.code, e.read().decode("utf-8", errors="replace"))
        return None
    except (urlerror.URLError, OSError, json.JSONDecodeError) as e:
        logger.warning("更新检查请求失败（服务器不可达？）: %s", e)
        return None


def download_update(server_base: str, filename: str) -> Optional[Path]:
    """从服务器流式下载指定软件包，保存到本地 _updates/ 目录。

    - filename 会进行 URL 编码，支持含空格或特殊字符的文件名。
    - 若文件已存在且大小非零则跳过重复下载，直接返回缓存路径。
    - 采用分块写入，避免大文件占满内存。
    返回下载后的本地文件 Path，失败返回 None。
    """
    if not filename:
        logger.error("download_update: filename 为空，取消下载")
        return None

    dest = _UPDATE_CACHE_DIR / filename
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("软件包已缓存，跳过下载: %s", dest)
        return dest

    url = server_base.rstrip("/") + "/update/download/" + urlparse.quote(filename)
    logger.info("开始下载更新包: %s", url)

    # 写入临时文件，下载完整后再重命名，防止中途中断留下损坏文件
    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SEC) as resp:
            with open(tmp_dest, "wb") as f:
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)

        size = tmp_dest.stat().st_size
        if size == 0:
            tmp_dest.unlink(missing_ok=True)
            logger.error("下载的文件为空: %s", filename)
            return None

        tmp_dest.rename(dest)
        logger.info("下载完成: %s  大小: %d bytes", dest, size)
        return dest

    except urlerror.HTTPError as e:
        tmp_dest.unlink(missing_ok=True)
        logger.error("下载失败 HTTP %s: %s", e.code, e.read().decode("utf-8", errors="replace"))
        return None
    except (urlerror.URLError, OSError) as e:
        tmp_dest.unlink(missing_ok=True)
        logger.error("下载失败: %s", e)
        return None


def check_and_download(server_base: str, current_version: str) -> Optional[Path]:
    """检查更新，若有新版本则下载到本地 _updates/ 目录。

    返回值：
    - None：无需更新、服务器不可达或下载失败
    - Path：下载成功的本地文件路径
    """
    logger.info("检查软件更新（当前版本: %s）…", current_version)
    result = check_for_update(server_base, current_version)
    if result is None:
        logger.warning("更新检查失败，跳过本次更新")
        return None

    if not result.get("needs_update"):
        logger.info(
            "已是最新版本 %s（服务器最新: %s）",
            current_version,
            result.get("latest_version", current_version),
        )
        return None

    latest_ver = result.get("latest_version", "?")
    filename = str(result.get("filename") or "").strip()
    size = result.get("size", 0)

    if not filename:
        logger.error("服务器返回的 filename 为空，取消下载")
        return None

    logger.info(
        "发现新版本: %s → %s，文件: %s，大小: %d bytes，开始下载…",
        current_version, latest_ver, filename, size,
    )

    zip_path = download_update(server_base, filename)
    if zip_path is None:
        logger.error("下载更新包失败")
        return None

    logger.info("更新包已下载至: %s", zip_path)
    return zip_path
