import json
import os
import queue
import secrets
import shutil
import struct
import tempfile
import threading
import time
import zipfile
import hashlib
import sys
from typing import Any, Callable, cast
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2


ALLOWED_EXTS = [".txt"]
PART_SIZE_MB_DEFAULT = 49
CHUNK_SIZE = 4 * 1024 * 1024
MAGIC = b"LZYA1"
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
KDF_ITERATIONS = 200_000


def _log(q, msg):
    if q is not None:
        q.put(("log", msg))


def _pbkdf2_key(password, salt, iterations):
    return PBKDF2(password, salt, dkLen=32, count=iterations, hmac_hash_module=SHA256)


def encrypt_file(src_path, out_path, password, q=None):
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
            _log(q, f"加密中 {processed}/{total} 字节")

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


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def split_file(enc_path, out_dir, part_size_bytes, q=None):
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
            _log(q, f"分片中 {processed}/{total} 字节")

    return parts


def build_manifest(manifest_path, data):
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def copy_restore_exe(out_dir, q=None):
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).with_name("restore_gui.exe"))
    candidates.append(Path(__file__).with_name("restore_gui.exe"))
    candidates.append(Path.cwd() / "dist" / "restore_gui.exe")

    for cand in candidates:
        if cand.exists():
            shutil.copy2(cand, out_dir / "restore_gui.exe")
            _log(q, "已复制 restore_gui.exe")
            return True
    _log(q, "未找到 restore_gui.exe，已跳过复制")
    return False


def worker(state, q):
    try:
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

        try:
            if src.is_dir():
                _log(q, "检测到文件夹，开始打包 ZIP")
                temp_zip_path = Path(temp_dir) / f"{src.name}.zip"
                with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(src):
                        for name in files:
                            full = Path(root) / name
                            rel = full.relative_to(src)
                            zf.write(full, rel.as_posix())
                src_to_encrypt = temp_zip_path
                original_size = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
            else:
                src_to_encrypt = src

            _log(q, "开始加密")
            enc_path = Path(temp_dir) / "encrypted.dat"
            kdf_info = encrypt_file(src_to_encrypt, enc_path, password, q=q)

            _log(q, "开始分片")
            parts = split_file(enc_path, out_dir, part_size, q=q)

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
            _log(q, "清单已生成")
            copy_restore_exe(out_dir, q=q)
            _log(q, f"完成，输出目录：{out_dir}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        q.put(("done", "处理完成"))
    except Exception as e:
        q.put(("error", str(e)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("蓝奏云分片助手 - 分片工具")
        self.geometry("640x420")
        self.resizable(False, False)

        self.src_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self.password = tk.StringVar()
        self.password2 = tk.StringVar()
        self.part_size_mb = tk.StringVar(value=str(PART_SIZE_MB_DEFAULT))

        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._build_ui()
        self._schedule_poll()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="选择文件/文件夹：").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.src_path, width=50).grid(row=0, column=1, sticky="w")
        ttk.Button(frm, text="选择", command=self.choose_src).grid(row=0, column=2, padx=5)

        ttk.Label(frm, text="输出目录：").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.out_dir, width=50).grid(row=1, column=1, sticky="w")
        ttk.Button(frm, text="选择", command=self.choose_out).grid(row=1, column=2, padx=5)

        ttk.Label(frm, text="分片大小(MB)：").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.part_size_mb, width=10).grid(row=2, column=1, sticky="w")

        ttk.Label(frm, text="密码（可留空）：").grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.password, show="*", width=30).grid(row=3, column=1, sticky="w")

        ttk.Label(frm, text="确认密码：").grid(row=4, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.password2, show="*", width=30).grid(row=4, column=1, sticky="w")

        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="we", pady=10)

        ttk.Button(frm, text="开始处理", command=self.start).grid(row=6, column=0, columnspan=3, pady=5)

        self.log_text = tk.Text(frm, height=10, width=70)
        self.log_text.grid(row=7, column=0, columnspan=3, pady=5)
        self.log_text.configure(state="disabled")

    def choose_src(self):
        path = filedialog.askopenfilename()
        if not path:
            path = filedialog.askdirectory()
        if path:
            self.src_path.set(path)

    def choose_out(self):
        path = filedialog.askdirectory()
        if path:
            self.out_dir.set(path)

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start(self):
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

        self.progress.start(10)
        state = {
            "src": self.src_path.get(),
            "out_dir": self.out_dir.get(),
            "password": self.password.get(),
            "part_size": part_size,
        }
        t = threading.Thread(target=worker, args=(state, self.queue), daemon=True)
        t.start()

    def _schedule_poll(self) -> None:
        after_func = cast(Callable[..., object], self.after)
        after_func(200, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "error":
                    self.progress.stop()
                    messagebox.showerror("错误", item[1])
                elif item[0] == "done":
                    self.progress.stop()
                    messagebox.showinfo("完成", item[1])
        except queue.Empty:
            pass
        self._schedule_poll()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
