"""
modbus_setup_gui.py —— modbus_setup_tool.py 的图形前端
========================================================

界面布局（从上到下）：
1) 配置文件栏：路径输入 + 选择 / 新建 / 重载 / 保存
2) JSON 编辑器：直接对当前文件做修改并保存（保存时校验 JSON 语法）
3) 操作区：4 个功能按钮（init / show / write-ip / test），
   每个按钮各自带一个下拉框，列出 modbus_setup_tool.py 对应子命令的常用变体；
   write-ip / test 还带一个"模块名"输入框，用于 -m 选项
4) 底部日志面板：流式显示子进程 stdout / stderr，可清空

依赖：Python 标准库（tkinter）。
被调用：同目录下的 modbus_setup_tool.py（其自身依赖 pymodbus==2.5）。

直接运行：
    Windows : python modbus_setup_gui.py
    Linux   : python3 modbus_setup_gui.py
    macOS   : python3 modbus_setup_gui.py

Linux 上若提示 ``ModuleNotFoundError: No module named 'tkinter'`` 或
``_tkinter ... not configured``，先按发行版安装 Tk：

    Debian / Ubuntu : sudo apt install python3-tk
    Fedora / RHEL   : sudo dnf install python3-tkinter
    Arch / Manjaro  : sudo pacman -S tk
    openSUSE        : sudo zypper install python3-tk

无显示器的服务器（SSH/CI）跑 GUI 需要 X 转发或 VNC，无 UI 场景请改用
命令行 modbus_setup_tool.py。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    BOTH, DISABLED, END, LEFT, NORMAL, WORD, X,
    StringVar, Tk, filedialog, messagebox,
)
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import List, Optional


# Windows 下让 print 输出走 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


HERE = Path(__file__).resolve().parent
TOOL_PATH = HERE / "modbus_setup_tool.py"
DEFAULT_CONFIG = HERE / "setup.json"


# ---------------------------------------------------------------------------
# 字体配置（按优先级覆盖）：
#   1) 环境变量 MODBUS_GUI_MONO_FONT / MODBUS_GUI_UI_FONT 最高优先
#   2) 下面 FORCE_* 两个常量次之（直接改这两行即可，比修改候选列表方便）
#   3) 都为空时按 CANDIDATES_* 列表逐个探测系统已装字体
# ---------------------------------------------------------------------------

FORCE_MONO_FONT = ""  # 留空：启动时从 Tk 实际识别到的字体里自动挑
FORCE_UI_FONT   = ""  # 留空：启动时从 Tk 实际识别到的字体里自动挑

CANDIDATES_MONO = (
    # 自带中文的等宽（最优先，CJK 与 Latin 同基线、双宽对齐）
    "Noto Sans Mono CJK SC", "Noto Sans Mono CJK TC",
    "WenQuanYi Zen Hei Mono", "WenQuanYi Micro Hei Mono",
    "Sarasa Mono SC", "Source Han Mono SC", "Source Han Mono",
    # Windows
    "Consolas", "Cascadia Mono", "Cascadia Code",
    # macOS
    "Menlo", "Monaco",
    # 不含中文的等宽兜底（CJK 会被系统替换字体）
    "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono",
    "Source Code Pro", "Courier New", "Courier",
)

CANDIDATES_UI = (
    "Noto Sans CJK SC", "Noto Sans CJK TC",
    "Source Han Sans SC", "Source Han Sans CN",
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
    "Microsoft YaHei UI", "Microsoft YaHei",
    "PingFang SC", "Hiragino Sans GB",
    "Ubuntu", "Cantarell", "DejaVu Sans", "Liberation Sans",
    "Segoe UI", "Arial",
)


def _available_families() -> set:
    import tkinter.font as tkfont
    try:
        return set(tkfont.families())
    except Exception:
        return set()


def _resolve_font(forced: str, env_var: str, candidates: tuple, size: int,
                  default_name: str) -> tuple:
    """统一的字体挑选：env > FORCE_常量 > 候选列表 > 默认命名字体。

    注意：Linux 上 fontconfig/fc-list 能看到的 TTC 子字体名，不一定会出现在
    tkinter.font.families() 返回值里。因此 env / FORCE_ 指定的字体直接交给 Tk，
    不再提前判定“不存在”，避免误回退。
    """
    chosen = (os.environ.get(env_var) or "").strip() or forced.strip()
    available = _available_families()
    if chosen:
        return (chosen, size)
    for name in candidates:
        if name in available:
            return (name, size)
    return (default_name, size)


def pick_mono_font(size: int) -> tuple:
    return _resolve_font(FORCE_MONO_FONT, "MODBUS_GUI_MONO_FONT",
                         CANDIDATES_MONO, size, "TkFixedFont")


def pick_ui_font(size: int) -> tuple:
    return _resolve_font(FORCE_UI_FONT, "MODBUS_GUI_UI_FONT",
                         CANDIDATES_UI, size, "TkDefaultFont")


# ---------------------------------------------------------------------------
# 下拉变体：每个子命令的"细致功能"
# ---------------------------------------------------------------------------


@dataclass
class Variant:
    label: str
    args: List[str]              # 传给 modbus_setup_tool.py 的参数（不含 -c <file>）
    needs_module: bool = False   # 是否需要在 args[0] 后插入 -m <模块名>


INIT_VARIANTS: List[Variant] = [
    Variant("生成示例配置（已存在则报错）", ["init"]),
    Variant("生成示例配置（强制覆盖）",     ["init", "--force"]),
]

SHOW_VARIANTS: List[Variant] = [
    Variant("打印简要摘要",       ["show"]),
    Variant("打印详细摘要 (-v)",  ["show", "-v"]),
]

WRITE_VARIANTS: List[Variant] = [
    Variant("全部模块 - dry-run 预览",         ["write-ip", "--all", "--dry-run"]),
    Variant("全部模块 - 实际写入 (-y)",        ["write-ip", "--all", "-y"]),
    Variant("全部模块 - 实际写入(失败即停)",   ["write-ip", "--all", "-y", "--stop-on-error"]),
    Variant("指定模块 - dry-run 预览",         ["write-ip", "--dry-run"],                       needs_module=True),
    Variant("指定模块 - 实际写入 (-y)",        ["write-ip", "-y"],                              needs_module=True),
    Variant("指定模块 - 实际写入(失败即停)",   ["write-ip", "-y", "--stop-on-error"],           needs_module=True),
]

TEST_VARIANTS: List[Variant] = [
    Variant("全部模块 (target IP)",                  ["test"]),
    Variant("全部模块 (current IP)",                 ["test", "--use-current"]),
    Variant("全部模块 (current IP) - 重复 3 轮",     ["test", "--use-current", "--repeat", "3"]),
    Variant("全部模块 - 导出 result.json (current)", ["test", "--use-current", "-o", "result.json"]),
    Variant("指定模块 (target IP)",                  ["test"],                          needs_module=True),
    Variant("指定模块 (current IP)",                 ["test", "--use-current"],         needs_module=True),
]


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.geometry("1000x740")
        self.root.minsize(820, 600)

        self.config_path = StringVar(value=str(DEFAULT_CONFIG))
        self.module_write = StringVar()
        self.module_test = StringVar()
        self.module_combos: List[ttk.Combobox] = []
        self.dirty = False
        self._loading = False

        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.proc: Optional[subprocess.Popen] = None

        self._build_ui()
        self._update_title()
        self._poll_log()

        p = Path(self.config_path.get())
        if p.exists():
            self.load_file(p)
        else:
            self._log_status(f"默认路径 {p} 不存在，可点「选择」打开其他文件或「新建」创建。")

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        # 跨平台主题：vista 仅 Windows；aqua 仅 macOS；clam 在所有平台可用且较"现代"
        style = ttk.Style()
        preferred = ("vista", "aqua", "clam", "alt", "default")
        available_themes = set(style.theme_names())
        for theme in preferred:
            if theme in available_themes:
                try:
                    style.theme_use(theme)
                    break
                except Exception:
                    continue

        self.style = style
        self.apply_font(log_change=False)
        style.configure("TButton", padding=(8, 4))
        style.configure("Run.TButton", padding=(14, 4))

        # --- 文件栏
        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(fill=X)
        ttk.Label(bar, text="配置文件:").pack(side=LEFT)
        ttk.Entry(bar, textvariable=self.config_path).pack(side=LEFT, fill=X, expand=True, padx=6)
        ttk.Button(bar, text="选择...",  command=self.browse_file).pack(side=LEFT, padx=2)
        ttk.Button(bar, text="新建",      command=self.new_file   ).pack(side=LEFT, padx=2)
        ttk.Button(bar, text="重载",      command=self.reload_file).pack(side=LEFT, padx=2)
        ttk.Button(bar, text="保存",      command=self.save_file  ).pack(side=LEFT, padx=2)

        # --- JSON 编辑器（固定较矮，不随窗口放大；多余空间留给日志）
        edit_frame = ttk.LabelFrame(self.root, text="JSON 编辑器（保存时会校验语法）", padding=4)
        edit_frame.pack(fill=X, expand=False, padx=10, pady=4)
        self.editor = ScrolledText(edit_frame, wrap="char", font=self.editor_font,
                                    undo=True, height=15)
        self.editor.configure(spacing1=3, spacing2=1, spacing3=5)
        self.editor.pack(fill=BOTH, expand=True)
        self.editor.bind("<<Modified>>", self._on_modified)

        # --- 操作区
        actions = ttk.LabelFrame(self.root, text="操作（每行：功能 → 下拉框选具体变体 → 执行）", padding=10)
        actions.pack(fill=X, padx=10, pady=4)
        actions.columnconfigure(1, weight=1)

        self._build_action_row(actions, 0, "init",      INIT_VARIANTS,  None)
        self._build_action_row(actions, 1, "show",      SHOW_VARIANTS,  None)
        self._build_action_row(actions, 2, "write-ip",  WRITE_VARIANTS, self.module_write)
        self._build_action_row(actions, 3, "test",      TEST_VARIANTS,  self.module_test)

        # 控制行：停止 / 清日志
        ctl = ttk.Frame(actions)
        ctl.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        self.stop_btn = ttk.Button(ctl, text="停止当前命令", command=self.stop_proc, state=DISABLED)
        self.stop_btn.pack(side=LEFT)
        ttk.Button(ctl, text="清空日志", command=self.clear_log).pack(side=LEFT, padx=8)

        # --- 日志（吃掉窗口剩余的所有垂直空间，并给一个较高的初始值）
        log_frame = ttk.LabelFrame(self.root, text="日志输出", padding=4)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=(4, 10))
        self.log = ScrolledText(
            log_frame, wrap="none", height=24, font=self.log_font, state=DISABLED,
            background="#111", foreground="#dadada", insertbackground="#dadada",
        )
        self.log.configure(spacing1=2, spacing2=1, spacing3=4)
        self.log.pack(fill=BOTH, expand=True)
        self.log.tag_configure("cmd",    foreground="#7fdbff")
        self.log.tag_configure("end_ok", foreground="#7CFC9F")
        self.log.tag_configure("end_ng", foreground="#ff6b6b")
        self.log.tag_configure("status", foreground="#ffd166")
        self.log.tag_configure("err",    foreground="#ff6b6b")

    def apply_font(self, log_change: bool = True):
        """使用 Tk 默认字体，并加大字号/行距，避免 Linux 中文字体回退时挤压。"""
        # 编辑器已经验证正常，因此 UI 也统一使用同一个 TkTextFont，
        # 避免 ttk 控件继续走 Ubuntu/Tk 的另一套默认小字体。
        self.ui_font = "TkTextFont"
        self.editor_font = "TkTextFont"
        self.log_font = "TkTextFont"

        import tkinter.font as tkfont
        # 不再设置 family：交给 Ubuntu/Tk/fontconfig 自己选最合适的中文回退字体。
        # 只放大字号和行高相关指标，解决中文字上下/左右挤压的问题。
        for nm, size in (
            ("TkDefaultFont", 12),
            ("TkTextFont", 12),
            ("TkHeadingFont", 12),
            ("TkMenuFont", 12),
            ("TkCaptionFont", 12),
            ("TkTooltipFont", 12),
            ("TkIconFont", 12),
        ):
            try:
                tkfont.nametofont(nm).configure(size=size, weight="normal")
            except Exception:
                pass

        self.root.option_add("*Font", self.ui_font)
        self.root.option_add("*Listbox*Font", self.ui_font)
        self.root.option_add("*TCombobox*Listbox.font", self.ui_font)
        if hasattr(self, "style"):
            self.style.configure(".", font=self.ui_font)
            self.style.configure("TLabel", font=self.ui_font)
            self.style.configure("TButton", font=self.ui_font)
            self.style.configure("TEntry", font=self.ui_font)
            self.style.configure("TCombobox", font=self.ui_font)
            self.style.configure("TLabelframe.Label", font=self.ui_font)

        if hasattr(self, "editor"):
            self.editor.configure(font=self.editor_font)
        if hasattr(self, "log"):
            self.log.configure(font=self.log_font)
        if log_change and hasattr(self, "log"):
            self._log_status("已切换为系统默认字体 + 加大行距模式")

    def _build_action_row(self, parent, row: int, name: str,
                          variants: List[Variant], module_var: Optional[StringVar]):
        ttk.Label(parent, text=name, width=10).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)

        var = StringVar(value=variants[0].label)
        cb = ttk.Combobox(parent, textvariable=var, values=[v.label for v in variants],
                           state="readonly")
        cb.grid(row=row, column=1, sticky="ew", padx=2, pady=4)

        if module_var is not None:
            ttk.Label(parent, text="模块名:").grid(row=row, column=2, sticky="e", padx=(12, 4))
            module_cb = ttk.Combobox(
                parent,
                textvariable=module_var,
                values=[],
                state="readonly",
                width=18,
            )
            module_cb.grid(row=row, column=3, sticky="w")
            self.module_combos.append(module_cb)
        else:
            ttk.Label(parent, text="").grid(row=row, column=2)
            ttk.Label(parent, text="").grid(row=row, column=3)

        ttk.Button(
            parent, text="执行", style="Run.TButton",
            command=lambda: self.run_variant(variants, var.get(), module_var),
        ).grid(row=row, column=4, sticky="e", padx=(12, 0))

    # --------------------------------------------------------------- 文件操作

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="选择 JSON 配置",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
            initialdir=str(HERE),
        )
        if path:
            if self.dirty and not self._confirm_discard():
                return
            self.load_file(Path(path))

    def new_file(self):
        path = filedialog.asksaveasfilename(
            title="新建 JSON 配置",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(HERE),
        )
        if not path:
            return
        if self.dirty and not self._confirm_discard():
            return
        self.config_path.set(path)
        self._set_editor_text("")
        self._refresh_module_choices("")
        self.dirty = False
        self._update_title()
        self._log_status(f"已选定新文件 {path}（可执行 init 生成模板，或直接在编辑器粘贴 JSON 后保存）")

    def reload_file(self):
        p = Path(self.config_path.get())
        if not p.exists():
            messagebox.showwarning("提示", f"文件不存在：{p}")
            return
        if self.dirty and not self._confirm_discard():
            return
        self.load_file(p)

    def load_file(self, p: Path):
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as ex:
            messagebox.showerror("打开失败", str(ex))
            return
        self.config_path.set(str(p))
        self._set_editor_text(content)
        self._refresh_module_choices(content)
        self.dirty = False
        self._update_title()
        self._log_status(f"已加载 {p}（{len(content)} 字节）")

    def save_file(self) -> bool:
        p_str = self.config_path.get().strip()
        if not p_str:
            messagebox.showwarning("提示", "请先选择/新建文件路径")
            return False
        p = Path(p_str)
        if not p.parent.exists():
            messagebox.showerror("保存失败", f"目录不存在：{p.parent}")
            return False

        content = self.editor.get("1.0", END).rstrip("\n") + "\n"
        # 校验 JSON
        try:
            json.loads(content)
        except json.JSONDecodeError as ex:
            messagebox.showerror("JSON 格式错误", f"未保存。\n\n{ex}")
            self._log_status(f"保存被拒绝（JSON 语法错误）：{ex}")
            return False
        try:
            p.write_text(content, encoding="utf-8")
        except Exception as ex:
            messagebox.showerror("保存失败", str(ex))
            return False
        self.dirty = False
        self._refresh_module_choices(content)
        self._update_title()
        self._log_status(f"已保存 {p}")
        return True

    def _refresh_module_choices(self, content: Optional[str] = None):
        """从当前 JSON 的 modules[].name 刷新模块名下拉框。"""
        if content is None:
            content = self.editor.get("1.0", END).strip()

        names: List[str] = []
        if content.strip():
            try:
                data = json.loads(content)
                modules = data.get("modules", []) if isinstance(data, dict) else []
                for module in modules:
                    if not isinstance(module, dict):
                        continue
                    name = str(module.get("name", "")).strip()
                    if name and name not in names:
                        names.append(name)
            except json.JSONDecodeError:
                pass

        for combo in self.module_combos:
            combo.configure(values=names)

        for var in (self.module_write, self.module_test):
            current = var.get().strip()
            if current not in names:
                var.set(names[0] if names else "")

    def _confirm_discard(self) -> bool:
        return messagebox.askyesno("有未保存的修改", "继续操作会丢弃未保存的修改，是否继续？")

    def _set_editor_text(self, content: str):
        self._loading = True
        try:
            self.editor.delete("1.0", END)
            if content:
                self.editor.insert("1.0", content)
            self.editor.edit_reset()
            self.editor.edit_modified(False)
        finally:
            self.root.after_idle(lambda: setattr(self, "_loading", False))

    def _on_modified(self, _evt):
        if self._loading:
            self.editor.edit_modified(False)
            return
        if self.editor.edit_modified():
            if not self.dirty:
                self.dirty = True
                self._update_title()
            self.editor.edit_modified(False)

    def _update_title(self):
        base = "Modbus Setup Tool — GUI"
        p = self.config_path.get() or "(未选择)"
        mark = " *" if self.dirty else ""
        self.root.title(f"{base}  [{p}]{mark}")

    # --------------------------------------------------------------- 执行命令

    def run_variant(self, variants: List[Variant], label: str, module_var: Optional[StringVar]):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("提示", "已有命令在运行，请先「停止」或等待完成")
            return

        v = next((x for x in variants if x.label == label), None)
        if not v:
            return

        cfg = self.config_path.get().strip()
        if not cfg:
            messagebox.showwarning("缺少配置文件", "请先在顶部选择或新建配置文件")
            return

        # 未保存提示（init/save 文件本身要被覆盖时除外）
        is_init = v.args and v.args[0] == "init"
        if self.dirty and not is_init:
            ans = messagebox.askyesnocancel(
                "未保存", "JSON 编辑器有未保存改动，是否保存后再执行？\n（取消则中止执行）",
            )
            if ans is None:
                return
            if ans and not self.save_file():
                return

        # 组装参数
        args = list(v.args)
        if v.needs_module:
            mod = (module_var.get() if module_var else "").strip()
            if not mod:
                messagebox.showwarning("缺少模块名", "请在右侧下拉框选择模块名")
                return
            args = [args[0], "-m", mod] + args[1:]

        # init 没有 -c 时也会写到当前选的文件，这里仍传 -c 保证写到正确位置
        cmd = [sys.executable, "-u", str(TOOL_PATH), "-c", cfg] + args
        self._start_proc(cmd, is_init=is_init)

    def _start_proc(self, cmd: List[str], is_init: bool = False):
        self._append_log("$ " + " ".join(cmd) + "\n", tag="cmd")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=str(HERE),
            )
        except Exception as ex:
            self._append_log(f"启动失败：{ex}\n", tag="err")
            return

        self.stop_btn.config(state=NORMAL)
        threading.Thread(
            target=self._reader, args=(self.proc, is_init), daemon=True,
        ).start()

    def _reader(self, proc: subprocess.Popen, is_init: bool):
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log_queue.put(("OUT", line))
            rc = proc.wait()
            self.log_queue.put(("END", rc, is_init))
        except Exception as ex:
            self.log_queue.put(("END", -1, is_init, f"读取异常 {ex}"))

    def stop_proc(self):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            self._append_log("[已请求停止]\n", tag="status")
        except Exception as ex:
            self._append_log(f"[停止失败 {ex}]\n", tag="err")

    # ------------------------------------------------------------------ 日志

    def _poll_log(self):
        finished = False
        finished_is_init = False
        finished_rc = 0
        finished_err: Optional[str] = None
        while True:
            try:
                evt = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if evt[0] == "OUT":
                self._append_log(evt[1])
            elif evt[0] == "END":
                finished = True
                finished_rc = evt[1] if len(evt) > 1 else 0
                finished_is_init = evt[2] if len(evt) > 2 else False
                finished_err = evt[3] if len(evt) > 3 else None
        if finished:
            self.stop_btn.config(state=DISABLED)
            tag = "end_ok" if finished_rc == 0 else "end_ng"
            self._append_log(f"[退出码 {finished_rc}]\n", tag=tag)
            if finished_err:
                self._append_log(f"[{finished_err}]\n", tag="err")
            # init 成功后自动重新加载文件
            if finished_is_init and finished_rc == 0:
                p = Path(self.config_path.get())
                if p.exists():
                    self.load_file(p)
                    self._log_status("init 完成，已重新加载到编辑器")
        self.root.after(80, self._poll_log)

    def _append_log(self, text: str, tag: Optional[str] = None):
        self.log.config(state=NORMAL)
        if tag:
            self.log.insert(END, text, tag)
        else:
            self.log.insert(END, text)
        self.log.see(END)
        self.log.config(state=DISABLED)

    def _log_status(self, msg: str):
        self._append_log(f"[GUI] {msg}\n", tag="status")

    def clear_log(self):
        self.log.config(state=NORMAL)
        self.log.delete("1.0", END)
        self.log.config(state=DISABLED)


def main():
    if not TOOL_PATH.exists():
        messagebox.showerror(
            "找不到 modbus_setup_tool.py",
            f"GUI 需要与 modbus_setup_tool.py 放在同一目录：\n{HERE}",
        )
        return
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
