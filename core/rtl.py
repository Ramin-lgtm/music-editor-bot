# -*- coding: utf-8 -*-
"""شکل‌دهی حروف فارسی/عربی (اتصال حروف) و چینش راست‌به‌چپ برای رندر متن بدون وابستگی به raqm/fribidi."""

# حرف: (مجزا, آخر, اول, وسط)  — None یعنی به حرف بعدی وصل نمی‌شود
_F = {
    "ء": ("\uFE80",), "آ": ("\uFE81", "\uFE82"), "أ": ("\uFE83", "\uFE84"), "ؤ": ("\uFE85", "\uFE86"),
    "إ": ("\uFE87", "\uFE88"), "ئ": ("\uFE89", "\uFE8A", "\uFE8B", "\uFE8C"), "ا": ("\uFE8D", "\uFE8E"),
    "ب": ("\uFE8F", "\uFE90", "\uFE91", "\uFE92"), "ة": ("\uFE93", "\uFE94"),
    "ت": ("\uFE95", "\uFE96", "\uFE97", "\uFE98"), "ث": ("\uFE99", "\uFE9A", "\uFE9B", "\uFE9C"),
    "ج": ("\uFE9D", "\uFE9E", "\uFE9F", "\uFEA0"), "ح": ("\uFEA1", "\uFEA2", "\uFEA3", "\uFEA4"),
    "خ": ("\uFEA5", "\uFEA6", "\uFEA7", "\uFEA8"), "د": ("\uFEA9", "\uFEAA"), "ذ": ("\uFEAB", "\uFEAC"),
    "ر": ("\uFEAD", "\uFEAE"), "ز": ("\uFEAF", "\uFEB0"),
    "س": ("\uFEB1", "\uFEB2", "\uFEB3", "\uFEB4"), "ش": ("\uFEB5", "\uFEB6", "\uFEB7", "\uFEB8"),
    "ص": ("\uFEB9", "\uFEBA", "\uFEBB", "\uFEBC"), "ض": ("\uFEBD", "\uFEBE", "\uFEBF", "\uFEC0"),
    "ط": ("\uFEC1", "\uFEC2", "\uFEC3", "\uFEC4"), "ظ": ("\uFEC5", "\uFEC6", "\uFEC7", "\uFEC8"),
    "ع": ("\uFEC9", "\uFECA", "\uFECB", "\uFECC"), "غ": ("\uFECD", "\uFECE", "\uFECF", "\uFED0"),
    "ف": ("\uFED1", "\uFED2", "\uFED3", "\uFED4"), "ق": ("\uFED5", "\uFED6", "\uFED7", "\uFED8"),
    "ك": ("\uFED9", "\uFEDA", "\uFEDB", "\uFEDC"), "ل": ("\uFEDD", "\uFEDE", "\uFEDF", "\uFEE0"),
    "م": ("\uFEE1", "\uFEE2", "\uFEE3", "\uFEE4"), "ن": ("\uFEE5", "\uFEE6", "\uFEE7", "\uFEE8"),
    "ه": ("\uFEE9", "\uFEEA", "\uFEEB", "\uFEEC"), "و": ("\uFEED", "\uFEEE"), "ى": ("\uFEEF", "\uFEF0"),
    "ي": ("\uFEF1", "\uFEF2", "\uFEF3", "\uFEF4"),
    # فارسی
    "پ": ("\uFB56", "\uFB57", "\uFB58", "\uFB59"), "چ": ("\uFB7A", "\uFB7B", "\uFB7C", "\uFB7D"),
    "ژ": ("\uFB8A", "\uFB8B"), "ک": ("\uFB8E", "\uFB8F", "\uFB90", "\uFB91"),
    "گ": ("\uFB92", "\uFB93", "\uFB94", "\uFB95"), "ی": ("\uFBFC", "\uFBFD", "\uFBFE", "\uFBFF"),
}
_LAM_ALEF = {"آ": ("\uFEF5", "\uFEF6"), "أ": ("\uFEF7", "\uFEF8"), "إ": ("\uFEF9", "\uFEFA"), "ا": ("\uFEFB", "\uFEFC")}
_TASHKEEL = set("\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0653\u0654\u0655\u0670")
_ZW = "\u200c\u200d"
_DIGITS = {**{chr(0x6F0 + i): str(i) for i in range(10)}}   # ارقام فارسی همان‌طور نمایش داده می‌شوند


def _dual(ch):
    f = _F.get(ch)
    return f is not None and len(f) == 4


def _joins_right(ch):
    """آیا این حرف می‌تواند از سمت راست (حرف قبلی) بگیرد؟ (هر حرف عربی به‌جز ء)"""
    f = _F.get(ch)
    return f is not None and len(f) >= 2


