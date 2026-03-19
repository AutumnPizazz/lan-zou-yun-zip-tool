import queue
import threading
import urllib.error
import urllib.request
import webbrowser
import json
import ctypes
from typing import Any, Callable, Literal, cast

import tkinter as tk
from tkinter import TclError, messagebox, ttk
from tkinter import font as tkfont

from lan_zou_yun import get_app_version
from lan_zou_yun.app_state import (
    APP_CONFIG_NAME,
    AppConfig,
    LATEST_RELEASE_API,
    RELEASES_PAGE_URL,
    get_font_scale_limits,
    get_runtime_base_dir,
)
from lan_zou_yun.restore_gui import RestorePage
from lan_zou_yun.split_gui import SplitPage


class HomePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, padding=24)
        self.controller = controller
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="蓝奏云分片助手", style="Header.TLabel").grid(row=0, column=0, pady=(10, 8))
        ttk.Label(
            self,
            text="选择要执行的功能。程序会记住常用路径和分片大小，配置文件保存在程序同目录。",
            justify="center",
            wraplength=560,
        ).grid(row=1, column=0, pady=(0, 16))

        self.last_mode_var = tk.StringVar()
        ttk.Label(self, textvariable=self.last_mode_var, style="Muted.TLabel").grid(row=2, column=0, pady=(0, 24))

        cards = ttk.Frame(self)
        cards.grid(row=3, column=0, pady=(0, 24))
        cards.columnconfigure((0, 1), weight=1)

        self.split_button = ttk.Button(
            cards, text="开始分片", style="Card.TButton", command=lambda: self.controller.show_page("split")
        )
        self.split_button.grid(row=0, column=0, padx=12, ipadx=28, ipady=18)
        self.restore_button = ttk.Button(
            cards, text="开始还原", style="Card.TButton", command=lambda: self.controller.show_page("restore")
        )
        self.restore_button.grid(row=0, column=1, padx=12, ipadx=28, ipady=18)

        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, pady=(0, 12))
        self.check_update_button = ttk.Button(actions, text="检查更新", command=self.controller.check_for_updates)
        self.check_update_button.grid(row=0, column=0, padx=6)

        self.hint_var = tk.StringVar()
        ttk.Label(self, textvariable=self.hint_var, style="Muted.TLabel").grid(row=5, column=0)

        zoom_bar = self.controller.build_zoom_controls(self)
        zoom_bar.grid(row=6, column=0, pady=(18, 6))
        ttk.Label(self, text="提示：按 Ctrl+鼠标滚轮 或 点击按钮缩放文字", style="Hint.TLabel").grid(
            row=7, column=0
        )

    def refresh(self):
        last_page = self.controller.config_store.get("ui", "last_page", default="split")
        last_label = "分片" if last_page != "restore" else "还原"
        self.last_mode_var.set(f"上次使用：{last_label}")

        manifest_path = get_runtime_base_dir() / "manifest.txt"
        if manifest_path.exists():
            self.hint_var.set(f"检测到同目录清单：{manifest_path.name}，可直接进入“还原”。")
        else:
            self.hint_var.set(f"配置文件：{APP_CONFIG_NAME}")

    def set_navigation_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.split_button.configure(state=state)
        self.restore_button.configure(state=state)
        self.check_update_button.configure(state=state)


def _normalize_version(version: str) -> tuple[int, ...]:
    normalized = version.strip().lstrip("vV")
    parts = []
    for part in normalized.split("."):
        digits = []
        for char in part:
            if char.isdigit():
                digits.append(char)
            else:
                break
        parts.append(int("".join(digits) or "0"))
    return tuple(parts)


