"""Generic storage layer. Every book (Quran, Nahj al-Balagha, duas...) uses the same tables.

books     : one row per book/collection
entries   : one row per readable unit (ayah, khutbah, dua paragraph...)
            group_no/group_title = chapter (sura, sermon, dua name); item_no = position in group
texts     : one row per (entry, kind, lang, translator) - Arabic original, translations, tafsir...
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "islamic.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL,
  title_fa TEXT NOT NULL, title_ar TEXT, category TEXT NOT NULL, source TEXT
);
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
  group_no INTEGER NOT NULL, group_title TEXT, item_no INTEGER NOT NULL,
  UNIQUE(book_id, group_no, item_no)
);
CREATE TABLE IF NOT EXISTS texts(
  id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id),
  kind TEXT NOT NULL,            -- original | translation | tafsir
  lang TEXT NOT NULL,            -- ar | fa | en
  translator TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL,
  UNIQUE(entry_id, kind, lang, translator)
);
CREATE INDEX IF NOT EXISTS ix_entries_book ON entries(book_id, group_no, item_no);
CREATE VIRTUAL TABLE IF NOT EXISTS texts_fts USING fts5(body, content='texts', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_book(con, slug, title_fa, category, title_ar=None, source=None) -> int:
    con.execute(
        "INSERT INTO books(slug,title_fa,title_ar,category,source) VALUES(?,?,?,?,?) "
        "ON CONFLICT(slug) DO UPDATE SET title_fa=excluded.title_fa,title_ar=excluded.title_ar,"
        "category=excluded.category,source=excluded.source",
        (slug, title_fa, title_ar, category, source))
    return con.execute("SELECT id FROM books WHERE slug=?", (slug,)).fetchone()[0]


def upsert_entry(con, book_id, group_no, item_no, group_title=None) -> int:
    con.execute(
        "INSERT INTO entries(book_id,group_no,group_title,item_no) VALUES(?,?,?,?) "
        "ON CONFLICT(book_id,group_no,item_no) DO UPDATE SET group_title=excluded.group_title",
        (book_id, group_no, group_title, item_no))
    return con.execute("SELECT id FROM entries WHERE book_id=? AND group_no=? AND item_no=?",
                       (book_id, group_no, item_no)).fetchone()[0]


def add_text(con, entry_id, kind, lang, body, translator=""):
    con.execute(
        "INSERT INTO texts(entry_id,kind,lang,translator,body) VALUES(?,?,?,?,?) "
        "ON CONFLICT(entry_id,kind,lang,translator) DO UPDATE SET body=excluded.body",
        (entry_id, kind, lang, translator, body))


def rebuild_fts(con):
    con.execute("INSERT INTO texts_fts(texts_fts) VALUES('rebuild')")
    con.commit()
