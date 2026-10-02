# -*- coding: utf-8 -*-
"""تست سرتاسری: main.py با یک سرور Bot API جعلی (شامل دانلود/آپلود فایل). python tests/e2e.py"""
import asyncio
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LOCK = threading.Lock()
UPDATES, CALLS, FILES = [], [], {}
CNT = {"upd": 1000, "mid": 500, "fid": 0}
LEFT = {77}
WORK = tempfile.mkdtemp()


def parse_multipart(ctype, body):
    boundary = ctype.split("boundary=")[1].encode()
    fields, file = {}, None
    for part in body.split(b"--" + boundary):
        if not part.strip(b"\r\n-"):
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        data = data[:-2] if data.endswith(b"\r\n") else data
        h = head.decode("utf-8", "replace")
        name = h.split('name="')[1].split('"')[0]
        if 'filename="' in h:
            file = (name, h.split('filename="')[1].split('"')[0], data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, file


FIELD = {"sendAudio": "audio", "sendVoice": "voice", "sendVideo": "video", "sendVideoNote": "video_note",
         "sendAnimation": "animation", "sendDocument": "document", "sendPhoto": "photo"}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        out = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):   # دانلود فایل
        fid = self.path.rsplit("/", 1)[-1]
        data = FILES.get(fid)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        method = self.path.rsplit("/", 1)[-1]
        ctype = self.headers.get("Content-Type", "")
        file = None
        if ctype.startswith("multipart"):
            body, file = parse_multipart(ctype, raw)
            body = {k: (json.loads(v) if v[:1] in "{[" else v) for k, v in body.items()}
        else:
            body = json.loads(raw or b"{}")
        res = True
        if method == "getMe":
            res = {"id": 99, "is_bot": True, "username": "TestBot", "first_name": "T"}
        elif method == "getUpdates":
            time.sleep(0.1)
            with LOCK:
                res = UPDATES[:]
                UPDATES.clear()
        elif method == "getFile":
            res = {"file_id": body["file_id"], "file_path": "files/" + body["file_id"], "file_size": len(FILES.get(body["file_id"], b""))}
        elif method == "getChat":
            if body.get("chat_id") == "@testch":
                res = {"id": -100123, "type": "channel", "title": "Test Channel"}
            else:
                return self._send({"ok": False, "error_code": 400, "description": "chat not found"})
        elif method == "getChatMember":
            uid = body["user_id"]
            st = "administrator" if uid in (99, 5, 1) else ("left" if uid in LEFT else "member")
            res = {"status": st, "can_post_messages": True, "user": {"id": uid}}
        elif method in FIELD or method == "sendMessage":
            CNT["mid"] += 1
            res = {"message_id": CNT["mid"], "chat": {"id": body.get("chat_id")}}
            if method in FIELD:
                CNT["fid"] += 1
                fid = f"OUT{CNT['fid']}"
                obj = {"file_id": fid, "file_unique_id": fid}
                if file:
                    FILES[fid] = file[2]
                    with open(os.path.join(WORK, f"{fid}.bin"), "wb") as f:
                        f.write(file[2])
                    obj["file_name"] = file[1]
                else:
                    obj["file_id"] = body.get(FIELD[method], fid)
                res[FIELD[method]] = obj
        with LOCK:
            CALLS.append({"m": method, "b": body, "f": (file[1], len(file[2]), file[2]) if file else None})
        self._send({"ok": True, "result": res})


def push(**kw):
    with LOCK:
        CNT["upd"] += 1
        UPDATES.append({"update_id": CNT["upd"], **kw})


def user(i):
    return {"id": i, "is_bot": False, "first_name": f"User{i}"}


def msg(uid, text=None, **extra):
    m = {"message_id": 1, "from": user(uid), "chat": {"id": uid, "type": "private"}, "date": 1}
    if text is not None:
        m["text"] = text
    m.update(extra)
    return {"message": m}


def cb(uid, data, chat=None, mid=77):
    return {"callback_query": {"id": str(CNT["upd"]), "from": user(uid), "data": data,
                               "message": {"message_id": mid, "chat": {"id": chat or uid, "type": "private"}}}}


def mark():
    with LOCK:
        return len(CALLS)


