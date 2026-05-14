#include <stdlib.h>
#include <string.h>

#include "my_application.h"

static bool hy_env_flag_enabled(const char* name) {
  const char* value = getenv(name);
  return value && strcmp(value, "0") != 0 && value[0] != '\0';
}

// 在 GTK/Flutter 初始化之前就读取环境变量，决定 Linux 渲染策略。
//
//   HY_FORCE_X11=1 时强制走 X11（规避 Wayland 下 FlView 偶发首帧只画半屏的 bug）。
//   HY_FORCE_WAYLAND=1 时强制走 Wayland（如果上面的 jiggle 修复在你机器上已经生效，
//   并且你想试一下原生 Wayland，可以打开它）。
//   HY_USE_HARDWARE_RENDERER=1 时保留硬件渲染；默认走软件渲染，规避部分 Linux 显卡/虚拟机
//   OpenGL 组合下的整窗灰屏、画面偏移和首帧不刷新。
//
// 直接调 setenv 必须发生在 my_application_new 之前，否则 GTK/GDK/Flutter Engine
// 已经选好后端，再设环境变量就来不及了。
static void hy_apply_backend_overrides() {
  if (hy_env_flag_enabled("HY_FORCE_WAYLAND")) {
    setenv("GDK_BACKEND", "wayland", 1);
  } else if (hy_env_flag_enabled("HY_FORCE_X11") ||
             (getenv("GDK_BACKEND") == nullptr && getenv("DISPLAY") != nullptr)) {
    setenv("GDK_BACKEND", "x11", 1);
  }

  if (!hy_env_flag_enabled("HY_USE_HARDWARE_RENDERER") &&
      getenv("FLUTTER_LINUX_RENDERER") == nullptr) {
    setenv("FLUTTER_LINUX_RENDERER", "software", 1);
    // Older Flutter engines do not know FLUTTER_LINUX_RENDERER; this keeps Mesa
    // on llvmpipe as a fallback instead of a broken GPU GL path.
    if (getenv("LIBGL_ALWAYS_SOFTWARE") == nullptr) {
      setenv("LIBGL_ALWAYS_SOFTWARE", "1", 1);
    }
  }
}

int main(int argc, char** argv) {
  hy_apply_backend_overrides();

  g_autoptr(MyApplication) app = my_application_new();
  return g_application_run(G_APPLICATION(app), argc, argv);
}
