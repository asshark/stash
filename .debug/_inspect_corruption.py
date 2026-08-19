import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect("file:C:/Users/areks/.stash/bin/clips?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

print("--- obiekt o rootpage 71 ---")
for row in conn.execute(
    "SELECT type, name, tbl_name, rootpage FROM sqlite_master WHERE rootpage = 71"
):
    print(dict(row))

print("\n--- sąsiednie rootpage ---")
for row in conn.execute(
    "SELECT type, name, tbl_name, rootpage FROM sqlite_master "
    "WHERE rootpage BETWEEN 55 AND 90 ORDER BY rootpage"
):
    print(dict(row))
