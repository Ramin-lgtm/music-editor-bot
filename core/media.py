# -*- coding: utf-8 -*-
"""عملیات صوت/تصویر با ffmpeg (کم‌مصرف: یک رشته، پریست ultrafast، بدون lookahead)."""
import asyncio
import os
import re
import shutil

import config
from . import rtl

_EXE = None
LOW = ["-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1"]
X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-pix_fmt", "yuv420p",
        "-x264-params", "rc-lookahead=0:ref=1:bframes=0:sync-lookahead=0:threads=1:lookahead-threads=0"]
POS = {
    "tl": "12:12", "tc": "(main_w-overlay_w)/2:12", "tr": "main_w-overlay_w-12:12",
    "ml": "12:(main_h-overlay_h)/2", "mc": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
    "mr": "main_w-overlay_w-12:(main_h-overlay_h)/2",
    "bl": "12:main_h-overlay_h-12", "bc": "(main_w-overlay_w)/2:main_h-overlay_h-12",
    "br": "main_w-overlay_w-12:main_h-overlay_h-12",
}


class MediaError(Exception):
    pass


def ffmpeg_exe():
    global _EXE
    if _EXE:
        return _EXE
    cand = config.FFMPEG or shutil.which("ffmpeg")
    if not cand:
        try:
            import imageio_ffmpeg
            cand = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa
            cand = None
    if not cand:
        raise MediaError("ffmpeg پیدا نشد (imageio-ffmpeg را نصب کن یا FFMPEG را در config بگذار).")
    try:
        if not os.access(cand, os.X_OK):
            os.chmod(cand, 0o755)
    except OSError:
        pass
    _EXE = cand
    return cand


async def _exec(args, timeout):
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe(), "-hide_banner", "-nostdin", *args,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaError("timeout")
    except asyncio.CancelledError:
        proc.kill()
        raise
    return proc.returncode, err.decode("utf-8", "replace")


async def run(args):
    rc, err = await _exec(["-loglevel", "error", "-y", *args], config.JOB_TIMEOUT)
    if rc != 0:
        raise MediaError(err.strip()[-600:] or f"ffmpeg rc={rc}")


async def probe(path):
    """اطلاعات فایل را با تحلیل خروجی ffmpeg -i می‌خواند (بدون ffprobe)."""
    rc, err = await _exec(["-i", path], 60)
    info = {"duration": 0.0, "has_video": False, "has_audio": False, "w": 0, "h": 0, "tags": {}, "cover": False}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    head = err.split("  Duration:")[0] if "  Duration:" in err else ""
    for ln in head.splitlines():
        t = re.match(r"^\s{4}(\w+)\s*:\s*(.*)$", ln)
        if t:
            info["tags"][t.group(1).lower()] = t.group(2).strip()
    for ln in err.splitlines():
        if "Stream #" not in ln:
            continue
        if "Audio:" in ln:
            info["has_audio"] = True
        elif "Video:" in ln:
            if "attached pic" in ln:
                info["cover"] = True
                continue
            info["has_video"] = True
            d = re.search(r"[, ](\d{2,5})x(\d{2,5})[, \[]", ln)
            if d:
                info["w"], info["h"] = int(d.group(1)), int(d.group(2))
    return info


def outpath(d, base, ext):
    n = 1
    while True:
        p = os.path.join(d, f"{base}_{n}{ext}")
        if not os.path.exists(p):
            return p
        n += 1


def _res(path, send_kind, **extra):
    return {"path": path, "send_kind": send_kind, "extra": extra}


