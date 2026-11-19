"""Mafatih al-Jinan importer (dataset downloaded from aminpaydar/Mafatih, Apache-2.0; nothing typed by hand).

Group = one section (فصل) across all chapters, numbered sequentially.
Item  = one article (dua / ziyarat / amal) inside that section.
Arabic = 'Text' blocks, Persian = 'Translate' + 'AboutText' blocks.
Run:  python -m importers.mafatih
"""
import json
import re
import urllib.request

from core import db

URL = "https://raw.githubusercontent.com/aminpaydar/Mafatih/master/mafatih-server/chapters.json"


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def run():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    chapters = json.load(urllib.request.urlopen(req, timeout=120))
    con = db.connect()
    book = db.upsert_book(con, "mafatih", "مفاتیح‌الجنان", "dua", "Mafatih al-Jinan", "aminpaydar/Mafatih")
    gno, n_art = 0, 0
    for ch in chapters:
        ch_title = _clean(ch.get("title"))
        for sec in ch.get("sections", []):
            gno += 1
            sec_title = _clean(sec.get("title")) or f"بخش {gno}"
            gtitle = f"{ch_title} · {sec_title}" if ch_title else sec_title
            for ino, art in enumerate(sec.get("articles", []), 1):
                ar_parts, fa_parts = [], []
                for it in art.get("items", []):
                    body = (it.get("content") or "").strip()
                    if not body:
                        continue
                    if it.get("type") == "Text":
                        ar_parts.append(body)
                    elif it.get("type") in ("Translate", "AboutText"):
                        fa_parts.append(body)
                title = _clean(art.get("title"))
                if not ar_parts and not fa_parts:
                    continue
                eid = db.upsert_entry(con, book, gno, ino, gtitle[:200])
                db.add_text(con, eid, "original", "ar", "\n".join(ar_parts))
                db.add_text(con, eid, "translation", "fa", (f"{title}\n" if title else "") + "\n".join(fa_parts),
                            "مفاتیح‌الجنان (انصاریان)")
                n_art += 1
    con.commit()
    db.rebuild_fts(con)
    print("ok sections", gno, "articles", n_art)


if __name__ == "__main__":
    run()
