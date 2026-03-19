import json
import os
import queue
import shutil
import struct
import tempfile
import threading
import zipfile
import hashlib
from typing import Any, Optional, cast, Callable
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2

from lan_zou_yun import get_app_version
from lan_zou_yun.gui_common import (
    ProgressPanelMixin,
    emit_log,
    emit_progress,
    format_size,
    overall_percent,
)


CHUNK_SIZE = 4 * 1024 * 1024
MAGIC = b"LZYA1"
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16


def _pbkdf2_key(password, salt, iterations):
    return PBKDF2(password, salt, dkLen=32, count=iterations, hmac_hash_module=SHA256)


def sha256_file(path, progress_callback=None):
    h = hashlib.sha256()
    processed = 0
    total = os.path.getsize(path)
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
            processed += len(chunk)
            if progress_callback is not None:
                progress_callback(processed, total)
    return h.hexdigest()


def decrypt_file(enc_path, out_path, password, q=None, progress_callback=None):
    total = os.path.getsize(enc_path)
    header_len = len(MAGIC) + SALT_LEN + NONCE_LEN + 4
    if total < header_len + TAG_LEN:
        raise ValueError("加密文件损坏")

    with open(enc_path, "rb") as f_in:
        magic = f_in.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError("清单与文件不匹配")
        salt = f_in.read(SALT_LEN)
        nonce = f_in.read(NONCE_LEN)
        iterations = struct.unpack(">I", f_in.read(4))[0]

        key = _pbkdf2_key(password, salt, iterations)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

        remaining = total - header_len - TAG_LEN
        processed = 0
        with open(out_path, "wb") as f_out:
            while remaining > 0:
                to_read = CHUNK_SIZE if remaining >= CHUNK_SIZE else remaining
                chunk = f_in.read(to_read)
                if not chunk:
                    break
                data = cipher.decrypt(chunk)
                f_out.write(data)
                remaining -= len(chunk)
                processed += len(chunk)
                emit_log(q, f"解密中 {processed}/{total} 字节")
                if progress_callback is not None:
                    progress_callback(processed, total)

            tag = f_in.read(TAG_LEN)
            try:
                cipher.verify(tag)
            except ValueError as e:
                raise ValueError("密码错误或文件已损坏") from e


def manifest_requires_password(manifest):
    return bool(manifest.get("password_required", True))


def verify_parts(base_dir, manifest, q=None, progress_callback=None):
    parts = manifest.get("parts", [])
    total_bytes = sum(part["size"] for part in parts)
    processed_bytes = 0
    for part in parts:
        name = part["name"]
        path = base_dir / name
        if not path.exists():
            raise FileNotFoundError(f"缺少分片：{name}")
        if path.stat().st_size != part["size"]:
            raise ValueError(f"分片大小不一致：{name}")
        part_base = processed_bytes
        sha = sha256_file(
            path,
            progress_callback=lambda current, total, part_name=name, base=part_base: (
                progress_callback(
                    base + current,
                    total_bytes,
                    f"正在校验 {part_name}（{format_size(base + current)} / {format_size(total_bytes)}）",
                )
                if progress_callback is not None
                else emit_progress(
                    q,
                    "校验分片",
                    base + current,
                    total_bytes,
                    f"正在校验 {part_name}（{format_size(base + current)} / {format_size(total_bytes)}）",
                )
            ),
        )
        if sha.lower() != part["sha256"].lower():
            raise ValueError(f"分片校验失败：{name}")
        processed_bytes += part["size"]
        emit_log(q, f"校验通过：{name}")


def rebuild_encrypted(base_dir, manifest, out_path, q=None, progress_callback=None):
    parts = sorted(manifest.get("parts", []), key=lambda x: x["index"])
    total_bytes = sum(part["size"] for part in parts)
    processed_bytes = 0
    with open(out_path, "wb") as f_out:
        for part in parts:
            path = base_dir / part["name"]
            with open(path, "rb") as f_in:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    processed_bytes += len(chunk)
                    if progress_callback is not None:
                        progress_callback(
                            processed_bytes,
                            total_bytes,
                            f"{format_size(processed_bytes)} / {format_size(total_bytes)}",
                        )
                    else:
                        emit_progress(
                            q,
                            "合并分片",
                            processed_bytes,
                            total_bytes,
                            f"{format_size(processed_bytes)} / {format_size(total_bytes)}",
                        )
            emit_log(q, f"已合并：{part['name']}")


