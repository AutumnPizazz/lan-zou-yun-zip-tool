import json
import os
import queue
import secrets
import shutil
import struct
import tempfile
import time
import zipfile
import hashlib
import sys
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2

from lan_zou_yun.app_state import APP_EXE_NAME, get_runtime_base_dir
from lan_zou_yun.gui_common import (
    ProgressPanelMixin,
    emit_log,
    emit_progress,
    format_size,
    overall_percent,
)


ALLOWED_EXTS = [".txt"]
PART_SIZE_MB_DEFAULT = 49
CHUNK_SIZE = 4 * 1024 * 1024
MAGIC = b"LZYA1"
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
KDF_ITERATIONS = 200_000


def _pbkdf2_key(password, salt, iterations):
    return PBKDF2(password, salt, dkLen=32, count=iterations, hmac_hash_module=SHA256)


def encrypt_file(src_path, out_path, password, q=None, progress_callback=None):
    salt = secrets.token_bytes(SALT_LEN)
    nonce = secrets.token_bytes(NONCE_LEN)
    key = _pbkdf2_key(password, salt, KDF_ITERATIONS)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

    header = MAGIC + salt + nonce + struct.pack(">I", KDF_ITERATIONS)
    total = os.path.getsize(src_path)
    processed = 0

    with open(src_path, "rb") as f_in, open(out_path, "wb") as f_out:
        f_out.write(header)
        while True:
            chunk = f_in.read(CHUNK_SIZE)
            if not chunk:
                break
            enc = cipher.encrypt(chunk)
            f_out.write(enc)
            processed += len(chunk)
            emit_log(q, f"加密中 {processed}/{total} 字节")
            if progress_callback is not None:
                progress_callback(processed, total)

    tag = cipher.digest()
    with open(out_path, "ab") as f_out:
        f_out.write(tag)

    return {
        "magic": MAGIC.decode("ascii"),
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "iterations": KDF_ITERATIONS,
        "kdf": "PBKDF2-HMAC-SHA256",
        "cipher": "AES-256-GCM",
        "tag_len": TAG_LEN,
    }


def split_file(enc_path, out_dir, part_size_bytes, q=None, progress_callback=None):
    parts = []
    total = os.path.getsize(enc_path)
    processed = 0
    index = 0

    with open(enc_path, "rb") as f:
        while True:
            data = f.read(part_size_bytes)
            if not data:
                break
            ext = secrets.choice(ALLOWED_EXTS)
            name = f"{secrets.token_hex(3)}{ext}"
            part_path = out_dir / name
            with open(part_path, "wb") as p:
                p.write(data)
            sha = hashlib.sha256(data).hexdigest()
            size = len(data)
            parts.append(
                {
                    "index": index,
                    "name": name,
                    "size": size,
                    "sha256": sha,
                }
            )
            index += 1
            processed += size
            emit_log(q, f"分片中 {processed}/{total} 字节")
            if progress_callback is not None:
                progress_callback(processed, total)

    return parts


def build_manifest(manifest_path, data):
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def copy_app_exe(out_dir, q=None):
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable))
    candidates.append(Path(__file__).with_name(APP_EXE_NAME))
    candidates.append(get_runtime_base_dir() / "dist" / APP_EXE_NAME)

    for cand in candidates:
        if cand.exists():
            shutil.copy2(cand, out_dir / APP_EXE_NAME)
            emit_log(q, f"已复制 {APP_EXE_NAME}")
            return True
    emit_log(q, f"未找到 {APP_EXE_NAME}，已跳过复制")
    return False


