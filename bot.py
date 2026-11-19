"""Telegram bot UI. Run:  TELEGRAM_BOT_TOKEN=xxx python3 bot.py"""
import asyncio
import datetime
import html
import io
import logging
import os
import random
import re
import subprocess
import urllib.request

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, TypeHandler, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, PersistenceInput, PicklePersistence, filters)

from core import library as lib
import stats

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------- data cache ----------
SURAS = {}      # n -> list of entries
TITLES = {}     # n -> clean name
TR_MODES = {
    "fool": ("فولادوند", ["فولادوند"]),
    "mak": ("مکارم شیرازی", ["مکارم شیرازی"]),
    "both": ("هر دو ترجمه", ["فولادوند", "مکارم شیرازی"]),
    "none": ("فقط عربی", []),
}
MODE_ORDER = ["fool", "mak", "both", "none"]
PAGE_CHARS, PAGE_MAX = 2200, 8
_pages_cache = {}


def fa_digits(n):
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def clean(s):
    return s.replace("ي", "ی").replace("ك", "ک").replace("ى", "ی").replace("\ufeff", "")


def load():
    for g in lib.list_groups("quran"):
        n = g["group_no"]
        words = g["group_title"].split()
        title = " ".join(words[1:]) if lib.normalize(words[0]) in ("سورة", "سوره") else g["group_title"]
        TITLES[n] = title
        SURAS[n] = lib.get_group("quran", n, limit=400)


def mode(ctx):
    return ctx.user_data.get("tr", "fool")


def pages(n, m):
    key = (n, m)
    if key in _pages_cache:
        return _pages_cache[key]
    out, cur, size = [], [], 0
    for e in SURAS[n]:
        sz = len(e["original"] or "") + sum(len(t) for k, t in e["translations"].items()
                                           if k in TR_MODES[m][1])
        if cur and (size + sz > PAGE_CHARS or len(cur) >= PAGE_MAX):
            out.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += sz
    if cur:
        out.append(cur)
    _pages_cache[key] = out
    return out


def page_of(n, ayah, m):
    for i, p in enumerate(pages(n, m)):
        if any(e["item_no"] == ayah for e in p):
            return i
    return 0


# ---------- rendering ----------
def render_ayah(e, m, num=True):
    ar = html.escape(clean(e["original"] or ""))
    mark = f" ﴿{fa_digits(e['item_no'])}﴾" if num else ""
    s = f"<b>{ar}</b>{mark}\n"
    for name in TR_MODES[m][1]:
        t = e["translations"].get(name)
        if t:
            label = f"<i>{name}</i>\n" if len(TR_MODES[m][1]) > 1 else ""
            s += f"<blockquote>{label}{html.escape(clean(t))}</blockquote>"
    return s + "\n"


def render_page(n, p, m):
    pg = pages(n, m)
    p = max(0, min(p, len(pg) - 1))
    head = (f"📖 <b>سوره {html.escape(TITLES[n])}</b>\n"
            f"سوره {fa_digits(n)} · {fa_digits(len(SURAS[n]))} آیه · صفحه {fa_digits(p+1)} از {fa_digits(len(pg))}\n"
            "━━━━━━━━━━━━━━\n\n")
    body = ""
    if p == 0 and n not in (1, 9):
        body += "<b>بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ</b>\n\n"
    body += "".join(render_ayah(e, m) for e in pg[p])
    if len(head + body) > 4000:  # e.g. 2:282 with two translations
        body = "".join(render_ayah(e, "fool") for e in pg[p]) + "<i>(به‌دلیل طول آیه فقط ترجمه فولادوند نمایش داده شد)</i>"
    return head + body, p, len(pg)


