"""Quran importer using the alquran.cloud API (texts are downloaded, never typed by hand).

Run:  python -m importers.quran
"""
import json
import urllib.request

from core import db

API = "https://api.alquran.cloud/v1/quran/{}"
# (edition id, kind, lang, translator label)
EDITIONS = [
    ("quran-uthmani", "original", "ar", ""),
    ("fa.fooladvand", "translation", "fa", "فولادوند"),
    ("fa.makarem", "translation", "fa", "مکارم شیرازی"),
]


def fetch(edition):
    with urllib.request.urlopen(API.format(edition), timeout=60) as r:
        return json.load(r)["data"]["surahs"]


def run():
    con = db.connect()
    book = db.upsert_book(con, "quran", "قرآن کریم", "quran", "القرآن الكريم", "api.alquran.cloud")
    for ed, kind, lang, tr in EDITIONS:
        try:
            surahs = fetch(ed)
        except Exception as e:
            print(f"! {ed} skipped: {e}")
            continue
        for s in surahs:
            for a in s["ayahs"]:
                text = a["text"].replace("\ufeff", "").strip()
                # the API glues the basmala onto ayah 1 of every sura except 1 (and 9 has none)
                if kind == "original" and lang == "ar" and a["numberInSurah"] == 1 and s["number"] not in (1, 9):
                    text = " ".join(text.split()[4:])
                eid = db.upsert_entry(con, book, s["number"], a["numberInSurah"], s["name"])
                db.add_text(con, eid, kind, lang, text, tr)
        con.commit()
        print("ok", ed)
    db.rebuild_fts(con)


if __name__ == "__main__":
    run()
