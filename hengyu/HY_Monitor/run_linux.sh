#!/usr/bin/env bash
# Linux 下一键启动 HY Monitor（开发态，热重载）。
#
# 使用：
#   cd hengyu/HY_Monitor
#   ./run_linux.sh                          # 连本机 test1.py
#   ./run_linux.sh http://192.168.1.20:8001 # 连远端
#   ./run_linux.sh --release                # 跑 Release（Linux 桌面下更稳）
#   ./run_linux.sh --wayland                # 显式走 Wayland（默认在 Wayland 会话下会
#                                           # 自动改走 X11，规避 FlView 首帧只画半屏 bug）
#
# 第一次跑会检查 flutter / zenity / GTK，并执行 flutter pub get。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BASE_URL=""
WANT_RELEASE="${HY_RELEASE:-0}"
# 0 = 不主动设置 GDK_BACKEND；1 = 强制 X11；2 = 强制 Wayland
BACKEND_PREF=0
if [[ "${HY_FORCE_X11:-0}" == "1" ]]; then BACKEND_PREF=1; fi
if [[ "${HY_FORCE_WAYLAND:-0}" == "1" ]]; then BACKEND_PREF=2; fi

for arg in "$@"; do
  case "$arg" in
    --release|-r)  WANT_RELEASE=1 ;;
    --debug)       WANT_RELEASE=0 ;;
    --x11)         BACKEND_PREF=1 ;;
    --wayland)     BACKEND_PREF=2 ;;
    -h|--help)
      sed -n '1,16p' "$0"
      exit 0
      ;;
    http://*|https://*) BASE_URL="$arg" ;;
    *)
      echo "[HY Monitor] 未识别的参数: $arg" >&2
      exit 1
      ;;
  esac
done

if ! command -v flutter >/dev/null 2>&1; then
  echo "[HY Monitor] flutter 未安装或未加入 PATH，请先安装 Flutter SDK。" >&2
  exit 1
fi

if ! flutter config --list 2>/dev/null | grep -qE "enable-linux-desktop:\s*true"; then
  echo "[HY Monitor] 启用 Linux 桌面支持…"
  flutter config --enable-linux-desktop >/dev/null
fi

MISSING_APT=()
for pkg in clang cmake ninja pkg-config zenity; do
  if ! command -v "$pkg" >/dev/null 2>&1; then
    MISSING_APT+=("$pkg")
  fi
done
if [[ ${#MISSING_APT[@]} -gt 0 ]]; then
  echo "[HY Monitor] 检测到缺少命令: ${MISSING_APT[*]}" >&2
  echo "            Ubuntu/Debian 可执行:  sudo apt install -y clang cmake ninja-build pkg-config libgtk-3-dev zenity" >&2
  exit 1
fi

echo "[HY Monitor] flutter pub get …"
flutter pub get

# Wayland 下偶发 FlView 初始只画半屏 / 全灰的渲染 bug。
# 默认策略：检测到 Wayland 会话且用户没有显式 --wayland，则自动改走 X11。
SESSION_TYPE="${XDG_SESSION_TYPE:-}"
case "$BACKEND_PREF" in
  1)
    echo "[HY Monitor] backend = X11 (HY_FORCE_X11/--x11)"
    export GDK_BACKEND=x11
    ;;
  2)
    echo "[HY Monitor] backend = Wayland (HY_FORCE_WAYLAND/--wayland)"
    export GDK_BACKEND=wayland
    ;;
  0)
    if [[ "$SESSION_TYPE" == "wayland" ]]; then
      echo "[HY Monitor] 检测到 Wayland 会话，为规避 FlView 首帧渲染 bug 自动切换到 X11。"
      echo "            如需强制使用 Wayland，请加 --wayland 或 export HY_FORCE_WAYLAND=1。"
      export GDK_BACKEND=x11
    else
      echo "[HY Monitor] 会话类型: ${SESSION_TYPE:-unknown}（沿用默认 GDK 后端）"
    fi
    ;;
esac

# 默认 Debug 模式；--release / HY_RELEASE=1 -> Release（Release 在 Linux 上更稳）。
FLUTTER_MODE_ARGS=()
if [[ "$WANT_RELEASE" == "1" ]]; then
  FLUTTER_MODE_ARGS+=(--release)
  echo "[HY Monitor] mode = Release"
else
  echo "[HY Monitor] mode = Debug（如遇渲染异常可改用 --release）"
fi

if [[ -n "$BASE_URL" ]]; then
  echo "[HY Monitor] 注入后端地址: $BASE_URL"
  exec flutter run -d linux "${FLUTTER_MODE_ARGS[@]}" --dart-define=HY_BASE_URL="$BASE_URL"
else
  exec flutter run -d linux "${FLUTTER_MODE_ARGS[@]}"
fi
