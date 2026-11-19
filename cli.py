"""Simple CLI to test the core.

  python cli.py books
  python cli.py suras
  python cli.py ayah 2 255
  python cli.py sura 112
  python cli.py search "صبر"
"""
import sys

from core import library as lib


def show(e):
    print(f"\n[{e['group_title']} - {e['group_no']}:{e['item_no']}]")
    print(e["original"] or "")
    for tr, body in e["translations"].items():
        print(f"  ({tr}) {body}")


def main(a):
    if not a:
        return print(__doc__)
    cmd, rest = a[0], a[1:]
    if cmd == "books":
        for b in lib.list_books():
            print(b["slug"], "-", b["title_fa"])
    elif cmd == "suras":
        for g in lib.list_groups("quran"):
            print(g["group_no"], g["group_title"], g["n"])
    elif cmd == "ayah":
        e = lib.get_entry("quran", int(rest[0]), int(rest[1]))
        show(e) if e else print("پیدا نشد")
    elif cmd == "sura":
        for e in lib.get_group("quran", int(rest[0]), limit=300):
            show(e)
    elif cmd == "search":
        for r in lib.search(" ".join(rest)):
            print(f"{r['slug']} {r['group_no']}:{r['item_no']} ({r['translator'] or r['lang']}) {r['snip']}")


main(sys.argv[1:])
