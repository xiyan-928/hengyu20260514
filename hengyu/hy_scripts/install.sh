#!/usr/bin/env bash
# HY 项目安装脚本（Linux）：conda 环境 ftapi、HY_Online 依赖、CDS350 驱动与 udev 规则。
# 本文件须为 Unix 换行（LF）。在 Cursor/VS Code 右下角将 CRLF 改为 LF 后再保存。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HY_ONLINE="$REPO_ROOT/HY_Online"
CDS350_ROOT="$HY_ONLINE/Devices/lib/CDS350"
CDS350_LIB="$CDS350_ROOT/lib"
RULES_SRC="$CDS350_ROOT/96-cds350.rules"

if [[ ! -d "$HY_ONLINE" ]]; then
  echo "未找到 HY_Online 目录: $HY_ONLINE" >&2
  exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "未检测到 conda，请先安装 Miniconda/Anaconda 并确保 conda 在 PATH 中。" >&2
  exit 1
fi

# 直接调用 env 内 pip，无需 conda run / conda activate（旧版 conda 无 run；activate 与 set -u 下 PS1 冲突）。
CONDA_BASE="$(conda info --base)"
FTAPI_ENV="$CONDA_BASE/envs/ftapi"
if [[ ! -x "$FTAPI_ENV/bin/pip" ]]; then
  conda create -n ftapi python=3.10 -y
fi

echo "在 ftapi 环境中安装 Python 依赖…"
# spc-spectra（pyspectra 的依赖）仅有 sdist，构建时会 import numpy；pip 默认隔离构建环境里没有 numpy，需关闭隔离。
"$FTAPI_ENV/bin/pip" install numpy pandas scipy
"$FTAPI_ENV/bin/pip" install "spc-spectra==0.4.0" --no-build-isolation
"$FTAPI_ENV/bin/pip" install -r "$HY_ONLINE/requirements.txt"

if [[ ! -d "$CDS350_LIB" ]]; then
  echo "未找到 CDS350 库目录: $CDS350_LIB（请将 lib 文件放入该目录后重试）" >&2
  exit 1
fi

if [[ ! -f "$RULES_SRC" ]]; then
  echo "未找到 udev 规则文件: $RULES_SRC" >&2
  exit 1
fi

echo "安装 CDS350 驱动库与 udev 规则（需要 root）…"
sudo cp -a "$CDS350_LIB"/. /usr/local/lib/
sudo ln -sf libftd2xx.so.1.4.27 /usr/local/lib/libftd2xx.so
sudo cp -a "$RULES_SRC" /etc/udev/rules.d/96-cds350.rules
sudo ldconfig
sudo udevadm control --reload-rules
sudo udevadm trigger


echo "安装完成。"
