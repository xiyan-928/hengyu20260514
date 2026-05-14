"""
通用启动脚本
用于启动HY Online FastAPI服务
从环境变量或.env文件读取配置
"""
import os
import uvicorn
from pathlib import Path

# 尝试加载.env文件
def load_env_file():
    """加载.env文件中的环境变量"""
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # 只设置尚未设置的环境变量
                    if key not in os.environ:
                        os.environ[key] = value

if __name__ == "__main__":
    # 加载环境配置
    load_env_file()
    
    # 获取配置
    device_mode = os.getenv("DEVICE_MODE", "mock")
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "true").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info")
    
    # 显示启动信息
    mode_desc = "模拟设备模式" if device_mode == "mock" else "真实设备模式"
    print(f"🚀 启动HY Online API服务 - {mode_desc}")
    print(f"📡 API地址: http://{host}:{port}")
    print(f"📖 API文档: http://{host}:{port}/docs")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )
