#!/usr/bin/env bash
# 启动屏幕键盘 onboard；卸载 ftdi_sio/usbserial；在 conda 环境 ftapi 中运行 HY_Online/start.py。
# 本文件须为 Unix 换行（LF）。
set -euo pipefail

echo "卸载 VCP 相关内核模块…"
set +e
echo "epd123" | sudo -S rmmod ftdi_sio
echo "epd123" | sudo -S rmmod usbserial
set -e

# 3. 在 ftapi 环境中运行 HY_Online/start.py（工作目录需为 HY_Online，以便加载 main:app）
cd ~/HY_Online
/home/europod/anaconda3/envs/ftapi/bin/python start_real.py
