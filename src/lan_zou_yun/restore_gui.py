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


CHUNK_SIZE = 4 * 1024 * 1024
MAGIC = b"LZYA1"
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16


def _log(q, msg):
    if q is not None:
        q.put(("log", msg))


def _pbkdf2_key(password, salt, iterations):
    return PBKDF2(password, salt, dkLen=32, count=iterations, hmac_hash_module=SHA256)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def decrypt_file(enc_path, out_path, password, q=None):
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
                _log(q, f"解密中 {processed}/{total} 字节")

            tag = f_in.read(TAG_LEN)
            try:
                cipher.verify(tag)
            except ValueError as e:
                raise ValueError("密码错误或文件已损坏") from e


def verify_parts(base_dir, manifest, q=None):
    parts = manifest.get("parts", [])
    for part in parts:
        name = part["name"]
        path = base_dir / name
        if not path.exists():
            raise FileNotFoundError(f"缺少分片：{name}")
        if path.stat().st_size != part["size"]:
            raise ValueError(f"分片大小不一致：{name}")
        sha = sha256_file(path)
        if sha.lower() != part["sha256"].lower():
            raise ValueError(f"分片校验失败：{name}")
        _log(q, f"校验通过：{name}")


def rebuild_encrypted(base_dir, manifest, out_path, q=None):
    parts = sorted(manifest.get("parts", []), key=lambda x: x["index"])
    with open(out_path, "wb") as f_out:
        for part in parts:
            path = base_dir / part["name"]
            with open(path, "rb") as f_in:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f_out.write(chunk)
            _log(q, f"已合并：{part['name']}")


def worker(state, q):
    try:
        manifest_path = Path(state["manifest"])
        if not manifest_path.exists():
            raise FileNotFoundError("清单文件不存在")
        base_dir = manifest_path.parent

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        _log(q, "开始校验分片")
        verify_parts(base_dir, manifest, q=q)

        temp_dir = tempfile.mkdtemp()
        try:
            enc_path = Path(temp_dir) / "encrypted.dat"
            _log(q, "开始合并分片")
            rebuild_encrypted(base_dir, manifest, enc_path, q=q)

            _log(q, "开始解密")
            zip_path = Path(temp_dir) / "output.zip"
            decrypt_file(enc_path, zip_path, state["password"], q=q)

            q.put(("select_save", str(zip_path), manifest))
        finally:
            pass
    except Exception as e:
        q.put(("error", str(e)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("蓝奏云分片助手 - 还原工具")
        self.geometry("640x420")
        self.resizable(False, False)

        self.manifest_path = tk.StringVar()
        self.queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self._build_ui()
        self._schedule_poll()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="清单文件：").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.manifest_path, width=50).grid(row=0, column=1, sticky="w")
        ttk.Button(frm, text="选择", command=self.choose_manifest).grid(row=0, column=2, padx=5)

        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=1, column=0, columnspan=3, sticky="we", pady=10)

        ttk.Button(frm, text="开始还原", command=self.start).grid(row=2, column=0, columnspan=3, pady=5)

        self.log_text = tk.Text(frm, height=12, width=70)
        self.log_text.grid(row=3, column=0, columnspan=3, pady=5)
        self.log_text.configure(state="disabled")

    def choose_manifest(self):
        path = filedialog.askopenfilename()
        if path:
            self.manifest_path.set(path)

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start(self):
        manifest = self.manifest_path.get()
        if not manifest:
            auto = Path.cwd() / "manifest.dat"
            if auto.exists():
                manifest = str(auto)
                self.manifest_path.set(manifest)
            else:
                messagebox.showwarning("提示", "请先选择清单文件")
                return

        password = self.ask_password()
        if password is None:
            return

        self.progress.start(10)
        state = {"manifest": manifest, "password": password}
        t = threading.Thread(target=worker, args=(state, self.queue), daemon=True)
        t.start()

    def ask_password(self) -> Optional[str]:
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
            if not pwd.get():
                messagebox.showwarning("提示", "密码不能为空")
                return
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
                elif item[0] == "error":
                    self.progress.stop()
                    messagebox.showerror("错误", item[1])
                elif item[0] == "select_save":
                    self.progress.stop()
                    self.on_select_save(item[1], item[2])
        except queue.Empty:
            pass
        self._schedule_poll()

    def on_select_save(self, temp_zip, manifest):
        temp_dir = Path(temp_zip).parent
        default_name = manifest.get("source", {}).get("zip_name") or "output.zip"
        save_path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            initialfile=default_name,
        )
        if not save_path:
            messagebox.showwarning("提示", "已取消保存")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return

        shutil.move(temp_zip, save_path)
        self._append_log(f"已保存：{save_path}")

        if messagebox.askyesno("提示", "是否自动解压？"):
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
