"""Nahj al-Balagha importer (downloaded dataset from yasinfadayiee/mishkat; nothing typed by hand).

Groups: sermons 1-241, letters 1001+, sayings (chunks of ~25) 2001+.
Run:  python -m importers.nahj
"""
import json
import urllib.request

from core import db

URL = "https://raw.githubusercontent.com/yasinfadayiee/mishkat/main/books/search/Nahj-al-Balagha-Radi.json"
BASE = {0: 0, 1: 1000, 2: 2000}
KIND = {0: "خطبه", 1: "نامه", 2: "حکمت"}


def run():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    rows = json.load(urllib.request.urlopen(req, timeout=120))
    con = db.connect()
    book = db.upsert_book(con, "nahj", "نهج‌البلاغه", "hadith", "نهج البلاغة", "mishkat")
    seen = {}
    for t, g, _id, num, fa, ar in rows:
        key = (t, g)
        first = key not in seen
        seen[key] = seen.get(key, 0) + 1
        gno = BASE[t] + g + 1
        if t == 2:
            title = f"حکمت‌ها (بخش {g+1})"
            item = num
        else:
            title = f"{KIND[t]} {g+1}"
            item = seen[key] - 1  # 0 = heading line
        eid = db.upsert_entry(con, book, gno, item, title)
        db.add_text(con, eid, "original", "ar", ar.strip())
        db.add_text(con, eid, "translation", "fa", fa.strip(), "نهج‌البلاغه (فارسی)")
    con.commit()
    db.rebuild_fts(con)
    print("ok", len(rows))


if __name__ == "__main__":
    run()
