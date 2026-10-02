# -*- coding: utf-8 -*-
"""ربات ویرایشگر موزیک و ویدیو.   اجرا:  python main.py"""
import asyncio
import logging
import os
import shutil
import sys

import config
from core import media
from core.bot import Editor
from core.db import DB
from core.tgapi import Bot, TgError, poll

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


async def main():
    if not config.BOT_TOKEN or "PUT_YOUR" in config.BOT_TOKEN:
        print("❌ توکن ربات تنظیم نشده. فایل config_local.py بساز (نمونه: config_local.example.py).")
        sys.exit(1)
    bot = Bot(config.BOT_TOKEN, config.API_BASE, config.LOCAL_API)
    try:
        me = await bot.get_me()
    except TgError as e:
        print(f"❌ اتصال به تلگرام ناموفق بود (توکن یا اینترنت را چک کن): {e}")
        sys.exit(1)
    shutil.rmtree(config.TMP_DIR, ignore_errors=True)
    os.makedirs(config.TMP_DIR, exist_ok=True)
    db = DB(config.DB_PATH)
    ed = Editor(bot, db, me)
    try:
        log.info("ffmpeg: %s", media.ffmpeg_exe())
    except media.MediaError as e:
        log.error("⚠️ %s", e)
    await bot.delete_webhook()
    asyncio.create_task(ed.janitor())
    log.info("Bot started as @%s", me.username)
    await poll(bot, ed.on_update)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code not in (0, None):
            print(e.code)
