"""
启动脚本 - 模拟设备模式
用于启动HY Online FastAPI服务（模拟设备模式）
"""
import os
import uvicorn

# 设置环境变量为模拟模式
os.environ["DEVICE_MODE"] = "mock"

if __name__ == "__main__":
    print("🚀 启动HY Online API服务 - 模拟设备模式")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="warning"
    )
