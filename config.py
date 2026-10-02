# -*- coding: utf-8 -*-
"""تنظیمات ربات. مقدارهای شخصی (توکن و ...) را در فایل config_local.py بگذار تا وارد گیت‌هاب نشود."""
import os


def _ids(s):
    return [int(x) for x in str(s).replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()]


BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", "")) or [123456789]

# ---- اتصال به تلگرام ----
API_BASE = os.getenv("TG_API_BASE", "https://api.telegram.org")
# سرور رسمی: دانلود تا ۲۰MB و آپلود تا ۵۰MB. برای فایل تا ۲GB باید سرور محلی telegram-bot-api راه بیندازی:
LOCAL_API = False
MAX_DOWNLOAD_MB = 20        # با LOCAL_API می‌تواند 1000 یا 2000 باشد
MAX_UPLOAD_MB = 50          # با LOCAL_API می‌تواند 2000 باشد

# ---- منابع (برای رَم کم) ----
MAX_JOBS = 1                # تعداد هم‌زمان ffmpeg
JOB_TIMEOUT = 1800          # ثانیه
MAX_HEIGHT = 720            # بزرگ‌ترین گزینه‌ی تغییر اندازه
GIF_SECONDS = 15
FFMPEG = os.getenv("FFMPEG", "")      # خالی = خودکار (ffmpeg سیستم یا imageio-ffmpeg)

# ---- مسیرها ----
TMP_DIR = os.getenv("TMP_DIR", "tmp")
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "DejaVuSans-Bold.ttf")
SESSION_TTL = 1800          # ثانیه

# ---- کاربران و پرداخت ----
DEFAULT_LANG = "fa"
FREE_DAILY = int(os.getenv("FREE_DAILY", "3"))   # عملیات رایگان روزانه
SUPPORT = "@your_support"
CHANNEL_LINK = "https://t.me/your_channel"

FORCE_JOIN = False          # عضویت اجباری در کانال
CHANNEL_USERNAME = "@your_channel"

ENABLE_CARD = True
CARD_NUMBER = "6037-0000-0000-0000"
CARD_HOLDER = "نام صاحب کارت"
ENABLE_STARS = False        # پرداخت با Telegram Stars

# هر بسته: id, credits (تعداد عملیات), days (اشتراک نامحدود), price (متن نمایشی), stars
PLANS = [
    {"id": "c10", "credits": 10, "days": 0, "price": "20,000 تومان", "stars": 40},
    {"id": "c50", "credits": 50, "days": 0, "price": "80,000 تومان", "stars": 150},
    {"id": "d30", "credits": 0, "days": 30, "price": "150,000 تومان", "stars": 300},
]

FLOOD_LIMIT = 40
FLOOD_BLOCK_SECONDS = 60

try:                          # تنظیمات شخصی (در .gitignore)
    from config_local import *  # noqa
except ImportError:
    pass
