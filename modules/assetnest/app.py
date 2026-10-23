"""AssetNest 启动器：本地服务 + 独立应用窗口。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend import paths  # noqa: E402
from backend.api import Api  # noqa: E402
from backend.server import free_port, serve  # noqa: E402


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def ask_dir(out_file: str, title: str = "选择文件夹") -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        p = filedialog.askdirectory(title=title)
        root.destroy()
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(p or "")
    except Exception:
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass


def find_browser() -> str:
    cands = [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def open_window(url: str) -> subprocess.Popen | None:
    exe = find_browser()
    if exe:
        args = [
            exe, f"--app={url}", "--window-size=1500,940", "--window-position=90,50",
            f"--user-data-dir={os.path.join(paths.data_dir(), 'browser')}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-features=Translate,CalculateNativeWinOcclusion",
            "--hide-crash-restore-bubble", "--disable-session-crashed-bubble",
            "--disk-cache-size=268435456",
        ]
        try:
            return subprocess.Popen(args, close_fds=True)
        except Exception:
            pass
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    return None


def ping(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False


def instance_path() -> str:
    return os.path.join(paths.data_dir(), "instance.json")


def read_instance() -> dict:
    try:
        with open(instance_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_instance(port: int) -> None:
    try:
        with open(instance_path(), "w", encoding="utf-8") as f:
            json.dump({"port": port, "pid": os.getpid(), "ts": time.time()}, f)
    except Exception:
        pass


def clear_instance() -> None:
    try:
        os.remove(instance_path())
    except OSError:
        pass


def main(argv: list[str]) -> int:
    _utf8()
    if "--askdir" in argv:
        i = argv.index("--askdir")
        out = argv[i + 1] if i + 1 < len(argv) else ""
        title = argv[i + 2] if i + 2 < len(argv) else "选择文件夹"
        if out:
            ask_dir(out, title)
        return 0

    no_window = "--no-window" in argv
    port_arg = 0
    if "--port" in argv:
        try:
            port_arg = int(argv[argv.index("--port") + 1])
        except Exception:
            port_arg = 0

    if not no_window:
        inst = read_instance()
        if inst.get("port") and ping(int(inst["port"])):
            open_window(f"http://127.0.0.1:{inst['port']}/")
            return 0

    api = Api()
    port = port_arg or free_port()
    httpd = serve(api, port)
    url = f"http://127.0.0.1:{port}/"
    write_instance(port)
    print(f"[AssetNest] {url}")
    print(f"[AssetNest] 数据目录 {paths.data_dir()}")

    proc = None
    if not no_window:
        proc = open_window(url)

    started = time.time()
    try:
        while not api.quit_event.is_set():
            time.sleep(0.7)
            if proc is not None and proc.poll() is not None and time.time() - started > 3:
                time.sleep(1.5)
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        clear_instance()
        print("[AssetNest] 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