def _fetch_latest_release_info() -> dict[str, str]:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "lan-zou-zip-tool-gui",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    return {
        "tag_name": str(data.get("tag_name", "")).strip(),
        "html_url": str(data.get("html_url", "")).strip() or RELEASES_PAGE_URL,
        "name": str(data.get("name", "")).strip(),
    }


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self._enable_windows_dpi_awareness()
        self._apply_tk_scaling()
        self.title(f"蓝奏云分片助手 v{get_app_version()}")

        self.config_store = AppConfig()
        self.config_store.load()
        self._font_scale_min, self._font_scale_max, self._font_scale_step = get_font_scale_limits()
        self._font_scale = 1.0
        self._named_fonts: dict[str, tkfont.Font] = {}
        self._named_font_bases: dict[str, int] = {}
        self._apply_window_geometry()
        self.font_scale_var = tk.StringVar()
        self._configure_styles()
        self._init_font_scaling()

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)

        self.home_page = HomePage(self.container, self)
        self.split_page = SplitPage(self.container, self, self.config_store)
        self.restore_page = RestorePage(self.container, self, self.config_store)
        self.pages = {
            "home": self.home_page,
            "split": self.split_page,
            "restore": self.restore_page,
        }

        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.bind_all("<Control-MouseWheel>", self._on_ctrl_mousewheel)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_home()

    @staticmethod
    def _enable_windows_dpi_awareness():
        try:
            shcore = ctypes.windll.shcore
        except AttributeError:
            shcore = None
        if shcore is not None and hasattr(shcore, "SetProcessDpiAwareness"):
            try:
                shcore.SetProcessDpiAwareness(2)
                return
            except OSError:
                pass
        try:
            user32 = ctypes.windll.user32
        except AttributeError:
            user32 = None
        if user32 is not None and hasattr(user32, "SetProcessDPIAware"):
            try:
                user32.SetProcessDPIAware()
            except OSError:
                pass

    def _apply_tk_scaling(self):
        try:
            dpi = self.winfo_fpixels("1i")
            scale = max(dpi / 72.0, 1.0)
            self.tk.call("tk", "scaling", scale)
        except TclError:
            pass

    def _apply_window_geometry(self):
        width = int(self.config_store.get("ui", "window_width", default=760) or 760)
        height = int(self.config_store.get("ui", "window_height", default=620) or 620)
        self.geometry(f"{width}x{height}")
        self.minsize(720, 560)
        self.resizable(True, True)

    def _configure_styles(self):
        style = ttk.Style(self)
        self._create_named_font("AppHeaderFont", 18, "bold")
        self._create_named_font("AppSectionFont", 12, "bold")
        self._create_named_font("AppPhaseFont", 10, "bold")
        self._create_named_font("AppCardFont", 11, "normal")
        style.configure("Header.TLabel", font="AppHeaderFont")
        style.configure("Section.TLabel", font="AppSectionFont")
        style.configure("Phase.TLabel", font="AppPhaseFont")
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Card.TButton", font="AppCardFont")
        style.configure("Hint.TLabel", foreground="#666666")

    @staticmethod
    def _run_background_task(target, state, task_queue):
        try:
            target(state, task_queue)
            if target.__name__ == "run_split":
                task_queue.put(("done", "处理完成"))
        except Exception as e:
            task_queue.put(("error", str(e)))

    @staticmethod
    def start_background_task(target, state):
        task_queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
        threading.Thread(
            target=MainApp._run_background_task,
            args=(target, state, task_queue),
            daemon=True,
        ).start()
        return task_queue

    def show_home(self):
        if self.is_busy():
            return
        self.home_page.refresh()
        self.pages["home"].tkraise()
        self.refresh_navigation_state()

    def show_page(self, name: str):
        if self.is_busy():
            return
        if name == "split":
            self.split_page.load_config()
        elif name == "restore":
            self.restore_page.load_config()
        self.config_store.set("ui", "last_page", value=name)
        self.pages[name].tkraise()
        self.refresh_navigation_state()

    def is_busy(self):
        return self.split_page.is_running or self.restore_page.is_running

    def refresh_navigation_state(self):
        self.home_page.set_navigation_enabled(not self.is_busy())

    def check_for_updates(self):
        if self.is_busy():
            return
        self.home_page.check_update_button.configure(state="disabled")
        self.home_page.hint_var.set("正在检查更新...")
        threading.Thread(target=self._run_update_check, daemon=True).start()

    def _schedule_on_ui_thread(self, callback):
        after_func = cast(Callable[..., object], self.after)
        after_func(0, callback)

    def _run_update_check(self):
        try:
            release_info = _fetch_latest_release_info()
            self._schedule_on_ui_thread(lambda: self._finish_update_check(release_info, None))
        except urllib.error.URLError as e:
            self._schedule_on_ui_thread(
                lambda: self._finish_update_check(None, f"无法连接更新服务器：{e.reason}")
            )
        except Exception as e:
            self._schedule_on_ui_thread(lambda: self._finish_update_check(None, f"检查更新失败：{e}"))

    def _finish_update_check(self, release_info, error_message):
        self.home_page.refresh()
        self.home_page.check_update_button.configure(state="normal")
        if error_message:
            messagebox.showerror("检查更新", error_message)
            return
        self._show_update_result(release_info or {})

    @staticmethod
    def _show_update_result(release_info):
        current_version = get_app_version()
        latest_tag = release_info.get("tag_name", "")
        latest_version = latest_tag.lstrip("vV")
        if latest_tag and _normalize_version(latest_version) > _normalize_version(current_version):
            detail_name = release_info.get("name") or latest_tag
            should_open = messagebox.askyesno(
                "发现新版本",
                f"当前版本：v{current_version}\n最新版本：{detail_name}\n\n是否打开发布页面？",
            )
            if should_open:
                webbrowser.open(release_info.get("html_url") or RELEASES_PAGE_URL)
            return
        messagebox.showinfo("检查更新", f"当前已是最新版本：v{current_version}")

    def on_close(self):
        if self.is_busy():
            messagebox.showwarning("提示", "任务执行中，请等待完成后再关闭程序")
            return
        try:
            self.config_store.set("ui", "window_width", value=self.winfo_width())
            self.config_store.set("ui", "window_height", value=self.winfo_height())
            self.config_store.set("ui", "font_scale", value=self._font_scale)
        except (TclError, ValueError):
            pass
        self.split_page.sync_config()
        self.restore_page.sync_config()
        self.config_store.save()
        self.destroy()

    def _init_font_scaling(self):
        default_font = tkfont.nametofont("TkDefaultFont")
        self._font_base_size = int(default_font.cget("size"))
        self._font_base_sign = -1 if self._font_base_size < 0 else 1
        self._font_base_size = abs(self._font_base_size) or 10
        scale = self.config_store.get("ui", "font_scale", default=1.0)
        try:
            self._font_scale = float(scale)
        except (TypeError, ValueError):
            self._font_scale = 1.0
        self._font_scale = max(self._font_scale_min, min(self._font_scale, self._font_scale_max))
        self._apply_font_scale()

    def _create_named_font(self, name: str, base_size: int, weight: Literal["normal", "bold"]):
        font_obj = tkfont.Font(name=name, exists=False, family="Microsoft YaHei UI", size=base_size, weight=weight)
        self._named_fonts[name] = font_obj
        self._named_font_bases[name] = base_size

    def _apply_font_scale(self):
        size = int(round(self._font_base_size * self._font_scale))
        size = max(size, 9)
        size = size * self._font_base_sign
        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkTooltipFont",
        ):
            try:
                tkfont.nametofont(name).configure(size=size)
            except (TclError, KeyError):
                continue
        for name, font_obj in self._named_fonts.items():
            base = self._named_font_bases.get(name, 10)
            scaled = int(round(base * self._font_scale))
            scaled = max(scaled, 9)
            try:
                font_obj.configure(size=scaled)
            except TclError:
                continue
        self.font_scale_var.set(f"{int(self._font_scale * 100)}%")

    def zoom_in(self):
        self._font_scale = min(self._font_scale + self._font_scale_step, self._font_scale_max)
        self._apply_font_scale()

    def zoom_out(self):
        self._font_scale = max(self._font_scale - self._font_scale_step, self._font_scale_min)
        self._apply_font_scale()

    def zoom_reset(self):
        self._font_scale = 1.0
        self._apply_font_scale()

    def _on_ctrl_mousewheel(self, event):
        if event.delta > 0:
            self.zoom_in()
        elif event.delta < 0:
            self.zoom_out()

    def build_zoom_controls(self, parent):
        bar = ttk.Frame(parent)
        ttk.Label(bar, text="文字缩放：").grid(row=0, column=0, padx=(0, 6))
        ttk.Button(bar, text="A-", width=4, command=self.zoom_out).grid(row=0, column=1, padx=2)
        ttk.Button(bar, text="A+", width=4, command=self.zoom_in).grid(row=0, column=2, padx=2)
        ttk.Button(bar, text="重置", width=4, command=self.zoom_reset).grid(row=0, column=3, padx=2)
        ttk.Label(bar, textvariable=self.font_scale_var, style="Muted.TLabel").grid(row=0, column=4, padx=(6, 0))
        return bar


def main():
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
