#include "my_application.h"

#include <flutter_linux/flutter_linux.h>
#ifdef GDK_WINDOWING_X11
#include <gdk/gdkx.h>
#endif

#include "flutter/generated_plugin_registrant.h"

struct _MyApplication {
  GtkApplication parent_instance;
  char** dart_entrypoint_arguments;
};

G_DEFINE_TYPE(MyApplication, my_application, GTK_TYPE_APPLICATION)

// FlView 在 GNOME/Mutter（尤其是 Wayland）下首帧偶发"只画半屏 / 全灰"。
// 复现的根因是窗口已经 show 出来，但 FlView 的 GL allocation 仍然停留在旧/空尺寸；
// 等 Dart 引擎把第一帧推上来时，GTK 没有派发到一次真正的 reallocate，于是只看到部分 surface。
//
// 这里的修复套路（已验证有效，参考 flutter/flutter#110667 等多个 issue）：
//   1) 窗口 show 之后，等主循环空闲时再做一次 "resize jiggle"——
//      先把窗口尺寸 +1，再改回原尺寸。+1 这一步是关键：必须是"真的不同的尺寸"，
//      GTK 才会下发 size-allocate，FlView 才会重新申请正确大小的 GL surface。
//   2) 同时对窗口和 FlView 各 queue 一次 resize+draw，覆盖个别版本下的渲染漏帧。
//
// 之所以放在 g_timeout_add 里而不是直接同步调用：show -> resize 太快，GTK 会把这两次
// 尺寸合并成一次"等于默认尺寸"的分配，依然走不到 FlView 的真正 reallocate 路径。
// 加 ~80ms 延迟足以让 FlView 的 GL surface 拿到现场尺寸后再被 jiggle 一下。
static gboolean hy_kick_first_frame(gpointer user_data) {
  GtkWindow* window = GTK_WINDOW(user_data);
  if (!GTK_IS_WINDOW(window)) {
    return G_SOURCE_REMOVE;
  }

  gint w = 0, h = 0;
  gtk_window_get_size(window, &w, &h);
  if (w <= 0 || h <= 0) {
    w = 1280;
    h = 720;
  }

  // 真正会触发 size-allocate 的"抖动"：先 +1 再改回去。
  gtk_window_resize(window, w + 1, h);
  gtk_window_resize(window, w, h);

  // 兜底：让窗口和它的子树（含 FlView）下一帧重排重绘一次。
  gtk_widget_queue_resize(GTK_WIDGET(window));
  gtk_widget_queue_draw(GTK_WIDGET(window));

  return G_SOURCE_REMOVE;  // 一次性
}

