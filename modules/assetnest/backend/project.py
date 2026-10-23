"""项目模型：固定分类目录、文件夹树、文件列举与文件操作。"""
from __future__ import annotations

import os
import shutil
import time

from . import paths

MAX_DEPTH = 6


class ProjectError(Exception):
    pass


class Project:
    def __init__(self, root: str):
        self.root = os.path.normpath(os.path.abspath(root))

    # ---------- 基础 ----------
    def exists(self) -> bool:
        return os.path.isdir(self.root)

    def name(self) -> str:
        return os.path.basename(self.root.rstrip("\\/")) or self.root

    def rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.root).replace("\\", "/")
        except Exception:
            return ""

    def safe(self, path: str) -> str:
        p = os.path.normpath(os.path.abspath(path or self.root))
        root = self.root
        if p != root and not p.startswith(root + os.sep):
            raise ProjectError("路径不在当前项目内")
        return p

    def ensure_structure(self) -> list[str]:
        created = []
        if not os.path.isdir(self.root):
            os.makedirs(self.root, exist_ok=True)
        for c in paths.CATEGORIES:
            d = os.path.join(self.root, c["name"])
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
                created.append(c["name"])
        return created

    def category_of(self, path: str) -> dict:
        rel = self.rel(path)
        top = rel.split("/")[0] if rel else ""
        return paths.CATEGORY_MAP.get(top, {})

    # ---------- 树 ----------
    def _dir_counts(self, base: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for dirpath, dirnames, filenames in os.walk(base):
            if os.path.relpath(dirpath, base).count(os.sep) >= MAX_DEPTH:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in paths.IGNORE_DIRS
                           and not d.startswith(".")]
            counts[dirpath] = sum(1 for f in filenames if self._countable(f))
        return counts

    def _countable(self, fname: str) -> bool:
        if fname.startswith(".") or fname.startswith("~$"):
            return False
        if os.path.splitext(fname)[1].lower() in paths.SIDECAR_EXT:
            return False
        return paths.kind_of(fname) != "other"

    def _node(self, path: str, counts: dict[str, int], depth: int = 0) -> dict:
        name = os.path.basename(path) or path
        direct = counts.get(path, 0)
        total = direct
        children = []
        if depth < MAX_DEPTH:
            try:
                entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
            except OSError:
                entries = []
            for e in entries:
                if not e.is_dir(follow_symlinks=False):
                    continue
                if e.name in paths.IGNORE_DIRS or e.name.startswith("."):
                    continue
                child = self._node(e.path, counts, depth + 1)
                total += child["total"]
                children.append(child)
        return {"name": name, "path": path, "rel": self.rel(path), "count": direct,
                "total": total, "children": children}

    def tree(self) -> dict:
        root = {"name": self.name(), "path": self.root, "rel": "", "count": 0,
                "total": 0, "icon": "project", "children": []}
        try:
            root_entries = [e for e in os.scandir(self.root) if e.is_dir(follow_symlinks=False)]
        except OSError:
            return root
        known = {c["name"] for c in paths.CATEGORIES}
        for c in paths.CATEGORIES:
            p = os.path.join(self.root, c["name"])
            counts = self._dir_counts(p) if os.path.isdir(p) else {}
            node = self._node(p, counts) if os.path.isdir(p) else {
                "name": c["name"], "path": p, "rel": c["name"], "count": 0,
                "total": 0, "children": []}
            node.update({"icon": c["icon"], "color": c["color"], "key": c["key"],
                         "desc": c["desc"], "missing": not os.path.isdir(p)})
            root["children"].append(node)
            root["total"] += node["total"]
            root["count"] += node["count"]
        extras = []
        for e in root_entries:
            if e.name in known or e.name in paths.IGNORE_DIRS or e.name.startswith("."):
                continue
            counts = self._dir_counts(e.path)
            n = self._node(e.path, counts)
            n.update({"icon": "folder", "color": "#8b93a7", "key": "other"})
            extras.append(n)
            root["total"] += n["total"]
        if extras:
            root["children"].append({
                "name": "其他", "path": self.root, "rel": "", "icon": "folder",
                "color": "#8b93a7", "key": "other", "is_virtual": True,
                "count": 0, "total": sum(n["total"] for n in extras), "children": extras})
        return root

    # ---------- 列举 ----------
    def list_files(self, folder: str, recursive: bool = False, sort: str = "name_asc",
                   q: str = "", kinds: list[str] | None = None, favorite_only: bool = False,
                   rating_min: int = 0, limit: int = 4000) -> list[dict]:
        folder = self.safe(folder or self.root)
        if not os.path.isdir(folder):
            raise ProjectError("文件夹不存在：" + folder)
        items = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(folder):
                if os.path.relpath(dirpath, folder).count(os.sep) >= MAX_DEPTH:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if d not in paths.IGNORE_DIRS
                               and not d.startswith(".")]
                for f in filenames:
                    it = self._item(os.path.join(dirpath, f))
                    if it:
                        items.append(it)
                        if len(items) >= limit:
                            break
                if len(items) >= limit:
                    break
        else:
            try:
                with os.scandir(folder) as sc:
                    for e in sc:
                        if not e.is_file(follow_symlinks=False):
                            continue
                        it = self._item(e.path)
                        if it:
                            items.append(it)
            except OSError as e:
                raise ProjectError(f"无法读取文件夹：{e}")
        return self._filter(items, q, kinds, favorite_only, rating_min, sort)

    def _item(self, path: str) -> dict | None:
        name = os.path.basename(path)
        if name.startswith(".") or name.startswith("~$"):
            return None
        ext = os.path.splitext(name)[1].lower()
        if ext in paths.SIDECAR_EXT:
            return None
        kind = paths.kind_of(path)
        if kind == "other":
            return None
        if kind == "text" and ext in (".json", ".txt") and self._has_media_twin(path):
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        return {"path": path, "name": name, "ext": ext, "kind": kind, "size": st.st_size,
                "mtime": st.st_mtime, "rel": self.rel(path), "folder": os.path.basename(
                    os.path.dirname(path)) or self.name()}

    def _has_media_twin(self, path: str) -> bool:
        stem = os.path.splitext(path)[0]
        for e in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"):
            if os.path.isfile(stem + e):
                return True
        return False

    def _filter(self, items: list[dict], q: str, kinds, favorite_only, rating_min,
                sort: str) -> list[dict]:
        q = (q or "").strip()
        if q:
            ql = q.lower()
            items = [i for i in items if ql in i["name"].lower() or ql in i["rel"].lower()]
        if kinds:
            ks = set(kinds)
            items = [i for i in items if i["kind"] in ks]
        if favorite_only:
            items = [i for i in items if i.get("favorite")]
        if rating_min:
            items = [i for i in items if (i.get("rating") or 0) >= rating_min]
        key = sort or "name_asc"
        if key == "name_desc":
            items.sort(key=lambda i: i["name"].lower(), reverse=True)
        elif key == "mtime_desc":
            items.sort(key=lambda i: i["mtime"], reverse=True)
        elif key == "mtime_asc":
            items.sort(key=lambda i: i["mtime"])
        elif key == "size_desc":
            items.sort(key=lambda i: i["size"], reverse=True)
        elif key == "kind":
            items.sort(key=lambda i: (i["kind"], i["name"].lower()))
        else:
            items.sort(key=lambda i: i["name"].lower())
        return items

    # ---------- 文件操作 ----------
    def unique_path(self, path: str) -> str:
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        for i in range(1, 9999):
            cand = f"{stem} ({i}){ext}"
            if not os.path.exists(cand):
                return cand
        return path

    def mkdir(self, parent: str, name: str) -> str:
        parent = self.safe(parent or self.root)
        target = self.safe(os.path.join(parent, paths.safe_name(name)))
        if os.path.exists(target):
            # 重名时自动加序号，避免静默复用旧文件夹
            stem = target
            for i in range(1, 999):
                cand = f"{stem} ({i})"
                if not os.path.exists(cand):
                    target = cand
                    break
        os.makedirs(target, exist_ok=True)
        return target

    def rename(self, path: str, new_name: str) -> str:
        p = self.safe(path)
        base = os.path.basename(p)
        stem, ext = os.path.splitext(base)
        new_name = paths.safe_name(new_name).strip()
        if not new_name:
            raise ProjectError("名称不能为空")
        if os.path.isdir(p):
            target = os.path.join(os.path.dirname(p), new_name)
        else:
            if not os.path.splitext(new_name)[1]:
                new_name += ext
            target = os.path.join(os.path.dirname(p), new_name)
        target = self.safe(target)
        if os.path.normcase(target) == os.path.normcase(p):
            return p
        if os.path.exists(target):
            raise ProjectError("同名文件已存在")
        os.rename(p, target)
        return target

    def delete(self, path: str, hard: bool = False) -> tuple[bool, str]:
        p = self.safe(path)
        if p == self.root:
            raise ProjectError("不能删除项目根目录")
        if not os.path.exists(p):
            return False, "文件不存在"
        if hard and not os.path.isdir(p):
            try:
                os.remove(p)
                return True, ""
            except Exception as e:
                return False, str(e)
        removed, err = paths.delete_to_recycle_bin([p])
        return removed > 0, err

    def import_file(self, target_dir: str, rel_name: str, src, size: int = 0) -> dict:
        """把上传流写入目标分类目录，rel_name 可含子目录（拖拽文件夹时）。"""
        target_dir = self.safe(target_dir)
        rel_name = (rel_name or "").replace("\\", "/").lstrip("/")
        parts = [p for p in rel_name.split("/") if p not in ("", ".", "..")]
        if not parts:
            raise ProjectError("文件名无效")
        sub = os.path.join(target_dir, *[paths.safe_name(p) for p in parts[:-1]])
        os.makedirs(sub, exist_ok=True)
        dst = self.unique_path(os.path.join(sub, paths.safe_name(parts[-1])))
        tmp = dst + ".part"
        written = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
        os.replace(tmp, dst)
        st = os.stat(dst)
        return {"path": dst, "name": os.path.basename(dst), "size": written,
                "mtime": st.st_mtime, "kind": paths.kind_of(dst), "rel": self.rel(dst)}

    def signature(self) -> str:
        """项目内容指纹：路径 + 大小 + 修改时间，用于检测外部改动。"""
        rows = []
        stack = [self.root]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as sc:
                    entries = list(sc)
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name in paths.IGNORE_DIRS or e.name.startswith("."):
                            continue
                        stack.append(e.path)
                    elif self._countable(e.name):
                        st = e.stat()
                        rows.append(f"{self.rel(e.path)}|{st.st_size}|{int(st.st_mtime)}")
                except OSError:
                    continue
        rows.sort()
        import hashlib
        return hashlib.md5("\n".join(rows).encode("utf-8", "ignore")).hexdigest()

    def stats(self) -> dict:
        cat_stats = []
        total_files = total_size = 0
        for c in paths.CATEGORIES:
            p = os.path.join(self.root, c["name"])
            n = s = 0
            if os.path.isdir(p):
                for dirpath, dirnames, filenames in os.walk(p):
                    dirnames[:] = [d for d in dirnames if d not in paths.IGNORE_DIRS
                                   and not d.startswith(".")]
                    for f in filenames:
                        if not self._countable(f):
                            continue
                        try:
                            s += os.path.getsize(os.path.join(dirpath, f))
                            n += 1
                        except OSError:
                            pass
            total_files += n
            total_size += s
            cat_stats.append({**c, "count": n, "size": s})
        return {"files": total_files, "size": total_size, "categories": cat_stats,
                "root": self.root, "name": self.name()}

    def guess_category(self, kind: str, ext: str) -> str:
        if kind == "audio":
            return "音频"
        if kind == "video":
            return "成片" if "final" in ext else "视频"
        if kind == "text":
            return "剧本"
        if kind == "model":
            return "其他"
        return "人物"