def wait(pred, since, t=40):
    end = time.time() + t
    while time.time() < end:
        with LOCK:
            for c in CALLS[since:]:
                if pred(c):
                    return c
        time.sleep(0.05)
    return None


def texts(since):
    with LOCK:
        return [c["b"].get("text") or c["b"].get("caption") or "" for c in CALLS[since:] if c["m"] in ("sendMessage", "editMessageText")]


def has_btn(c, data):
    mk = c["b"].get("reply_markup")
    return bool(mk) and any(b.get("callback_data") == data for row in mk["inline_keyboard"] for b in row)


def rss(pid):
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmRSS"):
            return int(l.split()[1]) / 1024
    return 0


FAIL = []


def check(n, c, info=""):
    print("✅" if c else "❌", n, info)
    if not c:
        FAIL.append(n)


def say_like(c, sub):
    return c["m"] == "sendMessage" and sub in (c["b"].get("text") or "")


def upload(m, since, t=60):
    return wait(lambda c: c["m"] == m and c["f"], since, t)


def gen_media():
    from core import media
    ff = media.ffmpeg_exe()
    sh = lambda *a: subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", *a], check=True)
    sh("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "20", "-c:a", "libmp3lame", "-b:a", "128k", f"{WORK}/a.mp3")
    sh("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=330", "-t", "10",
       "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", f"{WORK}/v.mp4")
    sh("-f", "lavfi", "-i", "color=c=blue:s=300x300", "-frames:v", "1", f"{WORK}/c.png")
    for fid, p in (("IN_A", "a.mp3"), ("IN_V", "v.mp4"), ("IN_IMG", "c.png")):
        FILES[fid] = open(f"{WORK}/{p}", "rb").read()
    FILES["IN_ZIP"] = b"PK\x03\x04junk"


def audio_msg(uid, fid="IN_A", size=None):
    return msg(uid, audio={"file_id": fid, "file_name": "song.mp3", "file_size": size or len(FILES.get(fid, b"")),
                           "duration": 20, "mime_type": "audio/mpeg"})


def main():
    from core import media
    gen_media()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfgdir = os.path.join(WORK, "cfg")
    os.makedirs(cfgdir)
    open(os.path.join(cfgdir, "config_local.py"), "w").write(
        f'BOT_TOKEN="123:ABC"\nADMIN_IDS=[1]\nAPI_BASE="http://127.0.0.1:{port}"\nDB_PATH={os.path.join(WORK, "t.db")!r}\n'
        f'TMP_DIR={os.path.join(WORK, "tmp")!r}\nFREE_DAILY=3\nENABLE_STARS=True\nCARD_NUMBER="6037-1111-2222-3333"\n')
    env = dict(os.environ, PYTHONPATH=cfgdir)
    p = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(1.5)
        check("ربات بالا آمد", p.poll() is None)
        # ---- عضویت اجباری ----
        s = mark(); push(**msg(77, "/start"))
        c = wait(lambda c: c["m"] == "sendMessage" and has_btn(c, "sub:check"), s)
        urls = [b.get("url") for row in (c["b"]["reply_markup"]["inline_keyboard"] if c else []) for b in row]
        check("غیرعضو: پیام عضویت اجباری با لینک @CorvinV", c is not None and "https://t.me/CorvinV" in urls and "CorvinV" in c["b"]["text"])
        s = mark(); push(**audio_msg(77)); time.sleep(0.8)
        check("غیرعضو: فایل فرستادن هم قفل است", not any("چه کاری انجام بدم" in t for t in texts(s)) and any("CorvinV" in t for t in texts(s)))
        s = mark(); push(**cb(77, "op:trim")); time.sleep(0.8)
        check("غیرعضو: دکمه‌ها هم قفل‌اند", not any("زمان شروع" in t for t in texts(s)))
        s = mark(); push(**cb(77, "sub:check")); time.sleep(0.8)
        with LOCK:
            al = [c for c in CALLS[s:] if c["m"] == "answerCallbackQuery"]
        check("هنوز عضو نشده: «عضو نشدی»", bool(al) and al[-1]["b"].get("show_alert") is True)
        LEFT.discard(77)
        s = mark(); push(**cb(77, "sub:check"))
        check("بعد از عضویت قفل باز می‌شود", wait(lambda c: say_like(c, "ویرایشگر"), s) is not None)
        # ---- شروع و زبان ----
        s = mark(); push(**msg(5, "/start"))
        c = wait(lambda c: has_btn(c, "lang:fa:s"), s)
        check("انتخاب زبان در اولین /start", c is not None and has_btn(c, "lang:en:s") and has_btn(c, "lang:ar:s"))
        s = mark(); push(**cb(5, "lang:fa:s"))
        c = wait(lambda c: say_like(c, "ویرایشگر"), s)
        check("خوش‌آمد فارسی", c is not None and "۳" not in c["b"]["text"] and "3" in c["b"]["text"])
        # ---- ورودی صوتی و منو ----
        s = mark(); push(**audio_msg(5))
        c = wait(lambda c: say_like(c, "چه کاری انجام بدم"), s)
        check("منوی صوتی", c is not None and "song.mp3" in c["b"]["text"] and all(has_btn(c, f"op:{o}") for o in ("trim", "tovoice", "tags", "tovideo", "channel")) and not has_btn(c, "op:tomp3"))
        idle = rss(p.pid)
        # ---- برش ----
        s = mark(); push(**cb(5, "op:trim"))
        check("درخواست بازه", wait(lambda c: say_like(c, "زمان شروع و پایان"), s) is not None)
        s = mark(); push(**msg(5, "۲ ۸"))
        up = upload("sendAudio", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("برش صوت ۲ تا ۸", up is not None and abs(pr.get("duration", 0) - 6) < 0.4, f"{pr.get('duration')}")
        check("نام فایل خروجی", up is not None and up["f"][0].endswith("_trim.mp3"), str(up and up["f"][0]))
        c = wait(lambda c: say_like(c, "ادامه") or say_like(c, "انجام شد"), s)
        check("بعد از اتمام منوی ادامه می‌آید", c is not None)
        # ---- بازه نامعتبر ----
        s = mark(); push(**cb(5, "op:trim")); time.sleep(0.4); push(**msg(5, "50 60"))
        check("بازه نامعتبر رد می‌شود", wait(lambda c: say_like(c, "بازه نامعتبر"), s) is not None)
        push(**cb(5, "cancel")); time.sleep(0.3)
        # ---- مجدداً فایل را بفرست (نشست جدید) و تبدیل‌ها ----
        push(**audio_msg(5)); time.sleep(1.2)
        s = mark(); push(**cb(5, "op:tovoice"))
        up = upload("sendVoice", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("mp3 -> ویس", up is not None and up["f"][0].endswith(".ogg") and pr.get("has_audio"))
        s = mark(); push(**cb(5, "op:tomp3"))
        up = upload("sendAudio", s)
        check("ویس -> mp3", up is not None and up["f"][0].endswith(".mp3"))
        # ---- سهمیه رایگان تمام می‌شود ----
        s = mark(); push(**cb(5, "op:tags")); time.sleep(0.5)
        push(**cb(5, "tg:title")); time.sleep(0.3); push(**msg(5, "عنوان نو")); time.sleep(0.3)
        push(**cb(5, "tg:apply"))
        c = wait(lambda c: say_like(c, "اعتبارت تمام"), s)
        check("سهمیه ۳تایی رایگان تمام شد", c is not None and has_btn(c, "buy"))
        # ---- خرید کارت‌به‌کارت ----
        s = mark(); push(**msg(5, "/buy"))
        c = wait(lambda c: has_btn(c, "bp:c10"), s)
        check("لیست بسته‌ها", c is not None and has_btn(c, "bp:d30"))
        s = mark(); push(**cb(5, "bp:c10"))
        c = wait(lambda c: has_btn(c, "pm:card:c10"), s)
        check("روش‌های پرداخت (کارت و استارز)", c is not None and has_btn(c, "pm:stars:c10"))
        s = mark(); push(**cb(5, "pm:card:c10"))
        c = wait(lambda c: say_like(c, "6037-1111-2222-3333"), s)
        check("اطلاعات کارت", c is not None)
        s = mark(); push(**msg(5, photo=[{"file_id": "IN_IMG", "file_size": 10}]))
        c = wait(lambda c: c["m"] == "sendPhoto" and c["b"]["chat_id"] == 1, s)
        check("رسید برای ادمین فرستاده شد با دکمه تأیید", c is not None and has_btn(c, "pa:ok:1"))
        s = mark(); push(**cb(1, "pa:ok:1", mid=900))
        c = wait(lambda c: say_like(c, "پرداخت تأیید شد") and c["b"]["chat_id"] == 5, s)
        check("تأیید ادمین، پیام به کاربر", c is not None)
        s = mark(); push(**msg(5, "/me"))
        c = wait(lambda c: say_like(c, "حساب من"), s)
        check("اعتبار ۱۰ اضافه شد", c is not None and "10" in c["b"]["text"] and "0/3" in c["b"]["text"], c and c["b"]["text"].replace("\n", " | "))
        s = mark(); push(**cb(1, "pa:ok:1", mid=900)); time.sleep(0.6)
        check("تأیید دوباره اثری ندارد", not any("پرداخت تأیید شد" in t for t in texts(s)))
        # ---- تگ + کاور (فارسی) با اعتبار ----
        s = mark(); push(**cb(5, "tg:cover")); time.sleep(0.4); push(**msg(5, photo=[{"file_id": "IN_IMG", "file_size": 10}]))
        c = wait(lambda c: say_like(c, "ویرایش تگ"), s)
        check("کاور ثبت شد", c is not None and "✅" in c["b"]["text"])
        s = mark(); push(**cb(5, "tg:apply"))
        up = upload("sendAudio", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("تگ فارسی + کاور اعمال شد", up is not None and pr.get("tags", {}).get("title") == "عنوان نو" and pr.get("cover"), str(pr.get("tags")))
        check("title/performer در ارسال", up is not None and up["b"].get("title") == "عنوان نو")
        # ---- استارز ----
        s = mark(); push(**cb(5, "pm:stars:d30"))
        c = wait(lambda c: c["m"] == "sendInvoice", s)
        check("فاکتور استارز (XTR)", c is not None and c["b"]["currency"] == "XTR" and c["b"]["prices"][0]["amount"] == 300 and c["b"]["payload"] == "plan:d30")
        s = mark(); push(pre_checkout_query={"id": "pq1", "from": user(5), "currency": "XTR", "total_amount": 300, "invoice_payload": "plan:d30"})
        c = wait(lambda c: c["m"] == "answerPreCheckoutQuery", s)
        check("pre_checkout تأیید شد", c is not None and c["b"]["ok"] is True)
        s = mark(); push(**msg(5, successful_payment={"currency": "XTR", "total_amount": 300, "invoice_payload": "plan:d30", "telegram_payment_charge_id": "x"}))
        check("پرداخت استارز اشتراک داد", wait(lambda c: say_like(c, "پرداخت تأیید شد"), s) is not None)
        s = mark(); push(**msg(5, "/me"))
        c = wait(lambda c: say_like(c, "حساب من"), s)
        check("اشتراک نامحدود فعال", c is not None and "—" not in c["b"]["text"].split("نامحدود تا:")[1], c and c["b"]["text"].replace("\n", " | "))
        # ---- ویدیو ----
        s = mark(); push(**msg(5, video={"file_id": "IN_V", "file_name": "clip.mp4", "file_size": len(FILES["IN_V"]), "duration": 10, "width": 640, "height": 360}))
        c = wait(lambda c: say_like(c, "چه کاری انجام بدم"), s)
        check("منوی ویدیو", c is not None and all(has_btn(c, f"op:{o}") for o in ("trim", "tomp3", "gif", "resize", "wm", "vnote", "channel")) and "640×360" in c["b"]["text"])
        s = mark(); push(**cb(5, "op:gif"))
        up = upload("sendAnimation", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("ویدیو -> GIF (بی‌صدا)", up is not None and pr.get("has_video") and not pr.get("has_audio"))
        push(**msg(5, video={"file_id": "IN_V", "file_name": "clip.mp4", "file_size": len(FILES["IN_V"]), "duration": 10})); time.sleep(1.2)
        s = mark(); push(**cb(5, "op:resize"))
        c = wait(lambda c: has_btn(c, "rs:240"), s)
        check("گزینه‌های تغییر اندازه", c is not None and has_btn(c, "rs:720") and not has_btn(c, "rs:1080"))
        s = mark(); push(**cb(5, "rs:240"))
        up = upload("sendVideo", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("تغییر اندازه ۲۴۰p", up is not None and pr.get("h") == 240 and pr.get("has_audio"))
        push(**msg(5, video={"file_id": "IN_V", "file_name": "clip.mp4", "file_size": len(FILES["IN_V"]), "duration": 10})); time.sleep(1.2)
        s = mark(); push(**cb(5, "op:wm")); time.sleep(0.4); push(**cb(5, "wm:text")); time.sleep(0.4)
        push(**msg(5, "ربات موزیک @botgostar")); time.sleep(0.8)
        c = wait(lambda c: has_btn(c, "pos:br"), s)
        check("انتخاب جای واترمارک", c is not None)
        s = mark(); push(**cb(5, "pos:br"))
        up = upload("sendVideo", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("واترمارک متنی فارسی", up is not None and (pr.get("w"), pr.get("h")) == (640, 360) and pr.get("has_audio"))
        if up:
            subprocess.run([media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", os.path.join(WORK, f"OUT{CNT['fid']}.bin"), "-frames:v", "1", "/tmp/e2e_wm_frame.png"])
        s = mark(); push(**cb(5, "op:vnote"))
        up = upload("sendVideoNote", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("ویدیو مسیج مربعی", up is not None and (pr.get("w"), pr.get("h")) == (480, 480) and str(up["b"].get("length")) == "480")
        push(**msg(5, video={"file_id": "IN_V", "file_name": "clip.mp4", "file_size": len(FILES["IN_V"]), "duration": 10})); time.sleep(1.2)
        s = mark(); push(**cb(5, "op:tomp3"))
        up = upload("sendAudio", s)
        check("ویدیو -> mp3", up is not None and up["f"][0].endswith(".mp3"))
        # ---- mp3 -> ویدیو ----
        push(**audio_msg(5)); time.sleep(1.2)
        s = mark(); push(**cb(5, "op:tovideo")); time.sleep(0.4); push(**cb(5, "bg:img")); time.sleep(0.4)
        push(**msg(5, photo=[{"file_id": "IN_IMG", "file_size": 10}]))
        up = upload("sendVideo", s)
        pr = asyncio.run(media.probe(os.path.join(WORK, f"OUT{CNT['fid']}.bin"))) if up else {}
        check("mp3 -> ویدیو با تصویر", up is not None and pr.get("has_video") and pr.get("has_audio"))
        # ---- کانال و لایک ----
        s = mark(); push(**msg(6, "/setchannel")); time.sleep(0.4); push(**msg(6, "@testch"))
        check("غیرادمین کانال را ثبت نمی‌کند", wait(lambda c: say_like(c, "ادمین این کانال نیستی"), s) is not None)
        s = mark(); push(**msg(5, "/setchannel")); time.sleep(0.4); push(**msg(5, "@testch"))
        check("ثبت کانال", wait(lambda c: say_like(c, "کانال Test Channel ثبت شد"), s) is not None)
        s = mark(); push(**msg(5, "@nochannel")); push(**msg(5, "/setchannel")); time.sleep(0.3); push(**msg(5, "@nochannel"))
        check("کانال ناموجود", wait(lambda c: say_like(c, "کانال پیدا نشد"), s) is not None)
        push(**audio_msg(5)); time.sleep(1.2)
        s = mark(); push(**cb(5, "op:channel"))
        check("درخواست کپشن", wait(lambda c: say_like(c, "کپشن پست"), s) is not None)
        s = mark(); push(**msg(5, "پست تست"))
        c = wait(lambda c: c["m"] == "sendAudio" and c["b"]["chat_id"] == -100123, s)
        check("ارسال به کانال با file_id (بدون آپلود مجدد) و دکمه لایک", c is not None and c["f"] is None and has_btn(c, "lk:1") and "پست تست" in c["b"]["caption"])
        s = mark(); push(**cb(7, "lk:1", chat=-100123, mid=950))
        c = wait(lambda c: c["m"] == "editMessageReplyMarkup", s)
        check("لایک اول", c is not None and c["b"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "👍 1")
        s = mark(); push(**cb(8, "lk:1", chat=-100123, mid=950))
        c = wait(lambda c: c["m"] == "editMessageReplyMarkup", s)
        check("لایک دوم از کاربر دیگر", c is not None and c["b"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "👍 2")
        s = mark(); push(**cb(7, "lk:1", chat=-100123, mid=950))
        c = wait(lambda c: c["m"] == "editMessageReplyMarkup", s)
        check("برداشتن لایک", c is not None and c["b"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "👍 1")
        # ---- محدودیت‌ها ----
        s = mark(); push(**audio_msg(9, "IN_A", size=30 * 1024 * 1024))
        check("فایل بزرگ‌تر از ۲۰MB رد می‌شود", wait(lambda c: say_like(c, "بیشتر است"), s) is not None)
        with LOCK:
            asked = [c for c in CALLS[s:] if c["m"] == "getFile"]
        check("برای فایل بزرگ دانلود شروع نشد", not asked)
        s = mark(); push(**msg(9, document={"file_id": "IN_ZIP", "file_name": "x.zip", "mime_type": "application/zip", "file_size": 10}))
        check("نوع فایل پشتیبانی‌نشده", wait(lambda c: say_like(c, "پشتیبانی نمی‌شود"), s) is not None)
        s = mark(); push(**msg(9, "سلام"))
        check("متن بدون فایل", wait(lambda c: say_like(c, "اول یک فایل"), s) is not None)
        s = mark(); push(**msg(9, document={"file_id": "IN_ZIP", "file_name": "fake.mp3", "mime_type": "audio/mpeg", "file_size": 10}))
        check("فایل خراب (پسوند mp3 ولی محتوای نامعتبر)", wait(lambda c: say_like(c, "پشتیبانی نمی‌شود"), s) is not None)
        # ---- ادمین و بن ----
        s = mark(); push(**msg(1, "/admin"))
        c = wait(lambda c: say_like(c, "Admin"), s)
        check("پنل ادمین", c is not None and "jobs" in c["b"]["text"])
        s = mark(); push(**msg(5, "/admin")); time.sleep(0.6)
        check("کاربر عادی به ادمین دسترسی ندارد", not any("Admin" in t for t in texts(s)))
        push(**msg(1, "/ban 9")); time.sleep(0.5)
        s = mark(); push(**msg(9, "/start")); time.sleep(0.8)
        check("کاربر بن‌شده نادیده گرفته می‌شود", not texts(s))
        s = mark(); push(**msg(1, "/addcredit 9 5")); push(**msg(1, "/unban 9")); time.sleep(0.6)
        s = mark(); push(**msg(9, "/me"))
        check("آنبن + افزودن اعتبار", wait(lambda c: say_like(c, "حساب من") and "5" in c["b"]["text"], s) is not None)
        # ---- انگلیسی ----
        s = mark(); push(**msg(5, "/lang")); time.sleep(0.5); push(**cb(5, "lang:en:x"))
        check("تغییر زبان به انگلیسی", wait(lambda c: say_like(c, "Language changed"), s) is not None)
        s = mark(); push(**audio_msg(5))
        c = wait(lambda c: say_like(c, "What should I do?"), s)
        check("منوی انگلیسی", c is not None and any(b.get("text") == "✂️ Trim" for row in c["b"]["reply_markup"]["inline_keyboard"] for b in row))
        # ---- حافظه ----
        busy = rss(p.pid)
        print(f"\nRAM ربات: idle={idle:.1f}MB  بعد از همه‌ی عملیات={busy:.1f}MB  (ffmpeg پروسه‌ی جدا است)")
        check("رم پروسه‌ی ربات زیر ۵۰ مگابایت", busy < 50)
        check("پروسه زنده است", p.poll() is None)
        tmpdir = os.path.join(WORK, "tmp")
        check("فایل موقت برای نشست‌ها ساخته شده و قابل پاک‌سازی است", os.path.isdir(tmpdir))
    finally:
        p.terminate()
        try:
            out = p.communicate(timeout=3)[0]
        except Exception:
            out = ""
        if "Traceback" in out:
            print("\n--- خطاهای لاگ ---\n" + out[-2500:])
            FAIL.append("traceback in log")
    print("\nFAILED:" if FAIL else "\nALL OK", FAIL or "")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