def shape(text):
    """حروف را به شکل‌های مجزا/آخر/اول/وسط تبدیل می‌کند (ترتیب منطقی، هنوز بیدی نشده)."""
    chars = [c for c in text]
    n = len(chars)
    out = []
    i = 0
    while i < n:
        c = chars[i]
        if c not in _F:
            out.append(c)
            i += 1
            continue
        # حرف قبلی (با نادیده گرفتن اعراب) آیا به این وصل می‌شود؟
        j = len(out) - 1
        prev_connects = False
        k = i - 1
        while k >= 0 and chars[k] in _TASHKEEL:
            k -= 1
        if k >= 0 and _dual(chars[k]) and chars[k] not in _ZW:
            prev_connects = True
        # لام‌الف
        if c == "ل":
            m = i + 1
            while m < n and chars[m] in _TASHKEEL:
                m += 1
            if m < n and chars[m] in _LAM_ALEF:
                iso, fin = _LAM_ALEF[chars[m]]
                out.append(fin if prev_connects else iso)
                i = m + 1
                continue
        nxt = i + 1
        while nxt < n and chars[nxt] in _TASHKEEL:
            nxt += 1
        next_connects = nxt < n and _joins_right(chars[nxt]) and _dual(c)
        f = _F[c]
        if len(f) == 1:
            out.append(f[0])
        elif len(f) == 2:
            out.append(f[1] if prev_connects else f[0])
        else:
            if prev_connects and next_connects:
                out.append(f[3])
            elif prev_connects:
                out.append(f[1])
            elif next_connects:
                out.append(f[2])
            else:
                out.append(f[0])
        i += 1
    return "".join(out)


def _is_rtl(ch):
    o = ord(ch)
    return (0x0600 <= o <= 0x06FF and ch not in _DIGITS) or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF or 0x0590 <= o <= 0x05FF


_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")


def visual(text):
    """متن منطقی را به ترتیب نمایشی (چپ‌به‌راست) برای رندر ساده تبدیل می‌کند."""
    s = shape(text)
    s = s.replace("\u200c", "").replace("\u200d", "")
    if not any(_is_rtl(c) for c in s):
        return s
    # دسته‌بندی هر کاراکتر: R, L (لاتین/عدد), N (خنثی)
    kinds = []
    for c in s:
        if _is_rtl(c) or c in _TASHKEEL:
            kinds.append("R")
        elif c.isalnum():
            kinds.append("L")
        else:
            kinds.append("N")
    # خنثی‌ها: اگر بین دو R باشند R، وگرنه جهت پایه (R)
    for i, k in enumerate(kinds):
        if k == "N":
            kinds[i] = "R"
    # علامت‌های @ # و نقطه/خط‌تیره بین لاتین‌ها، و فاصله بین دو دسته‌ی لاتین/عدد، جزو همان دسته‌ی لاتین باشند
    for i in range(len(s) - 1):
        if s[i] in "@#" and kinds[i + 1] == "L":
            kinds[i] = "L"
    for i in range(1, len(s) - 1):
        if s[i] in " ._-/:" and kinds[i - 1] == "L" and kinds[i + 1] == "L":
            kinds[i] = "L"
    runs = []
    for c, k in zip(s, kinds):
        if runs and runs[-1][0] == k:
            runs[-1][1].append(c)
        else:
            runs.append([k, [c]])
    out = []
    for k, cs in reversed(runs):          # پاراگراف راست‌به‌چپ: ترتیب دسته‌ها وارونه
        out.append("".join(reversed(cs)).translate(_MIRROR) if k == "R" else "".join(cs))
    return "".join(out)


def render_text_png(text, path, font_path, size=64, color=(255, 255, 255, 235), stroke=3, max_width=1400):
    """متن را (با پشتیبانی فارسی) روی PNG شفاف رندر می‌کند. فقط هنگام نیاز Pillow را import می‌کند."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, size, layout_engine=ImageFont.Layout.BASIC)
    lines = [visual(l) for l in text.replace("\r", "").split("\n")[:3]]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    boxes = [probe.textbbox((0, 0), l, font=font, stroke_width=stroke) for l in lines]
    w = min(max_width, max(b[2] - b[0] for b in boxes) + 2 * stroke + 8)
    lh = max(b[3] - b[1] for b in boxes) + 10
    h = lh * len(lines) + 8
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        bw = boxes[i][2] - boxes[i][0]
        x = (w - bw) // 2 - boxes[i][0]
        d.text((x, 4 + i * lh - boxes[i][1] + 2), l, font=font, fill=color, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    img.save(path, "PNG")
    return img.size
