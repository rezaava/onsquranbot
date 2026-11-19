"""Telegram bot UI. Run:  TELEGRAM_BOT_TOKEN=xxx python3 bot.py"""
import datetime
import html
import logging
import os
import random
import re

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, PersistenceInput, PicklePersistence, filters)

from core import library as lib

logging.basicConfig(level=logging.INFO)

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


def kb_main():
    return KB([
        [B("📖 قرآن کریم", callback_data="sl:0")],
        [B("🔎 جستجو", callback_data="help"), B("🌅 آیه روز", callback_data="d")],
        [B("🎲 آیه تصادفی", callback_data="r"), B("🔖 نشان‌شده‌ها", callback_data="bl")],
        [B("⚙️ تنظیمات ترجمه", callback_data="set")],
        [B("🕌 نهج‌البلاغه · دعاها · زیارت‌ها (به‌زودی)", callback_data="soon")],
    ])


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


# ---------- views ----------
async def v_main(update, ctx):
    await send(update, MAIN_TEXT, kb_main())


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
async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    await q.answer()
    p = d.split(":")
    k = p[0]
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
    res = lib.search(t, "quran", limit=40)
    if not res:
        return await update.message.reply_text("🔍 نتیجه‌ای پیدا نشد. کلمه‌ی دیگری امتحان کنید.",
                                               reply_markup=KB([[B("🏠 منو", callback_data="m")]]))
    seen, items = set(), []
    for r in res:
        key = (r["group_no"], r["item_no"])
        if key not in seen:
            seen.add(key)
            items.append(r)
    items = items[:10]
    text = f"🔎 <b>نتایج «{html.escape(t)}»</b>\n━━━━━━━━━━━━━━\n\n"
    for r in items:
        snip = html.escape(clean(r["snip"])).replace("[[HL]]", "<b>").replace("[[/HL]]", "</b>")
        text += f"▪️ <i>{html.escape(TITLES[r['group_no']])} {fa_digits(r['group_no'])}:{fa_digits(r['item_no'])}</i>\n{snip}\n\n"
    rows, row = [], []
    for r in items:
        row.append(B(f"{fa_digits(r['group_no'])}:{fa_digits(r['item_no'])}", callback_data=f"a:{r['group_no']}:{r['item_no']}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([B("🏠 منو", callback_data="m")])
    await update.message.reply_text(text, reply_markup=KB(rows), parse_mode=ParseMode.HTML)


async def cmd_start(update, ctx):
    await v_main(update, ctx)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("متغیر TELEGRAM_BOT_TOKEN را تنظیم کنید (توکن را از @BotFather بگیرید).")
    load()
    os.makedirs("data", exist_ok=True)
    app = (Application.builder().token(token)
           .persistence(PicklePersistence("data/users.pickle",
                                          store_data=PersistenceInput(bot_data=False, chat_data=False, callback_data=False)))
           .build())
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
