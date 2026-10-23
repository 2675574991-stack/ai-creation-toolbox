"""业务 API：项目、文件树、预览、元数据、导入与文件操作。"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

from . import meta as metamod
from . import paths, thumbs
from .project import Project, ProjectError
from .store import Store


class ApiError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _default_ar(kind: str, ext: str) -> float:
    if kind == "video":
        return 16 / 9
    if kind == "audio":
        return 720 / 420
    if kind == "text":
        return 0.78
    if kind == "model":
        return 1.0
    return 1.0


class Api:
    def __init__(self):
        self.store = Store()
        self.quit_event = threading.Event()
        s = self.store.settings()
        root = s.get("project") or ""
        self.project = Project(root) if root and os.path.isdir(root) else None
        self._dims_budget = 600
        # 外部改动检测：rev 变化即代表磁盘上有增删改
        self.rev = 1
        self._sig = None
        self._watch_stop = threading.Event()
        threading.Thread(target=self._watch_loop, daemon=True, name="assetnest-watch").start()

    def _watch_loop(self) -> None:
        while not self._watch_stop.is_set():
            time.sleep(1.5)
            p = self.project
            if not p or not p.exists():
                continue
            t0 = time.time()
            try:
                sig = p.signature()
            except Exception:
                continue
            if self._sig is None:
                self._sig = sig
            elif sig != self._sig:
                self._sig = sig
                self.rev += 1
            # 素材很多时自动降频，避免频繁扫盘
            cost = time.time() - t0
            if cost > 0.15:
                time.sleep(min(8.0, cost * 8))

    def bump(self) -> None:
        """本服务自己改动了磁盘内容时调用，立即通知前端。"""
        self.rev += 1
        self._sig = None

    # ---------------- 项目 ----------------
    def project_payload(self) -> dict | None:
        if not self.project:
            return None
        try:
            st = self.project.stats()
        except Exception:
            st = {"files": 0, "size": 0, "categories": []}
        return {"root": self.project.root, "name": self.project.name(),
                "files": st["files"], "size": st["size"],
                "size_text": paths.human_size(st["size"])}

    def bootstrap(self) -> dict:
        settings = self.store.settings()
        tree = None
        if self.project and self.project.exists():
            try:
                tree = self.project.tree()
            except Exception:
                tree = None
        return {
            "app": {"name": paths.APP_NAME, "cn": paths.APP_CN, "slogan": paths.APP_SLOGAN,
                    "version": paths.VERSION, "data_dir": paths.data_dir()},
            "project": self.project_payload(),
            "tree": tree,
            "settings": settings,
            "recent": self.store.recent_projects(),
            "tags": self.store.all_tags(),
            "categories": paths.CATEGORIES,
            "ffmpeg": bool(thumbs._find_ffmpeg()),
            "rev": self.rev,
            "scan": None,
        }

    def open_project(self, path: str) -> dict:
        path = (path or "").strip().strip('"')
        if not path:
            raise ApiError("请选择项目文件夹")
        if not os.path.isdir(path):
            raise ApiError("文件夹不存在：" + path)
        p = Project(path)
        created = p.ensure_structure()
        self.project = p
        self._sig = None
        self.rev += 1
        self.store.save_settings({"project": p.root})
        self.store.touch_project(p.root, p.name())
        return {"project": self.project_payload(), "tree": p.tree(), "created": created,
                "settings": self.store.settings(), "rev": self.rev}

    def pick_folder(self, title: str = "选择项目文件夹") -> dict:
        tmp = tempfile.mktemp(suffix=".txt", prefix="assetnest_dir_")
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--askdir", tmp, title]
            else:
                cmd = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), "app.py"), "--askdir", tmp, title]
            subprocess.run(cmd, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.path.isfile(tmp):
                with open(tmp, "r", encoding="utf-8") as f:
                    return {"path": f.read().strip()}
        except Exception as e:
            return {"path": "", "error": str(e)}
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        return {"path": ""}

    def tree(self) -> dict:
        if not self.project:
            raise ApiError("尚未打开项目", 404)
        return {"tree": self.project.tree(), "project": self.project_payload()}

    # ---------------- 文件列表 ----------------
    def files(self, q: dict) -> dict:
        p = self._require_project()
        folder = q.get("folder") or p.root
        recursive = str(q.get("recursive", "0")) in ("1", "true")
        sort = q.get("sort") or self.store.settings().get("sort") or "name_asc"
        kinds = [k for k in (q.get("kinds") or "").split(",") if k]
        fav = str(q.get("favorite", "")) in ("1", "true")
        rating_min = int(q.get("rating_min") or 0)
        items = p.list_files(folder, recursive, sort, q.get("q", ""), kinds, fav, rating_min)
        self._attach_meta(items)
        return {"items": items, "total": len(items), "folder": os.path.normpath(folder),
                "recursive": recursive, "sort": sort}

    def _attach_meta(self, items: list[dict]) -> None:
        paths_ = [i["path"] for i in items]
        known = self.store.get_items(paths_)
        budget = self._dims_budget
        updates = []
        for it in items:
            key = paths.file_key(it["path"])
            it["key"] = key
            it["thumb"] = thumbs.has_thumb(key)
            it["favorite"] = 0
            it["rating"] = 0
            it["tags"] = []
            it["note"] = ""
            md = known.get(it["path"])
            w = h = 0
            if md:
                it["favorite"] = md.get("favorite") or 0
                it["rating"] = md.get("rating") or 0
                it["tags"] = md.get("tags") or []
                it["note"] = md.get("note") or ""
                w, h = md.get("width") or 0, md.get("height") or 0
            if it["kind"] == "image" and (not w or not h) and budget > 0:
                budget -= 1
                w, h = self._image_dims(it["path"])
                if w and h:
                    updates.append({"path": it["path"], "width": w, "height": h})
            it["w"], it["h"] = w, h
            it["ar"] = round(w / h, 4) if w and h else _default_ar(it["kind"], it["ext"])
            it["thumb_v"] = int(it["mtime"])
            it["size_text"] = paths.human_size(it["size"])
            it["mtime_text"] = paths.fmt_time(it["mtime"])
        for u in updates:
            try:
                self.store.update_item(u["path"], {"width": u["width"], "height": u["height"]})
            except Exception:
                pass

    def _image_dims(self, path: str) -> tuple[int, int]:
        try:
            from PIL import Image
            with Image.open(path) as im:
                return im.size
        except Exception:
            return 0, 0

    # ---------------- 元数据 ----------------
    def item_meta(self, q: dict) -> dict:
        p = self._require_project()
        path = p.safe(q.get("p") or "")
        if not os.path.exists(path):
            raise ApiError("文件不存在", 404)
        st = os.stat(path)
        kind = paths.kind_of(path) if os.path.isfile(path) else "folder"
        md = self.store.get_item(path)
        info = {
            "path": path, "name": os.path.basename(path), "rel": p.rel(path),
            "kind": kind, "ext": os.path.splitext(path)[1].lower().lstrip("."),
            "size": st.st_size if os.path.isfile(path) else 0,
            "size_text": paths.human_size(st.st_size if os.path.isfile(path) else 0),
            "mtime": st.st_mtime, "mtime_text": paths.fmt_time(st.st_mtime),
            "favorite": md.get("favorite", 0), "rating": md.get("rating", 0),
            "tags": md.get("tags", []), "note": md.get("note", ""),
            "is_dir": os.path.isdir(path), "key": paths.file_key(path),
        }
        if kind == "image" and not info.get("width"):
            w, h = self._image_dims(path)
            info["width"], info["height"] = w, h
        extra = {}
        if kind in ("image", "model"):
            try:
                extra = metamod.extract(path, kind)
            except Exception:
                extra = {}
            info["width"] = info.get("width") or extra.get("width") or 0
            info["height"] = info.get("height") or extra.get("height") or 0
            for k in ("positive", "negative", "model", "seed", "sampler", "steps", "cfg", "loras"):
                if extra.get(k):
                    info[k] = extra[k]
            info["meta"] = extra.get("meta") or {}
        if kind in ("image", "video", "audio"):
            thumb = paths.thumb_file(info["key"])
            info["thumb_url"] = f"/api/thumb?p={urllib.parse.quote(path)}&v={int(st.st_mtime)}" \
                if os.path.isfile(thumb) else ""
            info["file_url"] = f"/api/file?p={urllib.parse.quote(path)}&v={int(st.st_mtime)}"
        if kind == "text":
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    info["text"] = f.read(6000)
            except Exception:
                info["text"] = ""
        if kind == "audio":
            pk = thumbs.peek_peaks(info["key"])
            if pk:
                info["duration"] = pk.get("duration") or 0
        return info

    def save_meta(self, body: dict) -> dict:
        p = self._require_project()
        path = p.safe(body.get("path") or "")
        if not os.path.exists(path):
            raise ApiError("文件不存在", 404)
        patch = {}
        for k in ("rating", "favorite", "note", "tags", "duration"):
            if k in body:
                patch[k] = body[k]
        if patch:
            self.store.update_item(path, patch)
        md = self.store.get_item(path)
        return {"path": path, "favorite": md.get("favorite", 0), "rating": md.get("rating", 0),
                "tags": md.get("tags", []), "note": md.get("note", "")}

    def tags(self) -> dict:
        return {"tags": self.store.all_tags()}

    # ---------------- 缩略图 ----------------
    def thumb_path(self, q: dict) -> str:
        p = self._require_project()
        path = p.safe(q.get("p") or "")
        if not os.path.isfile(path):
            raise ApiError("文件不存在", 404)
        key = paths.file_key(path)
        if thumbs.has_thumb(key):
            return paths.thumb_file(key)
        kind = paths.kind_of(path)
        settings = self.store.settings()
        if kind == "image":
            thumbs.make_image(path, key, quality=84)
        elif kind == "video":
            thumbs.make_video(path, key, settings.get("ffmpeg", ""))
        if thumbs.has_thumb(key):
            if kind == "image":
                w, h = self._image_dims(path)
                if w and h:
                    self.store.update_item(path, {"width": w, "height": h})
            return paths.thumb_file(key)
        raise ApiError("尚未生成封面", 404)

    def poster(self, body: dict) -> dict:
        p = self._require_project()
        path = p.safe(body.get("path") or "")
        if not os.path.isfile(path):
            raise ApiError("文件不存在", 404)
        key = paths.file_key(path)
        ok = thumbs.save_poster(key, body.get("data") or "")
        duration = float(body.get("duration") or 0)
        if ok and duration:
            self.store.update_item(path, {"duration": duration})
        return {"ok": ok, "duration": duration,
                "thumb_url": f"/api/thumb?p={urllib.parse.quote(path)}&v={int(time.time())}"}

    def peaks(self, body: dict, q: dict) -> dict:
        p = self._require_project()
        path = p.safe(body.get("path") or q.get("p") or "")
        key = paths.file_key(path)
        if q:
            data = thumbs.peek_peaks(key)
            return {"peaks": (data or {}).get("peaks") or [], "duration": (data or {}).get("duration") or 0}
        if not os.path.isfile(path):
            raise ApiError("文件不存在", 404)
        ok = thumbs.save_peaks(key, body.get("peaks") or [], float(body.get("duration") or 0))
        if ok:
            self.store.update_item(path, {"duration": float(body.get("duration") or 0)})
        return {"ok": ok, "thumb_url": f"/api/thumb?p={urllib.parse.quote(path)}&v={int(time.time())}"}

    # ---------------- 导入 ----------------
    def import_stream(self, rfile, length: int, folder: str, rel_name: str) -> dict:
        p = self._require_project()
        rel_name = urllib.parse.unquote(rel_name or "")
        kind = paths.kind_of(rel_name)
        target = folder or ""
        if not target:
            target = os.path.join(p.root, p.guess_category(kind, os.path.splitext(rel_name)[1]))
        else:
            target = p.safe(target)
            if not os.path.isdir(target):
                os.makedirs(target, exist_ok=True)
        if length <= 0:
            raise ApiError("空文件")
        item = p.import_file(target, rel_name, _BoundedReader(rfile, length), length)
        key = paths.file_key(item["path"])
        if item["kind"] == "image":
            thumbs.make_image(item["path"], key, quality=84)
            w, h = self._image_dims(item["path"])
            if w and h:
                self.store.update_item(item["path"], {"width": w, "height": h})
        if item["kind"] == "video":
            thumbs.make_video(item["path"], key, self.store.settings().get("ffmpeg", ""))
        item["thumb"] = thumbs.has_thumb(key)
        item["thumb_v"] = int(item["mtime"])
        item["size_text"] = paths.human_size(item["size"])
        self.bump()
        return item

    # ---------------- 文件操作 ----------------
    def fs_list(self, q: dict) -> dict:
        """目录浏览：path 为空表示「此电脑」，返回盘符列表。"""
        raw = (q.get("path") or "").strip()
        if not raw:
            dirs = []
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                root = f"{letter}:\\"
                if os.path.exists(root):
                    dirs.append({"name": f"{letter}:", "path": root})
            return {"path": "", "parent": "", "dirs": dirs, "root": True}
        p = os.path.normpath(os.path.abspath(raw))
        if not os.path.isdir(p):
            raise ApiError("文件夹不存在：" + p)
        dirs = []
        try:
            with os.scandir(p) as sc:
                for e in sc:
                    try:
                        if not e.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    if e.name.startswith(".") or e.name in paths.IGNORE_DIRS:
                        continue
                    dirs.append({"name": e.name, "path": e.path})
        except PermissionError:
            raise ApiError("没有权限读取该文件夹")
        except OSError as e:
            raise ApiError(str(e))
        dirs.sort(key=lambda d: d["name"].lower())
        parent = os.path.dirname(p)
        if parent == p or p.endswith(":\\"):
            parent = ""
        return {"path": p, "parent": parent, "dirs": dirs[:800],
                "truncated": len(dirs) > 800, "root": False}

    def mkdir(self, body: dict) -> dict:
        p = self._require_project()
        parent = os.path.abspath((body.get("parent") or p.root).strip().strip('"'))
        name = body.get("name") or "新建文件夹"
        root_n = os.path.normcase(p.root)
        par_n = os.path.normcase(parent)
        inside = par_n == root_n or par_n.startswith(root_n + os.sep)
        if inside:
            target = p.mkdir(parent, name)
            self.bump()
            return {"path": target, "rel": p.rel(target), "outside": False,
                    "tree": p.tree(), "rev": self.rev}
        # 项目之外的任意磁盘位置
        if not os.path.isdir(parent):
            raise ApiError("位置不存在：" + parent)
        target = os.path.join(parent, paths.safe_name(name))
        base, i = target, 1
        while os.path.exists(target):
            target = f"{base} ({i})"
            i += 1
        try:
            os.makedirs(target)
        except Exception as e:
            raise ApiError("创建失败：" + str(e))
        return {"path": target, "rel": "", "outside": True, "tree": None, "rev": self.rev}

    def rename(self, body: dict) -> dict:
        p = self._require_project()
        old = p.safe(body.get("path") or "")
        new = p.rename(old, body.get("name") or "")
        if os.path.isfile(new):
            thumbs.drop(paths.file_key(old))
        self.bump()
        return {"path": new, "name": os.path.basename(new), "tree": p.tree(), "rev": self.rev}

    def delete(self, body: dict) -> dict:
        p = self._require_project()
        list_ = body.get("paths") or ([body["path"]] if body.get("path") else [])
        hard = bool(body.get("hard"))
        done, errors = [], []
        for raw in list_:
            try:
                target = p.safe(raw)
                ok, err = p.delete(target, hard)
                if ok:
                    done.append(target)
                    if os.path.isfile(target):
                        thumbs.drop(paths.file_key(target))
                    else:
                        thumbs.drop_all_under(target)
                else:
                    errors.append(f"{os.path.basename(target)}: {err}")
            except ProjectError as e:
                errors.append(str(e))
        if done:
            self.bump()
        return {"deleted": len(done), "errors": errors, "tree": p.tree(), "rev": self.rev}

    # ---------------- 移动 / 撤销 ----------------
    def move(self, body: dict) -> dict:
        p = self._require_project()
        target = p.safe(body.get("target") or "")
        if not os.path.isdir(target):
            raise ApiError("目标文件夹不存在")
        raw_paths = body.get("paths") or []
        if not raw_paths:
            raise ApiError("没有要移动的文件")
        moved, skipped, errors, ops = 0, 0, [], []
        for raw in raw_paths:
            try:
                src = p.safe(raw)
            except ProjectError as e:
                errors.append(str(e))
                continue
            if not os.path.exists(src):
                errors.append(f"{os.path.basename(src)}: 文件不存在")
                continue
            if os.path.normcase(os.path.dirname(src)) == os.path.normcase(target):
                skipped += 1
                continue
            if os.path.isdir(src) and (
                    os.path.normcase(target) == os.path.normcase(src)
                    or os.path.normcase(target).startswith(os.path.normcase(src) + os.sep)):
                errors.append(f"{os.path.basename(src)}: 不能移动到自身内部")
                continue
            dst = p.unique_path(os.path.join(target, os.path.basename(src)))
            try:
                shutil.move(src, dst)
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")
                continue
            moved += 1
            ops.append([src, dst])
            self.store.move_item(src, dst)
            if os.path.isfile(dst):
                thumbs.drop(paths.file_key(src))
            else:
                for dirpath, _dirs, files in os.walk(dst):
                    for f in files:
                        old_p = src + os.path.join(dirpath, f)[len(dst):]
                        thumbs.drop(paths.file_key(old_p))
        if moved:
            self.bump()
        return {"moved": moved, "skipped": skipped, "errors": errors, "ops": ops,
                "tree": p.tree(), "rev": self.rev}

    def move_undo(self, body: dict) -> dict:
        p = self._require_project()
        pairs = body.get("pairs") or []
        restored, errors = 0, []
        for pair in pairs:
            try:
                original, current = p.safe(pair[0]), p.safe(pair[1])
            except Exception as e:
                errors.append(str(e))
                continue
            if not os.path.exists(current):
                errors.append("文件已不在原位置")
                continue
            parent = os.path.dirname(original)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            back = p.unique_path(original)
            try:
                shutil.move(current, back)
            except Exception as e:
                errors.append(str(e))
                continue
            restored += 1
            self.store.move_item(current, back)
            thumbs.drop(paths.file_key(current))
        if restored:
            self.bump()
        return {"restored": restored, "errors": errors, "tree": p.tree(), "rev": self.rev}

    def reveal(self, body: dict) -> dict:
        p = self._require_project()
        path = p.safe(body.get("path") or "")
        if not os.path.exists(path):
            raise ApiError("路径不存在", 404)
        if body.get("open"):
            paths.open_with_default(path)
        else:
            paths.reveal_in_explorer(path)
        return {"ok": True}

    def copy_text(self, body: dict) -> dict:
        """把文本写入 Windows 剪贴板（前端 navigator.clipboard 失败时的兜底）。"""
        text = body.get("text") or ""
        if os.name != "nt":
            return {"ok": False, "error": "仅支持 Windows"}
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.CloseClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.SetClipboardData.restype = wintypes.HANDLE
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

            GMEM_MOVEABLE, CF_UNICODETEXT = 0x0002, 13
            data = (text + "\x00").encode("utf-16-le")

            opened = False
            for _ in range(8):
                if user32.OpenClipboard(None):
                    opened = True
                    break
                time.sleep(0.06)
            if not opened:
                return {"ok": False, "error": "剪贴板被其他程序占用"}
            try:
                user32.EmptyClipboard()
                h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not h:
                    return {"ok": False, "error": "GlobalAlloc 失败"}
                p = kernel32.GlobalLock(h)
                if not p:
                    kernel32.GlobalFree(h)
                    return {"ok": False, "error": "GlobalLock 失败"}
                ctypes.memmove(p, data, len(data))
                kernel32.GlobalUnlock(h)
                if not user32.SetClipboardData(CF_UNICODETEXT, h):
                    kernel32.GlobalFree(h)
                    return {"ok": False, "error": "SetClipboardData 失败"}
                return {"ok": True}
            finally:
                user32.CloseClipboard()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 导出 ----------------
    def export(self, q: dict, kind: str) -> tuple[bytes, str, str]:
        p = self._require_project()
        folder = q.get("folder") or p.root
        recursive = str(q.get("recursive", "1")) in ("1", "true")
        items = p.list_files(folder, recursive, q.get("sort") or "name_asc", q.get("q", ""), None)
        self._attach_meta(items)
        stamp = time.strftime("%Y%m%d_%H%M")
        if kind == "json":
            out = []
            for it in items:
                out.append({k: it.get(k) for k in ("name", "path", "rel", "kind", "size", "w", "h",
                                                   "mtime_text", "rating", "favorite", "tags", "note")})
            return (json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"),
                    "application/json; charset=utf-8", f"资产清单_{stamp}.json")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["名称", "相对路径", "类型", "大小(字节)", "宽", "高", "修改时间", "评分", "收藏", "标签", "备注"])
        for it in items:
            w.writerow([it["name"], it["rel"], it["kind"], it["size"], it.get("w", ""), it.get("h", ""),
                        it["mtime_text"], it.get("rating", 0), "是" if it.get("favorite") else "",
                        " ".join(it.get("tags") or []), it.get("note", "")])
        return (buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"资产清单_{stamp}.csv")

    # ---------------- 演示项目 ----------------
    def demo(self) -> dict:
        base = os.path.join(os.path.expanduser("~"), "Documents", "AssetNest 示例项目")
        p = Project(base)
        if not os.path.isdir(base) or not os.listdir(base):
            p.ensure_structure()
            _make_demo_assets(base)
        return self.open_project(base)

    # ---------------- 其它 ----------------
    def settings(self, body: dict) -> dict:
        return self.store.save_settings(body or {})

    def _require_project(self) -> Project:
        if not self.project or not self.project.exists():
            raise ApiError("尚未打开项目", 409)
        return self.project


class _BoundedReader:
    """把请求体包装成最多读取 length 字节的流。"""

    def __init__(self, rfile, length: int):
        self.rfile = rfile
        self.left = length

    def read(self, n: int = -1) -> bytes:
        if self.left <= 0:
            return b""
        want = self.left if n is None or n < 0 else min(n, self.left)
        data = self.rfile.read(want)
        self.left -= len(data)
        return data


# ---------------- 演示素材生成 ----------------
def _demo_font(size: int):
    from PIL import ImageFont
    for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.isfile(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return None


def _make_demo_assets(base: str) -> None:
    import math
    import struct
    import wave
    from PIL import Image, ImageDraw, ImageFilter

    def art(path: str, w: int, h: int, c1, c2, c3, title: str, sub: str, params: dict | None = None):
        img = Image.new("RGB", (w, h), c1)
        d = ImageDraw.Draw(img)
        for y in range(h):
            k = y / h
            d.line([(0, y), (w, y)], fill=(int(c1[0] + (c2[0] - c1[0]) * k),
                                          int(c1[1] + (c2[1] - c1[1]) * k),
                                          int(c1[2] + (c2[2] - c1[2]) * k)))
        for i in range(6):
            r = int(min(w, h) * (0.12 + i * 0.07))
            cx = int(w * (0.3 + 0.09 * math.sin(i * 1.7)))
            cy = int(h * (0.45 + 0.12 * math.cos(i * 1.3)))
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            dl = ImageDraw.Draw(layer)
            col = c3 if i % 2 == 0 else (255, 255, 255)
            dl.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*col, 42))
            layer = layer.filter(ImageFilter.GaussianBlur(r * 0.35))
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        d = ImageDraw.Draw(img)
        f1, f2 = _demo_font(max(28, w // 18)), _demo_font(max(16, w // 46))
        d.text((int(w * 0.06), int(h * 0.80)), title, fill=(255, 255, 255), font=f1)
        d.text((int(w * 0.06), int(h * 0.80) + max(40, w // 16)), sub, fill=(215, 220, 235), font=f2)
        if params:
            img.save(path, "PNG", pnginfo=_png_text(params))
        else:
            img.save(path, "PNG")

    def _png_text(kv: dict):
        from PIL import PngImagePlugin
        info = PngImagePlugin.PngInfo()
        for k, v in kv.items():
            info.add_text(k, v)
        return info

    def a1111(main: str, neg: str, model: str, seed: int, w: int, h: int, sampler="DPM++ 2M Karras"):
        return (f"{main}\nNegative prompt: {neg}\nSteps: 28, Sampler: {sampler}, CFG scale: 7, "
                f"Seed: {seed}, Size: {w}x{h}, Model hash: 879db523c3, Model: {model}, "
                f"Clip skip: 2, Version: v1.9.4")

    p = Project(base)
    os.makedirs(os.path.join(base, "人物"), exist_ok=True)

    script = """# 第 01 集 · 分镜脚本（示例）

