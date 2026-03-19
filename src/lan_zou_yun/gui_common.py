import tkinter as tk
from time import monotonic
from tkinter import ttk


def emit_log(q, msg):
    if q is not None:
        q.put(("log", msg))


def emit_progress(q, phase, current, total, detail="", overall=None):
    if q is not None:
        q.put(
            (
                "progress",
                {
                    "phase": phase,
                    "current": current,
                    "total": total,
                    "detail": detail,
                    "overall": overall,
                },
            )
        )


def format_size(num_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{int(num_bytes)} B"


def overall_percent(current, total, start_percent, span_percent):
    if total <= 0:
        return start_percent + span_percent
    ratio = min(max(current / total, 0.0), 1.0)
    return start_percent + span_percent * ratio


class ProgressPanelMixin:
    def _init_progress_state(self, idle_text):
        self.phase_var = tk.StringVar(value="等待开始")
        self.progress_var = tk.StringVar(value="0%")
        self.status_var = tk.StringVar(value=idle_text)
        self.speed_var = tk.StringVar(value="速度 --，预计剩余 --")
        self.is_running = False
        self.phase_started_at = 0.0
        self.current_phase = ""
        self.inputs = []

    def _build_progress_panel(self, parent, start_row, button_text, button_command, log_height=12, log_width=74):
        ttk.Label(parent, textvariable=self.phase_var, style="Phase.TLabel").grid(
            row=start_row, column=0, columnspan=3, sticky="w", pady=(12, 4)
        )

        self.progress = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.progress.grid(row=start_row + 1, column=0, columnspan=3, sticky="ew", pady=10)

        ttk.Label(parent, textvariable=self.progress_var).grid(
            row=start_row + 2, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(parent, textvariable=self.status_var).grid(
            row=start_row + 3, column=0, columnspan=3, sticky="w", pady=(2, 0)
        )
        ttk.Label(parent, textvariable=self.speed_var).grid(
            row=start_row + 4, column=0, columnspan=3, sticky="w", pady=(2, 8)
        )

        self.start_button = ttk.Button(parent, text=button_text, command=button_command)
        self.start_button.grid(row=start_row + 5, column=0, columnspan=3, pady=5)

        self.log_text = tk.Text(parent, height=log_height, width=log_width)
        log_row = start_row + 6
        parent.rowconfigure(log_row, weight=1)
        self.log_text.grid(row=log_row, column=0, columnspan=3, sticky="nsew", pady=5)
        self.log_text.configure(state="disabled")

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_running(self, running):
        self.is_running = running
        for widget in self.inputs:
            widget.configure(state="disabled" if running else "normal")

    @staticmethod
    def _format_eta(seconds):
        if seconds < 60:
            return f"{int(seconds)} 秒"
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes} 分 {secs} 秒"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分"

    def _reset_progress(self, status_text):
        self.progress["value"] = 0
        self.phase_var.set("准备开始")
        self.progress_var.set("0.0%")
        self.status_var.set(status_text)
        self.speed_var.set("速度 --，预计剩余 --")
        self.current_phase = ""
        self.phase_started_at = monotonic()

    def _handle_progress(self, payload):
        phase = payload["phase"]
        current = max(payload.get("current", 0), 0)
        total = max(payload.get("total", 0), 0)
        overall = payload.get("overall")
        detail = payload.get("detail", "")

        if phase != self.current_phase:
            self.current_phase = phase
            self.phase_started_at = monotonic()

        percent = max(0.0, min(float(overall or 0) * 100, 100.0))
        self.progress["value"] = percent
        self.phase_var.set(phase)
        self.progress_var.set(f"{percent:.1f}%")
        self.status_var.set(detail or "正在处理中")

        elapsed = max(monotonic() - self.phase_started_at, 0.001)
        if total > 0 and current > 0:
            speed = current / elapsed
            remaining = max(total - current, 0)
            eta = remaining / speed if speed > 0 else 0
            self.speed_var.set(
                f"速度 {format_size(speed)}/s，预计剩余 {self._format_eta(eta)}"
            )
        else:
            self.speed_var.set("速度 --，预计剩余 --")

    def _mark_complete(self, phase_text, status_text):
        self.progress["value"] = 100
        self.phase_var.set(phase_text)
        self.progress_var.set("100.0%")
        self.status_var.set(status_text)
        self.speed_var.set("速度 --，预计剩余 0 秒")
