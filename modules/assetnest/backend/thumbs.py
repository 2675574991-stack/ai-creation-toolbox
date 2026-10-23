"""缩略图与封面生成：图片缩略、视频首帧（ffmpeg）、音频波形。"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tempfile

from . import paths

THUMB_MAX = 720
AUDIO_W, AUDIO_H = 720, 420


def ensure_dirs(p: str) -> None:
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)


def make_image(path: str, key: str, size: int = THUMB_MAX, quality: int = 84) -> bool:
    out = paths.thumb_file(key)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return True
    ensure_dirs(out)
    tmp = out + f".{os.getpid()}.tmp"
    try:
        if _image_to(path, tmp, size, quality):
            os.replace(tmp, out)
            return True
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return False


def _image_to(src_path: str, out: str, size: int, quality: int) -> bool:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(src_path) as im:
        try:
            im.seek(0)
        except Exception:
            pass
        if (im.format or "").upper() in ("JPEG", "MPO"):
            try:
                im.draft("RGB", (size * 2, size * 2))
            except Exception:
                pass
        im = ImageOps.exif_transpose(im)
        has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in (im.info or {}))
        im = im.convert("RGBA" if has_alpha else "RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        im.save(out, "WEBP", quality=quality, method=5)
    return True


def make_video(path: str, key: str, ffmpeg: str = "", size: int = THUMB_MAX,
               quality: int = 84) -> bool:
    out = paths.thumb_file(key)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return True
    exe = ffmpeg or _find_ffmpeg()
    if not exe:
        return False
    ensure_dirs(out)
    frame = tempfile.mktemp(suffix=".png")
    try:
        for ts in ("1", "0"):
            cmd = [exe, "-y", "-loglevel", "error", "-ss", ts, "-i", path, "-frames:v", "1",
                   "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease", frame]
            subprocess.run(cmd, timeout=40, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           creationflags=0x08000000 if os.name == "nt" else 0)
            if os.path.isfile(frame) and os.path.getsize(frame) > 0:
                return _image_to(frame, out, size, quality)
        return False
    except Exception:
        return False
    finally:
        if os.path.isfile(frame):
            try:
                os.remove(frame)
            except OSError:
                pass


def _find_ffmpeg() -> str:
    exe = os.environ.get("ASSETNEST_FFMPEG") or ""
    if exe and os.path.isfile(exe):
        return exe
    for d in os.environ.get("PATH", "").split(os.pathsep):
        c = os.path.join(d, "ffmpeg.exe")
        if os.path.isfile(c):
            return c
    for base in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "bin")):
        c = os.path.join(base, "ffmpeg.exe")
        if os.path.isfile(c):
            return c
    return ""


def save_poster(key: str, data_url: str, quality: int = 86) -> bool:
    """接收前端 <video> 截取的首帧（dataURL），转存为 webp 封面。"""
    try:
        if "," in data_url and data_url.startswith("data:"):
            data_url = data_url.split(",", 1)[1]
        raw = base64.b64decode(data_url)
        if not raw:
            return False
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA") else "RGB")
            im.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
            out = paths.thumb_file(key)
            ensure_dirs(out)
            tmp = out + f".{os.getpid()}.tmp"
            im.save(tmp, "WEBP", quality=quality, method=5)
            os.replace(tmp, out)
        return True
    except Exception:
        return False


def save_peaks(key: str, peaks: list[float], duration: float = 0.0) -> bool:
    """保存波形峰值并渲染为封面图。"""
    try:
        peaks = [max(0.0, min(1.0, float(p))) for p in (peaks or [])][:600]
        if not peaks:
            return False
        out = paths.thumb_file(key)
        ensure_dirs(out)
        pj = paths.peaks_file(key)
        ensure_dirs(pj)
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"peaks": peaks, "duration": duration}, f)
        _render_wave(out, peaks, duration)
        return True
    except Exception:
        return False


def _render_wave(out: str, peaks: list[float], duration: float) -> None:
    from PIL import Image, ImageDraw, ImageFont

    W, H = AUDIO_W, AUDIO_H
    img = Image.new("RGB", (W, H), (23, 26, 33))
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(23 + 8 * k), int(26 + 10 * k), int(33 + 14 * k)))
    n = max(len(peaks), 2)
    pad = 56
    usable = W - pad * 2
    gap = max(1.0, usable / n * 0.35)
    bw = max(1.0, usable / n - gap)
    mid = H // 2 + 12
    amp = (H - 140) / 2
    for i, p in enumerate(peaks):
        x = pad + i * (usable / n)
        h = max(2.0, p * amp)
        color = (int(74 + 58 * p), int(206 + 30 * p), int(184 + 46 * p))
        d.rounded_rectangle([x, mid - h, x + bw, mid + h], radius=min(3, bw / 2), fill=color)
    d.line([(pad, mid), (W - pad, mid)], fill=(46, 54, 68), width=1)
    try:
        font = ImageFont.load_default(size=30)
        small = ImageFont.load_default(size=22)
    except Exception:
        font = small = None
    if duration:
        m, s = divmod(int(duration), 60)
        txt = f"{m}:{s:02d}" if m < 60 else f"{m // 60}:{m % 60:02d}:{s:02d}"
        d.text((pad, H - 62), txt, fill=(232, 234, 240), font=font)
    d.text((W - pad - 96, H - 58), "AUDIO", fill=(130, 140, 160), font=small)
    img.save(out, "WEBP", quality=86, method=5)


def drop(key: str) -> None:
    for p in (paths.thumb_file(key), paths.peaks_file(key)):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def peek_peaks(key: str) -> dict | None:
    p = paths.peaks_file(key)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def has_thumb(key: str) -> bool:
    p = paths.thumb_file(key)
    return os.path.isfile(p) and os.path.getsize(p) > 0


def drop_all_under(folder: str) -> None:
    """删除某个目录下所有文件的缩略图缓存（删除/移动目录时用）。"""
    base = paths.thumb_file("x")
    root = os.path.dirname(os.path.dirname(base))
    if not folder or not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(folder):
        for f in filenames:
            key = paths.file_key(os.path.join(dirpath, f))
            drop(key)
