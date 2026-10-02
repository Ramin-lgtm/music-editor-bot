# -*- coding: utf-8 -*-
"""کلاینت سبک Bot API فقط با کتابخانه‌ی استاندارد (دانلود/آپلود استریمی؛ فایل هرگز کامل وارد رَم نمی‌شود)."""
import asyncio
import http.client
import json
import logging
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid

log = logging.getLogger("tgapi")

SEND = {  # kind -> (method, field)
    "audio": ("sendAudio", "audio"), "voice": ("sendVoice", "voice"), "video": ("sendVideo", "video"),
    "video_note": ("sendVideoNote", "video_note"), "animation": ("sendAnimation", "animation"),
    "document": ("sendDocument", "document"), "photo": ("sendPhoto", "photo"),
}


class TgError(Exception):
    def __init__(self, description, code=0, retry_after=None):
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


def wrap(v):
    if isinstance(v, dict):
        return Obj(v)
    if isinstance(v, list):
        return [wrap(x) for x in v]
    return v


class Obj:
    """دسترسی attribute به دیکشنری‌های تلگرام؛ فیلد ناموجود => None."""

    def __init__(self, d):
        self.__dict__["_d"] = d

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        d = self.__dict__["_d"]
        if k == "full_name":
            name = ((d.get("first_name") or "") + " " + (d.get("last_name") or "")).strip()
            return name or d.get("title") or "User"
        if k == "from_user":
            k = "from"
        return wrap(d.get(k))


class CQ(Obj):
    def __init__(self, d, bot):
        super().__init__(d)
        self.__dict__["_bot"] = bot

    async def answer(self, text=None, show_alert=False, **kw):
        try:
            await self._bot.call("answerCallbackQuery", callback_query_id=self.id,
                                 text=text, show_alert=True if show_alert else None)
        except Exception as e:  # noqa
            log.debug("answerCallbackQuery: %s", e)


