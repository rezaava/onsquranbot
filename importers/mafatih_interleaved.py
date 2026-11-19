"""Mafatih al-Jinan importer with interleaved Arabic/Persian pairs.

Each Text block followed by its Translate becomes one entry (AR original, FA translation).
AboutText blocks are prepended to the next pair's Persian text.
Run:  python -m importers.mafatih_interleaved
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
    gno, n_pair = 0, 0
    for ch in chapters:
        ch_title = _clean(ch.get("title"))
        for sec in ch.get("sections", []):
            gno += 1
            sec_title = _clean(sec.get("title")) or f"بخش {gno}"
            gtitle = f"{ch_title} · {sec_title}" if ch_title else sec_title
            for art in sec.get("articles", []):
                art_title = _clean(art.get("title"))
                ar_buf, fa_buf, about = [], [], []
                ino = 0
                for it in art.get("items", []):
                    body = (it.get("content") or "").strip()
                    if not body:
                        continue
                    if it.get("type") == "AboutText":
                        about.append(body)
                    elif it.get("type") == "Text":
                        if fa_buf or ar_buf:
                            ino += 1
                            eid = db.upsert_entry(con, book, gno, ino, gtitle[:200])
                            db.add_text(con, eid, "original", "ar", "\n".join(ar_buf))
                            db.add_text(con, eid, "translation", "fa", "\n".join(fa_buf), "مفاتیح‌الجنان (انصاریان)")
                            ar_buf, fa_buf, about = [], [], []
                            n_pair += 1
                        ar_buf.append(body)
                    elif it.get("type") == "Translate":
                        prefix = (art_title + "\n") if ino == 0 and art_title else ""
                        fa_buf = about + [prefix + body if prefix else body]
                        about = []
                if ar_buf or fa_buf:
                    ino += 1
                    eid = db.upsert_entry(con, book, gno, ino, gtitle[:200])
                    db.add_text(con, eid, "original", "ar", "\n".join(ar_buf))
                    db.add_text(con, eid, "translation", "fa", "\n".join(fa_buf), "مفاتیح‌الجنان (انصاریان)")
                    n_pair += 1
    con.commit()
    db.rebuild_fts(con)
    print("ok sections", gno, "pairs", n_pair)


if __name__ == "__main__":
    run()
