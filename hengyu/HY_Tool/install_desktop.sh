#!/usr/bin/env bash
# install_desktop.sh —— 在 Ubuntu / Debian / 衍生发行版上注册 modbus_setup 启动器
#
# 一行装好：
#   bash install_desktop.sh
#
# 脚本特性：
#   - 自动修复 Windows CRLF 行尾（从 Windows 拷过来直接跑也不报 ^M 错）
#   - 检测 python3 / tkinter / pymodbus，缺失时主动提示用 apt / pip 安装
#   - .desktop 写到 ~/.local/share/applications/，无需 sudo
#   - 图标自动支持 modbus.png 或 modbus.svg（同目录下任选其一，svg 更清晰）
#   - 可选 --desktop-shortcut 在 ~/Desktop 也放一个，并设为"已信任"
#
# 用法：
#   bash install_desktop.sh                      # 用户级安装
#   bash install_desktop.sh --system             # 系统级（自动 sudo）
#   bash install_desktop.sh --uninstall          # 卸载（可加 --system）
#   bash install_desktop.sh --yes                # 跳过所有交互（CI / 自动化）
#   bash install_desktop.sh --no-deps            # 不检查 python 依赖
#   bash install_desktop.sh --desktop-shortcut   # 同时在 ~/Desktop 放一个
#   bash install_desktop.sh -h | --help          # 打印用法

# ---------------------------------------------------------------------------
# 0) 自愈 CRLF：Windows 上写的脚本拷到 Linux 时，bash 解释器读到 \r 会报怪错
# ---------------------------------------------------------------------------
if grep -q $'\r' "${BASH_SOURCE[0]}" 2>/dev/null; then
    echo "[CRLF] 检测到 Windows 行尾，已就地转为 Unix LF 并重新执行" >&2
    sed -i 's/\r$//' "${BASH_SOURCE[0]}"
    exec bash "${BASH_SOURCE[0]}" "$@"
fi

set -euo pipefail

# ---------------------------------------------------------------------------
# 1) 常量 & 参数解析
# ---------------------------------------------------------------------------

APP_ID="modbus_setup"
APP_DISPLAY="modbus_setup"
APP_COMMENT="Modbus 模块初次搭建与测试 GUI"
APP_CATEGORIES="Development;Utility;Network;"
APP_KEYWORDS="modbus;plc;tcp;setup;hengyu;"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GUI_PY="$SCRIPT_DIR/modbus_setup_gui.py"
ICON_PNG="$SCRIPT_DIR/modbus.png"
ICON_SVG="$SCRIPT_DIR/modbus.svg"

MODE="install"
SCOPE="user"
ASSUME_YES=0
SKIP_DEPS=0
WITH_DESKTOP=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --uninstall|-u)         MODE="uninstall" ;;
        --system|-s)            SCOPE="system" ;;
        --yes|-y)               ASSUME_YES=1 ;;
        --no-deps)              SKIP_DEPS=1 ;;
        --desktop-shortcut|-d)  WITH_DESKTOP=1 ;;
        -h|--help)
            sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "未知参数：$1（用 -h 查看用法）" >&2
            exit 2
            ;;
    esac
    shift
done

# 用户级 vs 系统级
if [[ "$SCOPE" == "system" ]]; then
    APPS_DIR="/usr/share/applications"
    ICON_ROOT="/usr/share/icons/hicolor"
    SUDO=""
    [[ $EUID -ne 0 ]] && SUDO="sudo"
else
    APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICON_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
    SUDO=""
fi

DESKTOP_FILE="$APPS_DIR/${APP_ID}.desktop"

# 询问 (Y/n)；--yes 时直接接受
confirm() {
    local prompt="$1"
    if [[ $ASSUME_YES -eq 1 ]]; then return 0; fi
    local ans
    read -rp "$prompt [Y/n]: " ans || ans=""
    case "${ans,,}" in
        ""|y|yes) return 0 ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# 2) 卸载分支
# ---------------------------------------------------------------------------

if [[ "$MODE" == "uninstall" ]]; then
    $SUDO rm -f "$DESKTOP_FILE"
    for size in scalable 48x48 64x64 128x128 256x256 512x512; do
        $SUDO rm -f "$ICON_ROOT/$size/apps/${APP_ID}.png" "$ICON_ROOT/$size/apps/${APP_ID}.svg"
    done
    rm -f "$HOME/Desktop/${APP_ID}.desktop"
    command -v update-desktop-database >/dev/null 2>&1 \
        && $SUDO update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 \
        && $SUDO gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
    echo "[OK] 已卸载 modbus_setup（$SCOPE）"
    exit 0
fi

# ---------------------------------------------------------------------------
# 3) 前置检查 + 缺失依赖辅助安装
# ---------------------------------------------------------------------------

if [[ ! -f "$GUI_PY" ]]; then
    echo "错误：找不到 GUI 主程序：$GUI_PY" >&2
    exit 1
fi

# Ubuntu/Debian 的标准解释器就是 python3
PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
    echo "错误：未找到 python3。Ubuntu 上请：sudo apt install python3" >&2
    exit 1
fi

# 是否 Ubuntu / Debian 系
HAS_APT=0
[[ -r /etc/os-release ]] && . /etc/os-release || true
if command -v apt >/dev/null 2>&1; then HAS_APT=1; fi