def worker(state, q):
    try:
        manifest_path = Path(state["manifest"])
        if not manifest_path.exists():
            raise FileNotFoundError("清单文件不存在")
        base_dir = manifest_path.parent

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        phases = [
            ("校验分片", 0.35),
            ("合并分片", 0.30),
            ("解密文件", 0.30),
            ("等待保存", 0.05),
        ]
        phase_offsets = {}
        current_offset = 0.0
        for phase_name, weight in phases:
            phase_offsets[phase_name] = (current_offset, weight)
            current_offset += weight

        emit_log(q, "开始校验分片")
        verify_total = sum(part["size"] for part in manifest.get("parts", []))
        verify_start, verify_span = phase_offsets["校验分片"]
        emit_progress(q, "校验分片", 0, verify_total, "正在检查所有分片", verify_start)
        verify_parts(
            base_dir,
            manifest,
            q=q,
            progress_callback=lambda current, total, detail: emit_progress(
                q,
                "校验分片",
                current,
                total,
                detail,
                overall_percent(current, total, verify_start, verify_span),
            ),
        )
        emit_progress(q, "校验分片", verify_total, verify_total, "分片校验完成", verify_start + verify_span)

        temp_dir = tempfile.mkdtemp()
        try:
            enc_path = Path(temp_dir) / "encrypted.dat"
            emit_log(q, "开始合并分片")
            merge_total = sum(part["size"] for part in manifest.get("parts", []))
            merge_start, merge_span = phase_offsets["合并分片"]
            emit_progress(q, "合并分片", 0, merge_total, "正在写入合并文件", merge_start)
            rebuild_encrypted(
                base_dir,
                manifest,
                enc_path,
                q=q,
                progress_callback=lambda current, total, detail: emit_progress(
                    q,
                    "合并分片",
                    current,
                    total,
                    detail,
                    overall_percent(current, total, merge_start, merge_span),
                ),
            )
            emit_progress(q, "合并分片", merge_total, merge_total, "分片合并完成", merge_start + merge_span)

            emit_log(q, "开始解密")
            zip_path = Path(temp_dir) / "output.zip"
            decrypt_total = enc_path.stat().st_size
            decrypt_start, decrypt_span = phase_offsets["解密文件"]
            emit_progress(q, "解密文件", 0, decrypt_total, "正在恢复原始内容", decrypt_start)
            decrypt_file(
                enc_path,
                zip_path,
                state["password"],
                q=q,
                progress_callback=lambda current, total: emit_progress(
                    q,
                    "解密文件",
                    current,
                    total,
                    f"{format_size(current)} / {format_size(total)}",
                    overall_percent(current, total, decrypt_start, decrypt_span),
                ),
            )
            wait_start, wait_span = phase_offsets["等待保存"]
            emit_progress(q, "等待保存", 1, 1, "请选择文件保存位置", wait_start + wait_span)

            q.put(("select_save", str(zip_path), manifest))
        finally:
            pass
    except Exception as e:
        q.put(("error", str(e)))


class App(tk.Tk, ProgressPanelMixin):
    def __init__(self):
        super().__init__()
        self.title(f"蓝奏云分片助手 v{get_app_version()} - 还原工具")
        self.geometry("680x500")
        self.resizable(False, False)

        self.manifest_path = tk.StringVar()
        self._init_progress_state("请选择清单后开始")
        self.queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self._build_ui()
        self._schedule_poll()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="清单文件：").grid(row=0, column=0, sticky="w")
        self.manifest_entry = ttk.Entry(frm, textvariable=self.manifest_path, width=50)
        self.manifest_entry.grid(row=0, column=1, sticky="w")
        self.manifest_button = ttk.Button(frm, text="选择", command=self.choose_manifest)
        self.manifest_button.grid(row=0, column=2, padx=5)

        self._build_progress_panel(frm, start_row=1, button_text="开始还原", button_command=self.start)
        self.inputs = [self.manifest_entry, self.manifest_button, self.start_button]

    def choose_manifest(self):
        path = filedialog.askopenfilename()
        if path:
            self.manifest_path.set(path)

    def start(self):
        if self.is_running:
            return
        manifest = self.manifest_path.get()
        if not manifest:
            auto = Path.cwd() / "manifest.txt"
            if auto.exists():
                manifest = str(auto)
                self.manifest_path.set(manifest)
            else:
                messagebox.showwarning("提示", "请先选择清单文件")
                return

        with open(manifest, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        password = self.ask_password(manifest_requires_password(manifest_data))
        if password is None:
            return

        self._reset_progress("正在初始化任务")
        self._set_running(True)
        state = {"manifest": manifest, "password": password}
        t = threading.Thread(target=worker, args=(state, self.queue), daemon=True)
        t.start()

    def ask_password(self, password_required: bool) -> Optional[str]:
        if not password_required:
            return ""

        dlg = tk.Toplevel(self)
        dlg.title("输入密码")
        dlg.geometry("300x140")
        dlg.resizable(False, False)

        pwd = tk.StringVar()
        ttk.Label(dlg, text="解密密码：").pack(pady=10)
        entry = ttk.Entry(dlg, textvariable=pwd, show="*")
        entry.pack()
        entry.focus()

        result: Optional[str] = None

        def on_ok():
            nonlocal result
            result = pwd.get()
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=on_ok).pack(pady=10)
        self.wait_window(dlg)
        return result

    def _schedule_poll(self) -> None:
        after_func = cast(Callable[..., object], self.after)
        after_func(200, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "progress":
                    self._handle_progress(item[1])
                elif item[0] == "error":
                    self._set_running(False)
                    messagebox.showerror("错误", item[1])
                elif item[0] == "select_save":
                    self._set_running(False)
                    self.on_select_save(item[1], item[2])
        except queue.Empty:
            pass
        self._schedule_poll()

    def on_select_save(self, temp_zip, manifest):
        temp_dir = Path(temp_zip).parent
        source_info = manifest.get("source", {})
        zip_used = bool(source_info.get("zip_used"))
        default_name = (
            source_info.get("zip_name")
            if zip_used
            else source_info.get("name") or "output.txt"
        )
        default_ext = ".zip" if zip_used else Path(default_name).suffix or ".txt"
        save_path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            initialfile=default_name,
        )
        if not save_path:
            messagebox.showwarning("提示", "已取消保存")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return

        self._mark_complete("还原完成", "文件已保存")
        shutil.move(temp_zip, save_path)
        self._append_log(f"已保存：{save_path}")

        if zip_used and messagebox.askyesno("提示", "是否自动解压？"):
            out_dir = filedialog.askdirectory()
            if out_dir:
                with zipfile.ZipFile(save_path, "r") as zf:
                    zf.extractall(out_dir)
                self._append_log(f"已解压到：{out_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
