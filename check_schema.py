import sqlite3, sys
try:
    con = sqlite3.connect("data/islamic.db")
    con.execute("SELECT 1 FROM nfts LIMIT 1")
    print("Schema OK")
except sqlite3.OperationalError:
    print("Missing nfts table, rebuilding...")
    from core import db
    db.rebuild_fts(con)
    con.close()
    print("Schema updated")
except Exception as e:
    print("Schema check failed:", e)
    sys.exit(1)
