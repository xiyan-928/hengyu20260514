# HY Monitor

对接 `HY_Online/test1.py` 的 Flutter 前端（**首选运行平台：Linux 桌面**）。test1.py 是一个独立 HTTP 聚合服务（默认 `http://<host>:8001`），集中接收多台边缘设备上报的传感器快照与 SPC 谱图文件。本 App 负责把这些数据呈现给运维/巡检人员。

支持平台：**Linux（主）/ Windows / Android**。Linux 端下载 SPC 时调用 GTK `zenity` 原生"另存为"对话框；移动端落到应用文档目录。

---

## 功能一览

| 模块 | 接口 | 说明 |
| --- | --- | --- |
| 设备总览 | `GET /devices` | 列出所有上报过数据的 device_id，显示每台最新一次快照的关键指标与告警状态 |
| 实时快照 | `GET /device/{id}/latest` | 每 N 秒轮询，展示 DDL / pH / pH 温度 / PT100 / 风机 / 阀门 / 告警 / 心跳 |
| 历史趋势 | `GET /device/{id}` | 把所有历史快照绘制成折线图（DDL / pH / pH_Temp / PT100 / Fan） |
| SPC 管理 | `GET /spc/device/{id}`、`.../latest`、`.../files/{name}` | 列出该设备所有 SPC 文件；一键下载最新 / 按文件名下载到本地 |
| 上传自测 | `POST /upload`、`POST /spc/upload` | 设置页内置"上传模拟数据"按钮，便于联调 |

---

## 目录结构

```
HY_Monitor/
├── pubspec.yaml
├── analysis_options.yaml
├── README.md
├── linux/ windows/ android/            # 平台工程（由 flutter create 生成）
└── lib/
    ├── main.dart
    ├── app_config.dart                 # 默认 base_url、刷新间隔等常量
    ├── models/
    │   ├── device_data.dart            # 与后端 DeviceData 字段对齐
    │   └── spc_file_info.dart
    ├── services/
    │   └── api_service.dart            # 封装 test1.py 全部 REST 接口
    ├── providers/
    │   ├── settings_provider.dart      # base_url / 刷新周期，shared_preferences
    │   ├── devices_provider.dart       # 设备列表 + 各设备最新快照，定时刷新
    │   └── device_detail_provider.dart # 单设备详情/历史/SPC 列表
    ├── screens/
    │   ├── home_screen.dart            # 设备列表
    │   ├── device_detail_screen.dart   # TabBar: 实时 / 历史 / SPC
    │   ├── device_history_screen.dart
    │   ├── spc_files_screen.dart
    │   └── settings_screen.dart
    └── widgets/
        ├── metric_card.dart
        ├── valve_chip_panel.dart
        ├── alarm_banner.dart
        └── connection_status_bar.dart
```

---

## Linux 上从零到跑通

### 1. 系统依赖（Ubuntu/Debian 系）

```bash
sudo apt update
sudo apt install -y \
    curl git unzip xz-utils zip \
    clang cmake ninja-build pkg-config \
    libgtk-3-dev liblzma-dev libstdc++-12-dev \
    zenity                       # file_picker 的 Linux 另存为对话框依赖
```

> Fedora/RHEL： `sudo dnf install clang cmake ninja-build pkg-config gtk3-devel zenity`
>
> Arch： `sudo pacman -S clang cmake ninja pkgconf gtk3 zenity`

### 2. 安装 Flutter 并启用 Linux 桌面

```bash
# 以 3.32.x 为例
git clone --depth 1 -b stable https://github.com/flutter/flutter.git ~/flutter
echo 'export PATH="$HOME/flutter/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

flutter config --enable-linux-desktop
flutter doctor                          # 确认 "Linux toolchain" 没有红叉
```

### 3. 构建并运行 HY Monitor

推荐用脚本，它会自动检查依赖、识别 Wayland 并切到 X11、注入 `--dart-define=HY_BASE_URL` 等：

```bash
cd hengyu/HY_Monitor
chmod +x run_linux.sh                       # Windows 跨过来时记得加可执行位

./run_linux.sh                              # Debug，连本机 test1.py
./run_linux.sh http://192.168.1.20:8001     # 连远端后端
./run_linux.sh --release                    # Release（Linux 上更稳）
./run_linux.sh --wayland                    # 显式走原生 Wayland（默认会被切到 X11）
```

