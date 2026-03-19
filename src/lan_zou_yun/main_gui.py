import queue
import threading
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

from lan_zou_yun import get_app_version
from lan_zou_yun.app_state import APP_CONFIG_NAME, AppConfig, get_runtime_base_dir
from lan_zou_yun.restore_gui import RestorePage
from lan_zou_yun.split_gui import SplitPage


class HomePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, padding=24)
        self.controller = controller
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="蓝奏云分片助手", font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=0, pady=(10, 8)
        )
        ttk.Label(
            self,
            text="选择要执行的功能。程序会记住常用路径和分片大小，配置文件保存在程序同目录。",
            justify="center",
        ).grid(row=1, column=0, pady=(0, 16))

        self.last_mode_var = tk.StringVar()
        ttk.Label(self, textvariable=self.last_mode_var, foreground="#666666").grid(row=2, column=0, pady=(0, 24))

        cards = ttk.Frame(self)
        cards.grid(row=3, column=0, pady=(0, 24))
        cards.columnconfigure((0, 1), weight=1)

        self.split_button = ttk.Button(cards, text="开始分片", command=lambda: self.controller.show_page("split"))
        self.split_button.grid(row=0, column=0, padx=12, ipadx=24, ipady=18)
        self.restore_button = ttk.Button(cards, text="开始还原", command=lambda: self.controller.show_page("restore"))
        self.restore_button.grid(row=0, column=1, padx=12, ipadx=24, ipady=18)

        self.hint_var = tk.StringVar()
        ttk.Label(self, textvariable=self.hint_var, foreground="#666666").grid(row=4, column=0)

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


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"蓝奏云分片助手 v{get_app_version()}")
        self.geometry("760x620")
        self.resizable(False, False)

        self.config_store = AppConfig()
        self.config_store.load()

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

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_home()

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

    def on_close(self):
        if self.is_busy():
            messagebox.showwarning("提示", "任务执行中，请等待完成后再关闭程序")
            return
        self.split_page.sync_config()
        self.restore_page.sync_config()
        self.config_store.save()
        self.destroy()


def main():
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
