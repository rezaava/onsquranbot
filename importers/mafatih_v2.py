"""Mafatih importer v2: one group per article (title searchable), Arabic/Persian classified per line.
Run: python -m importers.mafatih_v2"""
import json, re, urllib.request
from core import db
from importers._cls import kind

URL = "https://raw.githubusercontent.com/aminpaydar/Mafatih/master/mafatih-server/chapters.json"
BAB = {"باب اول": 1, "باب دوم": 2, "باب سوم": 3}


def cl(s):
    return re.sub(r"[ \t\xa0]+", " ", s or "").strip()


def fa_fix(s):
    return s.replace("ي", "ی").replace("ك", "ک").replace("ى", "ی")


def run():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    chapters = json.load(urllib.request.urlopen(req, timeout=120))
    con = db.connect()
    book = db.upsert_book(con, "mafatih", "مفاتیح‌الجنان", "dua", "Mafatih al-Jinan", "aminpaydar/Mafatih")
    con.execute("DELETE FROM texts WHERE entry_id IN (SELECT id FROM entries WHERE book_id=?)", (book,))
    con.execute("DELETE FROM entries WHERE book_id=?", (book,))
    gno = 0
    for bi, ch in enumerate(chapters, 1):
        bab = cl(ch["title"])
        for sec in ch["sections"]:
            sec_t = cl(sec["title"])
            for art in sec["articles"]:
                title = fa_fix(cl(art["title"])) or sec_t
                lines = []
                for it in art["items"]:
                    for l in (it.get("content") or "").split("\n"):
                        l = cl(l)
                        if not l:
                            continue
                        if it["type"] == "Translate":
                            lg = "fa"
                        else:
                            lg = kind(l) or "fa"
                        lines.append((lg, l))
                blocks = []
                for lg, l in lines:
                    if blocks and blocks[-1][0] == lg:
                        blocks[-1][1].append(l)
                    else:
                        blocks.append((lg, [l]))
                pairs, i = [], 0
                while i < len(blocks):
                    lg, ls = blocks[i]
                    if lg == "ar":
                        fa = ""
                        if i + 1 < len(blocks):
                            fa = " ".join(blocks[i + 1][1]); i += 1
                        pairs.append(("\n".join(ls), fa))
                    else:
                        pairs.append(("", " ".join(ls)))
                    i += 1
                if not pairs:
                    continue
                gno += 1
                gt = f"{bab} · {sec_t} · {title}"[:250]
                for n, (ar, fa) in enumerate(pairs, 1):
                    eid = db.upsert_entry(con, book, gno, n, gt)
                    if ar:
                        db.add_text(con, eid, "original", "ar", ar)
                    db.add_text(con, eid, "translation", "fa", fa_fix(fa), "مفاتیح‌الجنان (انصاریان)")
    con.commit()
    db.rebuild_fts(con)
    print("ok articles", gno)


if __name__ == "__main__":
    run()