def kb_page(n, p, total, m, ctx):
    first = pages(n, m)[p][0]["item_no"]
    saved = [n, first] in ctx.user_data.get("bm", [])
    nav = []
    if p > 0:
        nav.append(B("◀️ قبلی", callback_data=f"s:{n}:{p-1}"))
    nav.append(B(f"{fa_digits(p+1)}/{fa_digits(total)}", callback_data="noop"))
    if p < total - 1:
        nav.append(B("بعدی ▶️", callback_data=f"s:{n}:{p+1}"))
    rows = [nav]
    ayahs = [e["item_no"] for e in pages(n, m)[p]]
    for i in range(0, len(ayahs), 5):
        rows.append([B(f"🔊 {fa_digits(a)}", callback_data=f"au:{n}:{a}") for a in ayahs[i:i+5]])
    rows.append([B("⭐ حذف نشان" if saved else "🔖 نشان‌کردن", callback_data=f"b:{n}:{first}:{p}"),
                 B(f"🌐 {TR_MODES[m][0]}", callback_data=f"c:{n}:{p}")])
    ns = []
    if n > 1:
        ns.append(B("⏮ سوره قبل", callback_data=f"s:{n-1}:0"))
    if n < 114:
        ns.append(B("سوره بعد ⏭", callback_data=f"s:{n+1}:0"))
    rows.append(ns)
    rows.append([B("📚 فهرست سوره‌ها", callback_data="sl:0"), B("🏠 منو", callback_data="m")])
    return KB(rows)


def kb_main(admin=False):
    rows = [
        [B("📖 قرآن کریم", callback_data="sl:0")],
        [B("🔎 جستجو", callback_data="help"), B("🌅 آیه روز", callback_data="d")],
        [B("🎲 آیه تصادفی", callback_data="r"), B("🔖 نشان‌شده‌ها", callback_data="bl")],
        [B("⚙️ تنظیمات ترجمه", callback_data="set")],
        [B("📜 نهج‌البلاغه", callback_data="nh")],
        [B("🤲 مفاتیح‌الجنان", callback_data="mf:0")],
        [B("🕌 زیارت‌ها (به‌زودی)", callback_data="soon")],
    ]
    if admin:
        rows.append([B("📊 آمار", callback_data="adm:stats"), B("👥 کاربران", callback_data="adm:users")])
        rows.append([B("📤 خروجی CSV", callback_data="adm:export")])
    return KB(rows)


MAIN_TEXT = ("╭─── ✦ ───╮\n"
             "   <b>بسم الله الرحمن الرحیم</b>\n"
             "╰─── ✦ ───╯\n\n"
             "به <b>ربات نور</b> خوش آمدید 🌙\n\n"
             "• از منو یک سوره انتخاب کنید\n"
             "• یا مستقیم بنویسید: <code>2:255</code> برای یک آیه، <code>36</code> برای یک سوره، "
             "نام سوره مثل <code>کوثر</code>، یا هر کلمه برای جستجو")


async def send(update, text, kb):
    q = update.callback_query
    kw = dict(text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
    if q:
        try:
            await q.edit_message_text(**kw)
        except Exception as ex:  # message not modified etc.
            if "not modified" not in str(ex):
                raise
    else:
        await update.effective_message.reply_text(**kw)


def ayah_audio(n, a):
    """Return (bytes, is_voice). Tries ogg/opus voice; falls back to the raw mp3."""
    mp3 = None
    err = None
    for host in ("everyayah.com", "www.everyayah.com"):
        try:
            req = urllib.request.Request(f"https://{host}/data/Alafasy_128kbps/{n:03d}{a:03d}.mp3",
                                         headers={"User-Agent": "Mozilla/5.0"})
            mp3 = urllib.request.urlopen(req, timeout=30).read()
            break
        except Exception as ex:
            err = ex
    if mp3 is None:
        raise err
    try:
        proc = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
                               "-c:a", "libopus", "-b:a", "48k", "-f", "ogg", "pipe:1"],
                              input=mp3, capture_output=True, check=True)
        return proc.stdout, True
    except Exception:
        log.exception("ffmpeg failed, sending mp3")
        return mp3, False


# ---------- views ----------
async def v_main(update, ctx):
    await send(update, MAIN_TEXT, kb_main(is_admin(update)))


async def v_list(update, ctx, page):
    per = 15
    total = (114 + per - 1) // per
    page = max(0, min(page, total - 1))
    nums = list(range(page * per + 1, min(114, (page + 1) * per) + 1))
    rows = []
    for i in range(0, len(nums), 3):
        rows.append([B(f"{fa_digits(n)}. {TITLES[n]}", callback_data=f"s:{n}:0") for n in nums[i:i+3]])
    nav = []
    if page > 0:
        nav.append(B("◀️", callback_data=f"sl:{page-1}"))
    nav.append(B(f"{fa_digits(page+1)}/{fa_digits(total)}", callback_data="noop"))
    if page < total - 1:
        nav.append(B("▶️", callback_data=f"sl:{page+1}"))
    rows += [nav, [B("🏠 منو", callback_data="m")]]
    await send(update, "📚 <b>فهرست سوره‌های قرآن</b>\nیک سوره را انتخاب کنید:", KB(rows))


