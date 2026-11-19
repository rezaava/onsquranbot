"""Bot-independent API. Telegram/Bale/Eitaa layers should only call these functions."""
import re

from . import db

_AR_DIAC = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")


def normalize(s: str) -> str:
    s = _AR_DIAC.sub("", s)
    return s.replace("ي", "ی").replace("ك", "ک").replace("ٱ", "ا")


def list_books(category=None):
    con = db.connect()
    q, a = "SELECT slug,title_fa,category FROM books", ()
    if category:
        q, a = q + " WHERE category=?", (category,)
    return [dict(r) for r in con.execute(q, a)]


def list_groups(book_slug):
    """Chapters (suras, sermons, duas...)."""
    con = db.connect()
    rows = con.execute(
        "SELECT group_no, group_title, COUNT(*) n FROM entries e JOIN books b ON b.id=e.book_id "
        "WHERE b.slug=? GROUP BY group_no ORDER BY group_no", (book_slug,))
    return [dict(r) for r in rows]


def _texts(con, entry_id, translators=None):
    out = {"original": None, "translations": {}}
    for t in con.execute("SELECT kind,translator,body FROM texts WHERE entry_id=?", (entry_id,)):
        if t["kind"] == "original":
            out["original"] = t["body"]
        elif t["kind"] == "translation" and (not translators or t["translator"] in translators):
            out["translations"][t["translator"]] = t["body"]
    return out


def get_entry(book_slug, group_no, item_no, translators=None):
    con = db.connect()
    r = con.execute(
        "SELECT e.id,e.group_no,e.group_title,e.item_no FROM entries e JOIN books b ON b.id=e.book_id "
        "WHERE b.slug=? AND group_no=? AND item_no=?", (book_slug, group_no, item_no)).fetchone()
    if not r:
        return None
    return {**dict(r), "book": book_slug, **_texts(con, r["id"], translators)}


def get_group(book_slug, group_no, offset=0, limit=10, translators=None):
    """Paged chapter content (for next/prev buttons)."""
    con = db.connect()
    rows = con.execute(
        "SELECT e.id,e.group_no,e.group_title,e.item_no FROM entries e JOIN books b ON b.id=e.book_id "
        "WHERE b.slug=? AND group_no=? ORDER BY item_no LIMIT ? OFFSET ?",
        (book_slug, group_no, limit, offset)).fetchall()
    return [{**dict(r), "book": book_slug, **_texts(con, r["id"], translators)} for r in rows]


def search(query, book_slug=None, lang=None, limit=20):
    """Full-text search over all books (or one)."""
    con = db.connect()
    q = " ".join(f'"{w}"' for w in normalize(query).split())
    if not q:
        return []
    sql = ("SELECT b.slug,e.group_no,e.group_title,e.item_no,t.translator,t.lang,"
           "snippet(texts_fts,0,'«','»','…',12) snip "
           "FROM texts_fts JOIN texts t ON t.id=texts_fts.rowid JOIN entries e ON e.id=t.entry_id "
           "JOIN books b ON b.id=e.book_id WHERE texts_fts MATCH ?")
    args = [q]
    if book_slug:
        sql, args = sql + " AND b.slug=?", args + [book_slug]
    if lang:
        sql, args = sql + " AND t.lang=?", args + [lang]
    sql += " ORDER BY rank LIMIT ?"
    return [dict(r) for r in con.execute(sql, args + [limit])]
