# -*- coding: utf-8 -*-
"""منطق ربات ویرایشگر موزیک/ویدیو: نشست، منو، عملیات، اعتبار/پرداخت، کانال و لایک، ادمین."""
import asyncio
import html
import logging
import os
import shutil
import time

import config
from . import i18n, media
from .media import MediaError
from .tgapi import CQ, Obj, TgError

log = logging.getLogger("bot")

AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac", ".wma", ".amr", ".mka"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".3gp", ".flv", ".wmv", ".ts", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
TR = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SEND_FIELD = {"audio": "audio", "voice": "voice", "video": "video", "video_note": "video_note",
              "animation": "animation", "document": "document"}
HEIGHTS = (144, 240, 360, 480, 720, 1080)
POSITIONS = [["tl", "tc", "tr"], ["ml", "mc", "mr"], ["bl", "bc", "br"]]
POS_ICON = {"tl": "↖️", "tc": "⬆️", "tr": "↗️", "ml": "⬅️", "mc": "⏺", "mr": "➡️", "bl": "↙️", "bc": "⬇️", "br": "↘️"}


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def kb(rows):
    out = []
    for row in rows:
        line = []
        for t, d in row:
            line.append({"text": t, "url": d[4:]} if d.startswith("url:") else {"text": t, "callback_data": d})
        out.append(line)
    return {"inline_keyboard": out}


def fmt_dur(sec):
    sec = int(round(sec or 0))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def parse_time(tok):
    tok = tok.translate(TR).strip()
    try:
        if ":" in tok:
            v = 0.0
            for p in tok.split(":"):
                v = v * 60 + float(p)
            return v
        return float(tok)
    except ValueError:
        return None


def parse_range(text):
    t = (text or "").translate(TR)
    for ch in "،,→–—-":
        t = t.replace(ch, " ")
    t = t.replace(" تا ", " ")
    toks = t.split()
    if len(toks) != 2:
        return None
    a, b = parse_time(toks[0]), parse_time(toks[1])
    if a is None or b is None:
        return None
    return a, b


async def tg(fn, *a, retries=2, **kw):
    for i in range(retries + 1):
        try:
            return await fn(*a, **kw)
        except Exception as e:  # noqa
            ra = getattr(e, "retry_after", None)
            if ra and i < retries:
                await asyncio.sleep(float(ra) + 0.5)
                continue
            if "not modified" not in str(e).lower():
                log.warning("telegram call failed: %s", e)
            return None


class BigOut(Exception):
    pass


class Sess:
    def __init__(self, uid, d):
        self.uid, self.dir = uid, d
        self.kind = self.path = self.file_id = self.send_kind = None
        self.name = ""
        self.info = {}
        self.step = None
        self.args = {}
        self.tags = {}
        self.cover = None
        self.busy = False
        self.t = time.time()