if [[ $SKIP_DEPS -eq 0 ]]; then
    # tkinter：GUI 必需
    if ! "$PY" -c "import tkinter" 2>/dev/null; then
        echo
        echo "提示：当前 python3 未启用 tkinter 模块，GUI 无法启动。"
        if [[ $HAS_APT -eq 1 ]] && confirm "现在用 sudo apt 安装 python3-tk？"; then
            sudo apt update
            sudo apt install -y python3-tk
        else
            echo "    Debian/Ubuntu : sudo apt install python3-tk"
            echo "    Fedora        : sudo dnf install python3-tkinter"
            echo "    Arch          : sudo pacman -S tk"
        fi
    fi

    # Ubuntu/Tk 对 WenQuanYi 中文字体渲染更稳定；缺失时安装一套。
    if ! fc-match "WenQuanYi Micro Hei" 2>/dev/null | grep -qi "wqy\\|WenQuanYi"; then
        echo
        echo "提示：未检测到 WenQuanYi 中文字体，GUI 中文显示可能发虚/挤压。"
        if [[ $HAS_APT -eq 1 ]] && confirm "现在用 sudo apt 安装 fonts-wqy-microhei fonts-wqy-zenhei？"; then
            sudo apt update
            sudo apt install -y fonts-wqy-microhei fonts-wqy-zenhei
        else
            echo "    手动安装：sudo apt install fonts-wqy-microhei fonts-wqy-zenhei"
        fi
    fi

    # pymodbus：modbus_setup_tool.py / mock_modbus_server.py 必需
    if ! "$PY" -c "import pymodbus" 2>/dev/null; then
        echo
        echo "提示：未安装 pymodbus，CLI 和 GUI 调用 Modbus 都会失败。"
        if confirm "现在用 pip 安装 pymodbus==2.5（--user）？"; then
            "$PY" -m pip install --user 'pymodbus==2.5'
        else
            echo "    手动安装：python3 -m pip install --user 'pymodbus==2.5'"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 4) 安装图标
# ---------------------------------------------------------------------------

ICON_LINE=""
if [[ -f "$ICON_SVG" ]]; then
    DST_DIR="$ICON_ROOT/scalable/apps"
    $SUDO mkdir -p "$DST_DIR"
    $SUDO install -m 0644 "$ICON_SVG" "$DST_DIR/${APP_ID}.svg"
    ICON_LINE="Icon=${APP_ID}"   # 用名字索引，desktop spec 推荐写法
    echo "  图标(SVG) : $DST_DIR/${APP_ID}.svg"
elif [[ -f "$ICON_PNG" ]]; then
    DST_DIR="$ICON_ROOT/256x256/apps"
    $SUDO mkdir -p "$DST_DIR"
    $SUDO install -m 0644 "$ICON_PNG" "$DST_DIR/${APP_ID}.png"
    ICON_LINE="Icon=${APP_ID}"
    echo "  图标(PNG) : $DST_DIR/${APP_ID}.png"
    # 顺手生成多尺寸，菜单/Dock 缩略图更清晰
    if command -v convert >/dev/null 2>&1; then
        for size in 48 64 128 512; do
            SZ="${size}x${size}"
            $SUDO mkdir -p "$ICON_ROOT/$SZ/apps"
            $SUDO convert "$ICON_PNG" -resize "${size}x${size}" \
                "$ICON_ROOT/$SZ/apps/${APP_ID}.png" 2>/dev/null || true
        done
    fi
else
    echo "提示：未找到图标文件 $ICON_PNG / $ICON_SVG，启动器将不带图标。"
    echo "      想要图标，请把 modbus.png（或 modbus.svg）放到：$SCRIPT_DIR"
fi

# ---------------------------------------------------------------------------
# 5) 写 .desktop 文件
# ---------------------------------------------------------------------------

$SUDO mkdir -p "$APPS_DIR"

TMP="$(mktemp)"
cat > "$TMP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_DISPLAY
Comment=$APP_COMMENT
Exec="$PY" "$GUI_PY"
$ICON_LINE
Path=$SCRIPT_DIR
Categories=$APP_CATEGORIES
Keywords=$APP_KEYWORDS
Terminal=false
StartupNotify=true
StartupWMClass=$APP_ID
EOF

$SUDO install -m 0644 "$TMP" "$DESKTOP_FILE"
rm -f "$TMP"

# 校验
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE" || \
        echo "（以上为 desktop-file-validate 提示，文件已写入，不影响菜单显示）"
fi

# 刷新菜单 / 图标缓存
command -v update-desktop-database >/dev/null 2>&1 \
    && $SUDO update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && $SUDO gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 6) 可选：在 ~/Desktop 上放一个图标
# ---------------------------------------------------------------------------

if [[ $WITH_DESKTOP -eq 1 ]]; then
    DESK_TARGET="$HOME/Desktop/${APP_ID}.desktop"
    mkdir -p "$HOME/Desktop"
    cp -f "$DESKTOP_FILE" "$DESK_TARGET"
    chmod +x "$DESK_TARGET"
    # Ubuntu/GNOME 要求显式 "trust"，否则桌面上图标会变白色问号
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESK_TARGET" metadata::trusted true 2>/dev/null || true
    fi
    echo "  桌面快捷  : $DESK_TARGET"
fi

# ---------------------------------------------------------------------------
# 7) 收尾
# ---------------------------------------------------------------------------

echo
echo "[OK] 已安装 modbus_setup 启动器（$SCOPE）"
echo "  .desktop : $DESKTOP_FILE"
echo "  程序     : $GUI_PY"
echo "  Python   : $PY"
echo
echo "现在可以在应用菜单（或按 Super 键搜索 \"modbus_setup\"）启动。"
echo "若菜单没立刻刷新，注销重登一次即可；也可命令行直接试运行："
echo "    \"$PY\" \"$GUI_PY\""