场景 1 · 雨夜街道 · 外景
    雨丝斜落，霓虹在积水里碎成一片光斑。
    林小满撑伞走过，停在一盏坏掉的路灯下。

场景 2 · 旧公寓楼道 · 内景
    声控灯闪烁三次。她把怀表贴在耳边，听见齿轮倒转的声音。

场景 3 · 天台 · 黄昏
    风很大。远处的城市像一张正在加载的图。

提示词备注：
    人物：lin xiaoman, 24yo, short black hair, trench coat, cinematic lighting
    风格：anamorphic, film grain, teal and orange
"""
    with open(os.path.join(base, "剧本", "第01集_分镜脚本.txt"), "w", encoding="utf-8") as f:
        f.write(script)
    with open(os.path.join(base, "剧本", "人物设定_林小满.txt"), "w", encoding="utf-8") as f:
        f.write("林小满 / 24 岁 / 修复师\n关键词：短发、旧风衣、随身怀表、克制\n"
                "参考：lin xiaoman, short black hair, trench coat, holding pocket watch\n")

    a = os.path.join(base, "人物")
    art(os.path.join(a, "林小满_正面设定.png"), 832, 1216, (28, 34, 58), (86, 60, 120),
        (120, 200, 255), "林小满 · 正面", "人物设定 / 三视图 A",
        {"parameters": a1111("lin xiaoman, 24yo, short black hair, trench coat, front view, "
                             "cinematic lighting, film grain, masterpiece", "lowres, bad anatomy, "
                             "watermark, extra fingers", "dreamshaper_8", 736251984, 832, 1216),
         "prompt": "{}", "workflow": "{}"})
    art(os.path.join(a, "林小满_侧面.png"), 832, 1216, (30, 26, 44), (120, 70, 90),
        (255, 180, 120), "林小满 · 侧面", "人物设定 / 三视图 B",
        {"parameters": a1111("lin xiaoman, side view, short black hair, trench coat, "
                             "neon rim light, masterpiece", "lowres, watermark, extra limbs",
                             "dreamshaper_8", 736251985, 832, 1216)})
    art(os.path.join(a, "反派_剪影.png"), 1216, 832, (12, 12, 18), (40, 20, 30),
        (255, 80, 90), "反派 · 剪影", "人物设定 / 氛围稿")
    os.makedirs(os.path.join(a, "林小满"), exist_ok=True)
    art(os.path.join(a, "林小满", "表情_01_平静.png"), 768, 768, (26, 30, 40), (60, 80, 110),
        (180, 220, 255), "表情 01 · 平静", "表情库")

    s = os.path.join(base, "场景")
    art(os.path.join(s, "雨夜街道.png"), 1344, 768, (10, 16, 30), (30, 60, 90),
        (80, 220, 255), "雨夜街道", "场景概念 / 霓虹与积水",
        {"parameters": a1111("rainy night street, neon reflections, wet asphalt, cinematic wide shot, "
                             "anamorphic lens flare, teal and orange", "people, text, watermark",
                             "juggernautXL_v9", 55231007, 1344, 768)})
    art(os.path.join(s, "天台黄昏.png"), 1344, 768, (60, 40, 60), (240, 150, 90),
        (255, 220, 160), "天台黄昏", "场景概念 / 城市天际线")
    os.makedirs(os.path.join(s, "街道"), exist_ok=True)
    art(os.path.join(s, "街道", "便利店_外景.png"), 1024, 1024, (20, 30, 40), (60, 90, 120),
        (255, 240, 200), "便利店 · 外景", "场景细节")

    d = os.path.join(base, "道具")
    art(os.path.join(d, "旧怀表.png"), 1024, 1024, (34, 28, 18), (120, 96, 50),
        (255, 210, 120), "旧怀表", "道具 / 关键道具")
    art(os.path.join(d, "怀表_齿轮特写.png"), 1024, 768, (18, 18, 22), (70, 62, 40),
        (255, 200, 90), "怀表 · 齿轮", "道具 / 特写")

    # 音频：合成两段示意音（带节奏起伏，波形更像真实素材）
    def lcg(seed: int):
        s = seed & 0x7FFFFFFF

        def nxt() -> float:
            nonlocal s
            s = (1103515245 * s + 12345) & 0x7FFFFFFF
            return s / 0x7FFFFFFF * 2 - 1

        return nxt

    def write_wav(path: str, frames: bytearray, fr: int = 22050) -> None:
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(fr)
            w.writeframes(bytes(frames))

    def wav_voice(path: str, seconds: float = 7.4) -> None:
        fr, n = 22050, int(22050 * 7.4)
        rnd = lcg(7)
        phase = 0.0
        frames = bytearray()
        for i in range(n):
            t = i / fr
            phrase = t % 1.62
            env = 0.0
            if 0.22 < phrase < 1.30:
                env = min(1.0, (phrase - 0.22) / 0.16) * min(1.0, (1.30 - phrase) / 0.26)
            f0 = 158 + 34 * math.sin(2 * math.pi * 0.42 * t) + 9 * math.sin(2 * math.pi * 2.7 * t)
            phase += 2 * math.pi * f0 / fr
            v = math.sin(phase) * 0.55 + math.sin(phase * 2) * 0.24 + math.sin(phase * 3) * 0.12
            v = (v + rnd() * 0.06) * env * (0.72 + 0.28 * abs(math.sin(2 * math.pi * 4.6 * t)))
            frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 21000))
        write_wav(path, frames)

    def wav_rain(path: str, seconds: float = 8.6) -> None:
        fr, n = 22050, int(22050 * 8.6)
        rnd = lcg(42)
        prev = 0.0
        frames = bytearray()
        for i in range(n):
            t = i / fr
            white = rnd()
            prev = prev * 0.86 + white * 0.14
            gust = 0.52 + 0.48 * abs(math.sin(2 * math.pi * 0.21 * t) * math.sin(2 * math.pi * 0.063 * t))
            v = prev * 1.7 * gust + white * 0.06
            frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 19000))
        write_wav(path, frames)

    wav_voice(os.path.join(base, "音频", "开场旁白_男声.wav"))
    wav_rain(os.path.join(base, "音频", "雨声环境.wav"))

    # 成片占位：文本说明
    with open(os.path.join(base, "成片", "交付说明.txt"), "w", encoding="utf-8") as f:
        f.write("把剪辑导出的成片放在这里，支持 mp4 / mov / webm。\n")