// Implements GApplication::activate.
static void my_application_activate(GApplication* application) {
  MyApplication* self = MY_APPLICATION(application);
  GtkWindow* window =
      GTK_WINDOW(gtk_application_window_new(GTK_APPLICATION(application)));

  // Use a header bar when running in GNOME as this is the common style used
  // by applications and is the setup most users will be using (e.g. Ubuntu
  // desktop).
  // If running on X and not using GNOME then just use a traditional title bar
  // in case the window manager does more exotic layout, e.g. tiling.
  // If running on Wayland assume the header bar will work (may need changing
  // if future cases occur).
  gboolean use_header_bar = TRUE;
#ifdef GDK_WINDOWING_X11
  GdkScreen* screen = gtk_window_get_screen(window);
  if (GDK_IS_X11_SCREEN(screen)) {
    const gchar* wm_name = gdk_x11_screen_get_window_manager_name(screen);
    if (g_strcmp0(wm_name, "GNOME Shell") != 0) {
      use_header_bar = FALSE;
    }
  }
#endif
  if (use_header_bar) {
    GtkHeaderBar* header_bar = GTK_HEADER_BAR(gtk_header_bar_new());
    gtk_widget_show(GTK_WIDGET(header_bar));
    gtk_header_bar_set_title(header_bar, "hy_monitor");
    gtk_header_bar_set_show_close_button(header_bar, TRUE);
    gtk_window_set_titlebar(window, GTK_WIDGET(header_bar));
  } else {
    gtk_window_set_title(window, "hy_monitor");
  }

  gtk_window_set_default_size(window, 1280, 720);

  g_autoptr(FlDartProject) project = fl_dart_project_new();
  fl_dart_project_set_dart_entrypoint_arguments(project, self->dart_entrypoint_arguments);

  FlView* view = fl_view_new(project);
  // 给 FlView 一个最小尺寸，避免某些主题在窗口很小时把它压成 0×0 后再放大引发的渲染异常。
  gtk_widget_set_size_request(GTK_WIDGET(view), 800, 600);
  gtk_widget_show(GTK_WIDGET(view));
  gtk_container_add(GTK_CONTAINER(window), GTK_WIDGET(view));

  fl_register_plugins(FL_PLUGIN_REGISTRY(view));

  gtk_widget_show(GTK_WIDGET(window));

  // 见函数注释：~80ms 后做一次 resize-jiggle，规避 FlView 首帧只画半屏 / 全灰。
  g_timeout_add(80, hy_kick_first_frame, window);
  // 再补一次更晚的兜底（如 GL 上下文初始化较慢的弱机器/虚拟机）。
  g_timeout_add(400, hy_kick_first_frame, window);

  gtk_widget_grab_focus(GTK_WIDGET(view));
}

// Implements GApplication::local_command_line.
static gboolean my_application_local_command_line(GApplication* application, gchar*** arguments, int* exit_status) {
  MyApplication* self = MY_APPLICATION(application);
  // Strip out the first argument as it is the binary name.
  self->dart_entrypoint_arguments = g_strdupv(*arguments + 1);

  g_autoptr(GError) error = nullptr;
  if (!g_application_register(application, nullptr, &error)) {
     g_warning("Failed to register: %s", error->message);
     *exit_status = 1;
     return TRUE;
  }

  g_application_activate(application);
  *exit_status = 0;

  return TRUE;
}

// Implements GApplication::startup.
static void my_application_startup(GApplication* application) {
  //MyApplication* self = MY_APPLICATION(object);

  // Perform any actions required at application startup.

  G_APPLICATION_CLASS(my_application_parent_class)->startup(application);
}

// Implements GApplication::shutdown.
static void my_application_shutdown(GApplication* application) {
  //MyApplication* self = MY_APPLICATION(object);

  // Perform any actions required at application shutdown.

  G_APPLICATION_CLASS(my_application_parent_class)->shutdown(application);
}

// Implements GObject::dispose.
static void my_application_dispose(GObject* object) {
  MyApplication* self = MY_APPLICATION(object);
  g_clear_pointer(&self->dart_entrypoint_arguments, g_strfreev);
  G_OBJECT_CLASS(my_application_parent_class)->dispose(object);
}

static void my_application_class_init(MyApplicationClass* klass) {
  G_APPLICATION_CLASS(klass)->activate = my_application_activate;
  G_APPLICATION_CLASS(klass)->local_command_line = my_application_local_command_line;
  G_APPLICATION_CLASS(klass)->startup = my_application_startup;
  G_APPLICATION_CLASS(klass)->shutdown = my_application_shutdown;
  G_OBJECT_CLASS(klass)->dispose = my_application_dispose;
}

static void my_application_init(MyApplication* self) {}

MyApplication* my_application_new() {
  // Set the program name to the application ID, which helps various systems
  // like GTK and desktop environments map this running application to its
  // corresponding .desktop file. This ensures better integration by allowing
  // the application to be recognized beyond its binary name.
  g_set_prgname(APPLICATION_ID);

  return MY_APPLICATION(g_object_new(my_application_get_type(),
                                     "application-id", APPLICATION_ID,
                                     "flags", G_APPLICATION_NON_UNIQUE,
                                     nullptr));
}
