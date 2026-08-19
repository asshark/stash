"""Ocena zakresu uszkodzeń: ile wierszy da się jeszcze odczytać z każdej tabeli."""

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "C:/Users/areks/.stash/bin/clips.CORRUPT_20260727_0940"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

tables = [
    r[0]
    for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
]

broken = []
for table in tables:
    try:
        count = conn.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]
        print(f"  OK    {table:<28} {count}")
    except sqlite3.DatabaseError as exc:
        print(f"  BŁĄD  {table:<28} {exc}")
        broken.append(table)

print("\nUszkodzone tabele:", broken)

if "scenes" in broken:
    print("\n--- mapa dziur w tabeli scenes ---")
    reachable = 0
    holes = []
    last = 0
    max_id = None
    try:
        max_id = conn.execute("SELECT MAX(id) FROM scenes").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        print("  MAX(id) niedostępne:", exc)
    print("  max id:", max_id)

    step = 500
    current = 0
    limit = (max_id or 60000) + step
    while current < limit:
        upper = current + step
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM scenes WHERE id >= ? AND id < ?", (current, upper)
            ).fetchone()[0]
            reachable += n
        except sqlite3.DatabaseError:
            holes.append((current, upper))
        current = upper

    print(f"  odczytanych wierszy: {reachable}")
    print(f"  zakresów id nie do odczytania: {len(holes)}")
    for hole in holes[:20]:
        print("   ", hole)
