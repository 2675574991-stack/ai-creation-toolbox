"""路径、常量与系统小工具。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

APP_ID = "AssetNest"
APP_NAME = "AssetNest"
APP_CN = "素材巢"
APP_SLOGAN = "AICG 项目资产库"
VERSION = "1.0.0"

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".ico"}
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff"}
MODEL_EXT = {".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".onnx", ".bin", ".sft"}
TEXT_EXT = {".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".srt", ".ass", ".docx", ".pdf", ".doc"}

# 项目固定分类（名称, key, 图标, 主题色）
CATEGORIES = [
    {"name": "剧本", "key": "script", "icon": "text", "color": "#f2b544",
     "desc": "分镜脚本、提示词、文案"},
    {"name": "人物", "key": "character", "icon": "character", "color": "#9b8cff",
     "desc": "角色设定图、三视图、立绘"},
    {"name": "场景", "key": "scene", "icon": "scene", "color": "#4cc9f0",
     "desc": "场景概念图、环境氛围"},
    {"name": "道具", "key": "prop", "icon": "prop", "color": "#ff8fab",
     "desc": "道具、物件、特写素材"},
    {"name": "音频", "key": "audio", "icon": "audio", "color": "#38d39f",
     "desc": "配音、BGM、音效"},
    {"name": "视频", "key": "video", "icon": "video", "color": "#ff9f43",
     "desc": "生成视频、运镜片段"},
    {"name": "成片", "key": "final", "icon": "film", "color": "#e8eaf0",
     "desc": "剪辑成片、交付版本"},
]
CATEGORY_NAMES = [c["name"] for c in CATEGORIES]
CATEGORY_MAP = {c["name"]: c for c in CATEGORIES}

IGNORE_DIRS = {".git", ".svn", "__pycache__", "node_modules", "$RECYCLE.BIN",
               "System Volume Information", ".thumbnails", ".assetnest"}
SIDECAR_EXT = {".civitai.info"}


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in MODEL_EXT:
        return "model"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def data_dir() -> str:
    if os.environ.get("ASSETNEST_HOME"):
        d = os.environ["ASSETNEST_HOME"]
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, APP_ID)
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir() -> str:
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    return os.path.join(data_dir(), "assetnest.db")


def web_dir() -> str:
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, "web")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def file_key(path: str) -> str:
    return hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8", "ignore")).hexdigest()


def thumb_file(key: str) -> str:
    return os.path.join(cache_dir(), "thumbs", key[:2], key + ".webp")


def peaks_file(key: str) -> str:
    return os.path.join(cache_dir(), "peaks", key[:2], key + ".json")


def now_ts() -> int:
    return int(time.time())


def fmt_time(ts) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def human_size(n) -> str:
    n = float(n or 0)
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def jload(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def reveal_in_explorer(path: str) -> None:
    try:
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif os.path.isdir(path):
            subprocess.Popen(["explorer", os.path.normpath(path)])
    except Exception:
        pass


def open_with_default(path: str) -> None:
    try:
        os.startfile(path)  # noqa: S606
    except Exception:
        pass


def delete_to_recycle_bin(paths_list: list[str]) -> tuple[int, str]:
    if not paths_list or os.name != "nt":
        return 0, "仅支持 Windows"
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    src = "\0".join(os.path.normpath(p) for p in paths_list) + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = 3  # FO_DELETE
    op.pFrom = src
    op.pTo = None
    op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400 | 0x0200  # UNDO|NOCONFIRM|SILENT|NOERRORUI
    try:
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as e:  # pragma: no cover
        return 0, str(e)
    if res != 0:
        return 0, f"shell-error-{res}"
    return len(paths_list), ""


def safe_name(name: str) -> str:
    import re
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "").strip(" .")
    return name[:180] or "未命名"