async def v_sura(update, ctx, n, p):
    m = mode(ctx)
    text, p, total = render_page(n, p, m)
    await send(update, text, kb_page(n, p, total, m, ctx))


async def v_ayah(update, ctx, n, a):
    m = mode(ctx)
    ents = SURAS.get(n)
    if not ents or not 1 <= a <= len(ents):
        await send(update, "❌ این آیه وجود ندارد.", KB([[B("🏠 منو", callback_data="m")]]))
        return
    e = ents[a - 1]
    text = (f"📍 <b>سوره {html.escape(TITLES[n])}</b> · آیه {fa_digits(a)}\n━━━━━━━━━━━━━━\n\n"
            + render_ayah(e, m, num=False))
    nav = []
    if a > 1:
        nav.append(B("◀️ آیه قبل", callback_data=f"a:{n}:{a-1}"))
    if a < len(ents):
        nav.append(B("آیه بعد ▶️", callback_data=f"a:{n}:{a+1}"))
    saved = [n, a] in ctx.user_data.get("bm", [])
    kb = KB([nav,
             [B("⭐ حذف نشان" if saved else "🔖 نشان‌کردن", callback_data=f"ba:{n}:{a}"),
              B("📖 خواندن سوره", callback_data=f"s:{n}:{page_of(n, a, m)}")],
             [B("🔊 شنیدن آیه", callback_data=f"au:{n}:{a}")],
             [B("🏠 منو", callback_data="m")]])
    await send(update, text, kb)


async def v_daily(update, ctx, rnd=False):
    r = random.Random(None if rnd else datetime.date.today().toordinal())
    n = r.randint(1, 114)
    a = r.randint(1, len(SURAS[n]))
    await v_ayah(update, ctx, n, a)


async def v_bookmarks(update, ctx):
    bm = ctx.user_data.get("bm", [])
    if not bm:
        await send(update, "🔖 هنوز چیزی نشان نکرده‌اید.\nهنگام خواندن، دکمه «نشان‌کردن» را بزنید.",
                   KB([[B("🏠 منو", callback_data="m")]]))
        return
    rows = [[B(f"🔖 {TITLES[n]} · آیه {fa_digits(a)}", callback_data=f"a:{n}:{a}")] for n, a in bm[-20:]]
    rows.append([B("🏠 منو", callback_data="m")])
    await send(update, "🔖 <b>نشان‌شده‌های شما</b>", KB(rows))


async def v_settings(update, ctx):
    m = mode(ctx)
    rows = [[B(("✅ " if k == m else "▫️ ") + TR_MODES[k][0], callback_data=f"ts:{k}")] for k in MODE_ORDER]
    rows.append([B("🏠 منو", callback_data="m")])
    await send(update, "⚙️ <b>تنظیمات</b>\nترجمه‌ی نمایشی را انتخاب کنید:", KB(rows))


# ---------- handlers ----------
# ---------- Nahj al-Balagha ----------
NH_TYPES = {0: ("خطبه‌ها", "خطبه", 0, 241), 1: ("نامه‌ها", "نامه", 1000, 79), 2: ("حکمت‌ها", "حکمت", 2000, 24)}
_nh_cache = {}


def nh_pages(gno):
    if gno in _nh_cache:
        return _nh_cache[gno]
    out, cur, size = [], [], 0
    for e in lib.get_group("nahj", gno, limit=400):
        sz = len(e["original"] or "") + sum(len(t) for t in e["translations"].values())
        if cur and size + sz > 2800:
            out.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += sz
    if cur:
        out.append(cur)
    _nh_cache[gno] = out
    return out


def nh_type(gno):
    return 2 if gno > 2000 else 1 if gno > 1000 else 0


async def v_nahj(update, ctx):
    rows = [[B(f"📜 {NH_TYPES[t][0]}", callback_data=f"nl:{t}:0")] for t in (0, 1, 2)]
    rows.append([B("🏠 منو", callback_data="m")])
    await send(update, "📜 <b>نهج‌البلاغه</b>\nگردآوری سید رضی\n\nیک بخش را انتخاب کنید:", KB(rows))


