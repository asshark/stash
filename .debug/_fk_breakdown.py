import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rec = sqlite3.connect("file:C:/Users/areks/.stash/bin/clips_recovered?mode=ro", uri=True)

print("--- naruszenia FK wg tabeli i tabeli docelowej ---")
counter = Counter()
for table, rowid, parent, fkid in rec.execute("PRAGMA foreign_key_check"):
    counter[(table, parent)] += 1
for (table, parent), count in counter.most_common():
    print(f"  {table:<24} -> {parent:<20} {count}")

print("\n--- kolejność kolumn tabeli scenes ---")
for row in rec.execute("PRAGMA table_info(scenes)"):
    print(f"  {row[0]:>2} {row[1]:<16} {row[2]:<12} notnull={row[3]} default={row[4]}")