class Editor:
    def __init__(self, bot, db, me):
        self.bot, self.db, self.me = bot, db, me
        self.sess = {}
        self.sem = asyncio.Semaphore(config.MAX_JOBS)
        self.wait_receipt = {}
        self.hits, self.blocked = {}, {}
        self.sub_cache = {}

    # ------------------------------------------------------------------ ابزار
    def lang(self, uid):
        return self.db.lang(uid)

    def T(self, uid, key, **kw):
        return i18n.t(self.lang(uid), key, **kw)

    async def say(self, uid, key, markup=None, raw=False, **kw):
        text = key if raw else self.T(uid, key, **kw)
        return await tg(self.bot.send_message, chat_id=uid, text=text, reply_markup=markup)

    async def edit(self, uid, mid, text, markup=None):
        if mid:
            await tg(self.bot.edit_message_text, text=text, chat_id=uid, message_id=mid, reply_markup=markup)

    async def delete(self, uid, mid):
        if mid:
            await tg(self.bot.delete_message, chat_id=uid, message_id=mid)

    def flood_ok(self, uid):
        if uid in config.ADMIN_IDS:
            return True
        now = time.time()
        if self.blocked.get(uid, 0) > now:
            return False
        q = [t for t in self.hits.get(uid, []) if now - t < 10] + [now]
        self.hits[uid] = q
        if len(q) > config.FLOOD_LIMIT:
            self.blocked[uid] = now + config.FLOOD_BLOCK_SECONDS
            self.hits[uid] = []
            return False
        if len(self.hits) > 10000:
            self.hits.clear()
        return True

    # ------------------------------------------------------------------ نشست
    def new_session(self, uid):
        self.drop_session(uid)
        d = os.path.join(config.TMP_DIR, f"{uid}_{int(time.time() * 1000)}")
        os.makedirs(d, exist_ok=True)
        s = Sess(uid, d)
        self.sess[uid] = s
        return s

    def drop_session(self, uid):
        s = self.sess.pop(uid, None)
        if s:
            shutil.rmtree(s.dir, ignore_errors=True)

    def ensure_session(self, uid):
        return self.sess.get(uid) or self.new_session(uid)

    async def janitor(self):
        while True:
            await asyncio.sleep(120)
            now = time.time()
            for uid, s in list(self.sess.items()):
                if not s.busy and now - s.t > config.SESSION_TTL:
                    self.drop_session(uid)

    # ------------------------------------------------------------------ ورودی
    async def on_update(self, u):
        d = u._d
        if "message" in d:
            await self.on_message(Obj(d["message"]))
        elif "callback_query" in d:
            await self.on_callback(CQ(d["callback_query"], self.bot))
        elif "pre_checkout_query" in d:
            q = Obj(d["pre_checkout_query"])
            ok = str(q.invoice_payload or "").startswith("plan:")
            await tg(self.bot.answer_precheckout, q.id, ok, None if ok else "invalid")

    async def sub_ok(self, uid):
        if not config.FORCE_JOIN or uid in config.ADMIN_IDS:
            return True
        c = self.sub_cache.get(uid)
        if c and c[1] > time.time():
            return c[0]
        try:
            m = await self.bot.get_chat_member(config.CHANNEL_USERNAME, uid)
            ok = str(m.status) in ("creator", "administrator", "member") or (str(m.status) == "restricted" and bool(m.is_member))
        except Exception as e:  # noqa
            log.error("membership check failed: %s", e)
            if not getattr(self, "_warned", False):
                self._warned = True
                for a in config.ADMIN_IDS[:2]:
                    await tg(self.bot.send_message, chat_id=a,
                             text=f"⚠️ بررسی عضویت اجباری کار نمی‌کند. ربات باید در کانال {config.CHANNEL_USERNAME} ادمین باشد.\n{e}")
            return True
        self.sub_cache[uid] = (ok, time.time() + (300 if ok else 5))
        return ok

    async def prompt_join(self, uid):
        await self.say(uid, "join", kb([[(self.T(uid, "b_join"), f"url:https://t.me/{config.CHANNEL_USERNAME.lstrip('@')}")],
                                        [(self.T(uid, "b_joined"), "sub:check")]]), ch=config.CHANNEL_USERNAME)

    async def on_message(self, m):
        u = m.from_user
        if u is None or u.is_bot or m.chat.type != "private":
            return
        uid = u.id
        if not self.flood_ok(uid):
            return
        self.db.touch_user(uid, u.full_name, u.username)
        if self.db.is_banned(uid):
            return
        d = m._d
        if "successful_payment" in d:
            return await self.on_stars_paid(m)
        if not await self.sub_ok(uid):
            return await self.prompt_join(uid)
        text = m.text
        if text and text.startswith("/"):
            return await self.on_command(m)
        mk = self.media_kind(d)
        if mk:
            return await self.on_media(m, mk)
        if text:
            return await self.on_text(m)

    @staticmethod
    def media_kind(d):
        if "audio" in d:
            return "audio", "audio", d["audio"]
        if "voice" in d:
            return "audio", "voice", d["voice"]
        if "video_note" in d:
            return "video", "video_note", d["video_note"]
        if "animation" in d:
            return "video", "animation", d["animation"]
        if "video" in d:
            return "video", "video", d["video"]
        if "photo" in d:
            return "image", "photo", d["photo"][-1]
        if "document" in d:
            o = d["document"]
            mime = (o.get("mime_type") or "").lower()
            ext = os.path.splitext(o.get("file_name") or "")[1].lower()
            if mime.startswith("audio/") or ext in AUDIO_EXT:
                return "audio", "document", o
            if mime.startswith("video/") or ext in VIDEO_EXT:
                return "video", "document", o
            if mime.startswith("image/") or ext in IMAGE_EXT:
                return "image", "document", o
            return "unsupported", None, o
        return None

    # ------------------------------------------------------------------ دستورات
    async def on_command(self, m):
        uid = m.from_user.id
        head, *args = m.text.split()
        cmd, _, target = head[1:].partition("@")
        if target and self.me.username and target.lower() != self.me.username.lower():
            return
        cmd = cmd.lower()
        adm = uid in config.ADMIN_IDS
        if cmd == "start":
            if not self.db.has_lang(uid):
                return await self.lang_picker(uid, start=True)
            return await self.welcome(uid)
        if cmd == "help":
            return await self.say(uid, "help")
        if cmd == "lang":
            return await self.lang_picker(uid)
        if cmd == "cancel":
            self.drop_session(uid)
            self.wait_receipt.pop(uid, None)
            return await self.say(uid, "cancelled")
        if cmd in ("me", "balance"):
            return await self.show_balance(uid)
        if cmd == "buy":
            return await self.show_plans(uid)
        if cmd == "setchannel":
            s = self.ensure_session(uid)
            s.step = "setchannel"
            s.args["after"] = False
            return await self.say(uid, "ch_ask")
        if not adm:
            return
        if cmd == "admin":
            st = self.db.stats()
            by = "\n".join(f"  • {r['op']}: {r['n']}" for r in st["by_op"]) or "  —"
            return await self.say(uid,
                                  f"🛠 <b>Admin</b>\n👤 users: {st['users']}  🚫 banned: {st['banned']}\n"
                                  f"⚙️ jobs: {st['jobs']} (24h: {st['jobs24']})\n💳 pending: {st['pending']}  paid: {st['paid']}\n{by}\n\n"
                                  "/broadcast text|reply • /ban id • /unban id\n/addcredit id n • /addpremium id days", raw=True)
        if cmd == "broadcast":
            text = m.text.partition(" ")[2].strip()
            src = m.reply_to_message
            if not text and not src:
                return await self.say(uid, "/broadcast text — or reply to a message", raw=True)
            ok = fail = 0
            for tid in self.db.user_ids():
                try:
                    if src:
                        await self.bot.copy_message(tid, uid, src.message_id)
                    else:
                        await self.bot.send_message(tid, text)
                    ok += 1
                except Exception:  # noqa
                    fail += 1
                await asyncio.sleep(0.05)
            return await self.say(uid, f"✅ {ok} / ❌ {fail}", raw=True)
        if cmd in ("ban", "unban") and args and args[0].lstrip("-").isdigit():
            if int(args[0]) not in config.ADMIN_IDS:
                self.db.set_ban(int(args[0]), cmd == "ban")
            return await self.say(uid, f"{cmd}: {args[0]}", raw=True)
        if cmd == "addcredit" and len(args) == 2 and args[0].isdigit() and args[1].lstrip("-").isdigit():
            self.db.touch_user(int(args[0]), "?")
            self.db.add_credits(int(args[0]), int(args[1]))
            return await self.say(uid, "✅", raw=True)
        if cmd == "addpremium" and len(args) == 2 and args[0].isdigit() and args[1].isdigit():
            self.db.touch_user(int(args[0]), "?")
            self.db.add_days(int(args[0]), int(args[1]))
            return await self.say(uid, "✅", raw=True)

    async def lang_picker(self, uid, start=False):
        rows = [[(n, f"lang:{c}:{'s' if start else 'x'}") for c, n in i18n.LANG_NAMES.items()]]
        await tg(self.bot.send_message, chat_id=uid, text=i18n.t("fa", "lang_pick") + "\n" + i18n.t("en", "lang_pick"),
                 reply_markup=kb(rows))

    async def welcome(self, uid):
        await self.say(uid, "welcome", free=config.FREE_DAILY)

    async def show_balance(self, uid):
        b = self.db.balance(uid)
        prem = time.strftime("%Y-%m-%d", time.gmtime(b["premium_until"])) if b["premium_until"] else "—"
        await self.say(uid, "balance", free_left=b["free_left"], free=config.FREE_DAILY, credits=b["credits"], premium=prem)

    # ------------------------------------------------------------------ دریافت فایل
    async def on_media(self, m, mk):
        kind, send_kind, o = mk
        uid = m.from_user.id
        if uid in self.wait_receipt and kind == "image":
            return await self.on_receipt(uid, m.from_user, o)
        if kind == "unsupported":
            return await self.say(uid, "unsupported")
        if kind == "image":
            return await self.on_image(uid, o, send_kind)
        s0 = self.sess.get(uid)
        if s0 and s0.busy:
            return await self.say(uid, "busy")
        size = o.get("file_size") or 0
        limit = config.MAX_DOWNLOAD_MB * 1024 * 1024
        if size > limit:
            return await self.say(uid, "too_big", size=fmt_size(size), max=fmt_size(limit))
        s = self.new_session(uid)
        st = await self.say(uid, "downloading")
        defaults = {"audio": "audio.mp3", "voice": "voice.ogg", "video": "video.mp4", "video_note": "note.mp4", "animation": "anim.mp4"}
        name = o.get("file_name") or defaults.get(send_kind, "file.bin")
        ext = os.path.splitext(name)[1].lower() or os.path.splitext(defaults.get(send_kind, ".bin"))[1]
        path = os.path.join(s.dir, "in" + ext)
        try:
            f = await self.bot.get_file(o["file_id"])
            await self.bot.download(f.file_path, path, max_bytes=limit)
            info = await media.probe(path)
            if not (info["has_audio"] or info["has_video"]):
                raise MediaError("no streams")
        except TgError as e:
            self.drop_session(uid)
            await self.delete(uid, st and st.message_id)
            if "too big" in str(e).lower():
                return await self.say(uid, "too_big", size=fmt_size(size), max=fmt_size(limit))
            log.warning("download failed: %s", e)
            return await self.say(uid, "err_process")
        except MediaError:
            self.drop_session(uid)
            await self.delete(uid, st and st.message_id)
            return await self.say(uid, "unsupported")
        s.kind, s.send_kind, s.path, s.name, s.file_id, s.info = kind, send_kind, path, name, o["file_id"], info
        s.tags = {k: info["tags"].get(k) for k in ("title", "artist", "album") if info["tags"].get(k)}
        await self.delete(uid, st and st.message_id)
        await self.show_menu(s)

    async def on_image(self, uid, o, send_kind):
        s = self.sess.get(uid)
        if not s or s.step not in ("wm_image", "tag_cover", "bg_image"):
            return await self.say(uid, "send_first")
        ext = ".png" if (o.get("mime_type") == "image/png" or (o.get("file_name") or "").lower().endswith(".png")) else ".jpg"
        path = os.path.join(s.dir, f"img_{int(time.time() * 1000)}{ext}")
        try:
            f = await self.bot.get_file(o["file_id"])
            await self.bot.download(f.file_path, path, max_bytes=20 * 1024 * 1024)
        except TgError:
            return await self.say(uid, "err_process")
        step, s.step = s.step, None
        if step == "wm_image":
            s.args["wm_png"] = path
            await self.ask_pos(s)
        elif step == "tag_cover":
            s.cover = path
            await self.show_tags(s)
        else:
            await self.run_op(s, "tovideo", image=path)

    def menu_rows(self, s):
        T = lambda k: self.T(s.uid, k)
        if s.kind == "audio":
            ops = ["trim"]
            if s.send_kind != "voice":
                ops.append("tovoice")
            if s.send_kind == "voice" or not s.path.lower().endswith(".mp3"):
                ops.append("tomp3")
            ops += ["tags", "tovideo"]
        else:
            ops = ["trim", "tomp3", "gif", "resize", "wm", "vnote"]
        ops.append("channel")
        btns = [(T("b_" + o), f"op:{o}") for o in ops]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        rows.append([(T("b_cancel"), "cancel")])
        return rows

    def info_text(self, s):
        size = fmt_size(os.path.getsize(s.path)) if s.path and os.path.exists(s.path) else "?"
        if s.kind == "audio":
            return self.T(s.uid, "info_audio", name=esc(s.name), dur=fmt_dur(s.info.get("duration")), size=size)
        return self.T(s.uid, "info_video", name=esc(s.name), dur=fmt_dur(s.info.get("duration")), size=size,
                      w=s.info.get("w"), h=s.info.get("h"))

    async def show_menu(self, s, head=None):
        text = (head + "\n\n" if head else "") + self.info_text(s) + "\n\n" + self.T(s.uid, "choose_op")
        await self.say(s.uid, text, kb(self.menu_rows(s)), raw=True)

    # ------------------------------------------------------------------ متن
    async def on_text(self, m):
        uid = m.from_user.id
        text = (m.text or "").strip()
        s = self.sess.get(uid)
        if uid in self.wait_receipt:
            return await self.say(uid, "card_info", **self.card_vars(self.wait_receipt[uid]))
        if not s or not s.step:
            return await self.say(uid, "send_first")
        s.t = time.time()
        step = s.step
        if step == "trim":
            r = parse_range(text)
            dur = s.info.get("duration") or 0
            if not r or r[0] < 0 or r[0] >= r[1] or (dur and r[0] >= dur):
                return await self.say(uid, "bad_range")
            a, b = r[0], min(r[1], dur) if dur else r[1]
            return await self.run_op(s, "trim", start=a, end=b)
        if step == "wm_text":
            if not text or len(text) > 60:
                return await self.say(uid, "ask_wm_text")
            png = os.path.join(s.dir, f"wm_{int(time.time() * 1000)}.png")
            try:
                await asyncio.to_thread(media.render_text, text, png)
            except Exception:
                log.exception("render text")
                return await self.say(uid, "err_process")
            s.args["wm_png"], s.step = png, None
            return await self.ask_pos(s)
        if step in ("tag_title", "tag_artist", "tag_album"):
            s.tags[step[4:]] = text[:120]
            s.step = None
            return await self.show_tags(s)
        if step == "caption":
            return await self.post_channel(s, text[:900])
        if step == "setchannel":
            return await self.set_channel(s, text)
        await self.say(uid, "send_first")

    # ------------------------------------------------------------------ کالبک‌ها
    async def on_callback(self, cq):
        u = cq.from_user
        if u is None or u.is_bot or not self.flood_ok(u.id):
            return await cq.answer()
        uid = u.id
        data = cq.data or ""
        kind, _, rest = data.partition(":")
        if self.db.is_banned(uid):
            return await cq.answer(self.T(uid, "banned"), show_alert=True)
        if kind == "lk":
            return await self.cb_like(cq, rest)
        if kind == "sub":
            self.sub_cache.pop(uid, None)
            if await self.sub_ok(uid):
                await cq.answer("✅")
                if cq.message:
                    await self.delete(uid, cq.message.message_id)
                return await self.welcome(uid)
            return await cq.answer(self.T(uid, "not_member"), show_alert=True)
        if not await self.sub_ok(uid):
            await cq.answer()
            return await self.prompt_join(uid)
        if kind == "pa":
            return await self.cb_approve(cq, rest)
        await cq.answer()
        self.db.touch_user(uid, u.full_name, u.username)
        mid = cq.message.message_id if cq.message else None
        if kind == "lang":
            code, _, mode = rest.partition(":")
            if code in i18n.LANGS:
                self.db.set_lang(uid, code)
                await self.delete(uid, mid)
                await self.welcome(uid) if mode == "s" else await self.say(uid, "lang_set")
            return
        if kind == "cancel":
            self.drop_session(uid)
            await self.delete(uid, mid)
            return await self.say(uid, "cancelled")
        if kind == "buy":
            return await self.show_plans(uid)
        if kind == "bp":
            return await self.cb_plan(uid, rest)
        if kind == "pm":
            return await self.cb_pay_method(uid, u, rest)
        s = self.sess.get(uid)
        if not s or not s.path and kind not in ("nocap",):
            return await self.say(uid, "expired")
        s.t = time.time()
        if kind == "op":
            return await self.cb_op(s, rest)
        if s.busy:
            return await self.say(uid, "busy")
        if kind == "rs":
            return await self.run_op(s, "resize", height=int(rest))
        if kind == "wm":
            s.step = "wm_text" if rest == "text" else "wm_image"
            return await self.say(uid, "ask_wm_text" if rest == "text" else "ask_wm_img")
        if kind == "pos":
            if not s.args.get("wm_png"):
                return await self.say(uid, "expired")
            return await self.run_op(s, "wm", png=s.args["wm_png"], pos=rest)
        if kind == "bg":
            if rest == "none":
                return await self.run_op(s, "tovideo", image=None)
            s.step = "bg_image"
            return await self.say(uid, "need_image")
        if kind == "tg":
            if rest == "apply":
                return await self.run_op(s, "tags")
            if rest == "cover":
                s.step = "tag_cover"
                return await self.say(uid, "ask_cover")
            if rest in ("title", "artist", "album"):
                s.step = "tag_" + rest
                return await self.say(uid, "ask_value", field=self.T(uid, "b_" + rest))
        if kind == "nocap":
            return await self.post_channel(s, None)

    async def cb_op(self, s, op):
        uid = s.uid
        if s.busy:
            return await self.say(uid, "busy")
        if op == "trim":
            s.step = "trim"
            return await self.say(uid, "ask_trim", dur=fmt_dur(s.info.get("duration")))
        if op in ("tovoice", "tomp3", "vnote"):
            if op == "vnote" and (s.info.get("duration") or 0) > 60:
                await self.say(uid, "vnote_note")
            return await self.run_op(s, op)
        if op == "gif":
            if (s.info.get("duration") or 0) > config.GIF_SECONDS:
                await self.say(uid, "gif_note", sec=config.GIF_SECONDS)
            return await self.run_op(s, "gif")
        if op == "tags":
            return await self.show_tags(s)
        if op == "tovideo":
            return await self.say(uid, "ask_bg", kb([[(self.T(uid, "b_bg_none"), "bg:none")]]))
        if op == "resize":
            hs = [h for h in HEIGHTS if h <= config.MAX_HEIGHT]
            btns = [(f"{h}p", f"rs:{h}") for h in hs]
            return await self.say(uid, "ask_resize", kb([btns[i:i + 3] for i in range(0, len(btns), 3)]))
        if op == "wm":
            return await self.say(uid, "ask_wmtype", kb([[(self.T(uid, "b_wm_text"), "wm:text"), (self.T(uid, "b_wm_img"), "wm:img")]]))
        if op == "channel":
            u = self.db.user(uid) or {}
            if u.get("channel_id"):
                s.step = "caption"
                return await self.say(uid, "ask_caption", kb([[(self.T(uid, "b_nocaption"), "nocap")]]))
            s.step = "setchannel"
            s.args["after"] = True
            return await self.say(uid, "ch_ask")

    async def ask_pos(self, s):
        rows = [[(POS_ICON[p], f"pos:{p}") for p in row] for row in POSITIONS]
        await self.say(s.uid, "ask_pos", kb(rows))

    async def show_tags(self, s):
        t = s.tags
        dash = lambda v: esc(v) if v else "—"
        text = self.T(s.uid, "tags_menu", title=dash(t.get("title")), artist=dash(t.get("artist")),
                      album=dash(t.get("album")), cover="✅" if s.cover else "—")
        T = lambda k: self.T(s.uid, k)
        rows = [[(T("b_title"), "tg:title"), (T("b_artist"), "tg:artist")], [(T("b_album"), "tg:album"), (T("b_cover"), "tg:cover")],
                [(T("b_apply"), "tg:apply")]]
        await self.say(s.uid, text, kb(rows), raw=True)

    # ------------------------------------------------------------------ اجرای عملیات
    async def do_op(self, s, op, a):
        if op == "trim":
            return await media.trim(s.path, s.dir, s.kind, s.send_kind, a["start"], a["end"])
        if op == "tovoice":
            return await media.to_voice(s.path, s.dir)
        if op == "tomp3":
            return await media.to_mp3(s.path, s.dir)
        if op == "tags":
            return await media.set_tags(s.path, s.dir, s.tags, s.cover)
        if op == "tovideo":
            return await media.audio_to_video(s.path, s.dir, a.get("image"))
        if op == "gif":
            return await media.to_gif(s.path, s.dir, config.GIF_SECONDS)
        if op == "resize":
            return await media.resize(s.path, s.dir, a["height"])
        if op == "wm":
            return await media.watermark(s.path, s.dir, a["png"], a["pos"], s.info.get("w") or 640)
        if op == "vnote":
            return await media.video_note(s.path, s.dir)
        raise MediaError("unknown op")

    async def run_op(self, s, op, **a):
        uid = s.uid
        if s.busy:
            return await self.say(uid, "busy")
        ok, src = self.db.can_use(uid)
        if not ok:
            return await self.say(uid, "no_quota", kb([[(self.T(uid, "b_buy"), "buy")]]), free=config.FREE_DAILY)
        s.busy, s.step = True, None
        st = await self.say(uid, "queued" if self.sem.locked() else "processing")
        smid = st and st.message_id
        try:
            async with self.sem:
                await self.edit(uid, smid, self.T(uid, "processing"))
                res = await self.do_op(s, op, a)
            out = res["path"]
            if os.path.getsize(out) > config.MAX_UPLOAD_MB * 1024 * 1024:
                raise BigOut()
            info = await media.probe(out)
            sk, extra = res["send_kind"], dict(res["extra"])
            extra["duration"] = int(info["duration"]) or extra.get("duration")
            if sk in ("video", "animation"):
                extra.update(width=info["w"] or None, height=info["h"] or None)
            if sk == "audio":
                extra.setdefault("title", info["tags"].get("title") or os.path.splitext(s.name)[0][:60])
                extra.setdefault("performer", info["tags"].get("artist"))
            await self.edit(uid, smid, self.T(uid, "uploading"))
            stem = os.path.splitext(s.name)[0][:60] or "file"
            fname = f"{stem}_{op}{os.path.splitext(out)[1]}"
            msg = await self.bot.send_file(sk, uid, path=out, filename=fname, **extra)
            obj = msg._d.get(SEND_FIELD[sk]) or {}
            s.path, s.send_kind, s.name = out, sk, fname
            s.kind = "audio" if sk in ("audio", "voice") else "video"
            s.file_id, s.info, s.cover = obj.get("file_id"), info, None
            s.tags = {k: info["tags"].get(k) for k in ("title", "artist", "album") if info["tags"].get(k)}
            self.db.consume(uid, src)
            self.db.log_job(uid, op, True)
            await self.delete(uid, smid)
            await self.show_menu(s, self.T(uid, "done"))
        except BigOut:
            self.db.log_job(uid, op, False)
            await self.edit(uid, smid, self.T(uid, "err_big_out", max=fmt_size(config.MAX_UPLOAD_MB * 1024 * 1024)))
        except (MediaError, TgError) as e:
            log.warning("op %s failed: %s", op, e)
            self.db.log_job(uid, op, False)
            await self.edit(uid, smid, self.T(uid, "err_process"))
        except Exception:
            log.exception("op %s crashed", op)
            self.db.log_job(uid, op, False)
            await self.edit(uid, smid, self.T(uid, "err_process"))
        finally:
            s.busy = False
            s.t = time.time()

    # ------------------------------------------------------------------ کانال و لایک
    async def set_channel(self, s, text):
        uid = s.uid
        ref = text.strip().split("/")[-1] if "t.me/" in text else text.strip()
        if not ref.startswith("@") and not ref.lstrip("-").isdigit():
            ref = "@" + ref
        if ref.lstrip("-").isdigit():
            ref = int(ref)
        try:
            chat = await self.bot.get_chat(ref)
            if chat.type != "channel":
                raise TgError("not a channel")
        except TgError:
            return await self.say(uid, "ch_notfound")
        try:
            bm = await self.bot.get_chat_member(chat.id, self.me.id)
            ok_bot = str(bm.status) == "creator" or (str(bm.status) == "administrator" and bm.can_post_messages is not False)
        except TgError:
            ok_bot = False
        if not ok_bot:
            return await self.say(uid, "ch_notadmin_bot")
        try:
            um = await self.bot.get_chat_member(chat.id, uid)
            ok_user = str(um.status) in ("creator", "administrator")
        except TgError:
            ok_user = False
        if not ok_user:
            return await self.say(uid, "ch_notadmin_user")
        self.db.set_channel(uid, chat.id, chat.title or str(ref))
        await self.say(uid, "ch_ok", ch=esc(chat.title or ref))
        if s.args.get("after") and s.path:
            s.step = "caption"
            await self.say(uid, "ask_caption", kb([[(self.T(uid, "b_nocaption"), "nocap")]]))
        else:
            s.step = None

    @staticmethod
    def like_kb(pid, n):
        return kb([[(f"👍 {n}", f"lk:{pid}")]])

    async def post_channel(self, s, caption):
        uid = s.uid
        u = self.db.user(uid) or {}
        ch = u.get("channel_id")
        s.step = None
        if not ch or not s.path:
            return await self.say(uid, "expired")
        pid = self.db.add_post(uid, ch)
        cap = esc(caption) if caption else None
        sk = s.send_kind
        try:
            if s.file_id:
                msg = await self.bot.send_file(sk, ch, file_id=s.file_id, caption=None if sk == "video_note" else cap,
                                               reply_markup=self.like_kb(pid, 0))
            else:
                msg = await self.bot.send_file(sk, ch, path=s.path, caption=None if sk == "video_note" else cap,
                                               reply_markup=self.like_kb(pid, 0))
        except TgError as e:
            log.warning("channel post failed: %s", e)
            return await self.say(uid, "ch_notadmin_bot")
        self.db.set_post_message(pid, msg.message_id)
        await self.say(uid, "posted")

    async def cb_like(self, cq, rest):
        try:
            pid = int(rest)
        except ValueError:
            return await cq.answer()
        liked, n = self.db.toggle_like(pid, cq.from_user.id)
        await cq.answer("👍" if liked else "💔")
        if cq.message:
            await tg(self.bot.edit_reply_markup, cq.message.chat.id, cq.message.message_id, self.like_kb(pid, n))

    # ------------------------------------------------------------------ پرداخت
    def plan(self, pid):
        return next((p for p in config.PLANS if p["id"] == pid), None)

    def plan_label(self, uid, p):
        if p["days"]:
            return self.T(uid, "plan_days", d=p["days"], price=p["price"])
        return self.T(uid, "plan_credits", n=p["credits"], price=p["price"])

    def card_vars(self, pid):
        p = self.plan(pid) or {"price": "?"}
        return {"price": p["price"], "card": config.CARD_NUMBER, "holder": esc(config.CARD_HOLDER)}

    async def show_plans(self, uid):
        rows = [[(self.plan_label(uid, p), f"bp:{p['id']}")] for p in config.PLANS]
        await self.say(uid, "plans_title", kb(rows))

    async def cb_plan(self, uid, pid):
        p = self.plan(pid)
        if not p:
            return
        rows = []
        if config.ENABLE_CARD:
            rows.append([(self.T(uid, "b_card"), f"pm:card:{pid}")])
        if config.ENABLE_STARS and p.get("stars"):
            rows.append([(self.T(uid, "b_stars"), f"pm:stars:{pid}")])
        await self.say(uid, "choose_method", kb(rows))

    async def cb_pay_method(self, uid, u, rest):
        method, _, pid = rest.partition(":")
        p = self.plan(pid)
        if not p:
            return
        if method == "card" and config.ENABLE_CARD:
            self.wait_receipt[uid] = pid
            return await self.say(uid, "card_info", **self.card_vars(pid))
        if method == "stars" and config.ENABLE_STARS and p.get("stars"):
            label = self.plan_label(uid, p)
            await tg(self.bot.call, "sendInvoice", chat_id=uid, title=label[:32], description=label[:255],
                     payload=f"plan:{pid}", currency="XTR", prices=[{"label": label[:32], "amount": p["stars"]}])

    async def on_receipt(self, uid, user, o):
        pid = self.wait_receipt.pop(uid, None)
        p = self.plan(pid)
        if not p:
            return
        pay = self.db.add_payment(uid, pid, "card", p["price"])
        for a in config.ADMIN_IDS:
            await tg(self.bot.send_file, "photo", a, file_id=o["file_id"],
                     caption=self.T(a, "admin_receipt", id=pay, user=f'<a href="tg://user?id={uid}">{esc(user.full_name)}</a> ({uid})',
                                    plan=self.plan_label(a, p), price=p["price"]),
                     reply_markup=kb([[(self.T(a, "b_approve"), f"pa:ok:{pay}"), (self.T(a, "b_reject"), f"pa:no:{pay}")]]))
        await self.say(uid, "receipt_sent")

    def grant(self, uid, p):
        if p["credits"]:
            self.db.add_credits(uid, p["credits"])
        if p["days"]:
            self.db.add_days(uid, p["days"])

    async def cb_approve(self, cq, rest):
        if cq.from_user.id not in config.ADMIN_IDS:
            return await cq.answer("⛔", show_alert=True)
        act, _, pid = rest.partition(":")
        pay = self.db.payment(int(pid)) if pid.isdigit() else None
        if not pay or pay["status"] != "pending":
            return await cq.answer("—", show_alert=True)
        p = self.plan(pay["plan"])
        if act == "ok" and p:
            self.grant(pay["uid"], p)
            self.db.set_payment(pay["id"], "paid")
            await self.say(pay["uid"], "pay_ok", plan=self.plan_label(pay["uid"], p))
            mark = "✅"
        else:
            self.db.set_payment(pay["id"], "rejected")
            await self.say(pay["uid"], "pay_no", support=config.SUPPORT)
            mark = "❌"
        await cq.answer(mark)
        if cq.message:
            await tg(self.bot.call, "editMessageCaption", chat_id=cq.message.chat.id, message_id=cq.message.message_id,
                     caption=f"{mark} #{pay['id']}")

    async def on_stars_paid(self, m):
        sp = m.successful_payment
        uid = m.from_user.id
        payload = str(sp.invoice_payload or "")
        p = self.plan(payload.split(":", 1)[1]) if payload.startswith("plan:") else None
        if not p:
            return
        self.grant(uid, p)
        self.db.add_payment(uid, p["id"], "stars", f"{p['stars']} XTR", "paid")
        await self.say(uid, "pay_ok", plan=self.plan_label(uid, p))