# ------------------------- صوت -------------------------
async def trim(src, d, kind, send_kind, start, end, tags=None):
    dur = max(0.1, end - start)
    if kind == "audio":
        ext = ".ogg" if send_kind == "voice" else (os.path.splitext(src)[1] or ".mp3")
        out = outpath(d, "trim", ext)
        await run(["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}", "-c", "copy", out])
        return _res(out, "voice" if send_kind == "voice" else "audio", duration=int(dur))
    out = outpath(d, "trim", ".mp4")
    await run(["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}", *LOW, *X264, "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out])
    return _res(out, "video", duration=int(dur), supports_streaming=True)


async def to_voice(src, d):
    out = outpath(d, "voice", ".ogg")
    await run(["-i", src, "-vn", "-map_metadata", "-1", *LOW, "-c:a", "libopus", "-b:a", "32k", "-ar", "48000",
               "-ac", "1", "-application", "voip", out])
    return _res(out, "voice")


async def to_mp3(src, d):
    out = outpath(d, "audio", ".mp3")
    await run(["-i", src, "-vn", "-map_metadata", "0", *LOW, "-c:a", "libmp3lame", "-b:a", "192k", out])
    return _res(out, "audio")


async def set_tags(src, d, tags, cover=None):
    meta = []
    for k in ("title", "artist", "album"):
        if tags.get(k) is not None:
            meta += ["-metadata", f"{k}={tags[k]}"]
    is_mp3 = src.lower().endswith(".mp3")
    out = outpath(d, "tagged", ".mp3")
    args = ["-i", src]
    if cover:
        args += ["-i", cover, "-map", "0:a", "-map", "1:v"]
        args += (["-c", "copy"] if is_mp3 else ["-c:a", "libmp3lame", "-b:a", "192k", "-c:v", "copy"])
        args += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    elif is_mp3:
        args += ["-map", "0", "-c", "copy"]
    else:
        args += ["-map", "0:a", "-c:a", "libmp3lame", "-b:a", "192k"]
    await run([*args, "-id3v2_version", "3", *meta, out])
    return _res(out, "audio", title=tags.get("title"), performer=tags.get("artist"))


async def audio_to_video(src, d, image=None):
    out = outpath(d, "video", ".mp4")
    if image:
        pre = ["-loop", "1", "-framerate", "2", "-i", image, "-i", src, "-vf",
               "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=black"]
    else:
        pre = ["-f", "lavfi", "-i", "color=c=black:s=640x360:r=2", "-i", src]
    await run([*pre, *LOW, *X264, "-tune", "stillimage", "-crf", "30", "-c:a", "aac", "-b:a", "128k",
               "-shortest", "-movflags", "+faststart", out])
    return _res(out, "video", width=640, height=360, supports_streaming=True)


# ------------------------- ویدیو -------------------------
async def video_to_mp3(src, d):
    return await to_mp3(src, d)


async def to_gif(src, d, seconds=15):
    out = outpath(d, "gif", ".mp4")
    await run(["-i", src, "-t", str(seconds), "-an", *LOW, "-vf", "fps=15,scale='min(480,iw)':-2:flags=bicubic",
               *X264, "-crf", "28", "-movflags", "+faststart", out])
    return _res(out, "animation")


async def resize(src, d, height):
    out = outpath(d, f"{height}p", ".mp4")
    await run(["-i", src, *LOW, "-vf", f"scale=-2:{height}", *X264, "-crf", "26", "-c:a", "aac", "-b:a", "96k",
               "-movflags", "+faststart", out])
    return _res(out, "video", supports_streaming=True)


async def watermark(src, d, png, pos, video_w):
    wm_w = max(48, int(max(video_w, 160) * 0.24) // 2 * 2)
    out = outpath(d, "wm", ".mp4")
    fc = (f"[1:v]scale={wm_w}:-1,format=rgba,colorchannelmixer=aa=0.9[wm];"
          f"[0:v][wm]overlay={POS.get(pos, POS['br'])},format=yuv420p[v]")
    await run(["-i", src, "-i", png, *LOW, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-crf", "24",
               "-x264-params", "rc-lookahead=0:ref=1:bframes=0:sync-lookahead=0:threads=1:lookahead-threads=0",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out])
    return _res(out, "video", supports_streaming=True)


async def video_note(src, d):
    out = outpath(d, "note", ".mp4")
    await run(["-i", src, "-t", "60", *LOW, "-vf", "crop='min(iw,ih)':'min(iw,ih)',scale=480:480", *X264,
               "-crf", "25", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", out])
    return _res(out, "video_note", length=480)


def render_text(text, path, size=64):
    return rtl.render_text_png(text, path, config.FONT_PATH, size=size)
