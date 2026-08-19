"""Kontrola stanu bazy aktualnie używanej przez Stash (tylko odczyt)."""

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for label, path in (
    ("aktualna clips", "C:/Users/areks/.stash/bin/clips"),
    ("clips_recovered", "C:/Users/areks/.stash/bin/clips_recovered"),
):
    print(f"=== {label} ===")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        print("  integrity:", conn.execute("PRAGMA integrity_check(3)").fetchone()[0][:200])
    except sqlite3.Error as exc:
        print("  integrity: BŁĄD", exc)
        continue
    for table in ("scenes", "performers_scenes", "scenes_tags", "scene_urls", "scenes_files"):
        try:
            print(f"  {table:<20}", conn.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0])
        except sqlite3.Error as exc:
            print(f"  {table:<20} BŁĄD: {exc}")
    conn.close()