async def v_nlist(update, ctx, t, page):
    name, word, base, cnt = NH_TYPES[t]
    per = 30
    total = (cnt + per - 1) // per
    page = max(0, min(page, total - 1))
    nums = list(range(page * per + 1, min(cnt, (page + 1) * per) + 1))
    rows = []
    for i in range(0, len(nums), 5):
        rows.append([B(fa_digits(n), callback_data=f"nv:{base+n}:0") for n in nums[i:i+5]])
    nav = []
    if page > 0:
        nav.append(B("◀️", callback_data=f"nl:{t}:{page-1}"))
    nav.append(B(f"{fa_digits(page+1)}/{fa_digits(total)}", callback_data="noop"))
    if page < total - 1:
        nav.append(B("▶️", callback_data=f"nl:{t}:{page+1}"))
    rows += [nav, [B("📜 نهج‌البلاغه", callback_data="nh"), B("🏠 منو", callback_data="m")]]
    what = "بخش" if t == 2 else word
    extra = "\n(هر بخش حکمت شامل حدود ۲۵ حکمت است)" if t == 2 else ""
    await send(update, f"📜 <b>{name} نهج‌البلاغه</b>\nشماره {what} را انتخاب کنید:{extra}", KB(rows))


async def v_nview(update, ctx, gno, p):
    pg = nh_pages(gno)
    if not pg:
        return await v_nahj(update, ctx)
    p = max(0, min(p, len(pg) - 1))
    t = nh_type(gno)
    name, word, base, cnt = NH_TYPES[t]
    num = gno - base
    title = f"حکمت‌ها · بخش {fa_digits(num)}" if t == 2 else f"{word} {fa_digits(num)}"
    s = f"📜 <b>{title}</b> · صفحه {fa_digits(p+1)} از {fa_digits(len(pg))}\n━━━━━━━━━━━━━━\n\n"
    for e in pg[p]:
        ar = html.escape(clean(e["original"] or ""))
        fa = html.escape(clean(" ".join(e["translations"].values())))
        s += f"<b>{ar}</b>\n<blockquote>{fa}</blockquote>\n"
    s = s[:4000]
    nav = []
    if p > 0:
        nav.append(B("◀️ قبلی", callback_data=f"nv:{gno}:{p-1}"))
    nav.append(B(f"{fa_digits(p+1)}/{fa_digits(len(pg))}", callback_data="noop"))
    if p < len(pg) - 1:
        nav.append(B("بعدی ▶️", callback_data=f"nv:{gno}:{p+1}"))
    ns = []
    if num > 1:
        ns.append(B(f"⏮ {word} قبل", callback_data=f"nv:{gno-1}:0"))
    if num < cnt:
        ns.append(B(f"{word} بعد ⏭", callback_data=f"nv:{gno+1}:0"))
    rows = [nav, ns, [B("📚 فهرست", callback_data=f"nl:{t}:{(num-1)//30}"), B("🏠 منو", callback_data="m")]]
    await send(update, s, KB([r for r in rows if r]))


# ---------- Mafatih al-Jinan ----------
_MF = {}


def mf_arts():
    if "a" not in _MF:
        arts = []
        for g in lib.list_groups("mafatih"):
            for e in lib.get_group("mafatih", g["group_no"], limit=400):
                fa = " ".join(e["translations"].values())
                title = clean(fa.split("\n")[0]).strip() or "بدون عنوان"
                arts.append({"g": g["group_no"], "i": e["item_no"], "title": title, "ar": e["original"] or "", "fa": fa})
        _MF["a"] = arts
        _MF["idx"] = {(x["g"], x["i"]): n for n, x in enumerate(arts)}
    return _MF["a"]


def _chunks(txt, n=1500):
    out, cur = [], ""
    for ln in txt.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        while len(ln) > n:
            out.append(ln[:n])
            ln = ln[n:]
        if cur and len(cur) + len(ln) > n:
            out.append(cur)
            cur = ""
        cur = (cur + "\n" + ln) if cur else ln
    if cur:
        out.append(cur)
    return out


