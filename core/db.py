# -*- coding: utf-8 -*-
import os
import sqlite3
import threading
import time

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT, lang TEXT, joined INTEGER,
    banned INTEGER DEFAULT 0, credits INTEGER DEFAULT 0, free_date TEXT DEFAULT '', free_used INTEGER DEFAULT 0,
    premium_until INTEGER DEFAULT 0, channel_id INTEGER, channel_title TEXT);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, op TEXT, ok INTEGER, at INTEGER);
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT, owner INTEGER, chat_id INTEGER, message_id INTEGER, at INTEGER);
CREATE TABLE IF NOT EXISTS likes(post_id INTEGER, uid INTEGER, PRIMARY KEY(post_id, uid));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, plan TEXT, method TEXT,
    price TEXT, status TEXT, at INTEGER);
"""


def today():
    return time.strftime("%Y-%m-%d", time.gmtime())


class DB:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.c.executescript(SCHEMA)
            self.c.commit()

    def _x(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur

    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        r = self._all(sql, args)
        return r[0] if r else None

    # ---- کاربران ----
    def touch_user(self, uid, name, username=None):
        self._x("INSERT INTO users(id,name,username,joined) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username",
                (uid, name, username, int(time.time())))

    def user(self, uid):
        return self._one("SELECT * FROM users WHERE id=?", (uid,))

    def lang(self, uid):
        u = self.user(uid)
        return (u and u["lang"]) or config.DEFAULT_LANG

    def has_lang(self, uid):
        u = self.user(uid)
        return bool(u and u["lang"])

    def set_lang(self, uid, lang):
        self._x("UPDATE users SET lang=? WHERE id=?", (lang, uid))

    def is_banned(self, uid):
        u = self.user(uid)
        return bool(u and u["banned"])

    def set_ban(self, uid, v):
        self._x("INSERT INTO users(id,name,joined,banned) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET banned=excluded.banned", (uid, "?", int(time.time()), 1 if v else 0))

    def user_ids(self):
        return [r["id"] for r in self._all("SELECT id FROM users WHERE banned=0")]

    # ---- اعتبار ----
    def balance(self, uid):
        u = self.user(uid) or {}
        used = u.get("free_used", 0) if u.get("free_date") == today() else 0
        prem = u.get("premium_until", 0) or 0
        return {"free_left": max(0, config.FREE_DAILY - used), "credits": u.get("credits", 0) or 0,
                "premium_until": prem if prem > time.time() else 0}

    def can_use(self, uid):
        """(ok, source) — source: premium | free | credit"""
        b = self.balance(uid)
        if b["premium_until"]:
            return True, "premium"
        if b["free_left"] > 0:
            return True, "free"
        if b["credits"] > 0:
            return True, "credit"
        return False, None

    def consume(self, uid, source):
        if source == "free":
            self._x("UPDATE users SET free_used=CASE WHEN free_date=? THEN free_used+1 ELSE 1 END, free_date=? WHERE id=?",
                    (today(), today(), uid))
        elif source == "credit":
            self._x("UPDATE users SET credits=MAX(0,credits-1) WHERE id=?", (uid,))

    def add_credits(self, uid, n):
        self._x("UPDATE users SET credits=credits+? WHERE id=?", (n, uid))

    def add_days(self, uid, days):
        u = self.user(uid) or {}
        base = max(int(time.time()), u.get("premium_until") or 0)
        self._x("UPDATE users SET premium_until=? WHERE id=?", (base + days * 86400, uid))

    def log_job(self, uid, op, ok):
        self._x("INSERT INTO jobs(uid,op,ok,at) VALUES(?,?,?,?)", (uid, op, 1 if ok else 0, int(time.time())))

    # ---- کانال و لایک ----
    def set_channel(self, uid, chat_id, title):
        self._x("UPDATE users SET channel_id=?, channel_title=? WHERE id=?", (chat_id, title, uid))

    def add_post(self, owner, chat_id):
        return self._x("INSERT INTO posts(owner,chat_id,message_id,at) VALUES(?,?,?,?)",
                       (owner, chat_id, 0, int(time.time()))).lastrowid

    def set_post_message(self, pid, mid):
        self._x("UPDATE posts SET message_id=? WHERE id=?", (mid, pid))

    def toggle_like(self, pid, uid):
        with self.lock:
            had = self.c.execute("SELECT 1 FROM likes WHERE post_id=? AND uid=?", (pid, uid)).fetchone()
            if had:
                self.c.execute("DELETE FROM likes WHERE post_id=? AND uid=?", (pid, uid))
            else:
                self.c.execute("INSERT INTO likes(post_id,uid) VALUES(?,?)", (pid, uid))
            n = self.c.execute("SELECT COUNT(*) FROM likes WHERE post_id=?", (pid,)).fetchone()[0]
            self.c.commit()
        return (not had), n

    def like_count(self, pid):
        return self._one("SELECT COUNT(*) AS n FROM likes WHERE post_id=?", (pid,))["n"]

    # ---- پرداخت ----
    def add_payment(self, uid, plan, method, price, status="pending"):
        return self._x("INSERT INTO payments(uid,plan,method,price,status,at) VALUES(?,?,?,?,?,?)",
                       (uid, plan, method, price, status, int(time.time()))).lastrowid

    def payment(self, pid):
        return self._one("SELECT * FROM payments WHERE id=?", (pid,))

    def set_payment(self, pid, status):
        self._x("UPDATE payments SET status=? WHERE id=?", (status, pid))

    def stats(self):
        t = int(time.time()) - 86400
        return {
            "users": self._one("SELECT COUNT(*) AS n FROM users")["n"],
            "banned": self._one("SELECT COUNT(*) AS n FROM users WHERE banned=1")["n"],
            "jobs": self._one("SELECT COUNT(*) AS n FROM jobs")["n"],
            "jobs24": self._one("SELECT COUNT(*) AS n FROM jobs WHERE at>?", (t,))["n"],
            "pending": self._one("SELECT COUNT(*) AS n FROM payments WHERE status='pending'")["n"],
            "paid": self._one("SELECT COUNT(*) AS n FROM payments WHERE status='paid'")["n"],
            "by_op": self._all("SELECT op, COUNT(*) AS n FROM jobs GROUP BY op ORDER BY n DESC LIMIT 12"),
        }