或直接用原生命令：

```bash
flutter pub get

# 开发态（热重载）
flutter run -d linux

# Release 构建
flutter build linux --release
./build/linux/x64/release/bundle/hy_monitor       # 产物可拷贝部署
```

### 4. 启动后端

```bash
cd ../HY_Online
python test1.py            # 监听 0.0.0.0:8001
```

首次进入 App 后点右上角 **设置** → 把 `base_url` 改成实际后端（如 `http://192.168.1.20:8001`）→ 点「测试连接」验证。配置会写入 `SharedPreferences`，下次启动自动带出。

---

## Linux 发行包部署

`flutter build linux --release` 产物位于 `build/linux/x64/release/bundle/`，结构形如：

```
bundle/
├── hy_monitor                 # 可执行
├── data/flutter_assets/...
├── lib/libapp.so
└── lib/libflutter_linux_gtk.so
```

整个 `bundle/` 拷贝到目标机即可运行；目标机仍需安装：

```bash
sudo apt install -y libgtk-3-0 zenity
```

---

## 与 test1.py 的字段映射

前端 `DeviceData` 模型严格对齐 `edge_device_data.py::DeviceData`：

```
device_id, ddl, ph, ph_temp, pt100,
valves(Map<String,bool>), is_alarming, fan_speed,
fan_read_ok, fan_last_error, fan_last_read_ts,
last_update_ts, last_error, running, interval
```

所有字段均允许缺失（解析时给默认值），未知字段一律忽略，保证边缘端 schema 微调时前端不崩。

---

## 常见问题

- **窗口一半是灰色 / 只有右侧 / AppBar 标题看不到 / 整窗灰屏**：Linux + GNOME/Mutter/Wayland 下 Flutter 3.x 已知的 FlView 首帧只画部分 GL surface 的 bug。本仓库已经做了多重兜底：
  1. `linux/runner/my_application.cc` 中 `hy_kick_first_frame` 会在窗口 show 之后 ~80ms 与 ~400ms 各做一次"resize jiggle"（先把窗口 +1 px 再改回原尺寸，强制 GTK 下发 size-allocate，让 FlView 的 GL surface 重新申请一次）。
  2. `linux/runner/main.cc` 在 GTK 初始化前读取 `HY_FORCE_X11` / `HY_FORCE_WAYLAND`，可在不改脚本的情况下切换 GDK 后端（双击 release 产物也生效）。
  3. `run_linux.sh` 检测到 `XDG_SESSION_TYPE=wayland` 时会**默认**切到 X11；要保留 Wayland 加 `--wayland` 即可。
  4. FlView 设了 `gtk_widget_set_size_request(view, 800, 600)`，避免极小尺寸下首帧 0×0 引发的渲染异常。
  5. 仍有问题时按顺序排查：
     ```bash
     flutter clean && flutter pub get          # 改过 C++ 必须 clean，否则 ninja 缓存
     ./run_linux.sh --release                  # Release 在 Linux 上更稳
     ./run_linux.sh --x11                      # 显式强制 X11
     echo "$XDG_SESSION_TYPE"                  # 确认当前会话类型
     ```
- **`./run_linux.sh: Permission denied`**：从 Windows / Git for Windows clone 到 Linux 会丢失可执行位。在仓库根执行 `chmod +x hengyu/HY_Monitor/run_linux.sh` 即可；或直接 `bash run_linux.sh`。
- **SPC 下载对话框没弹出来**：Linux 上 `file_picker` 依赖 `zenity`；请执行 `which zenity` 确认已安装。如果依然没弹窗，可启动前设置 `export PATH="$PATH"` 或检查桌面环境是否拦截了 polkit。
- **`flutter run -d linux` 失败，提示缺 `libgtk-3-dev`**：回到第 1 步安装 GTK 开发头文件。
- **连不上后端**：首次启动后默认 `base_url=http://127.0.0.1:8001`，如果前后端不在同一台机器，请到「设置」里改成后端实际 IP。后端 `test1.py` 默认绑定 `0.0.0.0`，外网能访问。
- **跨发行版运行**：Release 产物是动态链接到系统 GTK 的，不同发行版之间建议在目标机重新 `flutter build linux --release`，避免 glibc 版本问题。

---

## 许可

仅供项目内部使用。
