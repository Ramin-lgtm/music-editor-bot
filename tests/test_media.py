# -*- coding: utf-8 -*-
"""تست واقعی عملیات ffmpeg روی فایل‌های ساخته‌شده.   python tests/test_media.py"""
import asyncio
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import media  # noqa: E402

FAIL = []


def check(n, c, info=""):
    print("✅" if c else "❌", n, info)
    if not c:
        FAIL.append(n)


def gen(d):
    ff = media.ffmpeg_exe()
    sh = lambda *a: subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", *a], check=True)
    sh("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "20", "-c:a", "libmp3lame", "-b:a", "128k",
       "-metadata", "title=Old", f"{d}/a.mp3")
    sh("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=330", "-t", "10",
       "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", f"{d}/v.mp4")
    sh("-f", "lavfi", "-i", "color=c=red:s=300x300", "-frames:v", "1", f"{d}/cover.png")
    return f"{d}/a.mp3", f"{d}/v.mp4", f"{d}/cover.png"


async def main():
    d = tempfile.mkdtemp()
    a, v, cover = gen(d)
    pa, pv = await media.probe(a), await media.probe(v)
    check("probe audio", abs(pa["duration"] - 20) < 0.5 and pa["has_audio"] and not pa["has_video"] and pa["tags"].get("title") == "Old", str(pa))
    check("probe video", pv["has_video"] and (pv["w"], pv["h"]) == (1280, 720) and pv["has_audio"], str(pv))
    r = await media.trim(a, d, "audio", "audio", 5, 12)
    p = await media.probe(r["path"])
    check("trim audio", abs(p["duration"] - 7) < 0.3 and r["send_kind"] == "audio", f"{p['duration']:.2f}")
    r = await media.trim(v, d, "video", "video", 2, 6)
    p = await media.probe(r["path"])
    check("trim video (دقیق)", abs(p["duration"] - 4) < 0.4 and p["has_video"] and p["has_audio"], f"{p['duration']:.2f}")
    r = await media.to_voice(a, d)
    p = await media.probe(r["path"])
    check("mp3 -> voice (opus ogg)", r["path"].endswith(".ogg") and p["has_audio"] and r["send_kind"] == "voice")
    ogg = r["path"]
    r = await media.to_mp3(ogg, d)
    check("voice -> mp3", (await media.probe(r["path"]))["has_audio"] and r["path"].endswith(".mp3"))
    r = await media.video_to_mp3(v, d)
    p = await media.probe(r["path"])
    check("video -> mp3", abs(p["duration"] - 10) < 0.5 and not p["has_video"])
    r = await media.set_tags(a, d, {"title": "عنوان تست", "artist": "هنرمند", "album": "Album"}, cover)
    p = await media.probe(r["path"])
    check("tags + cover (فارسی)", p["tags"].get("title") == "عنوان تست" and p["tags"].get("artist") == "هنرمند" and p["cover"], str(p["tags"]) + str(p["cover"]))
    r = await media.set_tags(a, d, {"title": "NoCover"})
    check("tags بدون کاور", (await media.probe(r["path"]))["tags"].get("title") == "NoCover")
    r = await media.set_tags(ogg, d, {"title": "FromOgg"})
    check("tags روی فرمت غیر mp3 (تبدیل به mp3)", r["path"].endswith(".mp3") and (await media.probe(r["path"]))["tags"].get("title") == "FromOgg")
    r = await media.audio_to_video(a, d, cover)
    p = await media.probe(r["path"])
    check("mp3 -> video با تصویر", p["has_video"] and p["has_audio"] and abs(p["duration"] - 20) < 1 and (p["w"], p["h"]) == (640, 360), str((p["w"], p["h"], p["duration"])))
    r = await media.audio_to_video(a, d, None)
    check("mp3 -> video پس‌زمینه مشکی", (await media.probe(r["path"]))["has_video"])
    r = await media.to_gif(v, d, 4)
    p = await media.probe(r["path"])
    check("video -> gif (mp4 بی‌صدا)", p["has_video"] and not p["has_audio"] and p["duration"] <= 4.5 and r["send_kind"] == "animation", f"{p['duration']:.1f}")
    for h in (240, 480):
        r = await media.resize(v, d, h)
        p = await media.probe(r["path"])
        check(f"resize {h}p", p["h"] == h and p["w"] % 2 == 0 and p["has_audio"], f"{p['w']}x{p['h']}")
    png = os.path.join(d, "wm.png")
    media.render_text("ربات موزیک @botgostar", png)
    for pos in ("tl", "mc", "br"):
        r = await media.watermark(v, d, png, pos, pv["w"])
        p = await media.probe(r["path"])
        check(f"watermark متن {pos}", p["has_video"] and p["has_audio"] and (p["w"], p["h"]) == (1280, 720))
    r = await media.watermark(v, d, cover, "tr", pv["w"])
    check("watermark تصویر", (await media.probe(r["path"]))["has_video"])
    r = await media.video_note(v, d)
    p = await media.probe(r["path"])
    check("video note مربعی ۴۸۰", (p["w"], p["h"]) == (480, 480) and r["send_kind"] == "video_note" and r["extra"]["length"] == 480)
    # خطا: فایل خراب
    bad = os.path.join(d, "bad.mp3")
    open(bad, "wb").write(b"not media at all")
    try:
        await media.to_mp3(bad, d)
        check("فایل خراب خطا می‌دهد", False)
    except media.MediaError:
        check("فایل خراب خطا می‌دهد", True)
    # فریم واترمارک را برای بازبینی دستی ذخیره کن
    subprocess.run([media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", (await media.watermark(v, d, png, "bc", pv["w"]))["path"], "-frames:v", "1", "/tmp/wm_frame.png"])
    print("\nFAILED:" if FAIL else "\nALL OK", FAIL or "")
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