def mf_pages(idx):
    key = ("p", idx)
    if key in _MF:
        return _MF[key]
    art = mf_arts()[idx]
    blocks = []
    fa_lines = art["fa"].split("\n", 1)
    fa_body = fa_lines[1] if len(fa_lines) > 1 else ""
    for c in _chunks(clean(art["ar"])):
        blocks.append(f"<b>{html.escape(c)}</b>")
    for c in _chunks(clean(fa_body)):
        blocks.append(f"<blockquote>{html.escape(c)}</blockquote>")
    pages, cur, size = [], [], 0
    for bl in blocks:
        if cur and size + len(bl) > 3000:
            pages.append("\n".join(cur))
            cur, size = [], 0
        cur.append(bl)
        size += len(bl)
    if cur:
        pages.append("\n".join(cur))
    _MF[key] = pages or ["—"]
    return _MF[key]


async def v_mflist(update, ctx, page):
    arts = mf_arts()
    per = 10
    total = (len(arts) + per - 1) // per
    page = max(0, min(page, total - 1))
    rows = [[B(x["title"][:60], callback_data=f"mv:{n}:0")] for n, x in enumerate(arts[page * per:(page + 1) * per], page * per)]
    nav = []
    if page > 0:
        nav.append(B("◀️", callback_data=f"mf:{page-1}"))
    nav.append(B(f"{fa_digits(page+1)}/{fa_digits(total)}", callback_data="noop"))
    if page < total - 1:
        nav.append(B("▶️", callback_data=f"mf:{page+1}"))
    rows += [nav, [B("🏠 منو", callback_data="m")]]
    await send(update, "🤲 <b>مفاتیح‌الجنان</b>\nیکی را انتخاب کنید:", KB(rows))


async def v_mfview(update, ctx, idx, p):
    arts = mf_arts()
    if not 0 <= idx < len(arts):
        return await v_mflist(update, ctx, 0)
    pg = mf_pages(idx)
    p = max(0, min(p, len(pg) - 1))
    s = f"🤲 <b>{html.escape(arts[idx]['title'])}</b> · {fa_digits(p+1)}/{fa_digits(len(pg))}\n━━━━━━━━━━━━━━\n\n{pg[p]}"
    nav = []
    if p > 0:
        nav.append(B("◀️ قبلی", callback_data=f"mv:{idx}:{p-1}"))
    if p < len(pg) - 1:
        nav.append(B("بعدی ▶️", callback_data=f"mv:{idx}:{p+1}"))
    rows = [nav] if nav else []
    pn = []
    if idx > 0:
        pn.append(B("⏮ دعای قبل", callback_data=f"mv:{idx-1}:0"))
    if idx < len(arts) - 1:
        pn.append(B("دعای بعد ⏭", callback_data=f"mv:{idx+1}:0"))
    if pn:
        rows.append(pn)
    rows.append([B("📚 فهرست", callback_data=f"mf:{idx//10}"), B("🏠 منو", callback_data="m")])
    await send(update, s, KB(rows))


