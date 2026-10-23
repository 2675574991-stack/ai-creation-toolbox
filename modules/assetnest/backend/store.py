"""轻量存储：设置、最近项目、素材的人工元数据（评分/收藏/备注/标签）。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS projects(
  path TEXT PRIMARY KEY, name TEXT, created_at INTEGER, last_open INTEGER
);
CREATE TABLE IF NOT EXISTS items(
  path TEXT PRIMARY KEY,
  mtime REAL DEFAULT 0,
  size INTEGER DEFAULT 0,
  kind TEXT DEFAULT '',
  width INTEGER DEFAULT 0,
  height INTEGER DEFAULT 0,
  duration REAL DEFAULT 0,
  rating INTEGER DEFAULT 0,
  favorite INTEGER DEFAULT 0,
  note TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  updated_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_fav ON items(favorite);
"""

DEFAULT_SETTINGS = {
    "project": "",
    "tile": 220,
    "sort": "name_asc",
    "recursive": 0,
    "theme": "dark",
    "ffmpeg": "",
    "show_hidden": 0,
    "auto_poster": 1,
}


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or paths.db_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        with self.write() as c:
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=15000")
            self._local.conn = c
        return c

    def write(self):
        store = self

        class _Ctx:
            def __enter__(self):
                store._lock.acquire()
                self.c = store.conn()
                return self.c

            def __exit__(self, et, ev, tb):
                try:
                    self.c.commit() if et is None else self.c.rollback()
                finally:
                    store._lock.release()
                return False

        return _Ctx()

    # ---------- 设置 ----------
    def settings(self) -> dict:
        s = dict(DEFAULT_SETTINGS)
        rows = self.conn().execute("SELECT k,v FROM settings").fetchall()
        for r in rows:
            try:
                s[r["k"]] = json.loads(r["v"])
            except Exception:
                s[r["k"]] = r["v"]
        return s

    def save_settings(self, patch: dict) -> dict:
        s = self.settings()
        with self.write() as c:
            for k, v in (patch or {}).items():
                if k in DEFAULT_SETTINGS:
                    s[k] = v
                    c.execute("INSERT INTO settings(k,v) VALUES(?,?) "
                              "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                              (k, json.dumps(v, ensure_ascii=False)))
        return s

    # ---------- 项目 ----------
    def touch_project(self, path: str, name: str) -> None:
        with self.write() as c:
            c.execute("INSERT INTO projects(path,name,created_at,last_open) VALUES(?,?,?,?) "
                      "ON CONFLICT(path) DO UPDATE SET last_open=excluded.last_open, name=excluded.name",
                      (path, name, paths.now_ts(), paths.now_ts()))

    def recent_projects(self, limit: int = 8) -> list[dict]:
        rows = self.conn().execute(
            "SELECT * FROM projects WHERE path<>'' ORDER BY last_open DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows if os.path.isdir(r["path"])]

    # ---------- 条目 ----------
    def get_items(self, paths_: list[str]) -> dict[str, dict]:
        if not paths_:
            return {}
        out = {}
        for i in range(0, len(paths_), 300):
            chunk = paths_[i:i + 300]
            q = ",".join("?" * len(chunk))
            for r in self.conn().execute(f"SELECT * FROM items WHERE path IN ({q})", chunk):
                d = dict(r)
                d["tags"] = [t for t in (d.get("tags") or "").split("\x1f") if t]
                out[d["path"]] = d
        return out

    def get_item(self, path: str) -> dict:
        r = self.conn().execute("SELECT * FROM items WHERE path=?", (path,)).fetchone()
        if not r:
            return {"path": path, "rating": 0, "favorite": 0, "note": "", "tags": [],
                    "width": 0, "height": 0, "duration": 0}
        d = dict(r)
        d["tags"] = [t for t in (d.get("tags") or "").split("\x1f") if t]
        return d

    def ensure_item(self, path: str, kind: str, size: int, mtime: float) -> None:
        with self.write() as c:
            c.execute("INSERT OR IGNORE INTO items(path,kind,size,mtime) VALUES(?,?,?,?)",
                      (path, kind, size, mtime))

    def update_item(self, path: str, patch: dict, create_if_missing: bool = False) -> dict:
        allowed = {"rating", "favorite", "note", "tags", "width", "height", "duration", "kind", "size", "mtime"}
        sets, vals = [], []
        for k, v in patch.items():
            if k not in allowed:
                continue
            if k == "tags":
                v = "\x1f".join(t.strip() for t in (v or []) if t and t.strip())
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            return self.get_item(path)
        with self.write() as c:
            c.execute("INSERT OR IGNORE INTO items(path) VALUES(?)", (path,))
            c.execute(f"UPDATE items SET {','.join(sets)}, updated_at=? WHERE path=?",
                      vals + [paths.now_ts(), path])
        return self.get_item(path)

    def delete_item(self, path: str) -> None:
        with self.write() as c:
            c.execute("DELETE FROM items WHERE path=?", (path,))

    def move_item(self, old: str, new: str) -> None:
        """文件/文件夹移动后，把评分、标签、备注一并迁到新路径。"""
        old_prefix = old + os.sep
        with self.write() as c:
            rows = c.execute("SELECT path FROM items").fetchall()
            for r in rows:
                p = r["path"]
                if p != old and not p.startswith(old_prefix):
                    continue
                np = new + p[len(old):]
                try:
                    c.execute("UPDATE OR REPLACE items SET path=? WHERE path=?", (np, p))
                except Exception:
                    c.execute("DELETE FROM items WHERE path=?", (p,))

    def favorite_paths(self, project: str) -> list[str]:
        rows = self.conn().execute(
            "SELECT path FROM items WHERE favorite=1 AND path LIKE ?", (project.rstrip("\\/") + "%",))
        return [r["path"] for r in rows if os.path.isfile(r["path"])]

    def all_tags(self) -> list[dict]:
        counts: dict[str, int] = {}
        for r in self.conn().execute("SELECT tags FROM items WHERE tags<>''"):
            for t in (r["tags"] or "").split("\x1f"):
                if t:
                    counts[t] = counts.get(t, 0) + 1
        return [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