def _fieldval(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


class Bot:
    def __init__(self, token, base="https://api.telegram.org", local=False):
        self.token = token
        self.base = base.rstrip("/")
        self.local = local
        self.url = f"{self.base}/bot{token}/"

    # ---------- JSON ----------
    def _req(self, method, payload, timeout):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(self.url + method, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except Exception:  # noqa
                raise TgError(f"HTTP {e.code}", e.code)
        except (urllib.error.URLError, OSError) as e:
            raise TgError(f"network: {e}", -1)
        return self._result(body)

    @staticmethod
    def _result(body):
        if not body.get("ok"):
            p = body.get("parameters") or {}
            raise TgError(body.get("description", "error"), body.get("error_code", 0), p.get("retry_after"))
        return body["result"]

    async def call(self, method, _t=30, **params):
        params = {k: v for k, v in params.items() if v is not None}
        return wrap(await asyncio.to_thread(self._req, method, params, _t))

    # ---------- پیام‌ها ----------
    async def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        return await self.call("sendMessage", chat_id=chat_id, text=text, reply_markup=reply_markup,
                               parse_mode=parse_mode, link_preview_options={"is_disabled": True})

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, parse_mode="HTML"):
        return await self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                               reply_markup=reply_markup, parse_mode=parse_mode,
                               link_preview_options={"is_disabled": True})

    async def edit_reply_markup(self, chat_id, message_id, reply_markup):
        return await self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                               reply_markup=reply_markup)

    async def delete_message(self, chat_id, message_id):
        return await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)

    async def copy_message(self, chat_id, from_chat_id, message_id):
        return await self.call("copyMessage", chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)

    async def get_chat_member(self, chat_id, user_id):
        return await self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    async def get_chat(self, chat_id):
        return await self.call("getChat", chat_id=chat_id)

    async def get_me(self):
        return await self.call("getMe")

    async def delete_webhook(self):
        return await self.call("deleteWebhook", drop_pending_updates=True)

    # ---------- فایل: دانلود استریمی ----------
    async def get_file(self, file_id):
        return await self.call("getFile", file_id=file_id)

    def _download(self, file_path, dest, max_bytes):
        if self.local and os.path.isabs(file_path) and os.path.exists(file_path):
            shutil.copyfile(file_path, dest)
            return os.path.getsize(dest)
        url = f"{self.base}/file/bot{self.token}/{file_path}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
                n = 0
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    n += len(chunk)
                    if max_bytes and n > max_bytes:
                        raise TgError("file too big", 413)
                    f.write(chunk)
                return n
        except urllib.error.HTTPError as e:
            raise TgError(f"download HTTP {e.code}", e.code)
        except (urllib.error.URLError, OSError) as e:
            raise TgError(f"download network: {e}", -1)

    async def download(self, file_path, dest, max_bytes=None):
        return await asyncio.to_thread(self._download, file_path, dest, max_bytes)

    # ---------- فایل: آپلود استریمی (multipart) ----------
    def _upload(self, method, fields, field, path, filename, timeout):
        b = uuid.uuid4().hex
        parts = b"".join(
            (f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{_fieldval(v)}\r\n').encode()
            for k, v in fields.items() if v is not None)
        fn = (filename or os.path.basename(path)).replace('"', "").replace("\r", "").replace("\n", "")
        head = (f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{fn}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode()
        tail = f"\r\n--{b}--\r\n".encode()
        size = os.path.getsize(path)
        u = urllib.parse.urlparse(self.url + method)
        Conn = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = Conn(u.hostname, u.port, timeout=timeout)
        try:
            conn.putrequest("POST", u.path)
            conn.putheader("Content-Type", f"multipart/form-data; boundary={b}")
            conn.putheader("Content-Length", str(len(parts) + len(head) + size + len(tail)))
            conn.endheaders()
            conn.send(parts)
            conn.send(head)
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    conn.send(chunk)
            conn.send(tail)
            resp = conn.getresponse()
            raw = resp.read()
        except OSError as e:
            raise TgError(f"upload network: {e}", -1)
        finally:
            conn.close()
        try:
            body = json.loads(raw)
        except ValueError:
            raise TgError(f"upload HTTP {resp.status}", resp.status)
        return self._result(body)

    async def send_file(self, kind, chat_id, path=None, file_id=None, filename=None, caption=None,
                        reply_markup=None, **extra):
        """ارسال فایل با مسیر محلی (آپلود استریمی) یا file_id (بدون آپلود)."""
        method, field = SEND[kind]
        fields = {"chat_id": chat_id, "reply_markup": reply_markup, "parse_mode": "HTML" if caption else None,
                  "caption": caption}
        fields.update({k: v for k, v in extra.items() if v is not None})
        if file_id:
            fields[field] = file_id
            return await self.call(method, _t=120, **fields)
        return wrap(await asyncio.to_thread(self._upload, method, fields, field, path, filename, 3600))

    # ---------- پرداخت ----------
    async def answer_precheckout(self, qid, ok=True, error=None):
        return await self.call("answerPreCheckoutQuery", pre_checkout_query_id=qid, ok=ok, error_message=error)


async def poll(bot, handler):
    """long polling؛ هر آپدیت در یک task جدا پردازش می‌شود."""
    offset = None
    delay = 1
    tasks = set()

    async def run(u):
        try:
            await handler(u)
        except Exception:
            log.exception("update handler crashed")

    while True:
        try:
            ups = await bot.call("getUpdates", _t=45, offset=offset, timeout=30,
                                 allowed_updates=["message", "callback_query", "pre_checkout_query"])
            delay = 1
        except TgError as e:
            if e.code == 401:
                raise SystemExit("❌ توکن ربات نامعتبر است.")
            if e.code == 409:
                log.error("یک نمونه‌ی دیگر از همین ربات در حال اجراست (409). ۵ ثانیه صبر…")
                await asyncio.sleep(5)
            else:
                log.warning("getUpdates failed: %s", e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
            continue
        for u in ups:
            offset = u.update_id + 1
            t = asyncio.create_task(run(u))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