async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    await q.answer()
    p = d.split(":")
    k = p[0]
    if k == "adm":
        if not is_admin(update):
            return
        return await {"stats": cmd_stats, "users": cmd_users, "export": cmd_export}[p[1]](update, ctx)
    if k == "nh":
        return await v_nahj(update, ctx)
    if k == "nj":
        g, it = int(p[1]), int(p[2])
        pg = nh_pages(g)
        idx = next((i for i, x in enumerate(pg) if any(e["item_no"] == it for e in x)), 0)
        return await v_nview(update, ctx, g, idx)
    if k == "mf":
        return await v_mflist(update, ctx, int(p[1]))
    if k == "mv":
        return await v_mfview(update, ctx, int(p[1]), int(p[2]))
    if k == "nl":
        return await v_nlist(update, ctx, int(p[1]), int(p[2]))
    if k == "nv":
        return await v_nview(update, ctx, int(p[1]), int(p[2]))
    if k == "au":
        n, a = int(p[1]), int(p[2])
        try:
            data, is_voice = await asyncio.to_thread(ayah_audio, n, a)
            f = io.BytesIO(data)
            cap = f"{TITLES[n]} · آیه {fa_digits(a)}"
            if is_voice:
                f.name = f"{n:03d}{a:03d}.ogg"
                await q.message.reply_voice(f, caption=cap)
            else:
                f.name = f"{n:03d}{a:03d}.mp3"
                await q.message.reply_audio(f, title=cap, performer="مشاری العفاسی")
        except Exception as ex:
            log.exception("audio failed")
            await q.message.reply_text(f"❌ ارسال صوت ممکن نشد.\n{type(ex).__name__}: {ex}"[:300])
        return
    if k == "m":
        await v_main(update, ctx)
    elif k == "sl":
        await v_list(update, ctx, int(p[1]))
    elif k == "s":
        await v_sura(update, ctx, int(p[1]), int(p[2]))
    elif k == "a":
        await v_ayah(update, ctx, int(p[1]), int(p[2]))
    elif k == "c":
        i = MODE_ORDER.index(mode(ctx))
        n, pg = int(p[1]), int(p[2])
        first = pages(n, mode(ctx))[min(pg, len(pages(n, mode(ctx))) - 1)][0]["item_no"]
        ctx.user_data["tr"] = MODE_ORDER[(i + 1) % len(MODE_ORDER)]
        await v_sura(update, ctx, n, page_of(n, first, mode(ctx)))
    elif k == "ts":
        ctx.user_data["tr"] = p[1]
        await v_settings(update, ctx)
    elif k in ("b", "ba"):
        n, a = int(p[1]), int(p[2])
        bm = ctx.user_data.setdefault("bm", [])
        if [n, a] in bm:
            bm.remove([n, a])
            await q.answer("از نشان‌ها حذف شد")
        else:
            bm.append([n, a])
            await q.answer("🔖 نشان شد")
        if k == "b":
            await v_sura(update, ctx, n, int(p[3]))
        else:
            await v_ayah(update, ctx, n, a)
    elif k == "bl":
        await v_bookmarks(update, ctx)
    elif k == "d":
        await v_daily(update, ctx)
    elif k == "r":
        await v_daily(update, ctx, rnd=True)
    elif k == "set":
        await v_settings(update, ctx)
    elif k == "help":
        await send(update, "🔎 <b>جستجو</b>\n\nکافی است در چت بنویسید:\n"
                   "• <code>2:255</code> ← آیه\n• <code>36</code> ← سوره\n• <code>کوثر</code> ← نام سوره\n"
                   "• <code>صبر</code> ← جستجو در متن ترجمه‌ها و آیات",
                   KB([[B("🏠 منو", callback_data="m")]]))
    elif k == "soon":
        await q.answer("این بخش‌ها به‌زودی اضافه می‌شوند 🌱", show_alert=True)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    t = t.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    mt = re.fullmatch(r"(\d{1,3})\s*[:/\-.\s]\s*(\d{1,3})", t)
    if mt:
        return await v_ayah(update, ctx, int(mt[1]), int(mt[2]))
    if t.isdigit():
        n = int(t)
        if 1 <= n <= 114:
            return await v_sura(update, ctx, n, 0)
    nt = lib.normalize(t)
    if len(nt) >= 2:
        hits = [n for n, ti in TITLES.items() if len(nt) >= 3 and nt.replace("ال", "") in lib.normalize(ti).replace("ال", "")]
        if hits and len(hits) <= 3:
            rows = [[B(f"📖 سوره {TITLES[n]}", callback_data=f"s:{n}:0")] for n in hits]
            rows.append([B("🏠 منو", callback_data="m")])
            return await update.message.reply_text("📚 سوره‌های یافت‌شده:", reply_markup=KB(rows))
    def uniq(res, n):
        seen, out = set(), []
        for r in res:
            key = (r["group_no"], r["item_no"])
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out[:n]

    qi = uniq(lib.search(t, "quran", limit=40), 5)
    ni = uniq(lib.search(t, "nahj", limit=40), 3)
    mi = uniq(lib.search(t, "mafatih", limit=40), 3)
    if not qi and not ni and not mi:
        return await update.message.reply_text("🔍 نتیجه‌ای پیدا نشد. کلمه‌ی دیگری امتحان کنید.",
                                               reply_markup=KB([[B("🏠 منو", callback_data="m")]]))

    def hl(r):
        return html.escape(clean(r["snip"])).replace("[[HL]]", "<b>").replace("[[/HL]]", "</b>")

    def nlabel(r):
        if r["group_no"] > 2000:
            return f"حکمت {fa_digits(r['item_no'])}"
        return fa_digits(clean(r["group_title"]))

    text = f"🔎 <b>نتایج «{html.escape(t)}»</b>\n━━━━━━━━━━━━━━\n\n"
    rows = []
    if qi:
        text += "📖 <b>قرآن</b>\n"
        row = []
        for r in qi:
            text += f"▪️ <i>{html.escape(TITLES[r['group_no']])} {fa_digits(r['group_no'])}:{fa_digits(r['item_no'])}</i>\n{hl(r)}\n\n"
            row.append(B(f"{fa_digits(r['group_no'])}:{fa_digits(r['item_no'])}", callback_data=f"a:{r['group_no']}:{r['item_no']}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    if ni:
        text += "📜 <b>نهج‌البلاغه</b>\n"
        row = []
        for r in ni:
            lb = nlabel(r)
            text += f"▪️ <i>{html.escape(lb)}</i>\n{hl(r)}\n\n"
            row.append(B(f"📜 {lb}", callback_data=f"nj:{r['group_no']}:{r['item_no']}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    if mi:
        mf_arts()
        text += "🤲 <b>مفاتیح‌الجنان</b>\n"
        row = []
        for r in mi:
            n = _MF["idx"].get((r["group_no"], r["item_no"]))
            if n is None:
                continue
            ti = _MF["a"][n]["title"]
            text += f"▪️ <i>{html.escape(ti[:60])}</i>\n{hl(r)}\n\n"
            rows.append([B(f"🤲 {ti[:50]}", callback_data=f"mv:{n}:0")])
    rows.append([B("🏠 منو", callback_data="m")])
    await update.message.reply_text(text[:4000], reply_markup=KB(rows), parse_mode=ParseMode.HTML)


async def cmd_start(update, ctx):
    await v_main(update, ctx)


ADMINS = {int(x) for x in re.findall(r"\d+", os.environ.get("ADMIN_ID", ""))}


async def track(update: Update, ctx):
    if update.callback_query:
        ev = "btn:" + (update.callback_query.data or "").split(":")[0]
    elif update.message and update.message.text:
        t = update.message.text
        ev = "cmd:" + t.split()[0].lstrip("/").split("@")[0] if t.startswith("/") else "text"
    else:
        return
    stats.record(update.effective_user, ev)


def is_admin(update):
    return update.effective_user and update.effective_user.id in ADMINS


async def cmd_myid(update, ctx):
    await update.message.reply_text(f"آیدی عددی شما: {update.effective_user.id}")


async def cmd_stats(update, ctx):
    if not is_admin(update):
        return
    s = stats.summary()
    week = "\n".join(f"{d}: {u} کاربر / {n} درخواست" for d, u, n in s["week"]) or "-"
    top = "\n".join(f"{k}: {v}" for k, v in s["top"]) or "-"
    await update.effective_message.reply_text(
        f"📊 آمار بات\n━━━━━━━━━━\n👥 کل کاربران: {s['total']}\n🆕 جدید ۲۴ ساعت: {s['new24']}\n"
        f"🟢 فعال ۲۴ ساعت: {s['active24']}\n📅 فعال ۷ روز: {s['active7d']}\n"
        f"💬 درخواست امروز: {s['today_n']}\n💬 کل درخواست‌ها: {s['total_n']}\n\n"
        f"۷ روز اخیر (UTC):\n{week}\n\nپرکاربردترین‌ها:\n{top}")


async def cmd_users(update, ctx):
    if not is_admin(update):
        return
    lst = stats.users_list()
    lines = [f"{i}. {html.escape(u['name'] or '-')} "
             f"{'@' + u['username'] if u['username'] else ''} <code>{uid}</code> ({u['n']})"
             for i, (uid, u) in enumerate(lst[:30], 1)]
    await update.effective_message.reply_text(
        f"👥 {len(lst)} کاربر (۳۰ آخرین فعال)\n\n" + "\n".join(lines) + "\n\nلیست کامل: /export",
        parse_mode=ParseMode.HTML)


async def cmd_export(update, ctx):
    if not is_admin(update):
        return
    await update.effective_message.reply_document(stats.users_csv(), filename="users.csv")


async def _flush(app):
    stats.save(force=True)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("متغیر TELEGRAM_BOT_TOKEN را تنظیم کنید (توکن را از @BotFather بگیرید).")
    load()
    stats.load()
    os.makedirs(stats.STATE_DIR, exist_ok=True)
    app = (Application.builder().token(token)
           .persistence(PicklePersistence(os.path.join(stats.STATE_DIR, "users.pickle"),
                                          store_data=PersistenceInput(bot_data=False, chat_data=False, callback_data=False)))
           .post_shutdown(_flush)
           .build())
    app.add_handler(TypeHandler(Update, track), group=-1)
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