def run_split(state, q):
    src = Path(state["src"])
    out_base = Path(state["out_dir"])
    password = state["password"]
    part_size = state["part_size"]

    if not src.exists():
        raise FileNotFoundError("源文件不存在")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = out_base / f"{src.stem}_lanzou_out_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = tempfile.mkdtemp()
    original_size = src.stat().st_size if src.is_file() else 0
    phases = [
        ("压缩文件夹", 0.25),
        ("加密文件", 0.40),
        ("生成分片", 0.30),
        ("收尾处理", 0.05),
    ]
    if not src.is_dir():
        phases = [
            ("加密文件", 0.60),
            ("生成分片", 0.35),
            ("收尾处理", 0.05),
        ]
    phase_offsets = {}
    current_offset = 0.0
    for phase_name, weight in phases:
        phase_offsets[phase_name] = (current_offset, weight)
        current_offset += weight

    try:
        if src.is_dir():
            original_size = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
            emit_log(q, "检测到文件夹，开始打包 ZIP")
            temp_zip_path = Path(temp_dir) / f"{src.name}.zip"
            compressed = 0
            compress_start, compress_span = phase_offsets["压缩文件夹"]
            emit_progress(q, "压缩文件夹", 0, original_size, "正在准备 ZIP", compress_start)
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(src):
                    for name in files:
                        full = Path(root) / name
                        rel = full.relative_to(src)
                        zf.write(full, rel.as_posix())
                        compressed += full.stat().st_size
                        emit_progress(
                            q,
                            "压缩文件夹",
                            compressed,
                            original_size,
                            f"{format_size(compressed)} / {format_size(original_size)}",
                            overall_percent(compressed, original_size, compress_start, compress_span),
                        )
            src_to_encrypt = temp_zip_path
        else:
            src_to_encrypt = src

        emit_log(q, "开始加密")
        enc_path = Path(temp_dir) / "encrypted.dat"
        encrypt_total = os.path.getsize(src_to_encrypt)
        encrypt_start, encrypt_span = phase_offsets["加密文件"]
        emit_progress(q, "加密文件", 0, encrypt_total, "正在写入加密数据", encrypt_start)
        kdf_info = encrypt_file(
            src_to_encrypt,
            enc_path,
            password,
            q=q,
            progress_callback=lambda current, total: emit_progress(
                q,
                "加密文件",
                current,
                total,
                f"{format_size(current)} / {format_size(total)}",
                overall_percent(current, total, encrypt_start, encrypt_span),
            ),
        )

        emit_log(q, "开始分片")
        split_total = enc_path.stat().st_size
        split_start, split_span = phase_offsets["生成分片"]
        emit_progress(q, "生成分片", 0, split_total, "正在写入分片文件", split_start)
        parts = split_file(
            enc_path,
            out_dir,
            part_size,
            q=q,
            progress_callback=lambda current, total: emit_progress(
                q,
                "生成分片",
                current,
                total,
                f"{format_size(current)} / {format_size(total)}",
                overall_percent(current, total, split_start, split_span),
            ),
        )

        manifest = {
            "version": "1.0",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": {
                "name": src.name,
                "is_dir": src.is_dir(),
                "original_size": original_size,
                "zip_used": bool(src.is_dir()),
                "zip_name": f"{src.name}.zip" if src.is_dir() else None,
            },
            "encryption": kdf_info,
            "password_required": bool(password),
            "encrypted_size": enc_path.stat().st_size,
            "part_size": part_size,
            "allowed_exts": ALLOWED_EXTS,
            "parts": parts,
        }

        build_manifest(out_dir / "manifest.txt", manifest)
        emit_log(q, "清单已生成")
        copy_app_exe(out_dir, q=q)
        finalize_start, finalize_span = phase_offsets["收尾处理"]
        emit_progress(q, "收尾处理", 1, 1, f"正在生成清单并复制 {APP_EXE_NAME}", finalize_start + finalize_span)
        emit_log(q, f"完成，输出目录：{out_dir}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class SplitPage(ttk.Frame, ProgressPanelMixin):
    def __init__(self, parent, controller, config):
        super().__init__(parent, padding=10)
        self.controller = controller
        self.config_store = config
        self.src_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self.password = tk.StringVar()
        self.password2 = tk.StringVar()
        self.part_size_mb = tk.StringVar(value=str(PART_SIZE_MB_DEFAULT))
        self._init_progress_state("请选择文件或文件夹后开始")
        self.queue: Any = None
        self._build_ui()
        self.load_config()
        self._schedule_poll()

    def _build_ui(self):
        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 10))
        header.columnconfigure(1, weight=1)
        self.back_button = ttk.Button(header, text="返回首页", command=self.on_back)
        self.back_button.grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="分片", font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=1)

        ttk.Label(self, text="选择文件/文件夹：").grid(row=1, column=0, sticky="w")
        self.src_entry = ttk.Entry(self, textvariable=self.src_path, width=50)
        self.src_entry.grid(row=1, column=1, sticky="w")
        self.src_button = ttk.Button(self, text="选择", command=self.choose_src)
        self.src_button.grid(row=1, column=2, padx=5)

        ttk.Label(self, text="输出目录：").grid(row=2, column=0, sticky="w")
        self.out_entry = ttk.Entry(self, textvariable=self.out_dir, width=50)
        self.out_entry.grid(row=2, column=1, sticky="w")
        self.out_button = ttk.Button(self, text="选择", command=self.choose_out)
        self.out_button.grid(row=2, column=2, padx=5)

        ttk.Label(self, text="分片大小(MB)：").grid(row=3, column=0, sticky="w")
        self.part_size_entry = ttk.Entry(self, textvariable=self.part_size_mb, width=10)
        self.part_size_entry.grid(row=3, column=1, sticky="w")

        ttk.Label(self, text="密码（可留空）：").grid(row=4, column=0, sticky="w")
        self.password_entry = ttk.Entry(self, textvariable=self.password, show="*", width=30)
        self.password_entry.grid(row=4, column=1, sticky="w")

        ttk.Label(self, text="确认密码：").grid(row=5, column=0, sticky="w")
        self.password2_entry = ttk.Entry(self, textvariable=self.password2, show="*", width=30)
        self.password2_entry.grid(row=5, column=1, sticky="w")

        self._build_progress_panel(self, start_row=6, button_text="开始处理", button_command=self.start)
        self.inputs = [
            self.src_entry,
            self.src_button,
            self.out_entry,
            self.out_button,
            self.part_size_entry,
            self.password_entry,
            self.password2_entry,
            self.start_button,
            self.back_button,
        ]

    def load_config(self):
        self.src_path.set(self.config_store.get("split", "last_source_path", default=""))
        self.out_dir.set(self.config_store.get("split", "last_output_dir", default=""))
        part_size_mb = self.config_store.get("split", "part_size_mb", default=PART_SIZE_MB_DEFAULT)
        self.part_size_mb.set(str(part_size_mb))

    def sync_config(self):
        self.config_store.set("split", "last_source_path", value=self.src_path.get())
        self.config_store.set("split", "last_output_dir", value=self.out_dir.get())
        try:
            self.config_store.set("split", "part_size_mb", value=int(self.part_size_mb.get()))
        except ValueError:
            self.config_store.set("split", "part_size_mb", value=PART_SIZE_MB_DEFAULT)

    def on_back(self):
        if self.is_running:
            return
        self.sync_config()
        self.controller.show_home()

    def choose_src(self):
        initial_dir = self.src_path.get()
        if initial_dir and Path(initial_dir).exists():
            initial_dir = str(Path(initial_dir).parent) if Path(initial_dir).is_file() else initial_dir
        path = filedialog.askopenfilename(initialdir=initial_dir or None)
        if not path:
            path = filedialog.askdirectory(initialdir=initial_dir or None)
        if path:
            self.src_path.set(path)

    def choose_out(self):
        initial_dir = self.out_dir.get()
        if not initial_dir and self.src_path.get():
            initial_dir = str(Path(self.src_path.get()).parent) if Path(self.src_path.get()).exists() else self.src_path.get()
        path = filedialog.askdirectory(initialdir=initial_dir or None)
        if path:
            self.out_dir.set(path)

    def start(self):
        if self.is_running:
            return
        if not self.src_path.get():
            messagebox.showwarning("提示", "请先选择文件或文件夹")
            return
        if not self.out_dir.get():
            messagebox.showwarning("提示", "请先选择输出目录")
            return
        if self.password.get() != self.password2.get():
            messagebox.showwarning("提示", "两次密码不一致")
            return
        try:
            part_size = int(self.part_size_mb.get()) * 1024 * 1024
            if part_size <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "分片大小格式不正确")
            return

        password = self.password.get()
        self.sync_config()
        self.password.set("")
        self.password2.set("")
        self._reset_progress("正在初始化任务")
        self._set_running(True)
        self.controller.refresh_navigation_state()
        state = {
            "src": self.src_path.get(),
            "out_dir": self.out_dir.get(),
            "password": password,
            "part_size": part_size,
        }
        self.queue = self.controller.start_background_task(run_split, state)

    def _schedule_poll(self):
        self.after(200, self._poll_queue)

    def _poll_queue(self):
        if self.queue is not None:
            try:
                while True:
                    item = self.queue.get_nowait()
                    if item[0] == "log":
                        self._append_log(item[1])
                    elif item[0] == "progress":
                        self._handle_progress(item[1])
                    elif item[0] == "error":
                        self._set_running(False)
                        self.controller.refresh_navigation_state()
                        messagebox.showerror("错误", item[1])
                    elif item[0] == "done":
                        self._mark_complete("处理完成", "任务已完成")
                        self._set_running(False)
                        self.controller.refresh_navigation_state()
                        self.sync_config()
                        messagebox.showinfo("完成", item[1])
            except queue.Empty:
                pass
        self._schedule_poll()
